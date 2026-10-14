"""Semantic traits: intenti semantici risolti su contratti pubblici.

Il core non sa cosa significhi un trait. Sa validarne l'identita', propagarlo
nel grafo risolto e applicare regole registrate da plugin normali.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from app.core.errors import Report
from app.core.graph import EffectRequest, FROM_OVERRIDE, FROM_TRAIT
from app.core.params import ExpressionError, ParamSpec, evaluate, numeric
from app.core.resolved import ResolvedComposition, ResolvedNode, ResolvedValue

LOCAL = "local"
SUBTREE = "subtree"
SET = "set"
ADD = "add"


@dataclass(frozen=True)
class TraitSpec:
    id: str
    aliases: tuple[str, ...] = ()
    description: str = ""
    value: ParamSpec = field(default_factory=lambda: ParamSpec(0.0))
    scopes: tuple[str, ...] = (LOCAL, SUBTREE)
    operations: tuple[str, ...] = (SET, ADD)
    owner: str = ""
    version: str = "1.0.0"
    purpose: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "aliases", tuple(self.aliases))
        object.__setattr__(self, "scopes", tuple(self.scopes))
        object.__setattr__(self, "operations", tuple(self.operations))


@dataclass(frozen=True)
class TraitRequest:
    trait: str
    value: Any
    op: str = SET
    on: str = "root"
    scope: str = SUBTREE


@dataclass(frozen=True)
class TraitMatch:
    """Compatibilita' V1.

    Tutte le categorie dichiarate sono requisiti AND. Dentro roles,
    capabilities, param_roles, params e components i valori sono alternative.
    I tags sono un subset richiesto.
    """

    roles: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    param_roles: tuple[str, ...] = ()
    params: tuple[str, ...] = ()
    components: tuple[str, ...] = ()
    styles: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("roles", "tags", "capabilities", "param_roles",
                     "params", "components", "styles"):
            object.__setattr__(self, name, tuple(getattr(self, name)))


@dataclass(frozen=True)
class ParamPatch:
    expression: str = "value"
    param: str = ""
    semantic_role: str = ""

    def targets(self, node: ResolvedNode) -> list[str]:
        if self.param:
            return [self.param] if self.param in node.component.params else []
        if self.semantic_role:
            return [name for name, spec in sorted(node.component.params.items())
                    if getattr(spec, "semantic_role", "") == self.semantic_role]
        return []


@dataclass
class TraitRule:
    id: str
    trait: str
    match: TraitMatch = field(default_factory=TraitMatch)
    patches: tuple[ParamPatch, ...] = ()
    effects: tuple[EffectRequest, ...] = ()
    description: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "patches", tuple(self.patches))
        object.__setattr__(self, "effects", tuple(self.effects))


@dataclass
class TraitResolution:
    applied: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    unsupported: list[dict[str, Any]] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    values: dict[str, dict[str, Any]] = field(default_factory=dict)
    diagnostics: Report = field(default_factory=Report)

    def to_dict(self) -> dict[str, Any]:
        return {
            "applied": list(self.applied),
            "skipped": list(self.skipped),
            "unsupported": list(self.unsupported),
            "conflicts": list(self.conflicts),
            "values": {k: dict(v) for k, v in sorted(self.values.items())},
            "diagnostics": [{"code": d.code, "message": d.message,
                             "where": d.where, "severity": d.severity}
                            for d in self.diagnostics.sorted()],
        }


class TraitResolver:
    def __init__(self, registry, *, style: str = "") -> None:
        self.registry = registry
        self.style = style

    def run(self, composition: ResolvedComposition,
            report: Report | None = None) -> TraitResolution:
        report = report if report is not None else composition.report
        resolution = TraitResolution(diagnostics=report)
        requests = list(getattr(composition.graph, "traits", ()) or ())
        if not requests:
            composition.trait_resolution = resolution
            return resolution

        values = self._resolve_values(composition, requests, report)
        resolution.values = values
        outputs = self._collect_outputs(composition, values, report, resolution)
        self._apply_outputs(composition, outputs, report, resolution)
        self._rederive(composition, report)
        composition.trait_resolution = resolution
        return resolution

    def _resolve_values(self, composition: ResolvedComposition,
                        requests: list[TraitRequest],
                        report: Report) -> dict[str, dict[str, Any]]:
        current: dict[tuple[str, str], Any] = {}
        set_seen: dict[tuple[str, str], Any] = {}
        conflicted_values: set[tuple[str, str]] = set()
        for index, request in enumerate(requests):
            spec = self._trait(request.trait, report, where=request.on)
            if spec is None:
                continue
            if request.op not in spec.operations:
                report.add("TRAIT_OPERATION_UNSUPPORTED",
                           "'%s' non supporta op '%s'" % (spec.id, request.op),
                           where=request.on, alternatives=spec.operations)
                continue
            if request.scope not in spec.scopes or request.scope not in (LOCAL, SUBTREE):
                report.add("TRAIT_SCOPE_UNSUPPORTED",
                           "'%s' non supporta scope '%s'" % (spec.id, request.scope),
                           where=request.on, alternatives=spec.scopes)
                continue
            target = self._target(composition, request.on)
            if target is None:
                report.add("TRAIT_TARGET_NOT_FOUND",
                           "'%s' punta a un nodo che non c'e': '%s'"
                           % (spec.id, request.on),
                           where=request.on,
                           alternatives=[n.path for n in composition.walk()][:8])
                continue
            targets = [target] if request.scope == LOCAL else self._subtree(composition, target)
            for node in targets:
                key = (node.id, spec.id)
                if key in conflicted_values:
                    continue
                base = current.get(key, spec.value.default)
                raw = request.value if request.op == SET else float(base) + float(request.value)
                value = spec.value.coerce(raw)
                if request.op == SET and key in set_seen and set_seen[key] != value:
                    report.add("TRAIT_VALUE_CONFLICT",
                               "due set incompatibili per '%s'" % spec.id,
                               where=node.path)
                    current.pop(key, None)
                    conflicted_values.add(key)
                    continue
                if request.op == SET:
                    set_seen[key] = value
                current[key] = value
        out: dict[str, dict[str, Any]] = {}
        for (node_id, trait_id), value in sorted(current.items()):
            out.setdefault(node_id, {})[trait_id] = value
        return out

    def _collect_outputs(self, composition: ResolvedComposition,
                         values: dict[str, dict[str, Any]], report: Report,
                         resolution: TraitResolution) -> list[dict[str, Any]]:
        outputs: list[dict[str, Any]] = []
        for node in composition.walk():
            node_values = values.get(node.id, {})
            for trait_id, value in sorted(node_values.items()):
                rules = [r for r in self.registry.trait_rules(trait_id)
                         if self._matches(r.match, node, composition.style)]
                if not rules:
                    if self._worth_unsupported(node):
                        report.note("TRAIT_UNSUPPORTED",
                                    "'%s' non ha regole compatibili su '%s'"
                                    % (trait_id, node.ref), where=node.path)
                        resolution.unsupported.append(
                            {"trait": trait_id, "node": node.id, "ref": node.ref})
                    continue
                for rule in sorted(rules, key=lambda r: r.id):
                    for patch in rule.patches:
                        for param in patch.targets(node):
                            outputs.append({"kind": "param", "trait": trait_id,
                                            "value": value, "node": node,
                                            "rule": rule, "patch": patch,
                                            "param": param,
                                            "channel": (node.id, param)})
                    for effect in rule.effects:
                        if self.registry.effect(effect.type) is None:
                            report.add("TRAIT_EFFECT_NOT_FOUND",
                                       "effetto sconosciuto da trait: '%s'"
                                       % effect.type, where=node.path,
                                       alternatives=[e.id for e in
                                                     self.registry.effects()][:8])
                            continue
                        scope = effect.scope or "part:%s" % node.id
                        outputs.append({"kind": "effect", "trait": trait_id,
                                        "value": value, "node": node,
                                        "rule": rule, "effect": effect,
                                        "channel": (node.id, effect.type, scope)})
        return outputs

    def _apply_outputs(self, composition: ResolvedComposition, outputs: list[dict[str, Any]],
                       report: Report, resolution: TraitResolution) -> None:
        by_channel: dict[tuple, list[dict[str, Any]]] = {}
        for out in outputs:
            by_channel.setdefault(out["channel"], []).append(out)

        conflicted: set[tuple] = set()
        for channel, group in sorted(by_channel.items(), key=lambda item: str(item[0])):
            rule_ids = sorted({g["rule"].id for g in group})
            if len(rule_ids) <= 1:
                continue
            conflicted.add(channel)
            report.add("TRAIT_RULE_CONFLICT",
                       "piu' regole scrivono lo stesso channel",
                       where=self._channel_text(channel),
                       alternatives=rule_ids)
            resolution.conflicts.append({"channel": channel, "rules": rule_ids})

        for out in sorted(outputs, key=lambda o: (str(o["channel"]), o["rule"].id)):
            if out["channel"] in conflicted:
                continue
            if out["kind"] == "param":
                self._apply_param(out, report, resolution)
            else:
                self._apply_effect(out, composition, resolution)

    def _apply_param(self, out: dict[str, Any], report: Report,
                     resolution: TraitResolution) -> None:
        node: ResolvedNode = out["node"]
        param = out["param"]
        spec = node.component.params.get(param)
        if spec is None:
            return
        source = node.sources.get(param)
        previous = node.values.get(param, spec.default)
        if source is not None and source.source == FROM_OVERRIDE and node.from_plan:
            report.note("TRAIT_PATCH_SKIPPED_BY_OVERRIDE",
                        "'%s.%s' resta esplicito" % (node.id, param),
                        where=node.path)
            resolution.skipped.append({"reason": "override", "node": node.id,
                                       "param": param, "trait": out["trait"],
                                       "rule": out["rule"].id})
            return
        variables = numeric(node.values)
        variables.update({
            "value": float(previous) if isinstance(previous, (int, float)) else 0.0,
            "trait": float(out["value"]),
            "default": float(spec.default) if isinstance(spec.default, (int, float)) else 0.0,
            "min": float(spec.min) if spec.min is not None else float("-inf"),
            "max": float(spec.max) if spec.max is not None else float("inf"),
        })
        try:
            raw = evaluate(out["patch"].expression, variables)
        except ExpressionError as exc:
            report.warn("TRAIT_PATCH_EXPRESSION",
                        "'%s' non calcolabile: %s" % (out["rule"].id, exc),
                        where=node.path)
            return
        result = spec.coerce(raw)
        if isinstance(result, (int, float)) and abs(float(result) - float(raw)) > 1e-9:
            report.note("TRAIT_PATCH_CLAMPED",
                        "'%s.%s' portato da %s a %s"
                        % (node.id, param, raw, result), where=node.path)
        if result == previous:
            return
        node.values[param] = result
        node.sources[param] = ResolvedValue(
            result, FROM_TRAIT, origin=out["trait"], expression=out["patch"].expression,
            previous=previous)
        resolution.applied.append({
            "kind": "param", "trait": out["trait"], "request_value": out["value"],
            "rule_id": out["rule"].id, "node": node.id, "path": node.path,
            "channel": "%s.%s" % (node.id, param), "previous": previous,
            "result": result, "source": FROM_TRAIT})

    @staticmethod
    def _apply_effect(out: dict[str, Any], composition: ResolvedComposition,
                      resolution: TraitResolution) -> None:
        node: ResolvedNode = out["node"]
        effect: EffectRequest = out["effect"]
        scope = effect.scope or "part:%s" % node.id
        request = EffectRequest(type=effect.type, scope=scope,
                                params=dict(effect.params), amount=effect.amount)
        node.effects.append(request)
        composition.effects.append((node.id, request))
        resolution.applied.append({
            "kind": "effect", "trait": out["trait"], "rule_id": out["rule"].id,
            "node": node.id, "path": node.path,
            "channel": "%s.%s.%s" % (node.id, request.type, request.scope),
            "source": FROM_TRAIT})

    @staticmethod
    def _rederive(composition: ResolvedComposition, report: Report) -> None:
        for node in composition.walk():
            derivati = {n: s for n, s in node.component.params.items()
                        if s.is_derived and node.source(n) not in (FROM_TRAIT,)}
            if not derivati:
                continue
            parent = composition.node(node.link.parent) if node.link else None
            root = composition.node(composition.root)
            scopes = {"self": numeric(node.values),
                      "parent": numeric(parent.values) if parent else {},
                      "root": numeric(root.values) if root else {}}
            for name, spec in derivati.items():
                try:
                    value = spec.coerce(evaluate(spec.derived, scopes["self"], scopes))
                except ExpressionError:
                    continue
                node.values[name] = value

    def _trait(self, trait: str, report: Report, where: str = "") -> TraitSpec | None:
        spec = self.registry.trait(trait)
        if spec is None:
            code = "TRAIT_AMBIGUOUS" if self.registry.trait_ambiguous(trait) \
                else "TRAIT_NOT_FOUND"
            report.add(code, "trait sconosciuto o ambiguo: '%s'" % trait,
                       where=where,
                       alternatives=[t.id for t in self.registry.traits()][:8])
            return None
        return spec

    @staticmethod
    def _target(composition: ResolvedComposition, on: str) -> ResolvedNode | None:
        key = composition.graph.root_id if on in ("", "root") else on
        if key in composition.nodes:
            return composition.node(key)
        candidates = [n for n in composition.walk() if n.path == key]
        return candidates[0] if len(candidates) == 1 else None

    @staticmethod
    def _subtree(composition: ResolvedComposition, node: ResolvedNode) -> list[ResolvedNode]:
        out = [node]
        for child in composition.children(node.id):
            out.extend(TraitResolver._subtree(composition, child))
        return out

    @staticmethod
    def _matches(match: TraitMatch, node: ResolvedNode, style: str) -> bool:
        component = node.component
        tags = set(component.tags) | set(node.tags)
        caps = {c.name for c in component.provides}
        caps |= {m.capability for m in component.mounts if m.capability}
        param_roles = {getattr(s, "semantic_role", "")
                       for s in component.params.values() if getattr(s, "semantic_role", "")}
        local = component.id.partition(":")[2] or component.id
        if match.styles and style not in match.styles:
            return False
        if match.roles and component.role not in match.roles:
            return False
        if match.tags and not set(match.tags) <= tags:
            return False
        if match.capabilities and not any(c in caps for c in match.capabilities):
            return False
        if match.param_roles and not any(r in param_roles for r in match.param_roles):
            return False
        if match.params and not any(p in component.params for p in match.params):
            return False
        if match.components and component.id not in match.components and local not in match.components:
            return False
        return True

    @staticmethod
    def _worth_unsupported(node: ResolvedNode) -> bool:
        tags = set(node.component.tags) | set(node.tags)
        return bool(node.component.role and not ({"accent", "detail"} & tags))

    @staticmethod
    def _channel_text(channel: tuple) -> str:
        return ".".join(str(p) for p in channel)


def resolve_traits(composition: ResolvedComposition, registry,
                   report: Report | None = None) -> TraitResolution:
    return TraitResolver(registry, style=composition.style).run(composition, report=report)


def trait_requests_from_dict(items: Iterable[dict[str, Any]] | None) -> list[TraitRequest]:
    out: list[TraitRequest] = []
    for item in items or ():
        if not isinstance(item, dict):
            continue
        if "trait" not in item or "value" not in item:
            continue
        out.append(TraitRequest(
            trait=str(item["trait"]),
            value=item["value"],
            op=str(item.get("op") or SET),
            on=str(item.get("on") or "root"),
            scope=str(item.get("scope") or SUBTREE),
        ))
    return out
