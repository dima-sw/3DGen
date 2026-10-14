"""Effetti e stili: cio' che un plugin dichiara oltre ai componenti.

Un plugin non porta solo forme. Porta anche modi di deformarle (`lanky`,
`chunky`, `melted`) e modi di renderle (`low_poly`, `anime`). Il registry deve
poterli elencare come elenca i componenti, altrimenti l'unico vocabolario che
l'LLM vedrebbe sarebbe quello dei pezzi.

Qui ci sono le **dichiarazioni**, non le implementazioni:

    EffectSpec     che cosa un effetto si chiama, dove si applica, che
                   parametri accetta. Come si applichi e' del passo 5.
    StyleProfile   un insieme di numeri con un nome, che il core non
                   interpreta. Se domani "anime" volesse dire qualcosa che oggi
                   non esiste, aggiunge una chiave in `params` e il core non
                   cambia di una riga.

## Perche' `params` e' un dizionario libero negli stili

Perche' un `StyleProfile` con campi fissi — risoluzione, budget, smussatura —
sarebbe un contratto scritto guardando la pipeline di oggi. Uno stile
registrato da un plugin di terze parti puo' voler dire cose che qui non
sappiamo nominare. Il core garantisce identita' e ricerca; il significato dei
numeri appartiene a chi li legge.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from app.core.params import ParamSpec

# Ambiti su cui un effetto puo' agire. Sono gli stessi del `CompositionGraph`:
# un effetto dichiara dove sa applicarsi, il piano dichiara dove vuole
# applicarlo, e la verifica e' un confronto fra i due.
SCOPE_MODEL = "model"
SCOPE_PART = "part"
SCOPE_SUBTREE = "subtree"
SCOPE_ROLE = "role"
SCOPE_GROUP = "group"

SCOPES = (SCOPE_MODEL, SCOPE_PART, SCOPE_SUBTREE, SCOPE_ROLE, SCOPE_GROUP)

# Gli stadi, in ordine. L'ordine e' il contratto: cambiarlo cambia il risultato
# di ogni modello, e per questo sta scritto una volta sola.
#
#     structural   il grafo, prima che esista qualunque geometria
#     proportion   i **parametri**, prima del build: cambia cio' che si costruira'
#     local        i vertici di una parte
#     global       i vertici del modello intero
#     style        l'esagerazione del linguaggio visivo
#     final        posa, centratura, appoggio a terra
#
# La distinzione fra `proportion` e i tre stadi geometrici e' la piu'
# importante: una proporzione cambia **cosa** viene costruito, una deformazione
# cambia **cio' che e' stato costruito**. Confonderle da' modelli che sembrano
# giusti finche' non li si guarda da vicino.
STAGE_STRUCTURAL = "structural"
STAGE_PROPORTION = "proportion"
STAGE_LOCAL = "local"
STAGE_GLOBAL = "global"
STAGE_STYLE = "style"
STAGE_FINAL = "final"

STAGES = (STAGE_STRUCTURAL, STAGE_PROPORTION, STAGE_LOCAL, STAGE_GLOBAL,
          STAGE_STYLE, STAGE_FINAL)

# Gli stadi che lavorano sui parametri, prima che la geometria esista.
STAGES_BEFORE_GEOMETRY = (STAGE_STRUCTURAL, STAGE_PROPORTION)

# Che ne e' dei socket dopo che un effetto ha mosso i vertici. E' una domanda
# che sembra secondaria e non lo e': se la mesh si piega e i socket restano dove
# stavano, i figli si attaccano nel vuoto — ed e' un difetto che si vede solo
# guardando il modello, mai in una diagnosi.
#
#     preserve     i socket seguono la stessa mappa dei vertici. E' automatico
#                  quando l'effetto dichiara `deform`: la stessa funzione muove
#                  gli uni e gli altri, e non possono separarsi.
#     recompute    l'effetto ricostruisce i socket da se'
#     invalidate   dopo l'effetto i socket non vogliono piu' dire niente
PRESERVE_SOCKETS = "preserve"
RECOMPUTE_SOCKETS = "recompute"
INVALIDATE_SOCKETS = "invalidate"

SOCKET_POLICIES = (PRESERVE_SOCKETS, RECOMPUTE_SOCKETS, INVALIDATE_SOCKETS)

# Cosa succede se un effetto fallisce.
FATAL = "fatal"                 # il modello non ha senso senza
RECOVERABLE = "recoverable"     # si scarta l'effetto, il modello resta
COSMETIC = "cosmetic"           # non valeva molto comunque


@dataclass(frozen=True)
class ParamRule:
    """Come un effetto cambia un parametro: dichiarato, non programmato.

    `expression` viene valutata dal solito motore sicuro con `value` (il valore
    attuale) e `amount` (l'intensita' chiesta) disponibili, piu' gli altri
    parametri numerici del componente. Il risultato **ripassa** dal `ParamSpec`,
    quindi un effetto non puo' portare un parametro fuori dal suo intervallo:
    puo' spingere, non sfondare.

    Il bersaglio si dichiara per **ruolo semantico**, non per nome: un effetto
    che allunga non deve sapere che in un plugin il parametro si chiama `length`
    e in un altro `lunghezza_totale`. Chi scrive il componente dichiara che quel
    numero e' una lunghezza, e l'effetto parla quel linguaggio.
    """

    expression: str = "value"
    param: str = ""                  # nome esatto, se proprio serve
    semantic_role: str = ""          # oppure: qualunque parametro con quel ruolo
    role: str = ""                   # solo sui componenti con questo ruolo
    tags: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        object.__setattr__(self, "tags", _frozen(self.tags))

    def wants_param(self, name: str, spec) -> bool:
        if self.param:
            return name == self.param
        if self.semantic_role:
            return getattr(spec, "semantic_role", "") == self.semantic_role
        return False

    def wants_node(self, component) -> bool:
        if self.role and getattr(component, "role", "") != self.role:
            return False
        return self.tags <= getattr(component, "tags", frozenset())

    def describe(self) -> str:
        dove = self.param or ("ruolo %s" % self.semantic_role) or "?"
        return "%s -> %s" % (dove, self.expression)


def _frozen(values: Iterable[str] | None) -> frozenset[str]:
    return frozenset(values or ())


@dataclass(frozen=True)
class ParamEffect:
    """Un parametro di un componente che **pilota** un effetto installato.

    E' il verso opposto di `ParamRule`, e le due insieme chiudono il cerchio:
    `ParamRule` dice come un effetto cambia un parametro, `ParamEffect` dice
    come un parametro chiede un effetto. Serve ai componenti la cui geometria
    non si puo' rigenerare — una mesh importata ha un solo stato — e che quindi
    non possono esprimere "piu' curvo" come un numero da ricostruire: lo
    esprimono come una deformazione, cioe' come la cosa che il sistema degli
    effetti sa gia' fare.

        {"curve": {"default": 0.0, "min": -1.0, "max": 1.0,
                   "effect": {"type": "fx:bend", "parameter": "amount"}}}

    Quello che questa dichiarazione **non** e': non e' un secondo motore di
    deformazione. Non porta codice, non porta un'espressione, non porta una
    matrice. Dice solo «il valore di questo parametro e' l'intensita' (o un
    parametro) di quell'effetto», e la traduzione in `EffectRequest` avviene
    nella `EffectPipeline` esistente, che poi lo valida come qualunque altro
    effetto chiesto dal piano: effetto inesistente, ambito non supportato,
    valore fuori intervallo sono le diagnostiche di prima.

    `neutral` e' il valore per cui **non** si chiede niente: senza, una testa
    con `curve` a zero porterebbe in giro una piega da zero gradi, e ogni
    modello avrebbe un effetto in programma che non fa nulla. Vuoto significa
    "chiedi sempre".
    """

    param: str                           # il parametro del componente
    type: str                            # l'id di un EffectSpec installato
    parameter: str = "amount"            # quale knob dell'effetto riceve il valore
    scope: str = SCOPE_PART              # dove si applica, con la sintassi degli ambiti
    neutral: float | None = None         # il valore per cui non si chiede nulla

    @property
    def drives_amount(self) -> bool:
        return self.parameter == "amount"

    def wanted(self, value: Any) -> bool:
        """Questo valore chiede davvero l'effetto?"""
        if self.neutral is None:
            return True
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return True
        return abs(float(value) - float(self.neutral)) > 1e-9

    def describe(self) -> str:
        return "%s -> %s.%s [%s]" % (self.param, self.type, self.parameter,
                                     self.scope)


