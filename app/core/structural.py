"""Structural traits: deterministic graph rewrites before resolution.

The core knows only generic rewrite operations. Domain words live in plugins
through StructuralTraitRule declarations.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from math import isfinite
from typing import Any

from app.core.capability import Requirement
from app.core.component import Attachment
from app.core.errors import Report
from app.core.graph import CompositionGraph, CompositionNode, EffectRequest, SEPARATOR
from app.core.params import ParamSpec

EXACT = "exact"
BEST_EFFORT = "best_effort"
ENSURE_COUNT = "ensure_count"
INSTANCE_COUNT = "std:instance_count"
MAX_STRUCTURAL_COUNT = 64


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
    prototype: str = ""
    count: int = 1
    group: str = ""
    mode: str = EXACT
    trait: str = INSTANCE_COUNT
    rule: str = ""
    component: str = ""
    target: StructuralTarget = field(default_factory=StructuralTarget)

    def to_dict(self) -> dict[str, Any]:
        return {
            "op": self.op, "prototype": self.prototype, "count": self.count,
            "group": self.group, "mode": self.mode, "trait": self.trait,
            "rule": self.rule, "component": self.component,
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
                report.add("STRUCTURAL_TRAIT_NOT_FOUND",
                           "structural trait sconosciuto: '%s'" % request.trait,
                           where=request.on,
                           alternatives=[t.id for t in self.registry.structural_traits()][:8])
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
                target = rule.target if rule.target.key() != StructuralTarget().key() \
                    else request.normalized_target()
                prototype = rule.prototype or request.on
                op = EnsureCountOperation(
                    prototype=prototype, count=count,
                    group=rule.group or _basename(prototype),
                    mode=mode, trait=spec.id, rule=rule.id,
                    component=rule.component, target=target)
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
            prototype = self._prototype(graph, op, report)
            if prototype is None:
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
            for i in range(op.count - len(existing)):
                clone = self._clone(graph, prototypes[i % len(prototypes)], parent_id)
                created.append(clone.id)
            result.applied.append({"operation": op.to_dict(), "existing": len(existing),
                                   "created": created, "requested": op.count})
            if created:
                result.created.append({"prototype": graph.path(prototype.id),
                                       "ids": created})

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
        report.add("STRUCTURAL_PROTOTYPE_NOT_FOUND",
                   "prototype strutturale non trovato: '%s'" % op.prototype,
                   where=op.prototype)
        return None

    def _materialize_path(self, graph, path: str, report: Report) -> None:
        if not path or graph.node(path) is not None:
            return
        try:
            from app.core.resolver import resolve

            resolved = resolve(graph, self.registry, style=graph.style, report=Report())
        except Exception as exc:  # noqa: BLE001 - best effort discovery
            report.add("STRUCTURAL_PROTOTYPE_DISCOVERY_FAILED",
                       "prototype non esplorabile: %s" % exc, where=path)
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

    def _clone(self, graph, prototype, parent_id) -> CompositionNode:
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
        graph.operations.append(_operation("ensure_count", graph.path(node.id),
                                           {"prototype": graph.path(prototype.id)}))
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


def _operation(kind: str, target: str, detail: dict[str, Any]):
    from app.core.graph import Operation

    return Operation(kind, target, detail)


def resolve_structural_traits(graph: CompositionGraph, registry, *,
                              report: Report | None = None) -> StructuralTraitResolution:
    return StructuralTraitResolver(registry).run(graph, report=report)
