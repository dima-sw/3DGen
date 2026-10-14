"""Verifica di cio' che e' stato costruito.

Il builder produce geometria; qui si guarda se quella geometria vale qualcosa.
Non e' un giudizio estetico — quello e' del quality gate visivo — ma un elenco
di cose che, se sono andate storte, sono andate storte in modo silenzioso:
coordinate non finite, triangoli degeneri, giunti aperti, socket senza verso.

## Nessun requisito universale

Non tutto deve essere chiuso, non tutto deve essere una sola parte. Una lamina
e' aperta apposta; un modello fatto di pezzi separati e' fatto di pezzi separati
apposta. Percio' i controlli forti — `manifold`, `watertight`, `connected` —
si applicano **solo ai componenti che li dichiarano** in `Component.requires`.
Imporli a tutti vorrebbe dire vietare in anticipo geometrie legittime che
ancora nessuno ha scritto.

## Compenetrazione: non ogni sovrapposizione e' un difetto

Nel cartoon low poly le parti si compenetrano **apposta**. Un braccio entra
nella spalla, un collo entra nella testa, un piede entra nella caviglia: senza
quella sovrapposizione a ogni articolazione si vedrebbe una fessura. Quindi la
domanda non e' «queste due parti si intersecano?» — quasi sempre si' — ma
«si intersecano **piu' di quanto l'attacco preveda**?».

Due misure, tutte e due grossolane apposta:

    sommersione     fra un pezzo e chi lo tiene: quanto entra **oltre**
                    l'innesto dichiarato. Si misura lungo il verso del socket e
                    si confronta con `radius * insert`, cioe' con la
                    sovrapposizione che l'attacco prevedeva. E' l'unica misura
                    che puo' distinguere un braccio infilato nella spalla da un
                    braccio inghiottito dal torace.
    sovrapposizione fra due pezzi che non si tengono a vicenda: ingombri
                    intersecati **e** centri quasi coincidenti. Il secondo
                    criterio non e' un dettaglio: due segmenti in fila lungo una
                    diagonale hanno ingombri quasi identici senza toccarsi, e
                    senza di esso ogni braccio risulterebbe compenetrato con se
                    stesso.

Sono misure grossolane apposta — scatole e centri, niente collisioni vere. Il
giorno che servisse precisione si sostituisce questa funzione e basta: nessuno
la chiama se non da qui.

## Lo stile decide i propri criteri

`faces_per_normal >= 1.8` e' il criterio del low poly: distingue una forma
**disegnata** da una campionata, dove ogni triangolo ha la sua normale perche'
nessuno ha deciso dove mettere gli spigoli. Ma e' un criterio del low poly, non
della geometria in generale: sta nei parametri dello `StyleProfile`, e se uno
stile non lo dichiara non viene applicato.
"""
from __future__ import annotations

import numpy as np

from app.core.errors import Report
from app.core.socket import Socket
from app.geometry.kernel import faces_per_normal

# Quanto puo' restare aperto un giunto **oltre** la compenetrazione voluta,
# in frazione della misura del modello. Il posizionamento e' esatto per
# costruzione: questa soglia intercetta una deformazione che ha spostato la
# geometria lasciando indietro il socket.
GIUNTO_MASSIMO = 0.01

# Sotto quest'area un triangolo non e' una faccia, e' un artefatto.
AREA_MINIMA = 1e-12

REQUISITI = ("manifold", "watertight", "connected", "no_degenerate")

