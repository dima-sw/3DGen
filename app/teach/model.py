"""Il modello di una sessione di apprendimento. Separato da tutto il resto.

Un `TeachProject` non e' un modello e non e' un plugin: e' **il processo
attraverso cui 3DGen impara un concetto**. Per questo non entra in `.my3d` (che
rappresenta un modello generativo) e non entra in `.3dgenproj` (che rappresenta
un plugin in lavorazione): ha un formato suo, `.teach3d`.

## Le due meta', e perche' stanno separate

    ontologia      TeachNode: che cosa un drago **e'** — parti, sotto-parti,
                   count, mandatory/optional, importance, detail level, ruolo
    stato          NodeState: che cosa sappiamo del **coprirlo** — copertura,
                   candidati con le loro evidenze, la soluzione scelta, le
                   raccomandazioni dell'AI, i tentativi di generazione

Tenerle separate non e' ordine: e' la ragione per cui un secondo giro di
raffinamento puo' riscrivere la gerarchia senza perdere una decisione
validata, e per cui la copertura si puo' ricalcolare dopo **ogni**
installazione senza toccare l'ontologia. La milestone chiedeva «informazioni
equivalenti» per nodo (§2) e non una struttura unica: equivalenti lo sono, e
`TeachProject.tree()` le rimette insieme per chi deve soltanto leggerle.

## L'identita' di un nodo non e' l'id di un Component

`dragon.head.eye` e' un **percorso concettuale**: esiste prima che esista
un'implementazione, e sopravvive al fatto che quella implementazione sia un
componente dedicato, una `VariantRecipe`, un composite o un proxy. E' derivata
dai nomi — `genitore.slug(nome)` — con un suffisso numerico quando due fratelli
si chiamerebbero allo stesso modo. Un `Component` non ha copertura e un nodo
Teach non ha geometria: sono due cose diverse e si nominano in due modi diversi.

## I quattro stati sono quelli di V6

`VALIDATED` / `CANDIDATE` / `MISSING` / `PROXY` arrivano da
`app/authoring/model.py` e non vengono ridefiniti qui: V6 li ha rappresentati,
V7 li decide, e due elenchi di quattro stringhe che devono restare uguali sono
un elenco di troppo.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from app.authoring.model import CANDIDATE, COVERAGE, MISSING, PROXY, VALIDATED
from app.authoring.variant import VariantRecipe
from app.teach import errors
from app.teach.errors import TeachError

FORMAT_VERSION = 1
PROJECT_SUFFIX = ".teach3d"

# Limiti di forma della gerarchia. Non sono gusto: una decomposizione che
# arriva a trenta livelli o a mille nodi non e' un'ontologia, e' un modello che
# non si e' fermato (§8 della milestone).
MAX_DEPTH = 6
MAX_NODES = 120
MAX_COUNT = 64            # lo stesso tetto di `structural.MAX_STRUCTURAL_COUNT`

# Lo stato di completamento di un concetto.
LEARNING = "LEARNING"
LEARNED = "LEARNED"

# Da dove viene una soluzione.
FROM_LIBRARY = "library"       # un componente installato, cosi' com'e'
FROM_VARIANT = "variant"       # un componente installato piu' una ricetta
FROM_GENERATED = "generated"   # un componente nuovo, costruito e accettato

# Chi ha deciso. L'AI non compare, ed e' il punto di §14: raccomanda, non decide.
BY_USER = "user"
BY_DETERMINISTIC = "deterministic"

# Gli stati che una raccomandazione di idoneita' puo' avere (§14).
SUITABLE = "SUITABLE"
SUITABLE_WITH_PARAMETERS = "SUITABLE_WITH_PARAMETERS"
NEEDS_VISUAL_CHECK = "NEEDS_VISUAL_CHECK"
NOT_SUITABLE = "NOT_SUITABLE"
SUITABILITY = (SUITABLE, SUITABLE_WITH_PARAMETERS, NEEDS_VISUAL_CHECK,
               NOT_SUITABLE)

# I tre backend che un nodo mancante puo' prendere (§23). Sono una
# raccomandazione: l'utente li cambia, e il motore non ne preferisce uno per
# nessuna parola di dominio.
PROCEDURAL = "procedural_python"
DATA_MESH = "data_mesh"
COMPOSITE = "composite"
BACKENDS = (PROCEDURAL, DATA_MESH, COMPOSITE)

_SLUG = re.compile(r"[^a-z0-9]+")


def slug(value: str, fallback: str = "part") -> str:
    """Un nome leggibile ridotto a un segmento di percorso.

    Non e' `check_name`: quello **rifiuta** un nome sbagliato, e va bene per un
    nome che un umano ha scritto. Qui il nome arriva da un modello linguistico,
    quindi va normalizzato — e poi, se diventera' un nome di componente, dovra'
    passare comunque da `check_name`.
    """
    out = _SLUG.sub("_", str(value or "").strip().lower()).strip("_")
    return out or fallback


def _float(value, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(fallback)


def _strings(value) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(v) for v in value)


# --------------------------------------------------------------------------- #
# Le evidenze e i candidati
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Evidence:
    """Un pezzo di ragione, non un numero.

    §11 della milestone chiede esplicitamente che la copertura non sia una
    soglia su un punteggio. Un'evidenza e' percio' **nominata**: `role`,
    `capability`, `family`... e l'insieme dei nomi, non la loro somma, decide
    lo stato. Il `weight` serve solo a ordinare i candidati fra loro.
    """

    kind: str
    detail: str = ""
    weight: float = 0.0

    def describe(self) -> str:
        return "%s: %s" % (self.kind, self.detail) if self.detail else self.kind

    def to_dict(self) -> dict:
        return {"kind": self.kind, "detail": self.detail,
                "weight": round(float(self.weight), 4)}

    @classmethod
    def from_dict(cls, data: dict) -> "Evidence":
        return cls(kind=str(data.get("kind", "")),
                   detail=str(data.get("detail", "")),
                   weight=_float(data.get("weight", 0.0)))


@dataclass
class Candidate:
    """Un componente installato che potrebbe soddisfare un nodo, con il perche'."""

    component_id: str
    score: float = 0.0              # il punteggio di retrieval: partecipa, non decide
    verdict: str = MISSING          # la lettura di **questo** candidato da solo
    evidence: tuple[Evidence, ...] = ()
    reason: str = ""

    def __post_init__(self) -> None:
        self.evidence = tuple(self.evidence)
        self.score = _float(self.score)

    @property
    def kinds(self) -> frozenset[str]:
        return frozenset(e.kind for e in self.evidence)

    @property
    def weight(self) -> float:
        return sum(e.weight for e in self.evidence)

    def describe(self) -> str:
        return "%s  %.2f  %s  [%s]" % (self.component_id, self.score, self.verdict,
                                       ", ".join(sorted(self.kinds)))

    def to_dict(self) -> dict:
        return {"component": self.component_id, "score": round(self.score, 4),
                "verdict": self.verdict, "reason": self.reason,
                "evidence": [e.to_dict() for e in self.evidence]}

    @classmethod
    def from_dict(cls, data: dict) -> "Candidate":
        return cls(component_id=str(data.get("component", "")),
                   score=_float(data.get("score", 0.0)),
                   verdict=str(data.get("verdict", MISSING)),
                   reason=str(data.get("reason", "")),
                   evidence=tuple(Evidence.from_dict(e)
                                  for e in data.get("evidence", ())))


