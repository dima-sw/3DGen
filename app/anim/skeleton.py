"""Scheletro ricavato dal grafo delle parti.

Non c'e' niente da inventare: un assemblaggio *e' gia'* una gerarchia. Ogni
parte e' attaccata a un socket del padre, e quel socket e' esattamente il punto
attorno a cui la parte deve ruotare. Una gamba ruota attorno all'anca perche'
all'anca e' attaccata.

Da ogni giunto si prende anche la terna del socket — avanti, dorso, laterale —
cosi' un'animazione puo' dire "ruota attorno al laterale" (una gamba che
avanza) o "ruota attorno all'avanti" (un'ala che sbatte) senza sapere niente
dell'orientamento del modello nel mondo.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from app.core.logging_setup import get

log = get("anim.skeleton")


@dataclass
class Joint:
    """Un giunto: dove si ruota, attorno a cosa, e che parte trascina."""

    name: str                       # coincide con l'id della parte
    parent: str | None
    pivot: np.ndarray               # posizione nel mondo, a riposo
    forward: np.ndarray             # direzione del socket: dove "cresce" la parte
    up: np.ndarray                  # dorso
    side: np.ndarray                # laterale, = forward x up
    tags: list[str] = field(default_factory=list)
    radius: float = 0.1
    # "l" o "r", quando l'innesto lo dichiara. E' un dato, non una deduzione
    # dalla posizione: un'ala attaccata a un innesto sinistro sta a sinistra
    # anche se la geometria l'ha portata altrove. Si chiama `side_tag` perche'
    # `side` e' gia' il versore laterale della terna del giunto.
    side_tag: str = ""

    def axis(self, nome: str) -> np.ndarray:
        """Asse di rotazione per nome, nella terna del giunto."""
        return {"forward": self.forward, "up": self.up, "side": self.side}[nome]

    def has(self, *tags: str) -> bool:
        return bool(set(tags) & set(self.tags))


@dataclass
class Skeleton:
    joints: list[Joint] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.joints)

    def get(self, name: str) -> Joint | None:
        return next((j for j in self.joints if j.name == name), None)

    @property
    def root(self) -> Joint | None:
        return next((j for j in self.joints if j.parent is None), None)

    def children(self, name: str) -> list[Joint]:
        return [j for j in self.joints if j.parent == name]

    def descendants(self, name: str) -> list[Joint]:
        """Tutto cio' che si muove quando si muove questo giunto."""
        out: list[Joint] = []
        da_visitare = [name]
        while da_visitare:
            for figlio in self.children(da_visitare.pop()):
                out.append(figlio)
                da_visitare.append(figlio.name)
        return out

    def find(self, *tags: str) -> list[Joint]:
        """I giunti che portano almeno uno di questi tag, in ordine stabile."""
        return [j for j in self.joints if j.has(*tags)]

    def axes(self) -> tuple[int, int]:
        """(asse longitudinale, asse laterale) del modello, come indici 0/1/2.

        Il longitudinale e' la direzione muso-coda: si legge dalla posizione
        della testa rispetto al corpo, che e' un fatto semantico e non dipende
        da come il modello e' orientato nel mondo. Senza testa si ripiega sulla
        dispersione dei giunti, che per un corpo allungato dice la stessa cosa.
        La verticale e' sempre Y, per convenzione del catalogo.
        """
        orizzontali = (0, 2)
        # Se i giunti **dichiarano** un lato, l'asse laterale e' quello su cui
        # i sinistri e i destri si separano di piu'. E' un dato, non un
        # indizio: meglio di qualunque ipotesi ricavata dagli ingombri, e
        # risolve il caso in cui un corpo e' piu' largo che lungo.
        sinistri = [j.pivot for j in self.joints if j.side_tag.lower().startswith("l")]
        destri = [j.pivot for j in self.joints if j.side_tag.lower().startswith("r")]
        if sinistri and destri:
            centro_s = np.mean(np.asarray(sinistri, dtype=float), axis=0)
            centro_d = np.mean(np.asarray(destri, dtype=float), axis=0)
            distanza = np.abs(centro_s - centro_d)
            laterale = orizzontali[int(np.argmax([distanza[0], distanza[2]]))]
            return (2 if laterale == 0 else 0), laterale

        teste = self.find("head")
        radice = self.root
        if teste and radice is not None:
            direzione = np.abs(np.asarray(teste[0].pivot) - np.asarray(radice.pivot))
            lungo = orizzontali[int(np.argmax([direzione[0], direzione[2]]))]
        elif len(self.joints) > 1:
            pivots = np.array([j.pivot for j in self.joints])
            spread = pivots.max(axis=0) - pivots.min(axis=0)
            lungo = orizzontali[int(np.argmax([spread[0], spread[2]]))]
        else:
            lungo = 0
        return lungo, 2 if lungo == 0 else 0

    def sides(self, *tags: str) -> tuple[list[Joint], list[Joint]]:
        """Divide gli arti fra i due lati del corpo, sull'asse laterale."""
        arti = self.find(*tags)
        if len(arti) < 2:
            return arti, []
        _, laterale = self.axes()
        centro = float(np.median([j.pivot[laterale] for j in arti]))
        sinistra = [j for j in arti if j.pivot[laterale] <= centro]
        destra = [j for j in arti if j.pivot[laterale] > centro]
        return (sinistra, destra) if destra else (arti, [])

    def axis_vector(self, which: str) -> np.ndarray:
        """Un asse del **corpo** in coordinate mondo: longitudinale, laterale, verticale.

        Le rotazioni degli arti si esprimono meglio negli assi del corpo che in
        quelli del singolo socket: due gambe simmetriche hanno terne
        specchiate, e usando le loro si otterrebbero due passi in direzioni
        opposte proprio quando li si vuole alterni.
        """
        lungo, laterale = self.axes()
        indice = {"long": lungo, "lat": laterale, "up": 1}[which]
        asse = np.zeros(3)
        asse[indice] = 1.0
        return asse

    def lateral_sign(self, joint: Joint) -> float:
        """Da che parte del corpo sta un arto: +1 o -1, mai 0.

        Se l'innesto lo **dichiara** — `side="l"` o `"r"` — si usa quello: e'
        un dato scritto da chi ha costruito il componente, e non dipende da
        come la geometria e' finita nel mondo. Solo quando nessuno lo dichiara
        si guarda la posizione, che e' un'ipotesi e va trattata come tale.
        """
        if joint.side_tag:
            return -1.0 if joint.side_tag.lower().startswith("l") else 1.0
        _, laterale = self.axes()
        centro = float(np.median([j.pivot[laterale] for j in self.joints])) \
            if self.joints else 0.0
        return 1.0 if joint.pivot[laterale] > centro else -1.0

    def gait_phases(self, *tags: str) -> dict[str, float]:
        """Sfasamento di ogni arto in una camminata, fra 0 e 1.

        Gli arti in diagonale si muovono insieme: e' l'andatura di qualunque
        quadrupede, e su un bipede degenera nel semplice alternarsi delle due
        gambe. Ogni arto trascina i propri discendenti — stinco, piede — con lo
        stesso sfasamento, altrimenti la gamba si spezzerebbe a meta'.
        """
        lungo, laterale = self.axes()
        radici = [j for j in self.find(*tags)
                  if j.parent is None or not self.get(j.parent).has(*tags)]
        if not radici:
            return {}

        mediana_lat = float(np.median([j.pivot[laterale] for j in radici]))
        mediana_lon = float(np.median([j.pivot[lungo] for j in radici]))
        fasi: dict[str, float] = {}
        for arto in radici:
            # il lato dichiarato vince sulla posizione, per la stessa ragione
            # per cui vince in `lateral_sign`
            destra = self.lateral_sign(arto) > 0 if arto.side_tag \
                else arto.pivot[laterale] > mediana_lat
            davanti = arto.pivot[lungo] > mediana_lon
            fase = 0.0 if destra == davanti else 0.5
            fasi[arto.name] = fase
            for figlio in self.descendants(arto.name):
                fasi[figlio.name] = fase
        return fasi


