"""Gizmo e snap: geometria leggibile, e aiuti deterministici.

## Il gizmo e' geometria, non un overlay

Il viewport di 3DGen disegna una `Scene`, cioe' mesh con un materiale. Non ha
un canale per righe e frecce, e aggiungerglielo vorrebbe dire un secondo
sistema di rendering accanto a quello che c'e'. Quindi un gizmo qui e' **una
mesh in piu' nella scena di preview**, con un materiale che la distingue e il
tag `gizmo` che la rende riconoscibile.

La conseguenza che conta: i nodi di gizmo non sono il modello. Non entrano nel
conteggio dei triangoli di un `GenerationResult`, non vengono esportati, non
finiscono nel plugin — vivono solo nella scena che `preview_scene()` costruisce
per guardare. Un test lo verifica contando i triangoli con e senza.

Tre forme, e corrispondono a cio' che la milestone chiede di leggere:

    disco      dove sta il socket, e quanto e' grande (il raggio e' il raggio)
    freccia    il `direction`: da che parte esce il figlio
    barretta   l'`up`: come e' orientato il figlio girando attorno all'asse

## Gli snap sono aritmetica sui limiti, e basta

«Al centro dell'oggetto», «sulla faccia +Y del bounding box», «al massimo
lungo X», «allinea a -Z», «specchia L/R». Nessuno di questi guarda la
topologia, nessuno indovina niente, tutti danno lo stesso risultato ogni
volta. Nessun piazzamento assistito da un modello: non in V6.
"""
from __future__ import annotations

import numpy as np
import trimesh

from app.authoring import errors
from app.authoring.errors import AuthoringError
from app.core.authoring import ASSI
from app.core.material import MaterialSpec
from app.core.scene import Scene, SceneNode
from app.core.socket import orthogonal_up, unit

GIZMO_TAG = "gizmo"

# Tinte scelte per essere distinguibili su fondo scuro, non per essere belle.
DISC_MATERIAL = MaterialSpec(name="gizmo_disc", base_color="#4fa3ff", roughness=0.4,
                             opacity=0.9, description="innesto: dove e quanto grande")
DIRECTION_MATERIAL = MaterialSpec(name="gizmo_direction", base_color="#ffb347",
                                  roughness=0.4,
                                  description="innesto: da che parte esce il figlio")
UP_MATERIAL = MaterialSpec(name="gizmo_up", base_color="#7ddf64", roughness=0.4,
                           description="innesto: il dorso")
FRAME_MATERIALS = {
    "up": MaterialSpec(name="frame_up", base_color="#7ddf64", roughness=0.4),
    "front": MaterialSpec(name="frame_front", base_color="#4fa3ff", roughness=0.4),
    "growth_axis": MaterialSpec(name="frame_growth", base_color="#ffb347",
                                roughness=0.4),
}

AXES = tuple(sorted(ASSI))          # "+X", "-X", "+Y", ...


def axis_vector(axis: str) -> np.ndarray:
    """Il vettore di un asse nominato. Rifiuta un nome che non esiste."""
    name = str(axis or "").upper()
    if name not in ASSI:
        raise AuthoringError(errors.PROJECT_INVALID,
                             "asse atteso fra %s, non %r" % (", ".join(AXES), axis))
    return ASSI[name].copy()


# --------------------------------------------------------------------------- #
# Snap: aritmetica sui limiti
# --------------------------------------------------------------------------- #
def snap_to_center(bounds) -> tuple[float, float, float]:
    """Il centro del bounding box."""
    low, high = np.asarray(bounds[0], dtype=float), np.asarray(bounds[1], dtype=float)
    return tuple(float(v) for v in (low + high) * 0.5)


def snap_to_face(bounds, axis: str) -> tuple[float, float, float]:
    """Il centro della faccia del bounding box che guarda questo asse.

    E' lo snap piu' usato: «il socket della testa sta in cima al torso» vuol
    dire il centro della faccia +Y, non il vertice piu' alto.
    """
    low, high = np.asarray(bounds[0], dtype=float), np.asarray(bounds[1], dtype=float)
    vector = axis_vector(axis)
    index = int(np.argmax(np.abs(vector)))
    point = (low + high) * 0.5
    point[index] = high[index] if vector[index] > 0 else low[index]
    return tuple(float(v) for v in point)


def snap_to_extreme(bounds, axis: str) -> tuple[float, float, float]:
    """Il minimo o il massimo lungo un asse, con gli altri due al centro.

    Identico a `snap_to_face` nella posizione — la differenza fra «faccia» ed
    «estremo» su un bounding box e' il nome, non il punto — e tenuti separati
    perche' l'autore pensa a due cose diverse e il codice non deve costringerlo
    a scoprire che sono la stessa.
    """
    return snap_to_face(bounds, axis)


def mirror(position, direction, up, axis: str = "+X"):
    """Specchia un innesto rispetto al piano ortogonale all'asse.

    Serve per le coppie L/R: occhio sinistro e occhio destro sono lo stesso
    innesto con una coordinata invertita, e scriverli due volte a mano e' il
    modo di scriverne uno sbagliato. `up` resta ortogonale alla direzione
    perche' `orthogonal_up` lo garantisce (`app/core/socket.py`).
    """
    vector = axis_vector(axis)
    index = int(np.argmax(np.abs(vector)))
    flip = np.ones(3)
    flip[index] = -1.0
    new_position = np.asarray(position, dtype=float) * flip
    new_direction = unit(np.asarray(direction, dtype=float) * flip)
    new_up = orthogonal_up(new_direction, np.asarray(up, dtype=float) * flip)
    return (tuple(float(v) for v in new_position),
            tuple(float(v) for v in new_direction),
            tuple(float(v) for v in new_up))