# --------------------------------------------------------------------------- #
# Le decisioni
# --------------------------------------------------------------------------- #
@dataclass
class Solution:
    """Cio' che soddisfa un nodo, e chi lo ha deciso.

    `ref` e' **sempre** un componente installato: una variant non e' un terzo
    tipo di cosa, e' quel componente piu' una ricetta (`recipe`), esattamente
    come in V6 §14. `origin` dice da dove arriva, `decided_by` chi ha deciso —
    e `BY_AI` non esiste, perche' §14 vieta che un modello possa scrivere
    `VALIDATED`.
    """

    ref: str
    recipe: str = ""
    params: dict = field(default_factory=dict)
    origin: str = FROM_LIBRARY
    decided_by: str = BY_USER
    note: str = ""

    def __post_init__(self) -> None:
        self.params = dict(self.params)

    def describe(self) -> str:
        pieces = [self.ref]
        if self.recipe:
            pieces.append("recipe " + self.recipe)
        if self.params:
            pieces.append(", ".join("%s=%s" % (k, v)
                                    for k, v in sorted(self.params.items())))
        pieces.append("%s/%s" % (self.origin, self.decided_by))
        return " | ".join(pieces)

    def to_dict(self) -> dict:
        data: dict[str, Any] = {"ref": self.ref, "origin": self.origin,
                                "decided_by": self.decided_by}
        if self.recipe:
            data["recipe"] = self.recipe
        if self.params:
            data["params"] = dict(self.params)
        if self.note:
            data["note"] = self.note
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Solution":
        return cls(ref=str(data.get("ref", "")),
                   recipe=str(data.get("recipe", "")),
                   params=dict(data.get("params", {})),
                   origin=str(data.get("origin", FROM_LIBRARY)),
                   decided_by=str(data.get("decided_by", BY_USER)),
                   note=str(data.get("note", "")))


@dataclass
class SuitabilityRecord:
    """La raccomandazione di un modello su un candidato. Non decide niente.

    Resta nel progetto perche' e' la memoria di perche' una scelta e' stata
    fatta (§19), e perche' un secondo giro non deve rifare la stessa domanda.
    """

    component_id: str
    status: str = NEEDS_VISUAL_CHECK
    confidence: float = 0.0
    reason: str = ""
    suggested_params: dict = field(default_factory=dict)
    deep: bool = False

    def __post_init__(self) -> None:
        self.suggested_params = dict(self.suggested_params)
        self.confidence = _float(self.confidence)
        if self.status not in SUITABILITY:
            self.status = NEEDS_VISUAL_CHECK

    @property
    def recommends(self) -> bool:
        """Raccomanda il candidato? Non lo valida: §14."""
        return self.status in (SUITABLE, SUITABLE_WITH_PARAMETERS)

    def describe(self) -> str:
        return "%s: %s (%.2f) %s" % (self.component_id, self.status,
                                     self.confidence, self.reason)

    def to_dict(self) -> dict:
        data: dict[str, Any] = {"component": self.component_id,
                                "status": self.status,
                                "confidence": round(self.confidence, 4),
                                "reason": self.reason}
        if self.suggested_params:
            data["suggested_params"] = dict(self.suggested_params)
        if self.deep:
            data["deep"] = True
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "SuitabilityRecord":
        return cls(component_id=str(data.get("component", "")),
                   status=str(data.get("status", NEEDS_VISUAL_CHECK)),
                   confidence=_float(data.get("confidence", 0.0)),
                   reason=str(data.get("reason", "")),
                   suggested_params=dict(data.get("suggested_params", {})),
                   deep=bool(data.get("deep", False)))