def from_placements(placements: dict, offset=None) -> Skeleton:
    """Costruisce lo scheletro dalle pose calcolate dalla composizione.

    `placements` e' `Scene.placements`: id della parte -> `PlacedPart`.
    `offset` e' lo spostamento con cui la scena e' stata appoggiata a terra:
    le pose non lo conoscono, le mesh si', e i giunti devono stare con le mesh.
    """
    joints: list[Joint] = []
    scostamento = np.zeros(3) if offset is None else np.asarray(offset, dtype=float)
    for part_id, placed in placements.items():
        # `""` non e' un padre: e' la radice. Trattarlo come un id inesistente
        # riattaccava la radice a se stessa, con un avviso a ogni scheletro.
        parent = getattr(placed, "parent", None) or None
        socket = _parent_socket(placed, placements)

        if socket is None:
            # radice, o attacco perduto: il pivot e' l'origine della parte e la
            # terna e' quella del mondo. Non e' un caso limite raro, e' il torso.
            pivot = np.asarray(placed.placement.translation, dtype=float) + scostamento
            forward = np.array([0.0, 0.0, 1.0])
            up = np.array([0.0, 1.0, 0.0])
        else:
            pivot = np.asarray(socket.position, dtype=float) + scostamento
            forward = np.asarray(socket.direction, dtype=float)
            up = np.asarray(socket.up, dtype=float)
            parent = placed.parent

        side = np.cross(forward, up)
        norma = float(np.linalg.norm(side))
        side = side / norma if norma > 1e-9 else np.array([1.0, 0.0, 0.0])

        joints.append(Joint(
            name=part_id, parent=parent, pivot=pivot,
            forward=forward, up=up, side=side,
            tags=list(getattr(placed, "tags", [])),
            radius=float(socket.radius) if socket is not None else 0.1,
            side_tag=_lato(placed, socket)))

    _reparent_orphans(joints)
    log.info("scheletro: %d giunti, radice '%s'", len(joints),
             joints[0].name if joints else "-")
    return Skeleton(joints=joints)


