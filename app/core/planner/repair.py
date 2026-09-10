"""Le diagnosi, ridotte a qualcosa che si puo' rimandare a un modello.

Una correzione, e una sola. Perche' funzioni, cio' che si rimanda deve dire
tre cose e nessun'altra:

    che cosa non ha funzionato        'creature:dragon_head' non si attacca
    perche'                           l'innesto accetta 'opening'
    che cosa c'e' al suo posto        humanoid:head, creature:frog_head

La terza e' quella che fa la differenza. Un modello a cui si dice soltanto
«sbagliato» prova un'altra cosa a caso; un modello a cui si danno le
alternative **che esistono davvero** sceglie fra quelle. Le alternative non le
inventa questo file: le mette gia' il resolver dentro ogni diagnosi, perche' e'
lui che ha appena guardato nel registry.

## Cosa non si manda indietro

Non si manda il codice, non si mandano i moduli, non si mandano le eccezioni
interne. Un percorso di file in un messaggio a un modello e' rumore nel caso
migliore e una fuga di informazione nel peggiore.

## Cosa vale la pena correggere

Solo cio' che una riscrittura del piano puo' cambiare: un componente che non
esiste, un innesto incompatibile, un effetto sconosciuto, un parametro che non
c'e'. Un budget esaurito o una compenetrazione non si correggono cambiando dei
nomi, e riproporli spenderebbe la correzione per niente.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

MAX_VOCI = 8
MAX_ALTERNATIVE = 5

# Le diagnosi che una riscrittura del piano puo' davvero risolvere.
CORREGGIBILI = (
    "COMPONENT_NOT_FOUND", "PLUGIN_NOT_FOUND", "AMBIGUOUS_COMPONENT",
    "AMBIGUOUS_PROVIDER", "PROVIDER_INCOMPATIBLE", "SOCKET_INCOMPATIBLE",
    "NO_MOUNTS", "STYLE_INCOMPATIBLE", "PLAN_STYLE_INCOMPATIBLE",
    "EFFECT_NOT_FOUND", "EFFECT_SCOPE_INVALID", "PARAM_NOT_FOUND",
    "NODE_NO_REF", "DUPLICATE_NODE_ID", "ON_TARGET_MISSING",
    "ON_TARGET_AMBIGUOUS", "PLAN_NO_ROOT", "PLAN_NOT_AN_OBJECT",
)

_RIFERIMENTO = re.compile(r"'([A-Za-z0-9_.\-]+:[A-Za-z0-9_.\-]+)'")


@dataclass
class RepairEntry:
    """Un difetto, in forma di dato: cosa, dove, e cosa c'e' al suo posto."""

    code: str
    message: str
    where: str = ""
    why: str = ""
    ref: str = ""
    alternatives: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "where": self.where,
                "why": self.why, "ref": self.ref,
                "alternatives": list(self.alternatives)}

    def to_text(self) -> str:
        righe = ["- %s" % self.message]
        if self.where:
            righe[0] += "  [%s]" % self.where
        if self.why:
            righe.append("    perche': %s" % self.why)
        if self.alternatives:
            righe.append("    al suo posto: %s" % ", ".join(self.alternatives))
        return "\n".join(righe)


@dataclass
class Repair:
    """Il riassunto da rimandare indietro. Vuoto vuol dire: non riprovare."""

    entries: list[RepairEntry] = field(default_factory=list)

    @property
    def worth_retrying(self) -> bool:
        """C'e' qualcosa che una riscrittura possa cambiare?

        Se non c'e', non si richiama il modello. Una chiamata che non puo'
        migliorare niente costa comunque, e finisce per far sembrare che il
        sistema stia provando quando sta solo aspettando.
        """
        return bool(self.entries)

    def to_dict(self) -> list[dict]:
        return [e.to_dict() for e in self.entries]

    def to_text(self) -> str:
        return "\n".join(e.to_text() for e in self.entries)

    def __len__(self) -> int:
        return len(self.entries)


def repair_brief(report, *, codes: tuple[str, ...] = CORREGGIBILI) -> Repair:
    """Da un `Report` al riassunto per la correzione.

    Solo le diagnosi fatali e solo quelle correggibili: un avviso e' una cosa
    che il sistema ha gia' risolto da solo, e rimandarlo indietro inviterebbe a
    cambiare un piano che andava bene.
    """
    voci: list[RepairEntry] = []
    visti: set[tuple[str, str]] = set()
    for diagnosi in getattr(report, "sorted", lambda: [])():
        if not getattr(diagnosi, "fatal", False) or diagnosi.code not in codes:
            continue
        firma = (diagnosi.code, diagnosi.where)
        if firma in visti:
            continue
        visti.add(firma)
        voci.append(RepairEntry(
            code=diagnosi.code, message=diagnosi.message,
            where=diagnosi.where, why=getattr(diagnosi, "why", ""),
            ref=_riferimento(diagnosi),
            alternatives=tuple(getattr(diagnosi, "alternatives", ())
                               [:MAX_ALTERNATIVE])))
        if len(voci) >= MAX_VOCI:
            break
    return Repair(entries=voci)


def _riferimento(diagnosi) -> str:
    """Il componente di cui la diagnosi parla, se il messaggio lo nomina.

    Serve al planner finto, che deve poter sostituire **quel** riferimento
    senza interpretare una frase. Un modello vero legge il messaggio; un
    programma ha bisogno del nome in un campo.
    """
    trovato = _RIFERIMENTO.search(diagnosi.message or "")
    return trovato.group(1) if trovato else ""


# --------------------------------------------------------------------------- #
# Quale dei due piani e' migliore
# --------------------------------------------------------------------------- #
# I difetti, in ordine di gravita'. Sono pesi, non soglie: servono a mettere in
# fila due piani in modo ripetibile, non a dire quanto vale un modello.
#
# Distanziati perche' una categoria non possa essere pareggiata dalla somma di
# quelle sotto: dieci parametri fuori scala restano meno gravi di un pezzo che
# non si attacca, ed e' giusto cosi' — il primo lo aggiusta il componente, il
# secondo lascia un buco nel modello.
PESI = {
    "unresolved": 1000,        # un nodo che non e' entrato nel modello
    "fatal": 500,              # una diagnosi che ferma qualcosa
    "attachment": 250,         # un innesto rimasto senza risposta
    "parameter": 40,           # un nome di parametro che non esiste
    "budget": 20,              # si e' costruito meno di quanto chiesto
    "optional": 5,             # un accessorio lasciato fuori
}

_ATTACCO = ("SOCKET_INCOMPATIBLE", "PROVIDER_INCOMPATIBLE", "NO_MOUNTS",
            "ON_TARGET_MISSING", "ON_TARGET_AMBIGUOUS")
_PARAMETRO = ("PARAM_NOT_FOUND", "EFFECT_PARAM_NOT_FOUND", "PARAM_OUT_OF_RANGE",
              "CONSTRAINT_VIOLATED")
_BUDGET = ("BUDGET_EXCEEDED", "BUDGET_STOPPED", "MOUNT_CROWDED")


@dataclass(frozen=True)
class PlanScore:
    """Quanto un piano e' andato storto. Piu' basso e' meglio.

    Non e' un giudizio di qualita' e non prova a esserlo: non sa se un modello
    e' bello, sa contare cio' che non ha funzionato. Serve a una domanda sola —
    «la correzione ha migliorato le cose?» — e a quella risponde con dei numeri
    che due esecuzioni danno identici.

    Un modello linguistico non entra qui dentro. Se un giorno servisse un
    confronto piu' fine, sara' comunque fatto di conteggi.
    """

    unresolved: int = 0
    fatal: int = 0
    attachment: int = 0
    parameter: int = 0
    budget: int = 0
    optional: int = 0

    @property
    def total(self) -> int:
        return sum(PESI[nome] * getattr(self, nome) for nome in PESI)

    def describe(self) -> str:
        difetti = ["%s=%d" % (n, getattr(self, n)) for n in PESI
                   if getattr(self, n)]
        return "%d (%s)" % (self.total, ", ".join(difetti) or "niente")

    def __lt__(self, altro: "PlanScore") -> bool:
        return self.total < altro.total

    def __ge__(self, altro: "PlanScore") -> bool:
        return self.total >= altro.total


def plan_score(report, resolved=None) -> PlanScore:
    """Il punteggio di un piano: quanti difetti, e di che genere.

    Si guardano due cose. Il **referto**, che dice cosa non ha funzionato; e il
    **risolto**, che dice quanti pezzi sono rimasti fuori — un piano che
    risolve dieci nodi su dodici non e' come uno che ne risolve due su dodici,
    e il referto da solo non lo direbbe.
    """
    conta = {nome: 0 for nome in PESI}
    for diagnosi in getattr(report, "entries", ()) or ():
        codice = diagnosi.code
        if codice in _ATTACCO and diagnosi.fatal:
            conta["attachment"] += 1
        elif codice in _PARAMETRO:
            conta["parameter"] += 1
        elif codice in _BUDGET:
            conta["budget"] += 1
        elif getattr(diagnosi, "fatal", False):
            conta["fatal"] += 1
    conta["unresolved"] = len(getattr(resolved, "unresolved", ()) or ())
    return PlanScore(**conta)
