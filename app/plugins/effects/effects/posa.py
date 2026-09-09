"""La posa: quattro effetti che spostano cio' che e' gia' costruito.

    rotate    gira un gruppo attorno al punto da cui pende
    align     lo orienta verso una direzione dichiarata
    offset    lo sposta
    mirror    lo specchia

Sono tutti dello stadio `final`, e tutti mappe di punti: il builder muove i
vertici e i socket con la stessa funzione, e un pezzo che si attacca a un
braccio ruotato ci resta attaccato.

## Perche' servono, e perche' sono cosi' pochi

Il banco del mostro ha mostrato il problema: un corpo di pesce ha le pinne
pettorali di lato, e un braccio umano innestato li' esce **orizzontale**. Non
e' un difetto del plugin del pesce — le sue pinne stanno dove devono — e non e'
un difetto del braccio. E' che due vocabolari compatibili non concordano una
posa, e nessuno dei due puo' saperlo da solo.

La risposta minima e' dire la posa da fuori: «le braccia verso il basso». Non
serve un risolutore di cinematica, non servono vincoli: serve una rotazione
attorno al punto giusto, che e' l'unica cosa che un effetto non puo' ricavare
dai propri punti. Quel punto lo passa il builder in `ctx.pivot` — la spalla,
non l'origine — insieme a `ctx.reach`, il punto piu' lontano del gruppo, che
dice **dove il gruppo sta puntando adesso**.

Con quei due numeri, «orienta le braccia verso il basso» e' una rotazione sola,
e vale per un braccio umano su una spalla umana, su una pinna di pesce o su
un'ala di qualcosa che ancora non esiste.

## L'ambito va scelto, non indovinato

Una posa muove **cio' che l'ambito nomina**, e niente altro. `subtree:braccio_l`
prende il braccio con tutto quello che porta; `role:arm` prende i pezzi che
dichiarano quel ruolo, e se una mano ne dichiara un altro resta dov'era. Non e'
un difetto da correggere qui: e' l'ambito che dice cosa si muove, ed e' l'unico
posto in cui deve essere scritto. Per una posa, `subtree:` e' quasi sempre la
risposta.

## Quello che questi effetti non fanno

Non piegano un gomito, non tengono conto di dove arriva la mano, non risolvono
catene. Un gruppo si muove tutto insieme, rigido. Se un caso reale chiedera' di
posare una catena articolata, quello e' un sistema diverso e va detto, non
fatto crescere per aggiunte a questo.
"""
import numpy as np

from app.core.params import ENUM, FLOAT, RATIO, ParamSpec
from app.core.vocabulary import (PRESERVE_SOCKETS, RECOVERABLE, SCOPE_GROUP,
                                 SCOPE_MODEL, SCOPE_PART, SCOPE_ROLE,
                                 SCOPE_SUBTREE, STAGE_FINAL, EffectSpec)

# Le direzioni hanno un nome perche' chi chiede una posa ragiona per nomi, non
# per terne. Sono le stesse della convenzione di autoria: cio' che sta in piedi
# cresce verso +Y, e il davanti e' +Z.
DIREZIONI = {
    "down": (0.0, -1.0, 0.0), "up": (0.0, 1.0, 0.0),
    "left": (-1.0, 0.0, 0.0), "right": (1.0, 0.0, 0.0),
    "front": (0.0, 0.0, 1.0), "back": (0.0, 0.0, -1.0),
}
ASSI = {"X": 0, "Y": 1, "Z": 2}
POSE = (SCOPE_SUBTREE, SCOPE_PART, SCOPE_GROUP, SCOPE_ROLE, SCOPE_MODEL)


def _perno(ctx, punti: np.ndarray) -> np.ndarray:
    """Il punto attorno a cui si gira. Dal builder, o il centro di cio' che c'e'.

    Il ripiego non e' un caso raro da ignorare: un effetto puo' colpire la
    radice, che non pende da niente. Girare attorno al proprio centro e' li' la
    risposta giusta.
    """
    dato = getattr(ctx, "pivot", None)
    if dato is not None:
        return np.asarray(dato, dtype=float)
    if len(punti) == 0:
        return np.zeros(3)
    return (punti.min(axis=0) + punti.max(axis=0)) * 0.5


