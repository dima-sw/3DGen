"""Deterministic layout regions and policies.

Layout generates virtual socket frames for already-resolved repeated nodes. It
does not create graph nodes and it does not judge aesthetics.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import cos, radians, sin
from typing import Any, Callable, Iterable

import numpy as np

from app.core.component import BuildContext
from app.core.errors import Report
from app.core.socket import Socket, unit

POLICY_FAN = "fan"
POLICY_LINEAR = "linear"


@dataclass(frozen=True)
class LayoutRegion:
    id: str
    anchor_socket: str = ""
    allows_role: str = ""
    allows_capability: str = ""
    allows_tags: tuple[str, ...] = ()
    default_policy: str = POLICY_LINEAR
    allowed_policies: tuple[str, ...] = (POLICY_LINEAR,)
    capacity: int = 0
    span: float = 0.0
    spread_angle: float = 0.0
    min_spacing: float = 0.0
    min_scale: float = 1.0
    max_scale: float = 1.0
    allow_scale_to_fit: bool = False
    symmetry_group: str = ""
    side: str = ""
    center: tuple[float, float, float] = (0.0, 0.0, 0.0)
    direction: tuple[float, float, float] = (1.0, 0.0, 0.0)
    up: tuple[float, float, float] = (0.0, 1.0, 0.0)
    axis: tuple[float, float, float] = (0.0, 0.0, 1.0)
    elevation_span: float = 0.0
    depth_offset: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "allows_tags", tuple(self.allows_tags))
        object.__setattr__(self, "allowed_policies", tuple(self.allowed_policies))

    def allows(self, node) -> bool:
        comp = node.component
        if self.allows_role and comp.role != self.allows_role:
            return False
        if self.allows_capability and not comp.provides_capability(self.allows_capability):
            return False
        if self.allows_tags and not set(self.allows_tags) <= set(comp.tags):
            return False
        return True

    def validate(self, registry=None) -> list[str]:
        errors = []
        if not self.id:
            errors.append("missing_id")
        if self.capacity < 0:
            errors.append("invalid_capacity")
        if self.span < 0 or self.spread_angle < 0:
            errors.append("invalid_span")
        if self.min_spacing < 0:
            errors.append("negative_spacing")
        if self.min_scale <= 0 or self.max_scale <= 0 or self.min_scale > self.max_scale:
            errors.append("invalid_scale_range")
        if self.default_policy not in self.allowed_policies:
            errors.append("default_policy_not_allowed")
        if registry is not None:
            for policy in self.allowed_policies:
                if registry.layout_policy(policy) is None:
                    errors.append("unknown_policy:%s" % policy)
        return errors


@dataclass(frozen=True)
class LayoutFrame:
    socket: str
    position: tuple[float, float, float]
    direction: tuple[float, float, float]
    up: tuple[float, float, float]
    radius: float
    angle: float = 0.0

    def to_socket(self, capabilities=(), side: str = "", tags=()) -> Socket:
        return Socket(name=self.socket, position=np.asarray(self.position, dtype=float),
                      direction=np.asarray(self.direction, dtype=float),
                      up=np.asarray(self.up, dtype=float), radius=float(self.radius),
                      capabilities=tuple(capabilities), side=side, tags=frozenset(tags))

    def to_dict(self) -> dict[str, Any]:
        return {"socket": self.socket, "position": list(self.position),
                "direction": list(self.direction), "up": list(self.up),
                "radius": self.radius, "angle": self.angle}


@dataclass
class LayoutPlacement:
    node: str
    parent: str
    region: str
    policy: str
    frame_index: int
    socket: str
    scale: float = 1.0
    frame: LayoutFrame | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"node": self.node, "parent": self.parent, "region": self.region,
                "policy": self.policy, "frame_index": self.frame_index,
                "socket": self.socket, "scale": self.scale,
                **({"frame": self.frame.to_dict()} if self.frame else {})}


@dataclass
class LayoutProblem:
    code: str
    parent: str = ""
    child_group: str = ""
    requested: int = 0
    placed: int = 0
    remaining: int = 0
    region: str = ""
    required_span: float = 0.0
    available_span: float = 0.0
    min_scale: float = 1.0
    max_scale: float = 1.0
    attempts: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class LayoutPlan:
    placements: list[LayoutPlacement] = field(default_factory=list)
    problems: list[LayoutProblem] = field(default_factory=list)
    provenance: list[dict[str, Any]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def to_dict(self) -> dict[str, Any]:
        return {"placements": [p.to_dict() for p in self.placements],
                "problems": [p.to_dict() for p in self.problems],
                "provenance": list(self.provenance)}

    def by_parent(self) -> dict[str, list[LayoutPlacement]]:
        out: dict[str, list[LayoutPlacement]] = {}
        for placement in self.placements:
            out.setdefault(placement.parent, []).append(placement)
        return out


@dataclass
class LayoutPolicy:
    id: str
    apply: Callable[[LayoutRegion, list[Any], list[float]], tuple[list[LayoutFrame], float, LayoutProblem | None]]
    description: str = ""


class LayoutEngine:
    def __init__(self, registry) -> None:
        self.registry = registry

    def run(self, composition, report: Report | None = None) -> LayoutPlan:
        report = report if report is not None else composition.report
        plan = LayoutPlan()
        groups = self._groups(composition)
        for key, nodes in groups.items():
            parent_id, group_key = key
            parent = composition.node(parent_id)
            if parent is None or not nodes:
                continue
            regions = self._regions(parent, composition, report)
            # Repetition alone is not a layout request: components such as
            # four legs may be repeated but remain governed by their ordinary
            # resolver sockets.  A problem belongs only to a region that
            # explicitly claims at least one member of this group.
            regions = [region for region in regions
                       if any(region.allows(node) for node in nodes)]
            if not regions:
                continue
            selected = [r for r in regions if all(r.allows(n) for n in nodes)]
            if not selected:
                problem = LayoutProblem("no_compatible_region", parent=parent.path,
                                        child_group=group_key, requested=len(nodes),
                                        remaining=len(nodes))
                plan.problems.append(problem)
                report.add("LAYOUT_PROBLEM", "nessuna LayoutRegion compatibile",
                           where=parent.path, why=problem.code)
                continue
            self._place_group(parent, sorted(nodes, key=lambda n: n.path),
                              selected, plan, report, group_key)
        composition.layout_plan = plan
        if getattr(composition, "graph", None) is not None:
            composition.graph.layout_plan = plan
        return plan

    def _groups(self, composition) -> dict[tuple[str, str], list[Any]]:
        groups: dict[tuple[str, str], list[Any]] = {}
        for node in composition.walk():
            if node.link is None:
                continue
            key = node.component.role or ",".join(sorted(node.component.tags)) or node.ref
            groups.setdefault((node.link.parent, key), []).append(node)
        return groups

    def _regions(self, parent, composition, report) -> list[LayoutRegion]:
        provider = getattr(parent.component, "layout_regions", ())
        ctx = BuildContext(style=composition.style, detail_level=composition.detail_level,
                           depth=parent.depth, seed=composition.seed,
                           budget=composition.budget, path=parent.path,
                           report=report, node=parent, composition=composition)
        if callable(provider):
            regions = list(provider(parent.values, ctx) or ())
        else:
            regions = list(provider or ())
        seen: set[str] = set()
        out = []
        for region in regions:
            if region.id in seen:
                report.add("LAYOUT_REGION_INVALID",
                           "LayoutRegion duplicata: '%s'" % region.id,
                           where=parent.path)
                continue
            seen.add(region.id)
            errors = region.validate(self.registry)
            if errors:
                report.add("LAYOUT_REGION_INVALID",
                           "LayoutRegion '%s' non valida" % region.id,
                           where=parent.path, why=", ".join(errors))
                continue
            out.append(region)
        return out

    def _place_group(self, parent, nodes, regions, plan, report, group_key) -> None:
        if len(regions) == 2 and regions[0].symmetry_group and \
                regions[0].symmetry_group == regions[1].symmetry_group:
            if len(nodes) % 2 and all(n.link.side in ("l", "r") for n in nodes):
                problem = LayoutProblem("symmetry_conflict", parent=parent.path,
                                        child_group=group_key, requested=len(nodes),
                                        remaining=len(nodes),
                                        region=regions[0].symmetry_group)
                plan.problems.append(problem)
                report.add("LAYOUT_PROBLEM", "conteggio dispari in regioni simmetriche",
                           where=parent.path, why=problem.code)
                return
            left = [n for n in nodes if n.link.side == "l"]
            right = [n for n in nodes if n.link.side == "r"]
            if left and right:
                for side_nodes, region in ((left, self._region_for_side(regions, "l")),
                                           (right, self._region_for_side(regions, "r"))):
                    self._place_in_region(parent, side_nodes, region, plan, report, group_key)
                return
        self._place_in_region(parent, nodes, regions[0], plan, report, group_key)

    @staticmethod
    def _region_for_side(regions, side):
        for region in regions:
            if region.side == side:
                return region
        return regions[0]

    def _place_in_region(self, parent, nodes, region, plan, report, group_key) -> None:
        if region.capacity and len(nodes) > region.capacity:
            problem = LayoutProblem("capacity_exceeded", parent=parent.path,
                                    child_group=group_key, requested=len(nodes),
                                    region=region.id, remaining=len(nodes))
            plan.problems.append(problem)
            report.add("LAYOUT_PROBLEM", "LayoutRegion capacity superata",
                       where=parent.path, why=problem.code)
            return
        policy_id = region.default_policy
        policy = self.registry.layout_policy(policy_id)
        if policy is None:
            problem = LayoutProblem("invalid_attachment", parent=parent.path,
                                    child_group=group_key, requested=len(nodes),
                                    region=region.id, remaining=len(nodes))
            plan.problems.append(problem)
            report.add("LAYOUT_PROBLEM", "LayoutPolicy sconosciuta: '%s'" % policy_id,
                       where=parent.path, why=problem.code)
            return
        sizes = [self._envelope(n) for n in nodes]
        frames, scale, problem = policy.apply(region, nodes, sizes)
        if problem is not None:
            problem.parent = parent.path
            problem.child_group = group_key
            problem.requested = len(nodes)
            problem.remaining = len(nodes)
            plan.problems.append(problem)
            report.add("LAYOUT_PROBLEM", "layout fallito: %s" % problem.code,
                       where=parent.path, why=problem.code)
            return
        for index, (node, frame) in enumerate(zip(nodes, frames)):
            socket_name = "%s__%s_%d" % (region.id, policy_id, index + 1)
            frame = LayoutFrame(socket=socket_name, position=frame.position,
                                direction=frame.direction, up=frame.up,
                                radius=frame.radius, angle=frame.angle)
            node.link.parent_socket = socket_name
            node.link.scale_mode = "none"
            node.link.layout_scale = scale
            plan.placements.append(LayoutPlacement(node=node.id, parent=parent.id,
                                                   region=region.id,
                                                   policy=policy_id,
                                                   frame_index=index,
                                                   socket=socket_name,
                                                   scale=scale, frame=frame))
        plan.provenance.append({"region": region.id, "policy": policy_id,
                                "requested": len(nodes), "placed": len(frames),
                                "scale": scale, "fit": "success"})

    @staticmethod
    def _envelope(node) -> float:
        vals = node.values
        candidates = ["layout_envelope", "diameter", "width", "girth",
                      "radius", "height", "length", "size"]
        for name in candidates:
            if name in vals:
                try:
                    return max(float(vals[name]), 1e-4)
                except (TypeError, ValueError):
                    pass
        return 0.1


def fan_policy(region: LayoutRegion, nodes, sizes: list[float]):
    count = len(nodes)
    if count <= 0:
        return [], 1.0, None
    if region.capacity and count > region.capacity:
        return [], 1.0, LayoutProblem("capacity_exceeded", region=region.id)
    spread = float(region.spread_angle or 0.0)
    angles = [0.0] if count == 1 else [
        -spread * 0.5 + spread * i / (count - 1) for i in range(count)]
    direction = unit(region.direction, fallback=(1.0, 0.0, 0.0))
    up = unit(region.up, fallback=(0.0, 1.0, 0.0))
    axis = unit(region.axis, fallback=tuple(up))
    center = np.asarray(region.center, dtype=float)
    frames = []
    for i, angle in enumerate(angles):
        rot = _axis_angle(axis, angle)
        dir_i = rot @ direction
        elev = 0.0 if count == 1 else region.elevation_span * (i / (count - 1) - 0.5)
        depth = region.depth_offset * ((i % 2) * 2 - 1) * (abs(angle) / max(spread, 1.0))
        pos = center + up * elev + np.cross(axis, up) * depth
        frames.append(LayoutFrame(socket="", position=tuple(float(x) for x in pos),
                                  direction=tuple(float(x) for x in dir_i),
                                  up=tuple(float(x) for x in up),
                                  radius=max(sizes[i] * 0.5, 1e-4),
                                  angle=float(angle)))
    return frames, 1.0, None


def linear_policy(region: LayoutRegion, nodes, sizes: list[float]):
    count = len(nodes)
    if count <= 0:
        return [], 1.0, None
    if region.capacity and count > region.capacity:
        return [], 1.0, LayoutProblem("capacity_exceeded", region=region.id)
    largest = max(sizes or [0.1])
    spacing = max(float(region.min_spacing), 0.0)
    required = count * largest + max(0, count - 1) * spacing
    available = float(region.span or required)
    scale = 1.0
    attempts = [{"policy": POLICY_LINEAR, "scale": 1.0, "required_span": required,
                 "available_span": available}]
    if required > available + 1e-9:
        if not region.allow_scale_to_fit:
            return [], 1.0, LayoutProblem("insufficient_span", region=region.id,
                                          required_span=required,
                                          available_span=available,
                                          attempts=attempts)
        scale = (available - max(0, count - 1) * spacing) / max(count * largest, 1e-9)
        attempts.append({"policy": POLICY_LINEAR, "scale": scale,
                         "result": "scale_to_fit"})
        if scale < region.min_scale:
            return [], scale, LayoutProblem("scale_below_minimum", region=region.id,
                                            required_span=required,
                                            available_span=available,
                                            min_scale=region.min_scale,
                                            max_scale=region.max_scale,
                                            attempts=attempts)
        scale = min(scale, region.max_scale)
    axis = unit(region.axis, fallback=(0.0, 0.0, 1.0))
    direction = unit(region.direction, fallback=(1.0, 0.0, 0.0))
    up = unit(region.up, fallback=(0.0, 1.0, 0.0))
    center = np.asarray(region.center, dtype=float)
    offsets = [0.0] if count == 1 else np.linspace(-available * 0.5, available * 0.5, count)
    frames = []
    for i, offset in enumerate(offsets):
        pos = center + axis * float(offset)
        frames.append(LayoutFrame(socket="", position=tuple(float(x) for x in pos),
                                  direction=tuple(float(x) for x in direction),
                                  up=tuple(float(x) for x in up),
                                  radius=max(sizes[i] * 0.5 * scale, 1e-4)))
    return frames, float(scale), None


def _axis_angle(axis, degrees):
    a = unit(axis)
    t = radians(float(degrees))
    x, y, z = a
    c, s = cos(t), sin(t)
    return np.array([
        [c + x * x * (1 - c), x * y * (1 - c) - z * s, x * z * (1 - c) + y * s],
        [y * x * (1 - c) + z * s, c + y * y * (1 - c), y * z * (1 - c) - x * s],
        [z * x * (1 - c) - y * s, z * y * (1 - c) + x * s, c + z * z * (1 - c)],
    ])


def default_policies() -> tuple[LayoutPolicy, ...]:
    return (
        LayoutPolicy(POLICY_FAN, fan_policy, "uniform fan over an angular span"),
        LayoutPolicy(POLICY_LINEAR, linear_policy, "uniform linear distribution"),
    )


def resolve_layout(composition, registry, report: Report | None = None) -> LayoutPlan:
    return LayoutEngine(registry).run(composition, report=report)