@dataclass
class Attempt:
    """Un giro di generazione su un nodo. La cronologia non si butta (§34)."""

    index: int = 0
    node: str = ""
    backend: str = ""
    artifact: str = ""
    ok: bool = False
    codes: tuple[str, ...] = ()
    notes: str = ""
    repaired_from: int = -1

    def __post_init__(self) -> None:
        self.codes = tuple(self.codes)

    def describe(self) -> str:
        return "tentativo %d (%s): %s%s" % (
            self.index, self.backend, "ok" if self.ok else "falliti: " +
            ", ".join(self.codes[:4]),
            "" if self.repaired_from < 0 else " [riparazione di %d]" % self.repaired_from)

    def to_dict(self) -> dict:
        data: dict[str, Any] = {"index": int(self.index), "node": self.node,
                                "backend": self.backend, "ok": bool(self.ok)}
        for key in ("artifact", "notes"):
            value = getattr(self, key)
            if value:
                data[key] = value
        if self.codes:
            data["codes"] = list(self.codes)
        if self.repaired_from >= 0:
            data["repaired_from"] = int(self.repaired_from)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Attempt":
        return cls(index=int(data.get("index", 0)), node=str(data.get("node", "")),
                   backend=str(data.get("backend", "")),
                   artifact=str(data.get("artifact", "")),
                   ok=bool(data.get("ok", False)),
                   codes=_strings(data.get("codes", ())),
                   notes=str(data.get("notes", "")),
                   repaired_from=int(data.get("repaired_from", -1)))


@dataclass
class ArtifactRecord:
    """Un artefatto in staging, come il progetto se lo ricorda.

    I file stanno su disco: qui sta **dove**, di che specie, se e' stato
    reso fidato e se e' stato accettato. `trusted` parte falso e ci resta
    finche' qualcuno non lo cambia esplicitamente (§30).
    """

    id: str
    node: str = ""
    kind: str = DATA_MESH
    path: str = ""
    files: tuple[str, ...] = ()
    trusted: bool = False
    accepted: bool = False
    plugin_id: str = ""
    warnings: tuple[str, ...] = ()
    notes: str = ""

    def __post_init__(self) -> None:
        self.files = tuple(self.files)
        self.warnings = tuple(self.warnings)

    @property
    def code(self) -> bool:
        """Contiene Python? Allora e' codice, e non e' dati (§30)."""
        return any(str(f).endswith(".py") for f in self.files)

    @property
    def available(self) -> bool:
        return bool(self.path) and Path(self.path).is_dir()

    def describe(self) -> str:
        return "%s | %s | %d file | %s%s" % (
            self.id, self.kind, len(self.files),
            "fidato" if self.trusted else "non fidato",
            " | accettato" if self.accepted else "")

    def to_dict(self) -> dict:
        data: dict[str, Any] = {"id": self.id, "node": self.node,
                                "kind": self.kind, "path": self.path,
                                "files": list(self.files),
                                "trusted": bool(self.trusted),
                                "accepted": bool(self.accepted)}
        for key in ("plugin_id", "notes"):
            value = getattr(self, key)
            if value:
                data[key] = value
        if self.warnings:
            data["warnings"] = list(self.warnings)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "ArtifactRecord":
        return cls(id=str(data.get("id", "")), node=str(data.get("node", "")),
                   kind=str(data.get("kind", DATA_MESH)),
                   path=str(data.get("path", "")),
                   files=_strings(data.get("files", ())),
                   trusted=bool(data.get("trusted", False)),
                   accepted=bool(data.get("accepted", False)),
                   plugin_id=str(data.get("plugin_id", "")),
                   warnings=_strings(data.get("warnings", ())),
                   notes=str(data.get("notes", "")))


@dataclass
class Exchange:
    """Un prompt generato e la risposta che e' tornata. Entrambe si tengono.

    §7 chiede di tenere le due risposte dell'ontologia nel progetto, §34 la
    cronologia dei tentativi, §44 i prompt e le risposte dopo una riapertura.
    E' lo stesso oggetto per tutte: un prompt e' un prompt.
    """

    kind: str
    node: str = ""
    prompt: str = ""
    response: str = ""
    mode: str = "manual"            # manual | provider
    provider: str = ""
    seconds: float = 0.0
    accepted: bool = False

    def describe(self) -> str:
        return "%s%s | %s | %d caratteri di prompt | %s" % (
            self.kind, (" " + self.node) if self.node else "", self.mode,
            len(self.prompt), "importata" if self.accepted else "in attesa")

    def to_dict(self) -> dict:
        data: dict[str, Any] = {"kind": self.kind, "mode": self.mode,
                                "accepted": bool(self.accepted)}
        for key in ("node", "prompt", "response", "provider"):
            value = getattr(self, key)
            if value:
                data[key] = value
        if self.seconds:
            data["seconds"] = round(float(self.seconds), 4)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Exchange":
        return cls(kind=str(data.get("kind", "")), node=str(data.get("node", "")),
                   prompt=str(data.get("prompt", "")),
                   response=str(data.get("response", "")),
                   mode=str(data.get("mode", "manual")),
                   provider=str(data.get("provider", "")),
                   seconds=_float(data.get("seconds", 0.0)),
                   accepted=bool(data.get("accepted", False)))


