"""Capability: il contratto per nome, non per categoria.

Il core non sa che cosa sia una testa. Sa che un componente **fornisce**
`head_mount` e che un altro **richiede** `head_mount`, e che quindi i due
possono stare insieme. Se domani qualcuno inventa il `quantum_crystal_mount`,
il core non cambia di una riga.

Il motivo per cui questo modulo esiste separato dai socket: la compatibilita' e'
una domanda *semantica* — «questi due possono parlarsi?» — mentre il socket e'
una risposta *geometrica* — «dove, in che verso, quanto grande». Tenerle nello
stesso posto porta prima o poi a decidere la compatibilita' guardando la
posizione, che e' esattamente lo sbaglio da evitare.

## Come si sceglie fra piu' candidati

`Requirement.score(socket)` restituisce un punteggio, non un si'/no. Serve
perche' i livelli di risoluzione della specifica sono cinque, in ordine di
preferenza, e un ordine si esprime con un numero:

    5  id di socket esatto
    4  capability + lato giusto
    3  capability + tag compatibili
    2  capability
    1  ripiego: il socket accetta il requisito ma senza corrispondenze forti
   -1  incompatibile

**Il punteggio non decide da solo se due cose possono stare insieme.** Prima si
filtra chi e' compatibile, poi si ordina per qualita'. Un innesto con un
punteggio alto ma incompatibile resta incompatibile: l'ordine

    filtra gli incompatibili  ->  ordina i compatibili  ->  prendi il primo

non e' un dettaglio implementativo, e' cio' che impedisce di attaccare una cosa
qualunque a un posto qualunque solo perche' era il meno peggio.

## Il ripiego va concesso, non dedotto

`FALLBACK` non vuol dire "va bene lo stesso". Vuol dire "il contratto ammette
un'approssimazione". Un requisito che chiede il lato sinistro e trova solo il
destro **non** si attacca, a meno che qualcuno lo abbia dichiarato: o chi chiede
(`Requirement.allow_fallback`) o chi offre (`Mount.allow_fallback`). Senza
questa regola, "nessuna richiesta resta senza risposta" degenera in "attacca
comunque qualcosa da qualche parte", che e' peggio di un pezzo mancante: un
pezzo mancante si vede, un pezzo attaccato nel posto sbagliato sembra voluto.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

# Punteggi dei livelli di risoluzione. Nominati, perche' un 4 sparso nel codice
# non dice niente a nessuno.
EXACT_ID = 5
CAPABILITY_AND_SIDE = 4
CAPABILITY_AND_TAGS = 3
CAPABILITY = 2
FALLBACK = 1
INCOMPATIBLE = -1

# Lati riconosciuti. "" vuol dire "non mi interessa", non "centro".
SIDES = ("l", "r", "center", "top", "bottom", "front", "back")


def _frozen(values: Iterable[str] | None) -> frozenset[str]:
    return frozenset(values or ())


@dataclass(frozen=True)
class Capability:
    """Una cosa che un componente sa offrire o accettare.

    E' solo un nome piu' dei tag. Nessuna gerarchia obbligatoria: se qualcuno
    vuole dire che `dragon_head_mount` e' un `head_mount`, lo dichiara
    aggiungendo entrambi, non ereditando da una classe.
    """

    name: str
    tags: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        object.__setattr__(self, "tags", _frozen(self.tags))

    def __str__(self) -> str:
        return self.name if not self.tags else "%s{%s}" % (self.name,
                                                           ",".join(sorted(self.tags)))


@dataclass(frozen=True)
class Requirement:
    """Che cosa un attacco cerca.

    `socket_id` e' una preferenza, non un obbligo: se quel nome esiste vince,
    altrimenti si va per capability. E' cio' che permette a un braccio scritto
    per l'umanoide di attaccarsi a un torso di pesce, che il nome `shoulder_l`
    non ce l'ha ma un attacco per arti a sinistra si'.
    """

    capability: str = ""
    socket_id: str = ""
    side: str = ""
    tags: frozenset[str] = field(default_factory=frozenset)
    description: str = ""
    # accetto un ripiego? No, salvo dichiarazione contraria. Vedi la nota sul
    # ripiego in fondo al modulo: senza questo permesso, "attaccalo comunque
    # da qualche parte" diventa la regola invece dell'eccezione.
    allow_fallback: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "tags", _frozen(self.tags))

    def score(self, socket) -> int:
        """Quanto bene questo socket soddisfa il requisito. -1 = per niente."""
        if self.socket_id and socket.name == self.socket_id:
            return EXACT_ID

        offerte = {c.name for c in socket.capabilities}
        if self.capability and self.capability not in offerte:
            return INCOMPATIBLE
        if not self.capability and not self.socket_id:
            return FALLBACK          # nessuna richiesta: va bene qualunque cosa
        if not self.capability:
            return INCOMPATIBLE      # chiedeva un id preciso e non c'e'

        if self.side and socket.side == self.side:
            return CAPABILITY_AND_SIDE
        if self.side and socket.side and socket.side != self.side:
            # lato sbagliato: compatibile, ma e' l'ultima scelta
            return FALLBACK
        if self.tags and self.tags <= socket.all_tags():
            return CAPABILITY_AND_TAGS
        return CAPABILITY

    def describe(self) -> str:
        pezzi = []
        if self.socket_id:
            pezzi.append("socket '%s'" % self.socket_id)
        if self.capability:
            pezzi.append("capability '%s'" % self.capability)
        if self.side:
            pezzi.append("lato '%s'" % self.side)
        if self.tags:
            pezzi.append("tag %s" % ",".join(sorted(self.tags)))
        return " + ".join(pezzi) or "qualunque attacco"


@dataclass(frozen=True)
class Mount:
    """Un innesto **dichiarato**: cosa accetta, non dove sta.

    Serve al registry, che deve poter rispondere a «chi ha un attacco per una
    testa?» senza costruire niente. I socket veri nascono dentro `build` e
    portano posizione, verso e raggio: informazioni che esistono solo quando la
    geometria esiste. Questa e' la meta' non geometrica, quella che si puo'
    scrivere nel contratto e indicizzare a freddo.

    Il prezzo e' che la dichiarazione puo' divergere dalla realta' — un
    componente che dichiara `head_mount` e poi non lo costruisce. Verificarlo
    tocca al build layer, che ha in mano il `Piece`; qui si registra cio' che il
    componente promette.
    """

    capability: str
    socket_id: str = ""
    side: str = ""
    tags: frozenset[str] = field(default_factory=frozenset)
    description: str = ""
    # Quanti componenti accetta questo innesto:
    #     1   uno solo (il caso normale)
    #     N   al massimo N
    #     0   quanti se ne vuole, tipico di una superficie
    # Uno, salvo dichiarazione contraria: due pezzi nello stesso posto sono due
    # pezzi compenetrati, e nessuno se ne accorge finche' non guarda il modello.
    # E' una capienza **dichiarata**, non misurata: peso, volume e ingombro
    # reale sono cose che solo la geometria sa, e stanno nel build layer.
    capacity: int = 1
    # questo innesto accetta chi non lo soddisfa del tutto? Un attacco di
    # servizio, una superficie generica: cose dichiarate tali, non dedotte.
    allow_fallback: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "tags", _frozen(self.tags))

    # --- la stessa superficie di lettura di un `Socket` ------------------- #
    # `Requirement.score` sa gia' misurare un socket. Facendo in modo che un
    # `Mount` risponda alle stesse tre domande, la **scala di risoluzione e' una
    # sola**: quella che il resolver usa a freddo sulle dichiarazioni e quella
    # che il builder usera' a caldo sui socket veri. Due funzioni di punteggio
    # divergerebbero al primo caso particolare.
    @property
    def name(self) -> str:
        return self.socket_id

    @property
    def capabilities(self) -> tuple["Capability", ...]:
        return (Capability(self.capability, self.tags),) if self.capability else ()

    def all_tags(self) -> frozenset[str]:
        return self.tags

    def matches(self, capability: str = "", side: str = "",
                tags: Iterable[str] | None = None) -> bool:
        """Corrisponde a una domanda del registry? Vuoto significa «non filtro»."""
        if capability and self.capability != capability:
            return False
        # un innesto senza lato dichiarato va bene per qualunque lato: e' una
        # domanda di disponibilita', non una scelta. Solo una contraddizione
        # esplicita — chiedo sinistra, il componente ha solo destra — esclude.
        if side and self.side and self.side != side:
            return False
        return _frozen(tags) <= self.tags

    def __str__(self) -> str:
        pezzi = [self.capability]
        if self.side:
            pezzi.append(self.side)
        if self.socket_id:
            pezzi.append("@%s" % self.socket_id)
        return " ".join(pezzi)


def mount(capability: str, socket_id: str = "", side: str = "",
          tags: Iterable[str] = (), description: str = "",
          capacity: int = 1, allow_fallback: bool = False) -> Mount:
    """Scorciatoia per dichiarare un innesto in un plugin."""
    return Mount(capability=capability, socket_id=socket_id, side=side,
                 tags=_frozen(tags), description=description, capacity=capacity,
                 allow_fallback=allow_fallback)


def best_match(requirement: Requirement, sockets: Iterable) -> tuple[object, int]:
    """Il socket che soddisfa meglio il requisito, con il suo punteggio.

    A parita' di punteggio vince il primo in ordine di nome: la scelta deve
    essere **deterministica**, altrimenti lo stesso piano darebbe modelli
    diversi a seconda dell'ordine di un dizionario.
    """
    migliore, punteggio = None, INCOMPATIBLE
    for socket in sorted(sockets, key=lambda s: s.name):
        valore = requirement.score(socket)
        if valore > punteggio:
            migliore, punteggio = socket, valore
    return migliore, punteggio