def _versore(v: np.ndarray) -> np.ndarray:
    misura = float(np.linalg.norm(v))
    return v / misura if misura > 1e-12 else np.array([0.0, 1.0, 0.0])


def _rotazione(asse: np.ndarray, angolo: float) -> np.ndarray:
    """Rodrigues. Tre righe, e niente dipendenze."""
    k = _versore(np.asarray(asse, dtype=float))
    K = np.array([[0.0, -k[2], k[1]], [k[2], 0.0, -k[0]], [-k[1], k[0], 0.0]])
    return np.eye(3) + np.sin(angolo) * K + (1.0 - np.cos(angolo)) * (K @ K)


def _applica(punti: np.ndarray, perno: np.ndarray, M: np.ndarray) -> np.ndarray:
    return (np.asarray(punti, dtype=float) - perno) @ M.T + perno


def _da_a(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """La rotazione che porta `a` su `b`.

    Il caso opposto — `a` e `b` allineati e contrari — non ha un asse solo:
    tutte le rotazioni di mezzo giro attorno a un asse perpendicolare vanno
    bene. Se ne sceglie uno in modo deterministico, perche' due esecuzioni
    dello stesso piano devono dare lo stesso modello.
    """
    a, b = _versore(a), _versore(b)
    coseno = float(np.clip(a @ b, -1.0, 1.0))
    if coseno > 1.0 - 1e-9:
        return np.eye(3)
    if coseno < -1.0 + 1e-9:
        candidato = np.array([1.0, 0.0, 0.0]) if abs(a[0]) < 0.9 \
            else np.array([0.0, 1.0, 0.0])
        return _rotazione(np.cross(a, candidato), np.pi)
    return _rotazione(np.cross(a, b), float(np.arccos(coseno)))


# --------------------------------------------------------------------------- #
# rotate
# --------------------------------------------------------------------------- #
def ruota(punti: np.ndarray, ctx) -> np.ndarray:
    if len(punti) == 0:
        return punti
    asse = np.zeros(3)
    asse[ASSI.get(str(ctx.get("axis", "Z")).upper(), 2)] = 1.0
    angolo = np.radians(float(ctx.get("angle", 90.0)) * float(ctx.amount))
    return _applica(punti, _perno(ctx, punti), _rotazione(asse, angolo))


ROTATE = EffectSpec(
    id="rotate",
    description="gira un gruppo attorno al punto da cui pende",
    stage=STAGE_FINAL, scopes=POSE,
    amount=ParamSpec(1.0, RATIO, min=0.0, max=1.0,
                     description="quanta parte dell'angolo applicare"),
    params={"axis": ParamSpec("Z", ENUM, choices=("X", "Y", "Z"),
                              description="attorno a quale asse"),
            "angle": ParamSpec(90.0, FLOAT, min=-180.0, max=180.0,
                               description="di quanti gradi, con il segno")},
    deform=ruota, socket_policy=PRESERVE_SOCKETS, on_failure=RECOVERABLE,
    tags=frozenset({"posa"}),
)


# --------------------------------------------------------------------------- #
# align
# --------------------------------------------------------------------------- #
def orienta(punti: np.ndarray, ctx) -> np.ndarray:
    """Gira il gruppo finche' punta dove gli e' stato detto.

    «Dove punta adesso» e' il segmento fra il perno e il punto piu' lontano del
    gruppo: e' una definizione geometrica, non anatomica, e per questo funziona
    su un braccio, su una coda e su un'antenna.
    """
    if len(punti) == 0:
        return punti
    perno = _perno(ctx, punti)
    estremo = getattr(ctx, "reach", None)
    corrente = (np.asarray(estremo, dtype=float) - perno) if estremo is not None \
        else (punti[int(np.argmax(np.linalg.norm(punti - perno, axis=1)))] - perno)
    if float(np.linalg.norm(corrente)) < 1e-9:
        return punti
    voluta = np.asarray(DIREZIONI.get(str(ctx.get("direction", "down")).lower(),
                                      DIREZIONI["down"]), dtype=float)
    M = _da_a(corrente, voluta)
    quanto = float(ctx.amount)
    if quanto < 1.0:
        # una frazione della rotazione: si riduce l'angolo, non la matrice
        traccia = float(np.clip((np.trace(M) - 1.0) * 0.5, -1.0, 1.0))
        asse = np.array([M[2, 1] - M[1, 2], M[0, 2] - M[2, 0], M[1, 0] - M[0, 1]])
        if float(np.linalg.norm(asse)) > 1e-9:
            M = _rotazione(asse, float(np.arccos(traccia)) * quanto)
    return _applica(punti, perno, M)


ALIGN = EffectSpec(
    id="align",
    description="orienta un gruppo verso una direzione: giu', su, avanti, dietro",
    stage=STAGE_FINAL, scopes=POSE,
    amount=ParamSpec(1.0, RATIO, min=0.0, max=1.0,
                     description="quanta parte della rotazione applicare"),
    params={"direction": ParamSpec("down", ENUM, choices=tuple(sorted(DIREZIONI)),
                                   description="verso dove deve puntare")},
    deform=orienta, socket_policy=PRESERVE_SOCKETS, on_failure=RECOVERABLE,
    conflicts=frozenset({"mirror"}),
    tags=frozenset({"posa"}),
)


# --------------------------------------------------------------------------- #
# offset
# --------------------------------------------------------------------------- #
def sposta(punti: np.ndarray, ctx) -> np.ndarray:
    """Trasla il gruppo, in frazioni della sua estensione.

    In frazioni e non in metri, per la stessa ragione per cui una piega e' un
    angolo totale: lo stesso piano su una figura di sei metri e su una di
    sessanta centimetri deve dare la stessa forma.
    """
    if len(punti) == 0:
        return punti
    perno = _perno(ctx, punti)
    estremo = getattr(ctx, "reach", None)
    misura = float(np.linalg.norm(np.asarray(estremo, dtype=float) - perno)) \
        if estremo is not None else float(np.max(punti.max(axis=0) - punti.min(axis=0)))
    if misura < 1e-12:
        return punti
    passo = np.zeros(3)
    passo[ASSI.get(str(ctx.get("axis", "Y")).upper(), 1)] = \
        float(ctx.get("distance", 0.2)) * float(ctx.amount) * misura
    return np.asarray(punti, dtype=float) + passo


OFFSET = EffectSpec(
    id="offset",
    description="sposta un gruppo lungo un asse, in frazioni della sua estensione",
    stage=STAGE_FINAL, scopes=POSE,
    amount=ParamSpec(1.0, RATIO, min=0.0, max=1.0),
    params={"axis": ParamSpec("Y", ENUM, choices=("X", "Y", "Z")),
            "distance": ParamSpec(0.2, FLOAT, min=-3.0, max=3.0,
                                  description="in frazioni della lunghezza del gruppo")},
    deform=sposta, socket_policy=PRESERVE_SOCKETS, on_failure=RECOVERABLE,
    tags=frozenset({"posa"}),
)


# --------------------------------------------------------------------------- #
# mirror
# --------------------------------------------------------------------------- #
def specchia(punti: np.ndarray, ctx) -> np.ndarray:
    """Riflette il gruppo rispetto al piano che passa per il perno.

    Per il perno e non per l'origine: specchiare un braccio rispetto al piano
    del modello lo manderebbe dall'altra parte del corpo, che e' una cosa
    diversa da girarlo.
    """
    if len(punti) == 0:
        return punti
    asse = ASSI.get(str(ctx.get("axis", "X")).upper(), 0)
    perno = _perno(ctx, punti)
    fuori = np.array(punti, dtype=float, copy=True)
    fuori[:, asse] = 2.0 * perno[asse] - fuori[:, asse]
    return fuori


MIRROR = EffectSpec(
    id="mirror",
    description="specchia un gruppo rispetto al punto da cui pende",
    stage=STAGE_FINAL, scopes=POSE,
    amount=ParamSpec(1.0, RATIO, min=0.0, max=1.0),
    params={"axis": ParamSpec("X", ENUM, choices=("X", "Y", "Z"),
                              description="l'asse perpendicolare allo specchio")},
    deform=specchia, socket_policy=PRESERVE_SOCKETS, on_failure=RECOVERABLE,
    conflicts=frozenset({"align"}),
    tags=frozenset({"posa"}),
)
