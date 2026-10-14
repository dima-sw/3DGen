from __future__ import annotations

from math import dist

import pytest

from app.build.assembler import build
from app.core.effect import apply_effects
from app.core.errors import Report
from app.core.component import Attachment, Component, Piece
from app.core.graph import CompositionGraph
from app.core.layout import LayoutPolicy, resolve_layout
from app.core.params import ParamSpec
from app.core.registry import load
from app.core.resolver import resolve
from app.core.structural import (StructuralTarget, StructuralTraitRequest,
                                 StructuralTraitRule, StructuralTraitSpec,
                                 resolve_structural_traits)
from app.core.traits import resolve_traits


def _registry():
    return load(["app/plugins"]).freeze()


def _run(root_id, root_ref, trait, count, target, detail=1, params=None):
    registry = _registry()
    graph = CompositionGraph(detail_level=detail, seed=7)
    graph.set_root(root_id, root_ref, **(params or {}))
    graph.structural_traits = [StructuralTraitRequest(trait, count, on=target)]
    report = Report()
    structural = resolve_structural_traits(graph, registry, report=report)
    resolved = resolve(graph, registry, report=report)
    resolve_traits(resolved, registry, report=report)
    layout = resolve_layout(resolved, registry, report=report)
    result = build(apply_effects(resolved, registry), report=report)
    return graph, structural, resolved, layout, result, report


def test_structural_traits_expand_generic_counts_before_resolution():
    graph, resolution, resolved, layout, result, report = _run(
        "fox", "fox_stylized:fox", "fantasy:tail_count", 9, "fox/body")

    tails = [node for node in graph.children("body") if node.ref.endswith(":tail")]
    assert report.ok
    assert len(tails) == 9
    assert len(layout.placements) == 9
    assert result.triangles > 0
    assert resolution.plan.operations[0].op == "ensure_count"


@pytest.mark.parametrize("count", (1, 3, 5, 9))
def test_fox_count_matrix(count):
    _, _, resolved, layout, _, report = _run(
        "fox", "fox_stylized:fox", "fantasy:tail_count", count, "fox/body")
    assert report.ok
    assert len([node for node in resolved.walk() if node.component.role == "tail"]) == count
    assert len(layout.placements) == count


def test_fox_postmortem_frames_are_distinct_and_deterministic():
    first = _run("fox", "fox_stylized:fox", "fantasy:tail_count", 9, "fox/body")
    second = _run("fox", "fox_stylized:fox", "fantasy:tail_count", 9, "fox/body")
    first_layout, second_layout = first[3], second[3]
    positions = [placement.frame.position for placement in first_layout.placements]
    angles = [placement.frame.angle for placement in first_layout.placements]
    assert len({placement.socket for placement in first_layout.placements}) == 9
    assert min(dist(a, b) for index, a in enumerate(positions)
               for b in positions[index + 1:]) > 0.0
    assert angles == [-70.0, -52.5, -35.0, -17.5, 0.0,
                      17.5, 35.0, 52.5, 70.0]
    assert first_layout.to_dict() == second_layout.to_dict()


def test_structural_domains_keep_symmetric_side_assignment():
    graph, _, resolved, layout, result, report = _run(
        "car", "vehicle_stylized:car", "vehicle:wheel_count", 10,
        "car/wheel_fl")

    wheels = [node for node in resolved.walk() if node.component.role == "wheel"]
    sides = [node.link.side for node in wheels]
    assert report.ok
    assert len(wheels) == 10
    assert sides.count("l") == sides.count("r") == 5
    assert len(layout.placements) == 10
    assert result.triangles > 0


@pytest.mark.parametrize("count", (4, 6, 8, 10))
def test_wheel_count_matrix(count):
    _, _, resolved, layout, _, report = _run(
        "car", "vehicle_stylized:car", "vehicle:wheel_count", count,
        "car/wheel_fl")
    wheels = [node for node in resolved.walk() if node.component.role == "wheel"]
    assert report.ok
    assert len(wheels) == count
    assert len(layout.placements) == count


def test_wheel_postmortem_contact_stays_inside_body_and_above_ground():
    _, _, _, layout, result, report = _run(
        "car", "vehicle_stylized:car", "vehicle:wheel_count", 10,
        "car/wheel_fl")
    body_bounds = result.node("body").mesh.bounds
    assert report.ok
    for placement in layout.placements:
        x, y, _ = placement.frame.position
        assert abs(x) - placement.frame.radius <= max(abs(body_bounds[0][0]),
                                                      abs(body_bounds[1][0]))
        assert y - placement.frame.radius >= 0.0


def test_structural_domain_can_grow_anatomical_arms():
    _, _, resolved, layout, result, report = _run(
        "corpo", "humanoid_anatomical:body", "character:arm_count", 6,
        "corpo/torso/arm_l")

    arms = [node for node in resolved.walk() if node.component.role == "arm"]
    assert report.ok
    assert len(arms) == 6
    assert len(layout.placements) == 6
    assert result.triangles > 0