# Quanta parte di un figlio puo' finire **oltre** la compenetrazione che
# l'innesto prevedeva. Sotto questa quota e' l'incastro voluto; sopra, il
# pezzo e' sparito dentro chi lo tiene.
SOMMERSIONE_MASSIMA = 0.75
# Quanto possono intersecarsi gli ingombri di due parti che non si tengono a
# vicenda, in frazione della piu' piccola.
SOVRAPPOSIZIONE_MASSIMA = 0.60
# Quanto di se' un pezzo puo' avere sepolto, comunque, qualunque cosa l'attacco
# dichiari. Un `insert` esagerato non rende visibile cio' che sta dentro.
QUOTA_SEPOLTA = 0.30
# ...e quanto possono avvicinarsi i loro centri, in frazione della misura
# della piu' piccola. Due pezzi in fila hanno centri lontani; due pezzi nello
# stesso posto ce li hanno addosso.
CENTRI_VICINI = 0.35

# Un componente puo' dichiararsi **sfaccettato**: una sfera, un cristallo, un
# poliedro hanno legittimamente una normale per faccia, e misurarli con il
# criterio dei quadrilateri piatti direbbe che sono blob quando non lo sono.
FACCETTATO = "faceted"


def validate(result, *, style=None, report: Report | None = None) -> Report:
    """Controlla un `BuildResult`. Restituisce il referto, non solleva mai."""
    report = report if report is not None else result.report

    for costruito in result.walk():
        _coordinate(costruito, report)
        _vuoto(costruito, report)
        _degeneri(costruito, report)
        _socket(costruito, report)
        _requisiti(costruito, report)

    _limiti(result, report)
    _giunti(result, report)
    _compenetrazioni(result, style, report)
    _stile(result, style, report)
    return report


# --------------------------------------------------------------------------- #
# Sovrapposizioni
# --------------------------------------------------------------------------- #
def _scatola(costruito):
    mesh = costruito.mesh
    if mesh is None or len(mesh.vertices) == 0:
        return None
    return np.asarray(mesh.bounds, dtype=float)


def _intersezione(a, b) -> float:
    """Volume comune a due scatole allineate agli assi."""
    if a is None or b is None:
        return 0.0
    lati = np.clip(np.minimum(a[1], b[1]) - np.maximum(a[0], b[0]), 0.0, None)
    return float(np.prod(lati))


def _volume(scatola) -> float:
    if scatola is None:
        return 0.0
    return float(np.prod(np.clip(scatola[1] - scatola[0], 1e-9, None)))


def _compenetrazioni(result, style, report: Report) -> None:
    """Cerca le sovrapposizioni **oltre** quelle che l'attacco prevede."""
    max_sommersione = _soglia(style, "max_submersion", SOMMERSIONE_MASSIMA)
    max_sovrapposizione = _soglia(style, "max_overlap", SOVRAPPOSIZIONE_MASSIMA)
    max_centri = _soglia(style, "max_centre_distance", CENTRI_VICINI)

    pezzi = result.geometry()
    scatole = {n.id: _scatola(n) for n in pezzi}

    for costruito in pezzi:
        padre = result.node(costruito.parent) if costruito.parent else None
        if padre is None or padre.mesh is None:
            continue
        quota = _oltre_l_innesto(costruito, padre)
        if quota > max_sommersione:
            report.warn(
                "PART_SUBMERGED",
                "'%s' entra in '%s' per il %.0f%% oltre l'innesto"
                % (costruito.ref, padre.ref, quota * 100),
                where=costruito.node.path,
                why="l'attacco prevedeva una compenetrazione pari a "
                    "raggio x insert: oltre quella, il pezzo sparisce dentro")

    for indice, uno in enumerate(pezzi):
        for altro in pezzi[indice + 1:]:
            if uno.id == altro.parent or altro.id == uno.parent:
                continue          # si tengono a vicenda: gia' misurati sopra
            quota = _sovrapposizione(scatole.get(uno.id), scatole.get(altro.id),
                                     max_centri)
            if quota > max_sovrapposizione:
                report.warn(
                    "PARTS_INTERPENETRATE",
                    "'%s' e '%s' occupano lo stesso posto per il %.0f%%"
                    % (uno.ref, altro.ref, quota * 100),
                    where=uno.node.path,
                    why="non si tengono a vicenda, quindi nessun innesto "
                        "prevedeva questa sovrapposizione")


