"""Structural traits: deterministic graph rewrites before resolution.

The core knows only generic rewrite operations. Domain words live in plugins
through StructuralTraitRule declarations.

## The prototype is selected, not addressed

A structural rule says *what* to repeat, never *where it sits*. Up to V2 the
prototype was a literal node path (``car/wheel_fl``, ``corpo/torso/arm_l``),
which made a semantic behaviour depend on the id the planner happened to pick:
the same plan worked with a root called ``car`` and failed with ``jeep``.

The selector that fixes this already existed. ``StructuralTarget`` selects by
``role`` / ``capability`` / ``tags`` / ``components``, and every rule already
declared one in ``target`` to count its siblings. So there is one selector per
rule, and it answers both questions — *what am I counting* and *what do I
clone* — because they are the same thing. ``StructuralTraitRule.prototype``
stays as an optional literal path for the two cases that genuinely address a
node: ``std:instance_count``, where the request itself points at one, and a
rule that must clone something other than what it counts.

### How one prototype is chosen out of several, in order

Two passes. First the candidates that satisfy the **whole** selector; only if
there are none, those that satisfy at least one facet, and then the choice is
reported as a partial match. Inside a pass, ascending:

    1. component exact match        the rule names this component
    2. role                         declared role equals the requested one
    3. capability                   the node provides the requested capability
    4. tags                         overlap with the requested tags, descending
    5. layout region                the parent declares a region accepting it
    6. depth                        shallowest: the top of a repeated group,
                                    not a link inside its chain
    7. path                         stable order, so ties never float

Facets 2-4 are constant inside the first pass by construction — every candidate
matched the same selector — and discriminate in the second. Facets 5 and 6 are
what pick ``shoulder_l`` over ``upper_arm`` / ``elbow`` / ``forearm``, which all
declare ``role="arm"`` in a chained anatomy: the shoulder's parent is the only
one declaring a ``LayoutRegion`` that accepts an arm, and it is the shallowest.

Nothing here knows the words arm, wheel or tail. All seven facets read data the
component declared.

### Where the copies go

Not from a path either. A clone inherits the prototype's **parent relation** and
a deep copy of its ``Attachment``, hence its ``Requirement`` (capability, side,
tags) and ``own_socket``: socket compatibility is preserved by construction.
Then ``LayoutEngine`` distributes the group through the region and policy the
parent declared. The structural trait decides *how many*; layout decides
*where*. Keeping that split is why six wheels can be asked for without the car
component knowing the number six.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from math import isfinite
from typing import Any

from app.core.capability import Requirement
from app.core.component import Attachment, BuildContext
from app.core.errors import Report
from app.core.graph import CompositionGraph, CompositionNode, EffectRequest, SEPARATOR
from app.core.params import ParamSpec

EXACT = "exact"
BEST_EFFORT = "best_effort"
ENSURE_COUNT = "ensure_count"
INSTANCE_COUNT = "std:instance_count"
MAX_STRUCTURAL_COUNT = 64
# Un trait — semantico o strutturale — che il planner ha inventato. Un codice
# solo per i due casi, perche' la politica e' una sola.
UNKNOWN_TRAIT_SKIPPED = "UNKNOWN_TRAIT_SKIPPED"


@dataclass(frozen=True)
class StructuralTarget:
    role: str = ""
    capability: str = ""
    tags: tuple[str, ...] = ()
    components: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "tags", tuple(self.tags))
        object.__setattr__(self, "components", tuple(self.components))

    @classmethod
    def from_value(cls, value: Any) -> "StructuralTarget":
        if isinstance(value, StructuralTarget):
            return value
        if not isinstance(value, dict):
            return cls()
        return cls(role=str(value.get("role") or ""),
                   capability=str(value.get("capability") or ""),
                   tags=tuple(str(t) for t in value.get("tags") or ()),
                   components=tuple(str(c) for c in value.get("components") or ()))

    def matches(self, node, component=None) -> bool:
        comp = component or getattr(node, "component", None)
        if comp is None:
            return False
        if self.components and comp.id not in self.components:
            return False
        if self.role and getattr(comp, "role", "") != self.role:
            return False
        if self.tags and not set(self.tags) <= set(getattr(comp, "tags", ())):
            return False
        if self.capability and not comp.provides_capability(self.capability):
            return False
        return True

    def key(self) -> tuple:
        return self.role, self.capability, tuple(sorted(self.tags)), tuple(self.components)

    @property
    def empty(self) -> bool:
        return self.key() == ("", "", (), ())

    def facets(self, node, component=None, *, component_ref: str = "") -> tuple:
        """Quanto di questo selettore un nodo soddisfa, facet per facet.

        Serve due volte: a scegliere fra candidati che hanno tutti superato
        `matches()` e a scegliere **quando nessuno** lo supera, invece di
        arrendersi. L'ordine delle voci e' l'ordine di priorita' documentato in
        testa al file, e sono tutte false per un nodo che non c'entra niente.
        """
        comp = component or getattr(node, "component", None)
        if comp is None:
            return (False, False, False, 0)
        atteso = set(self.components) | ({component_ref} if component_ref else set())
        return (
            comp.id in atteso,
            bool(self.role) and getattr(comp, "role", "") == self.role,
            bool(self.capability) and comp.provides_capability(self.capability),
            len(set(self.tags) & set(getattr(comp, "tags", ()))),
        )

    def describe(self) -> str:
        pezzi = [("role", self.role), ("capability", self.capability),
                 ("tags", ",".join(self.tags)),
                 ("components", ",".join(self.components))]
        detto = ["%s=%s" % (k, v) for k, v in pezzi if v]
        return " ".join(detto) or "nessun criterio"


@dataclass(frozen=True)
class StructuralTraitSpec:
    id: str
    aliases: tuple[str, ...] = ()
    description: str = ""
    value: ParamSpec = field(default_factory=lambda: ParamSpec(1))
    modes: tuple[str, ...] = (EXACT, BEST_EFFORT)
    max_count: int = MAX_STRUCTURAL_COUNT
    owner: str = ""
    version: str = "1.0.0"
    purpose: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "aliases", tuple(self.aliases))
        object.__setattr__(self, "modes", tuple(self.modes))


@dataclass(frozen=True)
class StructuralTraitRequest:
    trait: str
    value: Any
    on: str = "root"
    mode: str = EXACT
    scope: str = "local"
    target: Any = field(default_factory=dict)

    def normalized_target(self) -> StructuralTarget:
        return StructuralTarget.from_value(self.target)


@dataclass(frozen=True)
class EnsureCountOperation:
    op: str = ENSURE_COUNT
    prototype: str = ""              # percorso letterale, solo se dichiarato
    count: int = 1
    group: str = ""
    mode: str = EXACT
    trait: str = INSTANCE_COUNT
    rule: str = ""
    component: str = ""
    target: StructuralTarget = field(default_factory=StructuralTarget)
    # Dove cercare il prototipo. Non e' il prototipo: e' il sottoalbero dentro
    # cui cercarlo, cioe' l'`on` della richiesta quando nomina qualcosa che
    # esiste. Vuoto, o un percorso che non esiste piu', vuol dire "tutto".
    on: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "op": self.op, "prototype": self.prototype, "count": self.count,
            "group": self.group, "mode": self.mode, "trait": self.trait,
            "rule": self.rule, "component": self.component, "on": self.on,
            "target": {
                "role": self.target.role,
                "capability": self.target.capability,
                "tags": list(self.target.tags),
                "components": list(self.target.components),
            },
        }


@dataclass
class GraphRewritePlan:
    operations: list[EnsureCountOperation] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"operations": [op.to_dict() for op in self.operations]}


@dataclass
class StructuralTraitRule:
    id: str
    trait: str
    prototype: str = ""
    component: str = ""
    group: str = ""
    target: StructuralTarget = field(default_factory=StructuralTarget)
    description: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "target", StructuralTarget.from_value(self.target))


@dataclass
class StructuralTraitResolution:
    plan: GraphRewritePlan = field(default_factory=GraphRewritePlan)
    applied: list[dict[str, Any]] = field(default_factory=list)
    created: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: Report = field(default_factory=Report)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan": self.plan.to_dict(),
            "applied": list(self.applied),
            "created": list(self.created),
            "skipped": list(self.skipped),
            "conflicts": list(self.conflicts),
            "diagnostics": [{"code": d.code, "message": d.message,
                             "where": d.where, "severity": d.severity}
                            for d in self.diagnostics.sorted()],
        }


def structural_trait_requests_from_dict(items: Any) -> list[StructuralTraitRequest]:
    out = []
    for item in items or ():
        if not isinstance(item, dict):
            continue
        out.append(StructuralTraitRequest(
            trait=str(item.get("trait") or ""),
            value=item.get("value"),
            on=str(item.get("on") or "root"),
            mode=str(item.get("mode") or EXACT),
            scope=str(item.get("scope") or "local"),
            target=item.get("target") or {},
        ))
    return out


class StructuralTraitResolver:
    def __init__(self, registry, *, max_nodes: int = MAX_STRUCTURAL_COUNT) -> None:
        self.registry = registry
        self.max_nodes = int(max_nodes)

    def run(self, graph: CompositionGraph,
            report: Report | None = None) -> StructuralTraitResolution:
        report = report if report is not None else Report()
        result = StructuralTraitResolution(diagnostics=report)
        requests = list(getattr(graph, "structural_traits", ()) or ())
        if not requests:
            graph.structural_resolution = result
            return result

        ops = self._operations(graph, requests, report, result)
        result.plan.operations = ops
        if report.errors():
            graph.structural_resolution = result
            return result
        self._apply(graph, ops, report, result)
        graph.structural_resolution = result
        graph.graph_rewrite_plan = result.plan
        return result

    def _operations(self, graph, requests, report, result) -> list[EnsureCountOperation]:
        by_channel: dict[tuple, list[EnsureCountOperation]] = {}
        for request in requests:
            spec = self.registry.structural_trait(request.trait)
            if spec is None:
                # Un elemento facoltativo sconosciuto non distrugge una
                # struttura valida: si ignora e si dichiara. La regola, e i casi
                # che restano fatali, stanno in `app/core/planner/plans.py`.
                report.warn(UNKNOWN_TRAIT_SKIPPED,
                            "structural trait sconosciuto, ignorato: trait = '%s'"
                            % request.trait,
                            where=request.on,
                            why="un elemento facoltativo sconosciuto non "
                                "invalida il resto del piano",
                            alternatives=[t.id for t in self.registry.structural_traits()][:8])
                result.skipped.append({"trait": request.trait,
                                       "code": UNKNOWN_TRAIT_SKIPPED})
                continue
            count = self._count(request.value, spec, report, request.on)
            if count is None:
                continue
            mode = request.mode or EXACT
            if mode not in spec.modes:
                report.add("STRUCTURAL_MODE_UNSUPPORTED",
                           "'%s' non supporta mode '%s'" % (spec.id, mode),
                           where=request.on, alternatives=spec.modes)
                continue
            rules = self.registry.structural_trait_rules(spec.id)
            if spec.id == INSTANCE_COUNT and not rules:
                rules = [StructuralTraitRule(id="std:instance_count",
                                             trait=INSTANCE_COUNT,
                                             prototype=request.on)]
            for rule in rules:
                target = rule.target if not rule.target.empty \
                    else request.normalized_target()
                # Il percorso resta solo se qualcuno lo ha **dichiarato**. Senza
                # selettore ne' percorso non c'e' nient'altro che l'indirizzo
                # della richiesta: e' il caso di `std:instance_count`.
                prototype = rule.prototype or ("" if not target.empty else request.on)
                op = EnsureCountOperation(
                    prototype=prototype, count=count,
                    group=rule.group or _basename(prototype) or _group_name(target),
                    mode=mode, trait=spec.id, rule=rule.id,
                    component=rule.component, target=target,
                    on=request.on)
                by_channel.setdefault((prototype, target.key(), rule.group), []).append(op)

        operations: list[EnsureCountOperation] = []
        for channel, group in sorted(by_channel.items(), key=lambda item: str(item[0])):
            counts = {op.count for op in group}
            modes = {op.mode for op in group}
            if len(counts) > 1 or len(modes) > 1:
                report.add("STRUCTURAL_VALUE_CONFLICT",
                           "richieste strutturali incompatibili sullo stesso channel",
                           where=str(channel),
                           alternatives=[op.rule or op.trait for op in group])
                result.conflicts.append({"channel": channel,
                                         "operations": [op.to_dict() for op in group]})
                continue
            operations.append(sorted(group, key=lambda op: (op.rule, op.trait))[0])
        return operations

    def _count(self, raw, spec, report, where) -> int | None:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            report.add("STRUCTURAL_COUNT_INVALID",
                       "count non numerico: %r" % (raw,), where=where)
            return None
        if not isfinite(value) or value != int(value) or value < 0:
            report.add("STRUCTURAL_COUNT_INVALID",
                       "count deve essere intero non negativo: %r" % (raw,),
                       where=where)
            return None
        count = int(value)
        limit = min(int(spec.max_count), self.max_nodes)
        if count > limit:
            report.add("STRUCTURAL_COUNT_TOO_LARGE",
                       "count %d supera il limite %d" % (count, limit),
                       where=where)
            return None
        return count

    def _apply(self, graph, operations, report, result) -> None:
        for op in operations:
            prototype = self._locate(graph, op, report)
            if prototype is None:
                # Non trovata la parte da ripetere. Con `exact` il referto ha
                # gia' un errore e il piano si fermera'; con `best_effort` la
                # richiesta e' **persa**, e perdere qualcosa in silenzio e' il
                # difetto che V3.5 esisteva per togliere.
                result.skipped.append({"operation": op.to_dict(), "existing": 0,
                                       "code": "STRUCTURAL_PROTOTYPE_NOT_FOUND"})
                continue
            parent_id = graph.parents.get(prototype.id, "")
            existing = self._compatible_siblings(graph, parent_id, prototype, op)
            if len(existing) > op.count:
                code = "STRUCTURAL_EXACT_OVERCOUNT" if op.mode == EXACT else "STRUCTURAL_OVERCOUNT"
                message = "esistono gia' %d istanze, richieste %d" \
                    % (len(existing), op.count)
                if op.mode == EXACT:
                    report.add(code, message, where=graph.path(prototype.id))
                else:
                    report.warn(code, message, where=graph.path(prototype.id))
                result.skipped.append({"operation": op.to_dict(), "existing": len(existing)})
                continue
            created = []
            prototypes = existing or [prototype]
            # L'identita' del prototipo si legge **prima** di clonare: dopo, i
            # cloni sono fratelli con la stessa firma e gli ordinali cambiano.
            origine = graph.identity(prototype.id)
            for i in range(op.count - len(existing)):
                sorgente = prototypes[i % len(prototypes)]
                clone = self._clone(graph, sorgente, parent_id,
                                    op=op, origin=origine,
                                    index=len(existing) + i + 1,
                                    total=op.count)
                created.append(clone.id)
            result.applied.append({"operation": op.to_dict(), "existing": len(existing),
                                   "created": created, "requested": op.count,
                                   "prototype": graph.path(prototype.id),
                                   "prototype_identity": origine,
                                   "identities": [graph.identity(id) for id in created]})
            if created:
                result.created.append({"prototype": graph.path(prototype.id),
                                       "prototype_identity": origine,
                                       "ids": created,
                                       "identities": [graph.identity(id)
                                                      for id in created]})

    # ------------------------------------------------------------ prototipo #
    @staticmethod
    def _prototipo_mancante(report, op, message: str, *, where: str,
                            why: str = "", alternatives=()) -> None:
        """«Non ho trovato la parte da ripetere», con la severita' che il piano
        ha chiesto.

        **[V3.5]** Un punto solo per i tre posti che possono dirlo, e la
        severita' la decide `mode`, che e' il campo che esiste per questo:

            exact         il piano pretende esattamente N: non si puo' -> fatale
            best_effort   il piano accetta cio' che si puo' -> avviso, e si dice

        Prima era fatale in **entrambi** i modi, e `best_effort` che uccide un
        piano e' il contrario di best effort. L'incoerenza c'era da V2 e non si
        vedeva, perche' nessun planner scriveva `structural_traits`: si e' vista
        appena V3.5 ha fatto in modo che li scrivesse — un modello reale ha
        chiesto `best_effort` sulla richiesta 3 del PRODUCT-AUDIT e ha ottenuto
        zero triangoli invece di una degradazione dichiarata.

        Non e' un'indulgenza generica: `exact` non e' cambiato, e un
        `best_effort` saltato finisce in `StructuralTraitResolution.skipped`,
        quindi in `GenerationResult.skipped()`. Una richiesta persa resta
        leggibile — che e' l'altra meta' della stessa milestone.

        ## Il `why` dice che cosa si puo' fare, non solo cosa manca

        Le `alternatives` di questa diagnosi sono i **ruoli presenti**, e un
        piano non puo' assegnare un ruolo: sono utili a capire, inutili a
        correggere. Misurato sulla richiesta 3 del PRODUCT-AUDIT, la correzione
        unica e' partita, ha ricevuto `ears, head, limb, tail, torso` e non ha
        migliorato niente, perche' nessuna di quelle parole e' una mossa.
        Le mosse sono tre, e sono sempre le stesse per qualunque trait: una
        radice che possieda quella parte, `best_effort`, o togliere la
        richiesta. Dirlo e' informazione generica sul campo `mode`, non
        conoscenza di dominio: non nomina nessuna parte e nessun componente.
        """
        rimedi = ("scegli una radice che possieda quella parte, oppure "
                  'mode="best_effort" per costruire il resto e dichiarare la '
                  "richiesta persa, oppure togli la richiesta")
        why = "%s; %s" % (why, rimedi) if why else rimedi
        if op is not None and op.mode == BEST_EFFORT:
            report.warn("STRUCTURAL_PROTOTYPE_NOT_FOUND", message, where=where,
                        why=why, alternatives=list(alternatives))
        else:
            report.add("STRUCTURAL_PROTOTYPE_NOT_FOUND", message, where=where,
                       why=why, alternatives=list(alternatives))

    def _locate(self, graph, op, report) -> CompositionNode | None:
        """Il nodo da clonare: per percorso se dichiarato, altrimenti scelto.

        Le due strade finiscono nello stesso punto — un percorso, materializzato
        con la serie completa dei fratelli dichiarati dal padre. Quel percorso
        pero', nel caso del selettore, **viene scoperto a runtime** e non lo
        scrive nessuno: e' la differenza fra un'implementazione e un contratto.
        """
        if op.prototype:
            return self._prototype(graph, op, report)
        path, resolved = self._discover(graph, op, report)
        if not path:
            return None
        # L'albero risolto per scegliere e' lo stesso che serve a materializzare:
        # si passa, invece di risolverlo una seconda volta.
        self._materialize_path(graph, path, report, resolved=resolved)
        node = graph.node(path)
        if node is None:
            self._prototipo_mancante(
                report, op,
                "prototipo scelto ma non materializzabile: '%s'" % path,
                where=path, why=op.target.describe())
        return node

    def _discover(self, graph, op, report) -> tuple[str, Any]:
        """Il percorso del miglior candidato, o niente.

        Si guarda l'albero **risolto**, non il grafo: il prototipo di solito non
        sta nel piano, lo dichiara il componente attraverso `children`. E' la
        stessa esplorazione che faceva `_materialize_path`, spostata un gradino
        piu' su perche' adesso serve anche a scegliere.
        """
        resolved = self._explore(graph, report, where=op.on or op.prototype)
        if resolved is None:
            return "", None
        candidates = [n for n in resolved.walk() if n.link is not None]
        scope = self._scope(resolved, op.on)
        if scope:
            candidates = [n for n in candidates
                          if n.path == scope or n.path.startswith(scope + SEPARATOR)]
        strict = [n for n in candidates
                  if op.target.matches(n, n.component)] if not op.target.empty else []
        if not strict and op.component:
            strict = [n for n in candidates if n.component.id == op.component]
        pool, partial = strict, False
        if not pool:
            pool = [n for n in candidates
                    if any(self._facets(op, n))]
            partial = True
        if not pool:
            self._prototipo_mancante(
                report, op, "nessun nodo corrisponde al prototipo richiesto",
                where=graph.path(graph.root_id), why=op.target.describe(),
                alternatives=sorted({n.component.role for n in candidates
                                     if n.component.role})[:8])
            return "", resolved
        best = min(pool, key=lambda n: self._rank(op, n, resolved))
        if partial:
            report.note("STRUCTURAL_PROTOTYPE_PARTIAL_MATCH",
                        "prototipo scelto per corrispondenza parziale: '%s'"
                        % best.path, where=best.path,
                        why=op.target.describe())
        return best.path, resolved

    @staticmethod
    def _scope(resolved, on: str) -> str:
        """`on` e' un ambito, non un indirizzo.

        Quando nomina un nodo che esiste si cerca dentro quel sottoalbero;
        quando nomina qualcosa che la risoluzione ha sostituito — `arm_l`
        diventato `shoulder_l` — si cerca in tutto l'albero invece di fallire.
        E' la differenza fra restringere una ricerca e dipendere da un percorso.
        """
        if not on or on == "root":
            return ""
        return on if any(n.path == on for n in resolved.walk()) else ""

    @staticmethod
    def _facets(op, node) -> tuple:
        return op.target.facets(node, node.component, component_ref=op.component)

    def _rank(self, op, node, resolved) -> tuple:
        """La chiave d'ordinamento documentata in testa al file.

        A gradini e non come somma pesata, per la stessa ragione di V2: una
        somma ha dei numeri da tarare, e nessuno sa dire perche' valgano quelli.
        """
        esatto, ruolo, capability, tag = self._facets(op, node)
        return (not esatto, not ruolo, not capability, -tag,
                not self._parent_region_accepts(node, resolved),
                node.depth, node.path)

    @staticmethod
    def _parent_region_accepts(node, resolved) -> bool:
        """Il padre dichiara una LayoutRegion che accetterebbe questo nodo.

        E' il segnale piu' forte che un nodo sia la testa di un gruppo ripetuto
        e non un anello in mezzo a una catena, e viene da un contratto
        dichiarato — non da un nome. Le regioni sono spesso una callable, come
        in `LayoutEngine._regions`: si valutano allo stesso modo, perche' una
        regione che dipende dai parametri del padre e' la norma e non un caso
        strano.
        """
        parent = resolved.nodes.get(node.link.parent) if node.link else None
        if parent is None:
            return False
        provider = getattr(parent.component, "layout_regions", ())
        try:
            if callable(provider):
                ctx = BuildContext(style=resolved.style,
                                   detail_level=resolved.detail_level,
                                   depth=parent.depth, seed=resolved.seed,
                                   budget=resolved.budget, path=parent.path,
                                   report=Report(), node=parent,
                                   composition=resolved)
                regions = list(provider(parent.values, ctx) or ())
            else:
                regions = list(provider or ())
            return any(region.allows(node) for region in regions)
        except Exception:                         # noqa: BLE001
            # Una regione che non si sa valutare non e' una prova di niente:
            # si perde un gradino di ordinamento, non la riscrittura.
            return False

    def _prototype(self, graph, op, report) -> CompositionNode | None:
        node = graph.node(op.prototype)
        if node is None:
            self._materialize_path(graph, op.prototype, report)
            node = graph.node(op.prototype)
        if node is not None:
            return node
        if op.component:
            self._materialize_path(graph, op.prototype.rsplit(SEPARATOR, 1)[0], report)
            node = graph.node(op.prototype)
        if node is not None:
            return node
        if op.component:
            parent_path = op.prototype.rsplit(SEPARATOR, 1)[0]
            parent = self._ensure_parent(graph, parent_path, report)
            if parent is None:
                return None
            base = _basename(op.prototype) or _basename(op.component)
            node_id = _free_id(graph, base)
            attachment = Attachment(id=node_id, component=op.component)
            node = graph._link(node_id, op.component, parent.id, attachment, {})
            node.requested = True
            graph.operations.append(type(graph.operations[0])(
                "structural_prototype", graph.path(node.id), {"ref": op.component})
                if graph.operations else _operation("structural_prototype",
                                                    graph.path(node.id),
                                                    {"ref": op.component}))
            return node
        self._prototipo_mancante(
            report, op, "prototype strutturale non trovato: '%s'" % op.prototype,
            where=op.prototype)
        return None

    def _explore(self, graph, report: Report, *, where: str = ""):
        """L'albero dichiarato, risolto una volta per riscrittura.

        Serve a scoprire cio' che il piano non nomina — i figli che un
        componente dichiara attraverso `children` — e serve due volte: a
        scegliere il prototipo e a materializzarlo. Le diagnosi di questa
        risoluzione si buttano: e' un'esplorazione, non la risoluzione vera, che
        avviene dopo la riscrittura e con il suo referto.
        """
        try:
            from app.core.resolver import resolve

            return resolve(graph, self.registry, style=graph.style, report=Report())
        except Exception as exc:  # noqa: BLE001 - best effort discovery
            report.add("STRUCTURAL_PROTOTYPE_DISCOVERY_FAILED",
                       "prototype non esplorabile: %s" % exc, where=where)
            return None

    def _materialize_path(self, graph, path: str, report: Report,
                          *, resolved=None) -> None:
        if not path or graph.node(path) is not None:
            return
        if resolved is None:
            resolved = self._explore(graph, report, where=path)
        if resolved is None:
            return
        chain = [n for n in resolved.walk()
                 if path == n.path or path.startswith(n.path + SEPARATOR)]
        chain.sort(key=lambda n: n.depth)
        materialize = list(chain)
        # Discover the complete sibling set declared by the prototype's
        # parent.  This lets a generic count request preserve side/capability
        # information already authored by the component without teaching the
        # kernel domain words such as wheel or arm.
        parent_path = path.rsplit(SEPARATOR, 1)[0] if SEPARATOR in path else ""
        parent_node = next((n for n in resolved.walk()
                            if n.path == parent_path), None)
        if parent_node is not None:
            for child_id in parent_node.children:
                child = resolved.nodes.get(child_id)
                if child is not None:
                    materialize.append(child)
        unique = {}
        for item in materialize:
            unique[item.path] = item
        for resolved_node in sorted(unique.values(), key=lambda n: n.depth):
            if graph.node(resolved_node.path) is not None:
                continue
            if resolved_node.link is None:
                continue
            parent = resolved.nodes.get(resolved_node.link.parent)
            if parent is None:
                continue
            parent_graph = graph.node(parent.path)
            if parent_graph is None:
                continue
            link = resolved_node.link
            # Resolved ids are path-shaped (``body/tail``), while graph ids
            # are local to their parent.  Keep the path for lookup and use
            # only the final segment as the graph id.
            node_id = _free_id(graph, _basename(resolved_node.path))
            requirement = link.requirement or Requirement(
                capability=link.capability, socket_id=link.parent_socket,
                side=link.side)
            component_ref = getattr(resolved_node.component, "id", "") \
                or resolved_node.requested_ref or resolved_node.ref
            attachment = Attachment(
                id=node_id, component=component_ref,
                requirement=requirement, own_socket=link.own_socket,
                level=1, scale_mode=link.scale_mode, insert=link.insert,
                roll=link.roll)
            node = graph._link(node_id, component_ref,
                               parent_graph.id, attachment, dict(resolved_node.values))
            node.requested = True
            node.tags = frozenset(resolved_node.tags)
            graph.operations.append(_operation("structural_materialize",
                                               graph.path(node.id),
                                               {"from": resolved_node.path}))

    def _ensure_parent(self, graph, path, report):
        if not path:
            return graph.nodes.get(graph.root_id)
        existing = graph.node(path)
        if existing is not None:
            return existing
        report.add("STRUCTURAL_PARENT_NOT_FOUND",
                   "parent prototype non disponibile: '%s'" % path, where=path)
        return None

    def _compatible_siblings(self, graph, parent_id, prototype, op):
        parent_children = graph.children(parent_id)
        component = (self.registry.component(graph.resolved_ref(prototype.id))
                     or self.registry.component(op.component))
        out = []
        for node in parent_children:
            comp = (self.registry.component(graph.resolved_ref(node.id))
                    or self.registry.component(op.component))
            same = node.ref == prototype.ref or graph.resolved_ref(node.id) == graph.resolved_ref(prototype.id)
            if op.target.key() != StructuralTarget().key():
                same = op.target.matches(node, comp)
            if same and comp is not None:
                out.append(node)
        return sorted(out, key=lambda n: graph.path(n.id))

    def _clone(self, graph, prototype, parent_id, *, op=None,
               origin: str = "", index: int = 0, total: int = 0) -> CompositionNode:
        new_id = _free_id(graph, prototype.id)
        attachment = _clone_attachment(prototype.attachment, new_id)
        node = graph._link(new_id, prototype.ref, parent_id, attachment,
                           deepcopy(prototype.overrides))
        node.effects = [EffectRequest(e.type, e.scope, dict(e.params), e.amount)
                        for e in prototype.effects]
        node.tags = frozenset(prototype.tags)
        node.requested = True
        if prototype.id in graph.swaps:
            graph.swaps[new_id] = graph.swaps[prototype.id]
        # Da dove viene questo nodo: il trait che lo ha chiesto, la regola, il
        # prototipo per identita' stabile (non per percorso: il percorso cambia
        # se qualcuno rinomina un nodo) e quale copia e'. Il registro delle
        # operazioni lo racconta a chi legge una diagnosi; `structural_provenance`
        # lo porta nel file di progetto.
        provenance = {"trait": op.trait if op is not None else INSTANCE_COUNT,
                      "rule": op.rule if op is not None else "",
                      "component": prototype.ref,
                      "prototype": origin,
                      "identity": graph.identity(node.id),
                      "clone_index": int(index), "clone_count": int(total)}
        graph.structural_provenance.append(provenance)
        graph.operations.append(_operation("ensure_count", graph.path(node.id),
                                           {"prototype": graph.path(prototype.id),
                                            **{k: v for k, v in provenance.items()
                                               if k != "component"}}))
        return node


def _clone_attachment(source: Attachment | None, new_id: str) -> Attachment | None:
    if source is None:
        return None
    clone = deepcopy(source)
    clone.id = new_id
    return clone


def _free_id(graph: CompositionGraph, base: str) -> str:
    stem = base.rsplit(SEPARATOR, 1)[-1] or "node"
    if stem not in graph.nodes:
        return stem
    index = 2
    while "%s_%d" % (stem, index) in graph.nodes:
        index += 1
    return "%s_%d" % (stem, index)


def _basename(path: str) -> str:
    return str(path or "").rsplit(SEPARATOR, 1)[-1]


def _group_name(target: StructuralTarget) -> str:
    """Il nome del canale quando non c'e' nessun percorso da cui ricavarlo.

    Serve solo a tenere distinte due richieste sullo stesso grafo, quindi basta
    che sia stabile e derivato dal selettore: non lo legge nessun contratto.
    """
    if target.role:
        return target.role
    if target.tags:
        return sorted(target.tags)[0]
    if target.capability:
        return target.capability
    if target.components:
        return _basename(sorted(target.components)[0].replace(":", SEPARATOR))
    return "group"


def _operation(kind: str, target: str, detail: dict[str, Any]):
    from app.core.graph import Operation

    return Operation(kind, target, detail)


def resolve_structural_traits(graph: CompositionGraph, registry, *,
                              report: Report | None = None) -> StructuralTraitResolution:
    return StructuralTraitResolver(registry).run(graph, report=report)