MIRROR_SIDES = {"l": "r", "r": "l"}


def mirror_name(name: str) -> str:
    """`eye_l` diventa `eye_r`. Solo quando il nome lo dice."""
    text = str(name)
    for suffix, other in (("_l", "_r"), ("_r", "_l"), ("_left", "_right"),
                          ("_right", "_left")):
        if text.endswith(suffix):
            return text[:-len(suffix)] + other
    return text + "_mirror"


# --------------------------------------------------------------------------- #
# Gizmo: geometria leggibile
# --------------------------------------------------------------------------- #
def _oriented(mesh: trimesh.Trimesh, direction, position) -> trimesh.Trimesh:
    """Porta una mesh costruita lungo +Z sull'asse e nel punto chiesti."""
    target = unit(direction)
    matrix = trimesh.geometry.align_vectors(np.array([0.0, 0.0, 1.0]), target)
    result = mesh.copy()
    result.apply_transform(matrix)
    result.apply_translation(np.asarray(position, dtype=float))
    return result


def socket_gizmo(socket, *, prefix: str = "", sides: int = 12) -> list[SceneNode]:
    """Disco, freccia e barretta per un `Socket`. Tre nodi, tag `gizmo`.

    Le misure seguono il raggio dell'innesto, perche' un gizmo di dimensione
    fissa su un socket da 2 cm e uno da 2 m non si leggerebbe in nessuno dei
    due casi.
    """
    radius = max(float(socket.radius), 1e-3)
    name = prefix or socket.name
    nodes: list[SceneNode] = []

    disc = trimesh.creation.cylinder(radius=radius, height=radius * 0.08,
                                     sections=sides)
    nodes.append(SceneNode(id="%s.disc" % name, name="%s disc" % socket.name,
                           mesh=_oriented(disc, socket.direction, socket.position),
                           material=DISC_MATERIAL, tags=[GIZMO_TAG, "socket"]))

    length = radius * 2.4
    shaft = trimesh.creation.cylinder(radius=radius * 0.12, height=length,
                                      sections=max(6, sides // 2))
    shaft.apply_translation((0.0, 0.0, length * 0.5))
    tip = trimesh.creation.cone(radius=radius * 0.3, height=radius * 0.8,
                                sections=max(6, sides // 2))
    tip.apply_translation((0.0, 0.0, length))
    arrow = trimesh.util.concatenate([shaft, tip])
    nodes.append(SceneNode(id="%s.direction" % name,
                           name="%s direction" % socket.name,
                           mesh=_oriented(arrow, socket.direction, socket.position),
                           material=DIRECTION_MATERIAL,
                           tags=[GIZMO_TAG, "socket", "direction"]))

    bar = trimesh.creation.box(extents=(radius * 0.16, radius * 0.16, radius * 1.3))
    bar.apply_translation((0.0, 0.0, radius * 0.65))
    nodes.append(SceneNode(id="%s.up" % name, name="%s up" % socket.name,
                           mesh=_oriented(bar, socket.up, socket.position),
                           material=UP_MATERIAL, tags=[GIZMO_TAG, "socket", "up"]))
    return nodes


def frame_gizmo(frame, *, size: float = 1.0, prefix: str = "frame") -> list[SceneNode]:
    """Una freccia per ciascun asse che il frame dichiara. Mai per gli altri.

    Un frame non dichiarato non produce niente: e' la regola 27 di
    `PROJECT-INDEX` applicata al disegno. Mostrare un asse inventato
    insegnerebbe una convenzione che l'autore non ha scritto.
    """
    nodes: list[SceneNode] = []
    span = max(float(size), 1e-3)
    for name in ("up", "front", "growth_axis"):
        axis = getattr(frame, name, "") if frame is not None else ""
        if not axis:
            continue
        length = span * (0.9 if name != "growth_axis" else 0.6)
        shaft = trimesh.creation.cylinder(radius=span * 0.02, height=length,
                                          sections=8)
        shaft.apply_translation((0.0, 0.0, length * 0.5))
        tip = trimesh.creation.cone(radius=span * 0.05, height=span * 0.12, sections=8)
        tip.apply_translation((0.0, 0.0, length))
        arrow = trimesh.util.concatenate([shaft, tip])
        nodes.append(SceneNode(
            id="%s.%s" % (prefix, name), name="%s %s" % (name, axis),
            mesh=_oriented(arrow, axis_vector(axis), (0.0, 0.0, 0.0)),
            material=FRAME_MATERIALS[name], tags=[GIZMO_TAG, "frame", name]))
    return nodes


def preview_scene(scene: Scene | None, *, sockets=(), frame=None,
                  plan=None) -> Scene:
    """La scena del modello piu' i gizmo. L'originale non si tocca.

    Si costruisce una scena nuova che riusa gli stessi `SceneNode`: cio' che
    si guarda nel pannello di authoring e cio' che si esporterebbe restano due
    oggetti, e i gizmo non possono finire nel secondo per distrazione.
    """
    nodes = list(scene.nodes) if scene is not None else []
    size = 1.0
    if scene is not None and scene.nodes:
        extents = scene.bounds()[1] - scene.bounds()[0]
        size = float(max(np.max(extents), 1e-3))
    out = Scene(plan=plan if plan is not None else getattr(scene, "plan", None),
                nodes=nodes)
    for socket in sockets:
        out.nodes.extend(socket_gizmo(socket))
    if frame is not None:
        out.nodes.extend(frame_gizmo(frame, size=size))
    return out


def model_nodes(scene: Scene) -> list[SceneNode]:
    """La scena senza i gizmo: cio' che e' davvero il modello."""
    return [n for n in scene.nodes if GIZMO_TAG not in n.tags]
