"""Dal modello costruito alla scena: l'unico punto in cui i due mondi si toccano.

    BuildResult      il risultato della pipeline: nodi, mesh, socket, diagnosi
    Scene            cio' che export, livelli di dettaglio, libreria,
                     animazione e interfaccia sanno gia' leggere

Non e' un adattatore di comodo destinato a sparire: e' la **forma di uscita**
del sistema. Il builder produce geometria e struttura; tutto cio' che viene
dopo — scrivere un glTF, decimare, salvare una miniatura, ricavare uno
scheletro — lavora su una scena, e non deve sapere niente di resolver, di
capability o di effetti.

## Cosa passa, e cosa no

Passano le mesh, i materiali risolti, le etichette, e **i nodi costruiti** come
pose: lo scheletro ha bisogno di sapere a quale innesto del padre una parte e'
appesa, e quell'informazione vive nei socket veri, non in una copia.

Non passano diagnosi interne, riferimenti al registry, ne' il piano risolto. Se
un giorno servissero a valle, il posto giusto per chiederli e' il
`GenerationResult`, che tiene insieme tutti gli strati.

## L'appoggio a terra e' una scelta, non un automatismo

La pipeline vecchia spostava sempre le mesh perche' il modello poggiasse su
y=0. Qui l'appoggio si chiede: `ground=True` per chi esporta o mostra un
oggetto in una scena, niente per chi vuole il modello dove i componenti lo
hanno costruito. Le pose non si spostano — condividono i socket con il
costruito — e di quanto sono state alzate le mesh sta scritto in
`Scene.ground_offset`, che e' esattamente cio' che lo scheletro somma.
"""
from __future__ import annotations

import numpy as np

from app.core.logging_setup import get
from app.core.material import MaterialSpec, default_material
from app.core.scene import Scene, SceneNode

log = get("build.scene")


def to_scene(result, registry=None, *, plan=None, ground: bool = False,
             strategy: str = "composition") -> Scene:
    """La scena di un `BuildResult`. Una funzione, nessuno stato.

    `registry` serve solo a dare un colore ai nomi dei materiali: senza, la
    scena esce grigia invece di non uscire.
    """
    scena = Scene(plan=plan if plan is not None else getattr(result, "composition", None),
                  strategy=strategy)

    for costruito in result.geometry():
        if costruito.mesh is None or not len(costruito.mesh.vertices):
            continue
        # Un materiale nominato e' una scelta esplicita. In sua assenza la
        # mesh puo' gia' portare colori: valgono per qualunque Component,
        # indipendentemente da come abbia costruito la propria geometria.
        importato = _materiale_visivo(costruito.mesh) if not costruito.material else None
        materiale = importato or (registry.material(costruito.material)
                                  if registry is not None
                                  else default_material(costruito.material))
        scena.add(SceneNode(
            id=costruito.id,
            name=_leggibile(costruito.id),
            # una **copia**: la scena e' una vista, e appoggiarla a terra non
            # deve spostare la geometria del builder. Senza questa copia, due
            # scene chieste dallo stesso risultato si appoggiavano una sopra
            # l'altra e i socket restavano indietro di tutto lo scostamento.
            mesh=costruito.mesh.copy(),
            material=materiale,
            preserve_visual=importato is not None,
            tags=sorted({*costruito.tags, costruito.material,
                         costruito.ref.partition(":")[0]})))

    # Le pose: i nodi costruiti stessi. Portano i socket nel sistema del
    # modello, ed e' l'unica cosa che serve a chi ricava uno scheletro.
    scena.placements = {n.id: n for n in result.walk()}
    scena.warnings = [d.message for d in result.report if d.fatal]
    scena.issues = list(result.report.sorted())

    if ground:
        _appoggia(scena)
    log.info("scena: %d nodi, %d triangoli", len(scena.nodes), scena.triangle_count)
    return scena


def _materiale_visivo(mesh) -> MaterialSpec | None:
    """Tinta rappresentativa per le viste a tinta unica; la mesh conserva tutte.

    `defined` distingue colori reali dal grigio che trimesh fornisce quando
    nessun autore ha scelto una tinta. Non introduce un altro sistema PBR.
    """
    visual = mesh.visual
    if not getattr(visual, "defined", False):
        return None
    try:
        colori = visual.to_color() if hasattr(visual, "to_color") else visual
        rgba = np.asarray(colori.main_color, dtype=float)
        if rgba.shape != (4,) or not np.all(np.isfinite(rgba)):
            return None
        rgba = np.clip(rgba, 0, 255)
        return MaterialSpec(name="imported", base_color="#%02x%02x%02x" %
                            tuple(int(c) for c in rgba[:3]),
                            opacity=max(float(rgba[3]) / 255.0, 0.05))
    except (AttributeError, TypeError, ValueError):
        return None


def _leggibile(id: str) -> str:
    """`torso/bacino` diventa `Torso Bacino`. Solo per gli occhi."""
    return id.replace("/", " ").replace("_", " ").strip().title()


def _appoggia(scena: Scene) -> None:
    """Alza le mesh finche' la piu' bassa tocca y=0, e registra di quanto.

    Si spostano le **mesh** e non le pose, perche' le pose condividono i socket
    con il modello costruito: muoverle vorrebbe dire spostare anche cio' a cui
    i figli sono attaccati. Chi ha bisogno delle pose nel sistema della scena
    somma `ground_offset` — e lo scheletro lo fa.
    """
    if not scena.nodes:
        return
    minimo = min(float(n.mesh.bounds[0][1]) for n in scena.nodes)
    spostamento = np.array([0.0, -minimo, 0.0])
    # Si registra **sempre**, anche quando e' zero: chi somma lo scostamento —
    # lo scheletro — deve trovare un vettore, non un `None` da distinguere da
    # un modello che per caso poggiava gia' a terra.
    scena.ground_offset = spostamento
    if abs(minimo) < 1e-9:
        return
    for nodo in scena.nodes:
        nodo.mesh.apply_translation(spostamento)