def _oltre_l_innesto(costruito, padre) -> float:
    """Frazione dei vertici del figlio che entrano oltre la compenetrazione voluta.

    Il verso del socket dice dove sta il fuori; `radius * insert` dice quanto
    dentro il pezzo doveva arrivare. Tutto cio' che sta piu' in la' non era
    previsto da nessuno.
    """
    link = costruito.node.link
    if link is None or costruito.mesh is None or len(costruito.mesh.vertices) == 0:
        return 0.0
    innesto = padre.socket_world(link.parent_socket) \
        or _per_capability(padre, link.capability)
    if innesto is None:
        return 0.0

    punti = np.asarray(costruito.mesh.vertices, dtype=float)
    profondita = (innesto.position - punti) @ innesto.direction

    # La compenetrazione prevista e' quella dichiarata... entro un limite. Un
    # attacco che dichiara di infilare il figlio dieci volte la propria taglia
    # non sta descrivendo un incastro, sta sbagliando: oltre una frazione di
    # cio' che il pezzo e' lungo, e' sepolto comunque, e la dichiarazione non
    # puo' renderlo visibile.
    misura = float(np.max(costruito.mesh.bounds[1] - costruito.mesh.bounds[0]))
    prevista = min(innesto.radius * max(float(link.insert), 0.0),
                   misura * QUOTA_SEPOLTA)
    return float(np.mean(profondita > prevista))


def _sovrapposizione(a, b, max_centri: float) -> float:
    """Quanto due ingombri occupano lo stesso posto. Zero se sono solo in fila."""
    comune = _intersezione(a, b)
    if comune <= 0.0:
        return 0.0
    misura_a = float(np.max(a[1] - a[0]))
    misura_b = float(np.max(b[1] - b[0]))
    distanza = float(np.linalg.norm((a[0] + a[1]) * 0.5 - (b[0] + b[1]) * 0.5))
    if distanza > min(misura_a, misura_b) * max_centri:
        return 0.0            # in fila, non sovrapposti
    return comune / max(min(_volume(a), _volume(b)), 1e-12)


def _parentele(result) -> dict:
    """Per ogni nodo, antenati e discendenti.

    Fra parenti la sovrapposizione e' cio' che tiene insieme il modello, e
    misurarla come difetto vorrebbe dire chiamare difetto ogni articolazione.
    """
    antenati = {}
    for costruito in result.walk():
        padre = costruito.parent
        antenati[costruito.id] = set(antenati.get(padre, set())) | (
            {padre} if padre else set())
    fuori = {id: set(catena) for id, catena in antenati.items()}
    for id, catena in antenati.items():
        for antenato in catena:
            fuori.setdefault(antenato, set()).add(id)
    return fuori


def _soglia(style, chiave: str, predefinito: float) -> float:
    """Le soglie sono configurabili: uno stile puo' dichiarare le proprie."""
    if style is None:
        return predefinito
    valore = style.get(chiave)
    return predefinito if valore is None else float(valore)


# --------------------------------------------------------------------------- #
# Per pezzo
# --------------------------------------------------------------------------- #
def _coordinate(costruito, report: Report) -> None:
    mesh = costruito.mesh
    if mesh is None or len(mesh.vertices) == 0:
        return
    vertici = np.asarray(mesh.vertices, dtype=float)
    if not np.all(np.isfinite(vertici)):
        quanti = int(np.sum(~np.isfinite(vertici).all(axis=1)))
        report.add("NON_FINITE_GEOMETRY",
                   "'%s' ha %d vertici non finiti" % (costruito.ref, quanti),
                   where=costruito.node.path,
                   why="una coordinata NaN o infinita rende inservibile tutto "
                       "cio' che la contiene")


