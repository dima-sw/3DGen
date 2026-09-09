"""Motore di composizione: da un grafo di parti a un corpo unico.

Comporre non significa sovrapporre scatole. Ogni parte dichiara dei socket
(posizione, direzione, dorso, raggio) e l'attacco e' una relazione geometrica
vera: si allinea la terna del socket figlio con quella del socket padre, si
adatta la scala perche' i raggi combacino, si spinge leggermente la parte dentro
il padre perche' la fusione abbia materia su cui lavorare.

La superficie viene estratta **una volta sola** dal campo fuso, poi ripartita
fra le parti in base a quale campo domina in ogni punto. Cosi' il corpo resta
unico e continuo, ma ogni parte conserva identita', materiale e tag: e' quello
che serve per dare una testa di pesce a un torso umano.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

import numpy as np
import trimesh

from app.core.logging_setup import get
from app.geometry import sdf
from app.geometry.recipe import Part, Socket, get_recipe, load_catalog
from app.geometry.surface import NORMAL, to_mesh_capped

log = get("geometry.composition")

# quanto una parte entra nel padre, in frazione del raggio del socket:
# senza compenetrazione la fusione morbida non unisce, lascia due pezzi staccati
DEFAULT_INSERT = 0.45
SCALE_LIMITS = (0.25, 4.0)
def _max_blend_ratio() -> float:
    """Quanto puo' valere il raggio di fusione rispetto allo spessore della
    parte che si fonde. Oltre, la parte non si fonde: si dissolve. Il numero
    e' dello stile, non della composizione."""
    from app.core.style import current

    return current().blend_ratio


class CompositionError(ValueError):
    pass


@dataclass
class Placement:
    """Posa di una parte nel sistema dell'assemblaggio."""

    rotation: np.ndarray = field(default_factory=lambda: np.eye(3))
    translation: np.ndarray = field(default_factory=lambda: np.zeros(3))
    scale: float = 1.0

    def apply_point(self, p: np.ndarray) -> np.ndarray:
        return self.scale * (self.rotation @ np.asarray(p, dtype=float)) + self.translation

    def apply_direction(self, d: np.ndarray) -> np.ndarray:
        return self.rotation @ np.asarray(d, dtype=float)

    def socket_world(self, socket: Socket) -> Socket:
        return Socket(name=socket.name,
                      position=self.apply_point(socket.position),
                      direction=self.apply_direction(socket.direction),
                      radius=socket.radius * self.scale,
                      kind=socket.kind,
                      up=self.apply_direction(socket.up))

    def wrap(self, node: sdf.Field) -> sdf.Field:
        return sdf.Transform(node, rotation=self.rotation,
                             translation=tuple(float(v) for v in self.translation),
                             scale=float(self.scale))


@dataclass
class PlacedPart:
    """Una parte istanziata e posata, pronta sia per la fusione sia per i test."""

    id: str
    part: Part
    placement: Placement
    blend: float
    material: str
    tags: list[str]
    hard: bool
    parent: str | None = None
    parent_socket: str = ""
    own_socket: str = "base"

    @property
    def field(self) -> sdf.Field:
        return self.placement.wrap(self.part.field)

    def socket_world(self, name: str) -> Socket | None:
        socket = self.part.socket(name)
        return self.placement.socket_world(socket) if socket else None

    def sockets_world(self) -> dict[str, Socket]:
        return {n: self.placement.socket_world(s) for n, s in self.part.sockets.items()}

    def centre(self) -> np.ndarray:
        lo, hi = self.field.bounds()
        return (lo + hi) / 2.0