@dataclass
class EffectSpec:
    """La dichiarazione di un effetto. Non la sua applicazione.

    `applies_to` elenca capability o tag su cui l'effetto ha senso: e' quello
    che permette a `effects_for` di rispondere senza che il core sappia cosa
    sia un umanoide. Vuoto vuol dire "su qualunque cosa" — la scelta giusta
    per una deformazione geometrica, che non ha bisogno di sapere cosa sta
    deformando.
    """

    id: str                                     # "plugin:lanky"
    name: str = ""
    description: str = ""
    stage: str = ""                             # uno di STAGES: dichiararlo e' d'obbligo
    scopes: tuple[str, ...] = ()                # vuoto = qualunque ambito
    params: dict[str, ParamSpec] = field(default_factory=dict)
    amount: ParamSpec | None = None             # l'intensita', con il suo intervallo
    applies_to: frozenset[str] = field(default_factory=frozenset)
    changes: tuple[ParamRule, ...] = ()         # se ci sono, e' un effetto di parametri
    conflicts: frozenset[str] = field(default_factory=frozenset)
    priority: int = 0                           # a parita' di stadio, chi va prima
    on_failure: str = RECOVERABLE
    socket_policy: str = PRESERVE_SOCKETS
    tags: frozenset[str] = field(default_factory=frozenset)
    # Due modi di dichiarare una deformazione, e il primo e' quello buono:
    #     deform(punti, ctx) -> punti     una mappa di punti
    #     apply(mesh, ctx)   -> mesh      una trasformazione qualunque
    # Con `deform` il builder muove vertici e socket con la stessa funzione, e
    # la coerenza non e' una convenzione da rispettare: e' impossibile romperla.
    deform: Any = None
    apply: Any = None

    def __post_init__(self) -> None:
        self.tags = _frozen(self.tags)
        self.applies_to = _frozen(self.applies_to)
        self.conflicts = _frozen(self.conflicts)
        self.scopes = tuple(self.scopes)
        self.changes = tuple(self.changes)
        self.name = self.name or self.local
        if self.amount is None:
            self.amount = ParamSpec(1.0, "ratio", min=0.0, max=1.0,
                                    description="intensita' dell'effetto")

    @property
    def moves_points(self) -> bool:
        """I socket si possono muovere con la stessa mappa dei vertici?"""
        return self.deform is not None and self.socket_policy == PRESERVE_SOCKETS

    def transform(self, mesh, ctx):
        """La mesh dopo l'effetto. `deform` se c'e', altrimenti `apply`."""
        if self.deform is not None:
            import numpy as np

            fuori = mesh.copy()
            fuori.vertices = self.deform(np.asarray(mesh.vertices, dtype=float), ctx)
            return fuori
        if self.apply is not None:
            return self.apply(mesh, ctx)
        return mesh

    def map_points(self, points, ctx):
        """Gli stessi punti, portati dove la deformazione li porterebbe."""
        if self.deform is None:
            return points
        import numpy as np

        return self.deform(np.asarray(points, dtype=float), ctx)

    @property
    def touches_parameters(self) -> bool:
        """Cambia cosa si costruira', invece di cio' che e' stato costruito."""
        return bool(self.changes)

    @property
    def geometric(self) -> bool:
        return self.stage not in STAGES_BEFORE_GEOMETRY

    def conflicts_with(self, other: "EffectSpec") -> bool:
        """Il conflitto e' simmetrico: basta che lo dichiari uno dei due."""
        return (other.local in self.conflicts or other.id in self.conflicts
                or self.local in other.conflicts or self.id in other.conflicts)

    @property
    def plugin(self) -> str:
        return self.id.partition(":")[0]

    @property
    def local(self) -> str:
        return self.id.partition(":")[2] or self.id

    def fits_scope(self, scope: str) -> bool:
        """Vuoto significa qualunque ambito. `part:testa` conta come `part`."""
        if not self.scopes or not scope:
            return True
        return scope.partition(":")[0] in self.scopes

    def fits(self, capability: str = "") -> bool:
        return not capability or not self.applies_to or capability in self.applies_to

    def describe(self) -> str:
        dove = ", ".join(self.scopes) or "qualunque ambito"
        return "%s (%s)" % (self.id, dove)