@dataclass
class NodeState:
    """Che cosa sappiamo del coprire un nodo. Mai che cosa il nodo e'."""

    coverage: str = MISSING
    candidates: tuple[Candidate, ...] = ()
    solution: Solution | None = None
    suitability: tuple[SuitabilityRecord, ...] = ()
    attempts: tuple[Attempt, ...] = ()
    backend: str = ""               # la scelta dell'utente, se l'ha fatta
    # L'utente ha deciso lui lo stato: un ricalcolo aggiorna i candidati e
    # **non** sovrascrive la copertura. E' §43: l'AI propone, l'utente decide,
    # e una decisione che un ricalcolo cancella non e' una decisione.
    locked: bool = False
    notes: str = ""
    asset: str = ""                 # un GLB fornito per questo nodo (§26)

    def __post_init__(self) -> None:
        self.candidates = tuple(self.candidates)
        self.suitability = tuple(self.suitability)
        self.attempts = tuple(self.attempts)
        if self.coverage not in COVERAGE:
            self.coverage = MISSING

    @property
    def best(self) -> Candidate | None:
        return self.candidates[0] if self.candidates else None

    def candidate(self, component_id: str) -> Candidate | None:
        for item in self.candidates:
            if item.component_id == component_id:
                return item
        return None

    def record_for(self, component_id: str) -> SuitabilityRecord | None:
        found = [r for r in self.suitability if r.component_id == component_id]
        return found[-1] if found else None

    def to_dict(self) -> dict:
        data: dict[str, Any] = {"coverage": self.coverage}
        if self.candidates:
            data["candidates"] = [c.to_dict() for c in self.candidates]
        if self.solution is not None:
            data["solution"] = self.solution.to_dict()
        if self.suitability:
            data["suitability"] = [r.to_dict() for r in self.suitability]
        if self.attempts:
            data["attempts"] = [a.to_dict() for a in self.attempts]
        for key in ("backend", "notes", "asset"):
            value = getattr(self, key)
            if value:
                data[key] = value
        if self.locked:
            data["locked"] = True
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "NodeState":
        solution = data.get("solution")
        return cls(coverage=str(data.get("coverage", MISSING)),
                   candidates=tuple(Candidate.from_dict(c)
                                    for c in data.get("candidates", ())),
                   solution=Solution.from_dict(solution) if solution else None,
                   suitability=tuple(SuitabilityRecord.from_dict(r)
                                     for r in data.get("suitability", ())),
                   attempts=tuple(Attempt.from_dict(a)
                                  for a in data.get("attempts", ())),
                   backend=str(data.get("backend", "")),
                   locked=bool(data.get("locked", False)),
                   notes=str(data.get("notes", "")),
                   asset=str(data.get("asset", "")))


# --------------------------------------------------------------------------- #
# L'ontologia
# --------------------------------------------------------------------------- #
@dataclass
class TeachNode:
    """Una parte del concetto. Nessuna geometria, nessun id di componente."""

    id: str
    name: str
    role: str = ""
    mandatory: bool = True
    count: int = 1
    importance: float = 0.5
    detail_level: int = 2
    description: str = ""
    children: tuple["TeachNode", ...] = ()

    def __post_init__(self) -> None:
        self.children = tuple(self.children)
        self.count = max(1, int(self.count))
        self.importance = min(1.0, max(0.0, _float(self.importance, 0.5)))
        self.detail_level = max(1, int(self.detail_level))

    # ------------------------------------------------------------- lettura #
    @property
    def leaf(self) -> bool:
        return not self.children

    @property
    def depth(self) -> int:
        """Quanti punti ci sono nel percorso: la radice e' 0."""
        return self.id.count(".")

    @property
    def weight(self) -> float:
        """Quanto pesa nel progresso: importanza per numero di istanze (§42)."""
        return max(0.0, self.importance) * max(1, self.count)

    def walk(self) -> Iterator["TeachNode"]:
        """Se stesso e la discendenza, in ordine stabile: padre prima dei figli.

        L'ordine conta: la copertura di un figlio guarda il candidato del
        **padre** (una capability che il padre accetta), quindi va calcolata
        dall'alto in basso. Vedi `app/teach/coverage.py`.
        """
        yield self
        for child in self.children:
            yield from child.walk()

    def find(self, node_id: str) -> "TeachNode | None":
        for node in self.walk():
            if node.id == node_id:
                return node
        return None

    def child(self, node_id: str) -> "TeachNode | None":
        for child in self.children:
            if child.id == node_id:
                return child
        return None

    def describe(self) -> str:
        return "%s%s%s %s" % (
            "  " * self.depth, self.name,
            "" if self.count == 1 else " x%d" % self.count,
            "mandatory" if self.mandatory else "optional")

    # --------------------------------------------------- serializzazione #
    def to_dict(self) -> dict:
        data: dict[str, Any] = {"id": self.id, "name": self.name,
                                "mandatory": bool(self.mandatory),
                                "count": int(self.count),
                                "importance": round(self.importance, 4),
                                "detail_level": int(self.detail_level)}
        for key in ("role", "description"):
            value = getattr(self, key)
            if value:
                data[key] = value
        if self.children:
            data["children"] = [c.to_dict() for c in self.children]
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "TeachNode":
        """Rilettura **fedele**: gli id sono quelli salvati, non ricalcolati.

        E' il contrario di `build_tree`, che li deriva dai nomi: una volta che
        una decisione e' appesa a `dragon.head.eye`, quell'id e' identita' e
        ricalcolarlo a ogni apertura vorrebbe dire perdere la decisione appena
        qualcuno rinomina un fratello.
        """
        if not isinstance(data, dict):
            raise TeachError(errors.PROJECT_INVALID, "un nodo e' un oggetto JSON")
        return cls(id=str(data.get("id", "")), name=str(data.get("name", "")),
                   role=str(data.get("role", "")),
                   mandatory=bool(data.get("mandatory", True)),
                   count=int(data.get("count", 1)),
                   importance=_float(data.get("importance", 0.5)),
                   detail_level=int(data.get("detail_level", 2)),
                   description=str(data.get("description", "")),
                   children=tuple(cls.from_dict(c)
                                  for c in data.get("children", ())))