@dataclass
class Composition:
    """Risultato della composizione: campo fuso, parti dure, pose."""

    parts: list[PlacedPart] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def soft(self) -> list[PlacedPart]:
        return [p for p in self.parts if not p.hard]

    @property
    def hard(self) -> list[PlacedPart]:
        return [p for p in self.parts if p.hard]

    def by_id(self, part_id: str) -> PlacedPart | None:
        return next((p for p in self.parts if p.id == part_id), None)

    def field(self) -> sdf.Field:
        soft = self.soft
        if not soft:
            raise CompositionError("nessuna parte fondibile nell'assemblaggio")
        return sdf.Union([p.field for p in soft], blend=[p.blend for p in soft])

    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        los, his = zip(*(p.field.bounds() for p in self.parts))
        return np.min(los, axis=0), np.max(his, axis=0)


# --------------------------------------------------------------------------- #
# Allineamento
# --------------------------------------------------------------------------- #
def attachment_placement(parent: Placement, parent_socket: Socket,
                         child_socket: Socket, *, scale_mode: str = "socket",
                         scale: float = 1.0, insert: float = DEFAULT_INSERT,
                         roll: float = 0.0) -> Placement:
    """Posa che porta il socket del figlio a innestarsi in quello del padre."""
    target = parent.socket_world(parent_socket)

    # la parte cresce nel verso opposto al proprio socket di base
    growth = -child_socket.direction
    child_frame = np.column_stack([growth, child_socket.up, np.cross(growth, child_socket.up)])
    target_frame = np.column_stack([target.direction, target.up,
                                    np.cross(target.direction, target.up)])
    rotation = target_frame @ child_frame.T

    if abs(roll) > 1e-9:
        rotation = _roll_matrix(target.direction, roll) @ rotation

    if scale_mode == "socket":
        factor = target.radius / max(child_socket.radius, 1e-6)
    elif scale_mode == "parent":
        factor = parent.scale
    else:
        factor = 1.0
    factor = float(np.clip(factor * float(scale), *SCALE_LIMITS))

    # spinta dentro il padre: garantisce sovrapposizione, quindi fusione vera
    anchor = target.position - target.direction * (target.radius * float(insert))
    translation = anchor - factor * (rotation @ child_socket.position)
    return Placement(rotation=rotation, translation=translation, scale=factor)


def _roll_matrix(axis: np.ndarray, degrees: float) -> np.ndarray:
    a = np.asarray(axis, dtype=float)
    a = a / (np.linalg.norm(a) or 1.0)
    t = np.radians(float(degrees))
    x, y, z = a
    c, s = np.cos(t), np.sin(t)
    return np.array([
        [c + x * x * (1 - c), x * y * (1 - c) - z * s, x * z * (1 - c) + y * s],
        [y * x * (1 - c) + z * s, c + y * y * (1 - c), y * z * (1 - c) - x * s],
        [z * x * (1 - c) - y * s, z * y * (1 - c) + x * s, c + z * z * (1 - c)],
    ])