@pytest.mark.parametrize("count", (2, 4, 6))
def test_arm_count_matrix(count):
    _, _, resolved, layout, _, report = _run(
        "corpo", "humanoid_anatomical:body", "character:arm_count", count,
        "corpo/torso/arm_l")
    arms = [node for node in resolved.walk() if node.component.role == "arm"]
    assert report.ok
    assert len(arms) == count
    assert len(layout.placements) == count


def test_layout_policy_is_extensible_without_core_domain_knowledge():
    policy = LayoutPolicy("test_policy", lambda region, nodes, sizes: ([], 1.0, None))
    registry = load(["app/plugins"])
    assert registry.register_layout_policy(policy, "test_extension")
    assert registry.layout_policy("test_extension:test_policy") is policy


def test_third_party_structural_trait_uses_only_generic_rewrite_runtime():
    registry = load(["app/plugins"])
    host = Component(
        id="host", build=lambda values, ctx: Piece(mesh=None),
        children=lambda values, ctx: [Attachment(id="antenna", component="antenna")],
        params={"size": ParamSpec(1.0)}, role="container")
    antenna = Component(
        id="antenna", build=lambda values, ctx: Piece(mesh=None),
        params={"size": ParamSpec(0.1)}, role="signal", tags=("signal",))
    assert registry.register_component(host, "third_party")
    assert registry.register_component(antenna, "third_party")
    spec = StructuralTraitSpec("custom:antenna_count", value=ParamSpec(1, min=0, max=8),
                               max_count=8, owner="third_party")
    rule = StructuralTraitRule(
        id="antenna_count", trait="custom:antenna_count",
        prototype="host/antenna", component="third_party:antenna",
        group="signal", target=StructuralTarget(role="signal"))
    assert registry.register_structural_trait(spec)
    assert registry.register_structural_trait_rule(rule, "third_party")
    graph = CompositionGraph(detail_level=1)
    graph.set_root("host", "third_party:host")
    graph.structural_traits = [StructuralTraitRequest(
        "custom:antenna_count", 3, on="host/antenna")]
    report = Report()
    resolution = resolve_structural_traits(graph, registry, report=report)
    assert report.ok
    assert len([node for node in graph.children("host")
                if node.ref == "third_party:antenna"]) == 3
    assert resolution.plan.operations[0].op == "ensure_count"


def test_structural_requests_round_trip_as_json_data():
    registry = _registry()
    graph = CompositionGraph(detail_level=1)
    graph.set_root("fox", "fox_stylized:fox")
    graph.structural_traits = [StructuralTraitRequest(
        "fantasy:tail_count", 9, on="fox/body", target={"role": "tail"})]
    restored = CompositionGraph.from_dict(graph.to_dict())
    assert restored.structural_traits[0].trait == "fantasy:tail_count"
    assert restored.structural_traits[0].target == {"role": "tail"}


def test_linear_layout_scale_to_fit_uses_public_component_parameters():
    _, _, resolved, layout, _, report = _run(
        "car", "vehicle_stylized:car", "vehicle:wheel_count", 10,
        "car/wheel_fl", params={"length": 2.4})
    assert report.ok
    assert len(layout.placements) == 10
    assert 0.70 <= layout.placements[0].scale < 1.0
    assert resolved is not None


def test_linear_layout_reports_scale_below_minimum_without_partial_success():
    _, _, _, layout, _, report = _run(
        "car", "vehicle_stylized:car", "vehicle:wheel_count", 10,
        "car/wheel_fl", params={"length": 1.4, "wheel_size": 1.10})
    assert not report.ok
    assert not layout.placements
    assert any(problem.code == "scale_below_minimum"
               for problem in layout.problems)


def test_structural_rewrite_is_idempotent():
    registry = _registry()
    graph = CompositionGraph(detail_level=1)
    graph.set_root("fox", "fox_stylized:fox")
    graph.structural_traits = [StructuralTraitRequest(
        "fantasy:tail_count", 9, on="fox/body")]
    first = resolve_structural_traits(graph, registry, report=Report())
    before = graph.to_dict()
    second = resolve_structural_traits(graph, registry, report=Report())
    assert before == graph.to_dict()
    assert len(first.created[0]["ids"]) == 8
    assert second.created == []


def test_best_effort_overcount_warns_without_removing_instances():
    registry = _registry()
    graph = CompositionGraph(detail_level=1)
    graph.set_root("fox", "fox_stylized:fox")
    graph.structural_traits = [StructuralTraitRequest(
        "std:instance_count", 0, on="fox/body/tail", mode="best_effort")]
    report = Report()
    resolution = resolve_structural_traits(graph, registry, report=report)
    assert report.ok
    assert len([node for node in graph.walk() if node.ref.endswith(":tail")]) == 1
    assert resolution.skipped[0]["existing"] == 1
