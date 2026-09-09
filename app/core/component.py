"""Component e Attachment: le due primitive universali.

Il core conosce **un solo tipo di nodo**. Un torso, una ruota, un pianeta, un
piercing, un ramo, un elmo sono tutti `Component`. Quello che li distingue non
e' una classe: e' come sono *montati*.

## Decoration non esiste come tipo

Una decorazione e' un componente montato con un `Attachment` che dichiara:

    optional=True      si puo' non metterla
    on_request=True    non compare con il detail_level, compare se la chiedi
    replaces=False     non prende il posto di niente

Cosi' `Testa -> Elmo -> Visiera -> Luce` e `Casa -> Finestra -> Telaio ->
Maniglia` girano sulla stessa identica macchina, e una decorazione puo'
contenere componenti — che e' quello che serve — senza una riga di codice
dedicata.

## Il core non sa costruire niente

`Component.build` e' una funzione qualunque che restituisce un `Piece`. Puo'
usare il kernel poligonale, l'SDF, il marching cubes, una mesh importata o
qualcosa che ancora non esiste. Il contratto e' **l'uscita**, non il metodo: e'
questo che permette a un `humanoid_lowpoly` e a un `humanoid_realistic` di
convivere senza che il core sappia in che cosa differiscono.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

import trimesh

from app.core.capability import Capability, Mount, Requirement
from app.core.constraints import Constraint
from app.core.params import ParamSpec
from app.core.socket import DEFAULT_INSERT, Socket


@dataclass
class BuildContext:
    """Quello che una regola puo' sapere del contesto in cui viene costruita.

    Passato a `build` perche' un plugin possa adattarsi — meno sezioni se il
    budget e' stretto, meno dettaglio se il livello e' basso — senza che il
    core gli imponga come.
    """

    style: str = "low_poly"
    detail_level: int = 2
    depth: int = 0
    seed: int = 0
    budget: Any = None
    path: str = ""
    report: Any = None
    # chi sta costruendo e dentro cosa. Servono a un plugin che voglia
    # adattarsi al contesto; non c'e' niente di globale qui dentro.
    node: Any = None
    composition: Any = None
    parent_piece: Any = None

    def deeper(self, path: str) -> "BuildContext":
        return BuildContext(style=self.style, detail_level=self.detail_level,
                            depth=self.depth + 1, seed=self.seed,
                            budget=self.budget, path=path, report=self.report,
                            composition=self.composition)


@dataclass
class Piece:
    """Cio' che una regola restituisce: geometria e punti di attacco.

    `mesh` puo' essere `None`: un componente che esiste solo per contenerne
    altri — il corpo di un umanoide, la radice di un albero di composizione —
    non ha geometria propria, ha figli.
    """

    mesh: trimesh.Trimesh | None = None
    sockets: dict[str, Socket] = field(default_factory=dict)
    material: str = ""
    tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def socket(self, name: str) -> Socket | None:
        return self.sockets.get(name)

    @property
    def triangles(self) -> int:
        return 0 if self.mesh is None else len(self.mesh.faces)


@dataclass
class Attachment:
    """Come un componente sta appeso a un altro.

    Il significato sta qui, non nel tipo del componente: gli stessi
    `Component` diventano struttura o decorazione a seconda di come si montano.
    """

    id: str
    component: str                       # riferimento qualificato "plugin:nome"
    requirement: Requirement | None = None
    own_socket: str = "base"

    # quando compare
    level: int = 2                       # dal detail_level in poi
    optional: bool = False               # si puo' omettere senza rompere niente
    on_request: bool = False             # non con il livello: solo se chiesto
    replaces: str = ""                   # id del fratello che sostituisce
    replaces_parent: bool = False        # prende il posto della geometria di chi lo contiene

    # dove si posa, quando non e' su chi lo contiene nel piano: il percorso
    # di una parte gia' prevista da qualcun altro. Vedi `deferred`.
    on: str = ""

    # come si posa
    scale_mode: str = "none"
    insert: float = DEFAULT_INSERT
    roll: float = 0.0

    params: dict[str, Any] = field(default_factory=dict)
    material: str = ""
    tags: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        self.tags = frozenset(self.tags)
        if self.requirement is None:
            self.requirement = Requirement()

    @property
    def deferred(self) -> bool:
        """Va appeso a un nodo che ancora non esiste quando lo si incontra.

        `on` e' il percorso di una parte **gia' prevista** da qualcun altro:
        `"testa/naso"` vuol dire «il naso che la testa dichiara da se'», non
        «un naso». Senza questo, chi volesse un piercing dovrebbe rimettere il
        naso nel piano — e allora sarebbe il suo naso a vincere su quello
        dichiarato, con tutti i parametri da riscrivere a mano.

        Il collegamento resta quello di sempre: quando il bersaglio esiste,
        questo attacco viene risolto come qualunque altro figlio suo.
        """
        return bool(self.on)

    @property
    def structural(self) -> bool:
        """Fa parte di cio' che l'oggetto e', non di cio' che porta."""
        return not (self.optional or self.on_request)

    @property
    def substitutes(self) -> bool:
        """Sostituisce qualcosa: il padre, oppure un fratello.

        Due sostituzioni diverse, e vanno tenute distinte. `replaces_parent`
        dice «quando compaio io, la geometria di chi mi contiene non si
        costruisce»: e' come un torso che a un certo livello diventa bacino piu'
        petto, e non deve restare anche il torso intero sotto. `replaces` invece
        nomina un fratello, e lo toglie dall'espansione.
        """
        return bool(self.replaces_parent or self.replaces)

    def wanted_at(self, detail_level: int, requested: bool = False) -> bool:
        """Compare a questo livello di dettaglio?

        Una decorazione chiesta esplicitamente entra **anche** se il livello
        non la prevede: chi domanda "una testa semplice con un piercing" non
        vuole che tutto l'albero diventi dettagliato per avere il piercing.
        """
        if self.on_request:
            return requested
        return self.level <= detail_level


@dataclass
class Component:
    """Una regola che sa costruire una parte, e che cosa ci si attacca."""

    id: str                                          # "plugin:nome"
    build: Callable[[dict, BuildContext], Piece]
    params: dict[str, ParamSpec] = field(default_factory=dict)
    children: Callable[[dict, BuildContext], list[Attachment]] | None = None
    constraints: tuple[Constraint, ...] = ()
    provides: tuple[Capability, ...] = ()            # cio' che il componente E'
    mounts: tuple[Mount, ...] = ()                   # gli innesti che ESPONE
    tags: frozenset[str] = field(default_factory=frozenset)
    role: str = ""                                   # per gli effetti di proporzione
    requires: frozenset[str] = field(default_factory=frozenset)   # controlli geometrici
    material: str = "default"
    description: str = ""
    styles: frozenset[str] = field(default_factory=frozenset)   # vuoto = qualunque

    def __post_init__(self) -> None:
        self.tags = frozenset(self.tags)
        self.styles = frozenset(self.styles)
        self.requires = frozenset(self.requires)
        self.provides = tuple(c if isinstance(c, Capability) else Capability(str(c))
                              for c in self.provides)
        self.mounts = tuple(m if isinstance(m, Mount) else Mount(str(m))
                            for m in self.mounts)
        self.constraints = tuple(self.constraints)

    # ------------------------------------------------------------- lettura #
    @property
    def plugin(self) -> str:
        return self.id.partition(":")[0]

    @property
    def name(self) -> str:
        return self.id.partition(":")[2] or self.id

    def provides_capability(self, name: str) -> bool:
        return any(c.name == name for c in self.provides)

    def accepts(self, capability: str = "", side: str = "",
                tags=()) -> bool:
        """Espone un innesto per questa capability?"""
        return any(m.matches(capability, side, tags) for m in self.mounts)

    def supports_style(self, style: str) -> bool:
        """Vuoto significa "qualunque": un componente non deve dichiarare gli
        stili per essere usabile, deve dichiararli per escluderne qualcuno."""
        return not self.styles or style in self.styles

    def expand(self, values: dict, ctx: BuildContext,
               requested: Iterable[str] = ()) -> list[Attachment]:
        """I figli che compaiono a questo livello, piu' quelli chiesti."""
        if self.children is None:
            return []
        voluti = set(requested)
        return [c for c in self.children(values, ctx)
                if c.wanted_at(ctx.detail_level, c.id in voluti)]

    def describe(self) -> str:
        capacita = ", ".join(str(c) for c in self.provides) or "nessuna"
        return "%s [%s] fornisce: %s" % (self.id, ", ".join(sorted(self.tags)) or "-",
                                         capacita)