# --------------------------------------------------------------------------- #
# Composizione di un assemblaggio
# --------------------------------------------------------------------------- #
def compose(assembly) -> Composition:
    """Costruisce e posa tutte le parti di un `AssemblySpec`.

    Le parti che falliscono vengono saltate con un avviso: il resto del modello
    si genera lo stesso (regola dell'errore recuperabile).
    """
    load_catalog()
    result = Composition()
    nodes = {node.id: node for node in assembly.parts}
    if not nodes:
        raise CompositionError("assemblaggio vuoto")

    root_id = assembly.root or assembly.parts[0].id
    if root_id not in nodes:
        root_id = assembly.parts[0].id

    for node_id in _topological_order(assembly, root_id, result.warnings):
        node = nodes[node_id]
        recipe = get_recipe(node.recipe)
        if recipe is None:
            result.warnings.append("ricetta sconosciuta '%s' per la parte '%s'"
                                   % (node.recipe, node.id))
            continue
        try:
            part = recipe.build(node.params)
        except Exception as exc:
            result.warnings.append("parte '%s' non costruita: %s" % (node.id, exc))
            continue

        if node.id == root_id or node.attach is None:
            placement = Placement(scale=float(getattr(node, "scale", 1.0) or 1.0))
            parent_id, parent_socket_name, own_socket_name = None, "", "base"
        else:
            placed_parent = result.by_id(node.attach.parent)
            if placed_parent is None:
                result.warnings.append("parte '%s': padre '%s' non disponibile"
                                       % (node.id, node.attach.parent))
                continue
            parent_socket = placed_parent.part.socket(node.attach.socket)
            if parent_socket is None:
                result.warnings.append(
                    "parte '%s': socket '%s' assente su '%s' (disponibili: %s)"
                    % (node.id, node.attach.socket, node.attach.parent,
                       ", ".join(placed_parent.part.socket_names())))
                continue
            own = part.socket(node.attach.own_socket or "base")
            if own is None:
                result.warnings.append("parte '%s': manca il socket di base" % node.id)
                continue
            placement = attachment_placement(
                placed_parent.placement, parent_socket, own,
                scale_mode=node.attach.scale_mode, scale=node.attach.scale,
                insert=node.attach.insert, roll=node.attach.roll)
            parent_id = node.attach.parent
            parent_socket_name = node.attach.socket
            own_socket_name = node.attach.own_socket or "base"

        blend = node.blend if node.blend is not None else assembly.blend
        result.parts.append(PlacedPart(
            id=node.id, part=part, placement=placement,
            blend=_blend_for(part, placement, float(blend)),
            material=node.material or part.material,
            tags=sorted(set(list(node.tags) + list(part.tags))),
            hard=bool(node.hard or part.hard),
            parent=parent_id, parent_socket=parent_socket_name,
            own_socket=own_socket_name,
        ))

    if not result.parts:
        raise CompositionError("nessuna parte dell'assemblaggio e' stata costruita")
    return result


def _blend_for(part: Part, placement: Placement, richiesto: float) -> float:
    """Fusione limitata dalla dimensione **piu' piccola** della parte.

    Una pinna spessa tre centimetri fusa con un raggio di sei sparisce dentro
    il corpo: il campo morbido la scioglie prima che arrivi a essere una pinna.
    E' cosi' che le appendici sottili diventavano bozzi. Il raggio di fusione
    non puo' valere piu' di una frazione dello spessore di cio' che si fonde.
    """
    lo, hi = part.field.bounds()
    minima = float(np.min(hi - lo)) * max(float(placement.scale), 1e-6)
    return float(np.clip(richiesto, 0.0, max(minima * _max_blend_ratio(), 1e-4)))


def _topological_order(assembly, root_id: str, warnings: list[str]) -> list[str]:
    """Padri prima dei figli. I cicli vengono spezzati con un avviso."""
    nodes = {node.id: node for node in assembly.parts}
    ordered: list[str] = []
    seen: set[str] = set()

    def visit(node_id: str, stack: tuple[str, ...] = ()) -> None:
        if node_id in seen or node_id not in nodes:
            return
        if node_id in stack:
            warnings.append("ciclo negli attacchi su '%s': lo tratto come radice" % node_id)
            return
        node = nodes[node_id]
        if node.attach is not None and node.id != root_id:
            visit(node.attach.parent, stack + (node_id,))
        seen.add(node_id)
        ordered.append(node_id)

    visit(root_id)
    for node_id in nodes:
        visit(node_id)
    return ordered