# --------------------------------------------------------------------------- #
# Il progresso
# --------------------------------------------------------------------------- #
@dataclass
class Progress:
    """Il progresso, con la formula scritta accanto ai numeri (§42).

    Due misure, e nessuna delle due nasconde l'altra:

        `mandatory_percent`   per **peso**: somma di `importance * count` dei
                              nodi mandatory soddisfatti sul totale. E' la
                              misura primaria, perche' un occhio e una zampa
                              non valgono uguale e il modello lo ha dichiarato
        `mandatory_nodes`     per **conteggio**: quanti nodi su quanti. E' la
                              misura onesta quando le importanze sono tutte
                              uguali, cioe' quando il peso non dice niente
    """

    mandatory_total: int = 0
    mandatory_validated: int = 0
    optional_total: int = 0
    optional_validated: int = 0
    weight_total: float = 0.0
    weight_validated: float = 0.0
    counts: dict = field(default_factory=dict)

    @property
    def mandatory_percent(self) -> float:
        if self.weight_total <= 0.0:
            return 100.0 if self.mandatory_total == 0 else 0.0
        return 100.0 * self.weight_validated / self.weight_total

    @property
    def mandatory_node_percent(self) -> float:
        if not self.mandatory_total:
            return 100.0
        return 100.0 * self.mandatory_validated / self.mandatory_total

    @property
    def optional_percent(self) -> float:
        if not self.optional_total:
            return 100.0
        return 100.0 * self.optional_validated / self.optional_total

    @property
    def complete(self) -> bool:
        return self.mandatory_validated >= self.mandatory_total

    def describe(self) -> str:
        return ("mandatory %.0f%% (peso) %d/%d nodi | optional %.0f%% %d/%d | "
                "%s" % (self.mandatory_percent, self.mandatory_validated,
                        self.mandatory_total, self.optional_percent,
                        self.optional_validated, self.optional_total,
                        ", ".join("%s %d" % (k, self.counts.get(k, 0))
                                  for k in COVERAGE)))

    def to_dict(self) -> dict:
        return {"mandatory_total": self.mandatory_total,
                "mandatory_validated": self.mandatory_validated,
                "optional_total": self.optional_total,
                "optional_validated": self.optional_validated,
                "weight_total": round(self.weight_total, 4),
                "weight_validated": round(self.weight_validated, 4),
                "mandatory_percent": round(self.mandatory_percent, 2),
                "mandatory_node_percent": round(self.mandatory_node_percent, 2),
                "optional_percent": round(self.optional_percent, 2),
                "counts": dict(self.counts)}