def _vuoto(costruito, report: Report) -> None:
    """Un pezzo che doveva avere geometria e non ne ha."""
    if not costruito.node.builds_geometry:
        return
    if costruito.piece.mesh is None:
        return                        # dichiarato senza geometria: e' legittimo
    if costruito.triangles == 0 or costruito.vertices == 0:
        report.add("EMPTY_GEOMETRY",
                   "'%s' ha costruito una mesh vuota" % costruito.ref,
                   where=costruito.node.path,
                   why="ha restituito una mesh, ma senza facce")


def _degeneri(costruito, report: Report) -> None:
    mesh = costruito.mesh
    if mesh is None or len(mesh.faces) == 0:
        return
    aree = np.asarray(mesh.area_faces, dtype=float)
    quanti = int(np.sum(~np.isfinite(aree) | (aree < AREA_MINIMA)))
    if not quanti:
        return
    grave = "no_degenerate" in costruito.component.requires
    messaggio = "'%s' ha %d triangoli degeneri su %d" % (costruito.ref, quanti,
                                                          len(mesh.faces))
    perche = "un triangolo di area nulla non ha una normale: rompe " \
             "l'ombreggiatura e ogni calcolo che la usa"
    if grave:
        report.add("DEGENERATE_TRIANGLES", messaggio,
                   where=costruito.node.path, why=perche)
    else:
        report.warn("DEGENERATE_TRIANGLES", messaggio,
                    where=costruito.node.path, why=perche)


def _socket(costruito, report: Report) -> None:
    for nome, s in sorted(costruito.sockets.items()):
        if not np.all(np.isfinite(s.position)) or not np.all(np.isfinite(s.direction)):
            report.add("INVALID_SOCKET",
                       "il socket '%s' di '%s' ha coordinate non finite"
                       % (nome, costruito.ref), where=costruito.node.path)
        elif float(np.linalg.norm(s.direction)) < 1e-6:
            report.add("INVALID_SOCKET",
                       "il socket '%s' di '%s' non ha un verso"
                       % (nome, costruito.ref), where=costruito.node.path,
                       why="senza direzione non si sa da che parte esce il figlio")


def _tiene_insieme(mesh) -> bool:
    """I volumi di questa mesh si toccano fra loro?

    Non basta contare i corpi. Un pezzo composto — un cranio piu' un muso — e'
    fatto di volumi che si **compenetrano** senza condividere un vertice, e per
    la libreria sono due corpi separati. Cio' che conta e' che stiano attaccati
    nello spazio, e per dirlo bastano gli ingombri.
    """
    try:
        corpi = mesh.split(only_watertight=False)
    except Exception:                                  # noqa: BLE001
        return True
    if len(corpi) <= 1:
        return True

    scatole = [np.asarray(c.bounds, dtype=float) for c in corpi]
    raggiunti, cambiato = {0}, True
    while cambiato:
        cambiato = False
        for indice in range(len(scatole)):
            if indice in raggiunti:
                continue
            if any(_intersezione(scatole[indice], scatole[j]) > 0
                   for j in raggiunti):
                raggiunti.add(indice)
                cambiato = True
    return len(raggiunti) == len(scatole)


def _manifold(mesh) -> bool:
    """Superficie orientata, con al piu' due facce per spigolo e fan connessi.

    La sola coerenza delle normali non vede ne' tre facce sullo stesso spigolo
    ne' due superfici unite soltanto in un vertice. I bordi aperti sono leciti:
    la chiusura e' il requisito separato `watertight`.
    """
    if not mesh.is_winding_consistent:
        return False
    if np.any(np.bincount(mesh.edges_unique_inverse) > 2):
        return False

    collegamenti = {}
    for faccia in np.asarray(mesh.faces):
        a, b, c = (int(i) for i in faccia)
        if len({a, b, c}) != 3:
            return False
        for centro, uno, altro in ((a, b, c), (b, c, a), (c, a, b)):
            link = collegamenti.setdefault(centro, {})
            link.setdefault(uno, set()).add(altro)
            link.setdefault(altro, set()).add(uno)
    for link in collegamenti.values():
        if any(len(vicini) > 2 for vicini in link.values()):
            return False
        raggiunti, pila = set(), [next(iter(link))]
        while pila:
            corrente = pila.pop()
            if corrente not in raggiunti:
                raggiunti.add(corrente)
                pila.extend(link[corrente] - raggiunti)
        if len(raggiunti) != len(link):
            return False
    return True