# --------------------------------------------------------------------------- #
# Dalla composizione alle mesh
# --------------------------------------------------------------------------- #
def to_meshes(composition: Composition, resolution: int = NORMAL,
              smooth: int = 5, budget: int = 0) -> list[tuple[PlacedPart, trimesh.Trimesh]]:
    """Estrae la superficie e la ripartisce fra le parti che l'hanno generata.

    Tre trattamenti diversi, perche' le parti non sono tutte uguali:

    - **il corpo** e cio' che ha volume viene fuso in una superficie sola e
      ripartito per campo dominante: un corpo continuo, con identita' per parte;
    - **le parti sottili** (pinne, membrane, creste) vengono estratte a parte,
      ognuna nella propria scatola. Fonderle costerebbe una griglia fittissima
      su tutto il modello — una pinna di tre centimetri su un corpo di due metri
      e' piu' sottile di una cella — e il risultato sarebbe comunque una pinna
      annegata nel corpo invece che una pinna;
    - **le parti dure** (occhi, denti, piastre) restano separate per definizione.

    `budget` e' il numero di triangoli voluto. La riduzione avviene **prima**
    della ripartizione, sulla superficie unica: si paga una decimazione sola, e
    i piani vengono scelti guardando tutto il corpo invece che un pezzo per volta.
    """
    out: list[tuple[PlacedPart, trimesh.Trimesh]] = []
    corposi, sottili = _split_by_thickness(composition.soft, resolution)

    if corposi:
        griglia = resolution_for(corposi, resolution)
        fused = to_mesh_capped(sdf.Union([p.field for p in corposi],
                                         blend=[p.blend for p in corposi]),
                               resolution=griglia, smooth=smooth)
        if budget > 0 and len(fused.faces) > budget:
            from app.geometry.lowpoly import decimate

            fused = decimate(fused, budget)
        if len(fused.faces):
            out.extend(_split_by_owner(fused, corposi))

    # Le appendici sottili e le parti dure prendono una quota del budget: sono
    # dettagli, non devono mangiarsi i triangoli del corpo.
    separate = list(sottili) + list(composition.hard)
    quota = int(budget * 0.25 / max(len(separate), 1)) if budget else 0
    for placed in separate:
        try:
            out.append((placed, _mesh_alone(placed, smooth, quota)))
        except Exception as exc:
            log.warning("parte '%s' non estratta da sola: %s", placed.id, exc)
    return [(placed, mesh) for placed, mesh in out if len(mesh.faces)]


def _mesh_alone(placed: PlacedPart, smooth: int, quota: int) -> trimesh.Trimesh:
    """Estrae una parte nella propria scatola, alla risoluzione che le serve.

    Nella sua scatola una pinna e' un oggetto normale: pochi centimetri di
    ingombro e qualche millimetro di spessore. La griglia che la risolve e'
    minuscola, e il bordo viene netto invece che sfumato.
    """
    lo, hi = placed.field.bounds()
    estensione = hi - lo
    rapporto = float(np.max(estensione)) / max(float(np.min(estensione)), 1e-6)
    # Con due o tre celle nello spessore una lamina esce gonfia e tonda: per
    # avere un bordo servono almeno cinque o sei celle da parte a parte.
    griglia = int(min(max(32, rapporto * CELLS_ACROSS_THIN), 190))
    # E la lisciatura, su una lamina, mangia proprio il bordo che si vuole.
    mesh = to_mesh_capped(placed.field, resolution=griglia, smooth=min(smooth, 1),
                          padding=0.03)
    if quota and len(mesh.faces) > quota:
        from app.geometry.lowpoly import decimate

        mesh = decimate(mesh, max(quota, 40))
    return mesh


def _split_by_thickness(parts: list[PlacedPart],
                        resolution: int) -> tuple[list[PlacedPart], list[PlacedPart]]:
    """Separa cio' che ha volume da cio' che e' una lamina.

    Il criterio non e' il tag ma la geometria: una parte piu' sottile di poche
    celle della griglia con cui verrebbe fusa non sopravvivrebbe alla fusione,
    qualunque cosa dica il suo nome.
    """
    if not parts:
        return [], []
    scatole = [p.field.bounds() for p in parts]
    lo = np.min([b[0] for b in scatole], axis=0)
    hi = np.max([b[1] for b in scatole], axis=0)
    passo = float(np.max(hi - lo)) / max(int(resolution), 8)

    corposi, sottili = [], []
    for placed, (plo, phi) in zip(parts, scatole):
        estensione = np.sort(phi - plo)
        spessore, mediana = float(estensione[0]), float(estensione[1])
        # Due condizioni, non una. "Piu' sottile di una cella" da sola prende
        # anche i piedi e le mani, che sono piccoli ma pieni: staccarli dalla
        # gamba li lascia a mezz'aria. Serve anche che sia davvero una lamina,
        # cioe' che una dimensione sia molto minore delle altre.
        lamina = spessore < mediana * PLATE_RATIO
        (sottili if lamina and spessore < passo * CELLS_PER_FEATURE
         else corposi).append(placed)

    # Il corpo non si estrae mai da solo: se tutto sembra sottile, la misura e'
    # sballata e conviene fondere comunque.
    if not corposi:
        return parts, []
    if sottili:
        log.info("estratte a parte perche' sottili: %s",
                 ", ".join(p.id for p in sottili))
    return corposi, sottili