# --------------------------------------------------------------------------- #
# Il progetto
# --------------------------------------------------------------------------- #
@dataclass
class TeachProject:
    """Il processo attraverso cui 3DGen impara un concetto. Serializzabile."""

    concept: str
    description: str = ""
    style: str = "low_poly"            # lo stile installato con cui si costruisce
    style_target: str = ""             # il testo che l'utente ha scritto
    detail_target: int = 2
    plugin_id: str = ""                # dove finira' la conoscenza nuova
    destination: str = ""
    root: TeachNode | None = None
    states: dict = field(default_factory=dict)
    recipes: dict = field(default_factory=dict)
    artifacts: dict = field(default_factory=dict)
    exchanges: tuple = ()
    # L'identita' dei plugin al momento dell'analisi: `id -> version#fingerprint`.
    # Serve a §45: un componente usato durante il Teach che dopo cambia si deve
    # poter rilevare, e i meccanismi per farlo sono quelli di V4.
    fingerprints: dict = field(default_factory=dict)
    completion: str = LEARNING
    root_component: str = ""
    passes: dict = field(default_factory=dict)
    notes: str = ""

    def __post_init__(self) -> None:
        self.concept = str(self.concept or "").strip()
        if not self.concept:
            raise TeachError(errors.PROJECT_INVALID,
                             "un progetto Teach deve nominare un concetto")
        self.plugin_id = self.plugin_id or slug(self.concept, "concept")
        self.exchanges = tuple(self.exchanges)
        self.detail_target = max(1, int(self.detail_target))

    # ------------------------------------------------------------- lettura #
    @property
    def learned(self) -> bool:
        return self.completion == LEARNED

    # **Un plugin per componente generato**, piu' uno per la radice. Tre
    # ragioni, e nessuna e' estetica:
    #
    #   1. un plugin **dati** rifiuta un `components` che nomini un `.py`
    #      (V4 §2), quindi un pezzo procedurale e un pezzo dichiarato in JSON
    #      non possono stare nella stessa cartella;
    #   2. mettere piu' componenti nello stesso plugin vorrebbe dire **fondere**
    #      due manifest a ogni accettazione, e una fusione di manifest e' un
    #      formato nuovo scritto per sbaglio;
    #   3. un pezzo che vive da solo si installa e si disinstalla da solo, ed e'
    #      cio' che serve a §39: imparare `wyvern` riusa l'ala del drago senza
    #      portarsi dietro il drago.
    #
    #     <base>_<nome>   un componente generato, o un composite intermedio
    #     <base>_pack     il composite della radice
    @property
    def pack_plugin(self) -> str:
        return "%s_pack" % self.plugin_id

    def plugin_named(self, name: str) -> str:
        """Il plugin di un componente generato per una parte di questo concetto."""
        return "%s_%s" % (self.plugin_id, slug(name, "part"))

    def owns(self, component_id: str) -> bool:
        """Questo componente e' conoscenza che questo Teach ha prodotto?

        Il prefisso e' la regola, e il limite dichiarato e' che un plugin
        preesistente chiamato `dragon_qualcosa` risulterebbe nostro. In cambio
        non serve tenere un elenco, che e' una cosa in piu' da aggiornare a
        ogni accettazione.
        """
        plugin = component_id.partition(":")[0]
        return plugin == self.pack_plugin or plugin.startswith(self.plugin_id + "_")

    def nodes(self) -> list[TeachNode]:
        return [] if self.root is None else list(self.root.walk())

    def node(self, node_id: str) -> TeachNode | None:
        return None if self.root is None else self.root.find(node_id)

    def require_node(self, node_id: str) -> TeachNode:
        node = self.node(node_id)
        if node is None:
            raise TeachError(errors.UNKNOWN_NODE,
                             "nessun nodo con id %r nella gerarchia" % node_id)
        return node

    def state(self, node_id: str) -> NodeState:
        """Lo stato di un nodo, creato vuoto se non c'era.

        Un nodo senza stato e' un nodo di cui non si sa niente, cioe'
        `MISSING`: rappresentarlo con l'assenza e con un oggetto vuoto sono la
        stessa cosa, e la seconda non obbliga chi legge a un `if`.
        """
        found = self.states.get(node_id)
        if found is None:
            found = NodeState()
            self.states[node_id] = found
        return found

    def parent_of(self, node_id: str) -> TeachNode | None:
        if self.root is None:
            return None
        for node in self.root.walk():
            if node.child(node_id) is not None:
                return node
        return None

    def coverage_of(self, node_id: str) -> str:
        return self.state(node_id).coverage

    def variant(self, name: str) -> VariantRecipe | None:
        return self.recipes.get(name)

    def artifact(self, artifact_id: str) -> ArtifactRecord | None:
        return self.artifacts.get(artifact_id)

    def exchange_of(self, kind: str, node: str = "") -> Exchange | None:
        """L'ultimo scambio di questa specie (e di questo nodo, se dato)."""
        found = [e for e in self.exchanges
                 if e.kind == kind and (not node or e.node == node)]
        return found[-1] if found else None

    def add_exchange(self, exchange: Exchange) -> Exchange:
        self.exchanges = self.exchanges + (exchange,)
        return exchange

    def tree(self) -> list[dict]:
        """Ontologia e stato rimessi insieme, una riga per nodo.

        E' la vista che la milestone disegna in §2 e §40: chi legge vuole il
        nodo **con** la sua copertura. Tenerle separate in memoria e unirle qui
        e' l'unico modo di avere entrambe le cose.
        """
        rows: list[dict] = []
        for node in self.nodes():
            state = self.state(node.id)
            rows.append({
                "id": node.id, "name": node.name, "role": node.role,
                "depth": node.depth, "mandatory": node.mandatory,
                "count": node.count, "importance": node.importance,
                "detail_level": node.detail_level,
                "description": node.description,
                "coverage": state.coverage,
                "solution": None if state.solution is None
                else state.solution.describe(),
                "candidates": [c.component_id for c in state.candidates],
                "locked": state.locked, "backend": state.backend})
        return rows

    def progress(self) -> Progress:
        """Le due misure di §42, piu' il conteggio per stato."""
        out = Progress(counts={k: 0 for k in COVERAGE})
        for node in self.nodes():
            state = self.state(node.id)
            out.counts[state.coverage] = out.counts.get(state.coverage, 0) + 1
            if not self.relevant(node):
                continue
            if node.mandatory:
                out.mandatory_total += 1
                out.weight_total += node.weight
                if state.coverage == VALIDATED:
                    out.mandatory_validated += 1
                    out.weight_validated += node.weight
            else:
                out.optional_total += 1
                if state.coverage == VALIDATED:
                    out.optional_validated += 1
        return out

    def relevant(self, node: TeachNode) -> bool:
        """Questo nodo serve al livello di dettaglio scelto? (§3)

        Il completamento richiede i mandatory **del livello richiesto**, non
        tutti: un'iride che il modello ha dichiarato a `detail_level 4` non
        blocca un drago chiesto a 2.
        """
        return int(node.detail_level) <= int(self.detail_target)

    def mandatory_missing(self) -> list[TeachNode]:
        """I nodi mandatory rilevanti che non hanno ancora una soluzione."""
        return [n for n in self.nodes()
                if n.mandatory and self.relevant(n)
                and self.state(n.id).coverage != VALIDATED]

    def concept_words(self) -> frozenset[str]:
        """Le parole che **il concetto** porta, senza i nomi delle parti.

        Serve alla copertura: un pezzo che nomina il concetto (un `dragon` nei
        tag) e' un pezzo di questo soggetto, mentre un pezzo che nomina solo la
        parte e' il pezzo giusto di un soggetto qualunque. Due cose diverse, e
        §10 le chiama `CANDIDATE` e `PROXY`.

        Lo **stile** non entra: `cartoon low-poly` non dice che cosa l'oggetto
        e', e lasciarlo entrare darebbe parentela a ogni pezzo che dichiara il
        tag `low_poly` — cioe' a mezza libreria, per una ragione che non
        riguarda il soggetto.
        """
        text = " ".join([self.concept, self.description])
        return frozenset(w for w in slug(text, "").split("_") if len(w) > 2)

    # --------------------------------------------------- serializzazione #
    def to_dict(self) -> dict:
        return {
            "format": FORMAT_VERSION, "concept": self.concept,
            "description": self.description, "style": self.style,
            "style_target": self.style_target,
            "detail_target": int(self.detail_target),
            "plugin_id": self.plugin_id, "destination": self.destination,
            "completion": self.completion,
            "root_component": self.root_component,
            "hierarchy": None if self.root is None else self.root.to_dict(),
            "states": {k: v.to_dict() for k, v in sorted(self.states.items())},
            "recipes": {k: v.to_dict() for k, v in sorted(self.recipes.items())},
            "artifacts": {k: v.to_dict()
                          for k, v in sorted(self.artifacts.items())},
            "exchanges": [e.to_dict() for e in self.exchanges],
            "fingerprints": dict(self.fingerprints),
            "passes": dict(self.passes), "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TeachProject":
        if not isinstance(data, dict):
            raise TeachError(errors.PROJECT_INVALID,
                             "un progetto Teach e' un oggetto JSON")
        version = int(data.get("format", 0) or 0)
        if version != FORMAT_VERSION:
            raise TeachError(errors.PROJECT_INVALID,
                             "formato %r non leggibile da questa versione "
                             "(attesa %d)" % (data.get("format"), FORMAT_VERSION))
        hierarchy = data.get("hierarchy")
        project = cls(concept=str(data.get("concept", "")),
                      description=str(data.get("description", "")),
                      style=str(data.get("style", "low_poly")),
                      style_target=str(data.get("style_target", "")),
                      detail_target=int(data.get("detail_target", 2)),
                      plugin_id=str(data.get("plugin_id", "")),
                      destination=str(data.get("destination", "")),
                      completion=str(data.get("completion", LEARNING)),
                      root_component=str(data.get("root_component", "")),
                      notes=str(data.get("notes", "")))
        project.root = TeachNode.from_dict(hierarchy) if hierarchy else None
        project.states = {str(k): NodeState.from_dict(v)
                          for k, v in dict(data.get("states", {})).items()}
        project.recipes = {str(k): VariantRecipe.from_dict(v)
                           for k, v in dict(data.get("recipes", {})).items()}
        project.artifacts = {str(k): ArtifactRecord.from_dict(v)
                             for k, v in dict(data.get("artifacts", {})).items()}
        project.exchanges = tuple(Exchange.from_dict(e)
                                  for e in data.get("exchanges", ()))
        project.fingerprints = {str(k): str(v) for k, v
                                in dict(data.get("fingerprints", {})).items()}
        project.passes = dict(data.get("passes", {}))
        return project

    def save(self, path) -> Path:
        target = Path(path)
        if target.suffix != PROJECT_SUFFIX:
            target = target.with_suffix(PROJECT_SUFFIX)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True),
                          encoding="utf-8")
        return target

    @classmethod
    def load(cls, path) -> "TeachProject":
        source = Path(path)
        if not source.is_file():
            raise TeachError(errors.FILE_MISSING,
                             "progetto Teach assente: %s" % source)
        try:
            data = json.loads(source.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            raise TeachError(errors.PROJECT_INVALID,
                             "progetto Teach illeggibile: %s" % exc) from exc
        return cls.from_dict(data)

    def describe(self) -> str:
        progress = self.progress()
        return "%s | %d nodi | %s | %s" % (self.concept, len(self.nodes()),
                                           progress.describe(), self.completion)


# --------------------------------------------------------------------------- #
# Dalla risposta dell'AI all'ontologia
# --------------------------------------------------------------------------- #
def build_tree(data: dict, *, concept: str = "", prefix: str = "",
               depth: int = 0, seen: set | None = None) -> TeachNode:
    """Costruisce l'albero **derivando gli id dai nomi**, con i limiti di forma.

    Gli id sono derivati e non letti: una risposta di un modello non deve
    poter scegliere l'identita' dei nodi, per la stessa ragione per cui V3 non
    lascia al planner l'identita' di un nodo del grafo (regola 15 di
    `PROJECT-INDEX`). Due fratelli con lo stesso nome prendono `_2`, `_3`: non
    e' un errore dell'autore, e' un plurale scritto due volte.

    Rifiuta — non ignora — cio' che renderebbe la gerarchia incoerente:
    profondita' oltre `MAX_DEPTH`, piu' di `MAX_NODES` nodi, `count` fuori
    dall'intervallo, un nome vuoto, un campo sconosciuto, `children` che non e'
    una lista, e un figlio che non e' un oggetto.

    ## Il ciclo, e perche' non c'e' un controllo per lui

    §6 chiede di rifiutare «un ciclo nella gerarchia», e la risposta onesta e'
    che **in questa forma un ciclo non si puo' esprimere**: un figlio e' un
    oggetto annidato, non un riferimento a un nodo per nome, quindi non esiste
    un arco che torni indietro. La forma in cui qualcuno proverebbe a scriverne
    uno — un figlio che e' una stringa, cioe' un riferimento — e' rifiutata
    perche' un figlio deve essere un oggetto, e un test lo fissa.

    Cio' che resta e' l'**identita' che si ripete**, che e' la stessa
    conseguenza vista dall'altro lato: due fratelli con lo stesso nome
    prenderebbero lo stesso percorso, e invece prendono `_2`, `_3`. Oltre
    `MAX_COUNT` fratelli omonimi e' `DUPLICATE_NODE`.
    """
    seen = set() if seen is None else seen
    if depth > MAX_DEPTH:
        raise TeachError(errors.HIERARCHY_TOO_DEEP,
                         "gerarchia troppo profonda: oltre %d livelli. Una parte "
                         "che non e' riutilizzabile da sola non e' un nodo (§8)"
                         % MAX_DEPTH)
    if not isinstance(data, dict):
        raise TeachError(errors.SCHEMA_INVALID, "un nodo e' un oggetto JSON")
    unknown = set(data) - {"name", "role", "mandatory", "count", "importance",
                           "detail_level", "description", "children", "optional"}
    if unknown:
        raise TeachError(errors.SCHEMA_INVALID,
                         "campi non ammessi in un nodo: %s"
                         % ", ".join(sorted(unknown)))
    name = str(data.get("name", "")).strip()
    if not name:
        raise TeachError(errors.SCHEMA_INVALID, "un nodo deve avere un nome")
    count = data.get("count", 1)
    if not isinstance(count, (int, float)) or isinstance(count, bool):
        raise TeachError(errors.SCHEMA_INVALID,
                         "count di %r non e' un numero: %r" % (name, count))
    count = int(count)
    if count <= 0 or count > MAX_COUNT:
        raise TeachError(errors.SCHEMA_INVALID,
                         "count di %r fuori intervallo: %d (ammesso 1..%d)"
                         % (name, count, MAX_COUNT))

    base = slug(name)
    node_id = "%s.%s" % (prefix, base) if prefix else (slug(concept or base))
    if not prefix and concept:
        node_id = slug(concept)
    candidate_id, ordinal = node_id, 1
    while candidate_id in seen:
        ordinal += 1
        candidate_id = "%s_%d" % (node_id, ordinal)
        if ordinal > MAX_COUNT:
            raise TeachError(errors.DUPLICATE_NODE,
                             "troppi fratelli chiamati %r" % name)
    node_id = candidate_id
    seen.add(node_id)
    if len(seen) > MAX_NODES:
        raise TeachError(errors.HIERARCHY_TOO_LARGE,
                         "gerarchia troppo grande: oltre %d nodi" % MAX_NODES)

    mandatory = data.get("mandatory")
    if mandatory is None and "optional" in data:
        mandatory = not bool(data.get("optional"))
    children_raw = data.get("children", ())
    if not isinstance(children_raw, (list, tuple)):
        raise TeachError(errors.SCHEMA_INVALID,
                         "children di %r non e' una lista" % name)
    children = tuple(build_tree(child, prefix=node_id, depth=depth + 1, seen=seen)
                     for child in children_raw)
    return TeachNode(id=node_id, name=name, role=str(data.get("role", "")).strip(),
                     mandatory=True if mandatory is None else bool(mandatory),
                     count=count,
                     importance=_float(data.get("importance", 0.5), 0.5),
                     detail_level=int(data.get("detail_level", 1 if depth == 0 else 2)),
                     description=str(data.get("description", "")).strip(),
                     children=children)