def _requisiti(costruito, report: Report) -> None:
    """Solo cio' che il componente ha dichiarato di volere."""
    voluti = costruito.component.requires & set(REQUISITI)
    mesh = costruito.mesh
    if not voluti or mesh is None or len(mesh.faces) == 0:
        return

    if "watertight" in voluti and not bool(mesh.is_watertight):
        report.add("GEOMETRY_REQUIREMENT",
                   "'%s' doveva essere chiuso e non lo e'" % costruito.ref,
                   where=costruito.node.path,
                   why="dichiarato in Component.requires")
    if "manifold" in voluti and not _manifold(mesh):
        report.add("GEOMETRY_REQUIREMENT",
                   "'%s' non e' una superficie manifold orientata" % costruito.ref,
                   where=costruito.node.path,
                   why="dichiarato in Component.requires")
    if "connected" in voluti and not _tiene_insieme(mesh):
        report.add("GEOMETRY_REQUIREMENT",
                   "'%s' e' venuto in pezzi che non si toccano" % costruito.ref,
                   where=costruito.node.path,
                   why="dichiarato in Component.requires")


# --------------------------------------------------------------------------- #
# Sul modello intero
# --------------------------------------------------------------------------- #
def _limiti(result, report: Report) -> None:
    limiti = result.bounds
    if limiti is None:
        if result.geometry():
            report.add("NON_FINITE_BOUNDS", "il modello non ha limiti calcolabili")
        return
    if not np.all(np.isfinite(limiti)):
        report.add("NON_FINITE_BOUNDS", "i limiti del modello non sono finiti",
                   why="c'e' almeno un vertice non finito")
    elif float(np.max(limiti[1] - limiti[0])) <= 0.0:
        report.add("NON_FINITE_BOUNDS", "il modello ha misura nulla")


def _giunti(result, report: Report) -> None:
    """Nessun pezzo staccato da chi lo tiene.

    La distanza attesa non e' zero: un figlio viene spinto **dentro** il padre
    di una frazione del raggio dell'innesto, altrimenti il giunto si vede. Si
    misura quindi lo scarto **oltre** quella compenetrazione voluta.
    """
    misura = float(np.max(result.size)) if result.bounds is not None else 0.0
    if misura <= 0.0:
        return

    for costruito in result.walk():
        link = costruito.node.link
        padre = result.node(costruito.parent) if link else None
        if link is None or padre is None:
            continue
        innesto = padre.socket_world(link.parent_socket) \
            or _per_capability(padre, link.capability)
        proprio = costruito.socket_world(link.own_socket)
        if innesto is None or proprio is None:
            continue

        distanza = float(np.linalg.norm(innesto.position - proprio.position))
        voluta = innesto.radius * float(link.insert)
        scarto = max(distanza - voluta, 0.0) / misura
        if scarto > GIUNTO_MASSIMO:
            report.warn("JOINT_GAP",
                        "'%s' e' staccato da '%s' di %.1f%% del modello"
                        % (costruito.ref, padre.ref, scarto * 100),
                        where=costruito.node.path,
                        why="innesto a %s, pezzo a %s"
                            % (np.round(innesto.position, 3),
                               np.round(proprio.position, 3)))


def _per_capability(padre, capability: str) -> Socket | None:
    if not capability:
        return None
    for nome in sorted(padre.sockets):
        if padre.sockets[nome].provides(capability):
            return padre.socket_world(nome)
    return None