# Quante celle di griglia deve occupare la parte piu' sottile perche' il
# marching cubes riesca a vederla. Sotto le due celle sparisce e basta.
CELLS_PER_FEATURE = 2.6
# Quante celle si vogliono nello spessore di una lamina estratta da sola.
CELLS_ACROSS_THIN = 6.0
# Sotto questo rapporto fra lo spessore e la dimensione mediana, una parte e'
# una lamina e non un volume: una pinna sta a 0.1, un piede a 0.7.
PLATE_RATIO = 0.35
# Oltre questo moltiplicatore non si sale: una parte degenere non deve poter
# chiedere una griglia da miliardi di celle.
MAX_RESOLUTION_BOOST = 3.5


def resolution_for(parts: list[PlacedPart], requested: int) -> int:
    """Alza la risoluzione quanto basta a far esistere la parte piu' sottile.

    Una pinna spessa tre centimetri e mezzo, su un corpo lungo due metri e
    mezzo, e' piu' sottile di una cella della griglia richiesta dallo stile: il
    marching cubes non la incontra mai e la pinna semplicemente non c'e'. Non
    e' un problema di stile ne' di fusione, e' campionamento. La griglia deve
    essere abbastanza fitta per il dettaglio piu' fine che si vuole vedere; a
    ridurre i triangoli ci pensa dopo la decimazione.
    """
    scatole = [p.field.bounds() for p in parts]
    lo = np.min([b[0] for b in scatole], axis=0)
    hi = np.max([b[1] for b in scatole], axis=0)
    diagonale = float(np.max(hi - lo))
    if diagonale <= 0:
        return requested

    sottile = min(float(np.min(b[1] - b[0])) for b in scatole)
    if sottile <= 1e-6:
        return requested
    servono = diagonale / (sottile / CELLS_PER_FEATURE)
    alzata = int(min(max(requested, servono), requested * MAX_RESOLUTION_BOOST))
    if alzata > requested:
        log.info("risoluzione alzata da %d a %d: la parte piu' sottile misura "
                 "%.3f m su %.2f m di ingombro", requested, alzata, sottile, diagonale)
    return alzata


def _split_by_owner(mesh: trimesh.Trimesh,
                    parts: list[PlacedPart]) -> list[tuple[PlacedPart, trimesh.Trimesh]]:
    """Assegna ogni triangolo alla parte il cui campo domina nel suo baricentro."""
    if len(parts) == 1:
        return [(parts[0], mesh)]

    centres = mesh.triangles_center
    distances = np.stack([p.field.sample(centres) for p in parts], axis=0)
    owner = np.argmin(distances, axis=0)

    pieces: list[tuple[PlacedPart, trimesh.Trimesh]] = []
    for index, placed in enumerate(parts):
        faces = np.flatnonzero(owner == index)
        if faces.size == 0:
            continue
        piece = mesh.submesh([faces], append=True, repair=False)
        if isinstance(piece, list):
            piece = piece[0] if piece else None
        if piece is None or not len(piece.faces):
            continue
        pieces.append((placed, piece))
    return pieces


def fused_mesh(composition: Composition, resolution: int = NORMAL,
               smooth: int = 5) -> trimesh.Trimesh:
    """La sola superficie fusa, senza ripartizione: utile ai validatori."""
    return to_mesh_capped(composition.field(), resolution=resolution, smooth=smooth)