@dataclass
class StyleProfile:
    """Uno stile registrabile: un nome, e dei numeri che il core non legge.

    ## `extends`, e perche' si risolve leggendo e non registrando

    Uno stile puo' partire da un altro e cambiargli due numeri: `cartoon` che
    e' `low_poly` con la soglia di planarita' piu' bassa. La catena si risolve
    quando si **legge** un valore, non quando si registra il profilo, perche'
    al momento della registrazione il padre puo' non essere ancora arrivato —
    l'ordine dei plugin non e' garantito e non deve esserlo.

    Chi collega i profili e' il registry, che li vede tutti; qui c'e' solo il
    rimando. Un `extends` che non porta da nessuna parte non e' un errore: il
    profilo vale per i numeri che dichiara, come qualunque altro.
    """

    id: str                                     # "core:low_poly"
    name: str = ""
    description: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    extends: str = ""                           # l'id del profilo di partenza
    tags: frozenset[str] = field(default_factory=frozenset)
    base: "StyleProfile | None" = None          # collegato dal registry

    def __post_init__(self) -> None:
        self.tags = _frozen(self.tags)
        self.name = self.name or self.local

    def chain(self) -> list["StyleProfile"]:
        """Questo profilo e quelli da cui discende, dal piu' vicino."""
        fuori, corrente, visti = [], self, set()
        while corrente is not None and id(corrente) not in visti:
            visti.add(id(corrente))
            fuori.append(corrente)
            corrente = corrente.base
        return fuori

    @property
    def plugin(self) -> str:
        return self.id.partition(":")[0]

    @property
    def local(self) -> str:
        return self.id.partition(":")[2] or self.id

    def get(self, key: str, default: Any = None) -> Any:
        """Un numero dello stile, cercato anche in quello da cui discende."""
        for profilo in self.chain():
            if key in profilo.params:
                return profilo.params[key]
        return default

    def values(self) -> dict[str, Any]:
        """Tutti i numeri effettivi: i propri vincono su quelli ereditati."""
        fuori: dict[str, Any] = {}
        for profilo in reversed(self.chain()):
            fuori.update(profilo.params)
        return fuori

    def describe(self) -> str:
        radici = " < ".join(p.id for p in self.chain()[1:])
        return "%s [%s]%s" % (self.id,
                              ", ".join(sorted(self.values())) or "senza parametri",
                              " (da %s)" % radici if radici else "")