def _lato(placed, socket) -> str:
    """Il lato dichiarato: prima dall'innesto usato, poi dal socket del padre."""
    collegamento = getattr(getattr(placed, "node", None), "link", None)
    dichiarato = getattr(collegamento, "side", "") if collegamento is not None else ""
    return dichiarato or getattr(socket, "side", "") or ""


def _parent_socket(placed, placements: dict):
    """Il socket del padre a cui questa parte e' attaccata, in coordinate mondo.

    Si chiede al padre, non alla parte: e' il padre a sapere dove sono i propri
    innesti, e dopo una deformazione e' il suo socket aggiornato a dire la
    verita'. Un pezzo che non sa a che cosa e' appeso non e' un errore — e' la
    radice — e restituisce niente.
    """
    parent_id = getattr(placed, "parent", None)
    if not parent_id or parent_id not in placements:
        return None
    padre = placements[parent_id]
    nome = getattr(placed, "parent_socket", "")
    return padre.socket_world(nome) if nome else None


def _reparent_orphans(joints: list[Joint]) -> None:
    """Un giunto il cui padre non esiste diventa figlio della radice.

    Meglio uno scheletro completo e un po' arbitrario che un pezzo di modello
    che l'animazione non muove affatto.
    """
    nomi = {j.name for j in joints}
    radici = [j for j in joints if j.parent is None]
    radice = radici[0].name if radici else None
    for giunto in joints:
        if giunto.parent is not None and giunto.parent not in nomi:
            log.warning("giunto '%s': padre '%s' assente, riattaccato alla radice",
                        giunto.name, giunto.parent)
            giunto.parent = radice
    # Piu' radici significa piu' modelli sciolti: si tiene la prima e le altre
    # le si appende, altrimenti l'esportazione produrrebbe alberi separati.
    for extra in radici[1:]:
        extra.parent = radice


def from_scene(scene) -> Skeleton:
    """Scheletro di una scena, se viene da un assemblaggio.

    Le scene da template non hanno un grafo di parti: restituiscono uno
    scheletro vuoto, e chi anima deve accorgersene invece di ricevere qualcosa
    di finto.
    """
    return from_placements(getattr(scene, "placements", {}) or {},
                           offset=getattr(scene, "ground_offset", None))