def silhouette_fill(result, cells: int = 32, axis: int = 2) -> float:
    """Quanta parte del proprio ingombro il modello riempie, visto di fronte.

    E' la misura che distingue una **figura** da una massa: braccia e gambe
    lasciano vuoti, un blob riempie la sua scatola. Si ottiene proiettando i
    triangoli su una griglia grossolana e contando le celle toccate.

    Non e' un giudizio: una casa e' legittimamente una scatola e riempie tutto.
    Per questo il controllo scatta **solo** se lo stile dichiara una soglia —
    misurarla e' utile, imporla a tutti vorrebbe dire vietare i cubi.
    """
    limiti = result.bounds
    if limiti is None or cells < 2:
        return 0.0
    piani = [i for i in (0, 1, 2) if i != axis]
    minimo = limiti[0][piani]
    misura = np.clip(limiti[1][piani] - minimo, 1e-9, None)

    griglia = np.zeros((cells, cells), dtype=bool)
    for costruito in result.geometry():
        mesh = costruito.mesh
        triangoli = np.asarray(mesh.vertices)[np.asarray(mesh.faces)][:, :, piani]
        basso = np.floor((triangoli.min(axis=1) - minimo) / misura * (cells - 1))
        alto = np.ceil((triangoli.max(axis=1) - minimo) / misura * (cells - 1))
        for (x0, y0), (x1, y1) in zip(basso.astype(int), alto.astype(int)):
            griglia[max(x0, 0):x1 + 1, max(y0, 0):y1 + 1] = True
    return float(griglia.mean())


def _stile(result, style, report: Report) -> None:
    """I criteri dello stile, se lo stile ne dichiara.

    Nessun criterio si applica d'ufficio: uno stile che non dichiara
    `faces_per_normal_min` non vuole quel controllo, e imporglielo vorrebbe
    dire decidere al posto suo come deve venire la sua geometria.
    """
    if style is None:
        return

    minimo = style.get("faces_per_normal_min")
    if minimo is not None:
        for costruito in result.geometry():
            # si misura la geometria **progettata** (`designed`), non quella
            # deformata: una piega rende non complanari dei quadrilateri che
            # erano piatti, e il numero direbbe "campionata" di una forma
            # disegnata benissimo. Lo stile giudica come e' stata costruita,
            # non che cosa le e' stato fatto dopo.
            mesh = costruito.designed or costruito.piece.mesh or costruito.mesh
            if mesh is None or len(mesh.faces) < 4:
                continue              # troppo poco per dire qualcosa
            if FACCETTATO in costruito.component.requires:
                continue              # dichiarato sfaccettato: e' voluto
            misurato = faces_per_normal(mesh)
            if misurato < float(minimo):
                report.warn("STYLE_QUALITY",
                            "'%s': %.2f facce per normale, ne servono %.2f"
                            % (costruito.ref, misurato, float(minimo)),
                            where=costruito.node.path,
                            why="sotto questa soglia la forma e' campionata, "
                                "non disegnata: ogni triangolo ha una normale "
                                "propria e non ci sono facce vere")

    massimo = style.get("silhouette_max_fill")
    if massimo is not None:
        riempimento = silhouette_fill(result)
        if riempimento > float(massimo):
            report.warn("STYLE_QUALITY",
                        "la silhouette riempie il %.0f%% del suo ingombro"
                        % (riempimento * 100),
                        why="oltre questa quota la forma non si legge: e' una "
                            "massa, non una figura")

    budget = style.get("triangle_budget")
    if budget is not None and result.triangles > int(budget):
        report.warn("STYLE_QUALITY",
                    "%d triangoli, il budget dello stile e' %d"
                    % (result.triangles, int(budget)),
                    why="lo stile '%s' dichiara quel tetto" % style.id)


def combined_report(result, style=None) -> Report:
    """Costruzione e verifica in un referto solo."""
    return validate(result, style=style, report=result.report)
