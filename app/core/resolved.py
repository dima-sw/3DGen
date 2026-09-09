"""Il piano risolto: quali componenti, collegati come.

E' il risultato del resolver e l'ingresso del builder. Contiene decisioni, non
geometria: **chi** si collega a **chi**, con quali parametri, attraverso quale
innesto. Dove esattamente, con che scala e con che orientamento lo decide il
builder, che avra' in mano i socket veri.

    graph       cosa voglio
    registry    cosa esiste
    resolved    cosa uso, e come si tiene insieme      <- questo file
    builder     dove finisce ogni vertice

## Il piano di partenza resta

`ResolvedComposition.graph` e' il `CompositionGraph` originale, intatto. Serve
per il debug — «volevo una testa umana e mi ritrovo un muso di drago: perche'?»
— e servira' alla correzione automatica di un piano, che ha bisogno di vedere
la richiesta accanto al risultato.

## Provenienza dei parametri

Ogni valore risolto sa da dove viene: predefinito del componente, calcolato da
un'espressione, imposto dal piano, o (piu' avanti) alterato da un effetto.
Senza questa memoria non si distingue un numero deciso da qualcuno da un numero
che e' semplicemente capitato — ed e' la distinzione che serve quando un
modello viene male e bisogna capire chi ha deciso cosa.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator

from app.core.capability import (CAPABILITY, CAPABILITY_AND_SIDE,
                                 CAPABILITY_AND_TAGS, EXACT_ID, FALLBACK,
                                 INCOMPATIBLE, Requirement)
from app.core.component import Component
from app.core.errors import Report
from app.core.graph import (FROM_DEFAULT, FROM_DERIVED, FROM_EFFECT,
                            FROM_OVERRIDE, CompositionGraph, EffectRequest)

# Come si e' arrivati a un innesto. Nomi, non numeri, perche' finiscono in una
# diagnosi che deve leggere un umano (o un modello linguistico).
LIVELLI = {
    EXACT_ID: "socket esatto",
    CAPABILITY_AND_SIDE: "capability e lato",
    CAPABILITY_AND_TAGS: "capability e tag",
    CAPABILITY: "capability",
    FALLBACK: "ripiego",
    INCOMPATIBLE: "incompatibile",
}

SEPARATOR = "/"


@dataclass(frozen=True)
class ResolvedValue:
    """Un parametro, con la memoria di chi lo ha deciso."""

    value: Any
    source: str = FROM_DEFAULT
    expression: str = ""              # se e' derivato o cambiato, la formula
    origin: str = ""                  # chi lo ha imposto: id del nodo o effetto
    previous: Any = None              # cosa c'era prima, se qualcuno l'ha cambiato

    @property
    def modified(self) -> bool:
        return self.previous is not None

    def describe(self, name: str = "") -> str:
        coda = " = %s" % self.expression if self.expression else ""
        prima = "" if not self.modified else " (era %s)" % self.previous
        return "%s%s (%s%s)%s" % ("%s: " % name if name else "", self.value,
                                  self.source, coda, prima)


@dataclass
class ResolvedLink:
    """Come un nodo si tiene al suo contenitore.

    Contiene **nomi**, non trasformazioni: il socket vero — posizione, verso,
    raggio — nasce dentro `build`, e inventarlo qui vorrebbe dire indovinare.
    Il builder ritrovera' `parent_socket` (o, se e' vuoto, la `capability`)
    dentro il `Piece` del padre.
    """

    parent: str = ""                  # id del nodo che lo contiene
    parent_socket: str = ""           # nome dichiarato dell'innesto, se c'e'
    capability: str = ""              # la capability che il collegamento usa
    side: str = ""
    own_socket: str = "base"          # il socket del figlio che si posa
    score: int = FALLBACK             # a che livello si e' risolto
    requirement: Requirement | None = None
    scale_mode: str = "none"
    # La taglia di cio' che questo nodo sostituisce, quando l'ha chiesto con
    # `fit_replaced`. La calcola il resolver, che ha i parametri del componente
    # sostituito; il builder la usa senza doverlo costruire per misurarlo.
    target_size: float = 0.0
    insert: float = 0.35
    roll: float = 0.0

    @property
    def how(self) -> str:
        return LIVELLI.get(self.score, "sconosciuto")

    def describe(self) -> str:
        dove = self.parent_socket or self.capability or "?"
        return "%s -> %s (%s)" % (self.own_socket, dove, self.how)


@dataclass
class ResolvedNode:
    """Un componente scelto, con i suoi valori e il suo collegamento."""

    id: str
    component: Component
    path: str = ""
    depth: int = 0
    requested_ref: str = ""           # cosa chiedeva il piano
    link: ResolvedLink | None = None  # None per la radice
    values: dict[str, Any] = field(default_factory=dict)
    sources: dict[str, ResolvedValue] = field(default_factory=dict)
    children: list[str] = field(default_factory=list)
    effects: list[EffectRequest] = field(default_factory=list)
    tags: frozenset[str] = field(default_factory=frozenset)
    builds_geometry: bool = True      # falso se i figli prendono il suo posto
    from_plan: bool = True            # falso se viene dall'espansione di un componente
    swapped_from: str = ""            # cosa c'era prima della sostituzione
    # quanti figli ha gia' preso ciascun innesto. Due pezzi nello stesso posto
    # sono due pezzi compenetrati, e non si vede finche' non si guarda.
    occupied: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.tags = frozenset(self.tags)
        self.path = self.path or self.id

    @property
    def ref(self) -> str:
        """Da cosa viene costruito. **Uno solo**, sempre."""
        return self.component.id

    @property
    def substituted(self) -> bool:
        return bool(self.swapped_from)

    def source(self, name: str) -> str:
        voce = self.sources.get(name)
        return voce.source if voce else ""

    def describe(self) -> str:
        pezzi = [self.ref]
        if self.substituted:
            pezzi.append("(era %s)" % self.swapped_from)
        if not self.builds_geometry:
            pezzi.append("[contenitore]")
        if self.link is not None:
            pezzi.append(self.link.describe())
        return "%s: %s" % (self.id, " ".join(pezzi))


@dataclass
class ResolvedComposition:
    """Il piano risolto, con accanto il piano di partenza e le diagnosi."""

    graph: CompositionGraph
    registry: Any = None
    style: str = "low_poly"
    detail_level: int = 2
    seed: int = 0
    budget: Any = None
    root: str = ""
    nodes: dict[str, ResolvedNode] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)     # visita deterministica
    unresolved: list[str] = field(default_factory=list)
    effects: list[tuple[str, EffectRequest]] = field(default_factory=list)
    report: Report = field(default_factory=Report)

    # ------------------------------------------------------------- lettura #
    @property
    def ok(self) -> bool:
        """Nessun errore fatale. Gli avvisi non impediscono di costruire."""
        return self.report.ok

    @property
    def diagnostics(self) -> list:
        return self.report.sorted()

    @property
    def warnings(self) -> list:
        return [d for d in self.report.entries if not d.fatal]

    def node(self, id: str) -> ResolvedNode | None:
        return self.nodes.get(id)

    def children(self, id: str) -> list[ResolvedNode]:
        nodo = self.nodes.get(id)
        return [self.nodes[c] for c in nodo.children if c in self.nodes] if nodo else []

    def walk(self) -> Iterator[ResolvedNode]:
        for id in self.order:
            if id in self.nodes:
                yield self.nodes[id]

    def refs(self) -> list[str]:
        """I componenti effettivamente usati, in ordine di visita."""
        return [self.nodes[id].ref for id in self.order if id in self.nodes]

    def geometry(self) -> list[ResolvedNode]:
        """Solo i nodi che producono una mesh: i contenitori non contano."""
        return [n for n in self.walk() if n.builds_geometry]

    def substitutions(self) -> dict[str, tuple[str, str]]:
        return {n.id: (n.swapped_from, n.ref) for n in self.walk() if n.substituted}

    def __len__(self) -> int:
        return len(self.nodes)

    def __contains__(self, id: str) -> bool:
        return id in self.nodes

    # ---------------------------------------------------------- descrizione #
    def describe(self) -> str:
        righe = []
        for nodo in self.walk():
            righe.append("%s%s" % ("  " * nodo.depth, nodo.describe()))
        if self.unresolved:
            righe.append("non risolti: %s" % ", ".join(self.unresolved))
        return "\n".join(righe)

    def to_dict(self) -> dict:
        def esporta(nodo: ResolvedNode) -> dict:
            fuori: dict[str, Any] = {"id": nodo.id, "ref": nodo.ref}
            if nodo.substituted:
                fuori["was"] = nodo.swapped_from
            if not nodo.builds_geometry:
                fuori["container"] = True
            if nodo.link is not None:
                fuori["link"] = {k: v for k, v in
                                 (("socket", nodo.link.parent_socket),
                                  ("capability", nodo.link.capability),
                                  ("side", nodo.link.side),
                                  ("own_socket", nodo.link.own_socket),
                                  ("how", nodo.link.how),
                                  ("scale_mode", nodo.link.scale_mode)) if v}
            if nodo.values:
                fuori["params"] = {k: (v if not isinstance(v, tuple) else list(v))
                                   for k, v in sorted(nodo.values.items())}
                fuori["sources"] = {k: nodo.sources[k].source
                                    for k in sorted(nodo.sources)}
            figli = [esporta(c) for c in self.children(nodo.id)]
            if figli:
                fuori["children"] = figli
            return fuori

        radice = self.nodes.get(self.root)
        return {"style": self.style, "detail_level": self.detail_level,
                "seed": self.seed,
                "root": esporta(radice) if radice is not None else {},
                "unresolved": list(self.unresolved),
                "diagnostics": [{"code": d.code, "message": d.message,
                                 "where": d.where, "severity": d.severity}
                                for d in self.diagnostics]}
