from __future__ import annotations

from pathlib import Path

import pytest

from app.ai.provider import OfflineProvider
from app.core.component import Component, Piece
from app.core.effect import apply_effects
from app.core.graph import CompositionGraph, EffectRequest, FROM_TRAIT
from app.core.params import DISTANCE, RATIO, ParamSpec
from app.core.registry import Registry, load
from app.core.resolver import resolve
from app.core.session import Options, Session, Version
from app.core.traits import (ParamPatch, TraitMatch, TraitRequest, TraitRule,
                             TraitSpec, resolve_traits)
from app.core.vocabulary import EffectSpec, STAGE_LOCAL
from app.core.planner.plans import validate_plan
from app.core.planner.vocabulary import build_vocabulary


PLUGIN = Path(__file__).resolve().parent.parent / "app" / "plugins"


def _piece(values, ctx):
    return Piece(mesh=None)


def component(id: str, **kwargs) -> Component:
    return Component(id=id, build=_piece, **kwargs)


@pytest.fixture(scope="module")
def catalog():
    registry = load([PLUGIN])
    assert not registry.report.errors(), registry.report.describe()
    return registry.freeze()


def _trait_registry(*rules: TraitRule) -> Registry:
    registry = Registry()
    registry.register_component(component(
        "demo:part",
        params={"length": ParamSpec(1.0, DISTANCE, min=0.2, max=3.0,
                                    semantic_role="length"),
                "width": ParamSpec(0.4, DISTANCE, min=0.1, max=2.0,
                                   semantic_role="girth"),
                "depth": ParamSpec(0.3, DISTANCE, min=0.1, max=2.0,
                                   semantic_role="girth")},
        role="part", tags=frozenset({"demo"})))
    registry.register_trait(TraitSpec(
        id="custom:elongation", aliases=("elongation",),
        value=ParamSpec(0.0, RATIO, min=0.0, max=1.0),
        scopes=("local", "subtree"), operations=("set", "add")))
    for rule in rules:
        registry.register_trait_rule(rule, plugin_id="third_party")
    return registry.freeze()


def test_trait_registry_aliases_and_ambiguity():
    registry = Registry()
    a = TraitSpec(id="a:mass", aliases=("mass",))
    b = TraitSpec(id="b:mass", aliases=("mass",))
    registry.register_trait(a)
    registry.register_trait(b)

    assert registry.trait("a:mass") is a
    assert registry.trait("b:mass") is b
    assert registry.trait("mass") is None
    assert registry.trait_ambiguous("mass")

    vocabulary = build_vocabulary(registry.freeze())
    assert {t.id for t in vocabulary.traits} == {"a:mass", "b:mass"}
    assert all(t.alias == "" for t in vocabulary.traits)


def test_third_party_extension_can_patch_by_param_semantic_role():
    rule = TraitRule(
        id="length_law", trait="custom:elongation",
        match=TraitMatch(param_roles=("length",)),
        patches=(ParamPatch(semantic_role="length",
                            expression="value * (1.0 + trait)"),))
    registry = _trait_registry(rule)
    graph = CompositionGraph()
    graph.set_root("root", "demo:part")
    graph.traits = [TraitRequest("elongation", 0.5)]

    resolved = resolve(graph, registry)
    traits = resolve_traits(resolved, registry)

    assert traits.applied
    assert resolved.node("root").values["length"] == pytest.approx(1.5)
    assert resolved.node("root").source("length") == FROM_TRAIT


def test_incompatible_set_requests_do_not_leave_a_hidden_winner():
    rule = TraitRule(
        id="length_law", trait="custom:elongation",
        match=TraitMatch(param_roles=("length",)),
        patches=(ParamPatch(semantic_role="length",
                            expression="value * (1.0 + trait)"),))
    registry = _trait_registry(rule)
    graph = CompositionGraph()
    graph.set_root("root", "demo:part")
    graph.traits = [TraitRequest("elongation", 0.2),
                    TraitRequest("elongation", 0.8)]

    resolved = resolve(graph, registry)
    traits = resolve_traits(resolved, registry)

    assert "TRAIT_VALUE_CONFLICT" in resolved.report.codes()
    assert traits.values == {}
    assert resolved.node("root").values["length"] == pytest.approx(1.0)


def test_same_channel_conflicts_skip_both_patches_but_disjoint_compose():
    conflict_a = TraitRule(
        id="a_width", trait="custom:elongation",
        match=TraitMatch(params=("width",)),
        patches=(ParamPatch(param="width", expression="value + trait"),))
    conflict_b = TraitRule(
        id="b_width", trait="custom:elongation",
        match=TraitMatch(params=("width",)),
        patches=(ParamPatch(param="width", expression="value + trait * 2"),))
    registry = _trait_registry(conflict_a, conflict_b)
    graph = CompositionGraph()
    graph.set_root("root", "demo:part")
    graph.traits = [TraitRequest("custom:elongation", 0.5)]

    resolved = resolve(graph, registry)
    traits = resolve_traits(resolved, registry)

    assert "TRAIT_RULE_CONFLICT" in resolved.report.codes()
    assert not traits.applied
    assert resolved.node("root").values["width"] == pytest.approx(0.4)

    depth_rule = TraitRule(
        id="c_depth", trait="custom:elongation",
        match=TraitMatch(params=("depth",)),
        patches=(ParamPatch(param="depth", expression="value + trait"),))
    registry = _trait_registry(conflict_a, depth_rule)
    resolved = resolve(graph, registry)
    traits = resolve_traits(resolved, registry)

    assert "TRAIT_RULE_CONFLICT" not in resolved.report.codes()
    assert resolved.node("root").values["width"] == pytest.approx(0.9)
    assert resolved.node("root").values["depth"] == pytest.approx(0.8)
    assert len(traits.applied) == 2


def test_explicit_user_override_wins_over_trait_patch():
    rule = TraitRule(
        id="width_law", trait="custom:elongation",
        match=TraitMatch(params=("width",)),
        patches=(ParamPatch(param="width", expression="value + trait"),))
    registry = _trait_registry(rule)
    graph = CompositionGraph()
    graph.set_root("root", "demo:part", width=0.7)
    graph.traits = [TraitRequest("custom:elongation", 0.5)]

    resolved = resolve(graph, registry)
    traits = resolve_traits(resolved, registry)

    assert resolved.node("root").values["width"] == pytest.approx(0.7)
    assert "TRAIT_PATCH_SKIPPED_BY_OVERRIDE" in resolved.report.codes()
    assert traits.skipped[0]["reason"] == "override"


def test_trait_effect_output_reuses_registered_effects():
    registry = Registry()
    registry.register_component(component(
        "demo:part",
        params={"length": ParamSpec(1.0, DISTANCE, min=0.2, max=3.0,
                                    semantic_role="length")},
        role="part", tags=frozenset({"demo"})))
    registry.register_trait(TraitSpec(
        id="custom:elongation", aliases=("elongation",),
        value=ParamSpec(0.0, RATIO, min=0.0, max=1.0),
        scopes=("local", "subtree"), operations=("set", "add")))
    registry.register_effect(EffectSpec(id="fx:glow", stage=STAGE_LOCAL,
                                        scopes=("part",)))
    registry.register_trait_rule(TraitRule(
        id="emit_effect", trait="custom:elongation",
        match=TraitMatch(roles=("part",)),
        effects=(EffectRequest("fx:glow", scope="part:"),)),
        plugin_id="third_party")
    registry.freeze()

    graph = CompositionGraph()
    graph.set_root("root", "demo:part")
    graph.traits = [TraitRequest("custom:elongation", 0.2)]
    resolved = resolve(graph, registry)
    traits = resolve_traits(resolved, registry)

    assert any(item["kind"] == "effect" for item in traits.applied)
    effected = apply_effects(resolved, registry)
    assert effected.planned[0].id == "fx:glow"


def test_body_mass_propagates_and_local_add_overrides_deeper_node(catalog):
    session = Session(provider=OfflineProvider())
    session.registry = catalog
    graph = CompositionGraph(style="low_poly", detail_level=2)
    graph.set_root("root", "humanoid_anatomical:body")
    graph.traits = [
        TraitRequest("body_mass", 0.6),
        TraitRequest("body_mass", 0.3, op="add", on="root/torso/abdomen",
                     scope="local"),
    ]

    result = session.build(graph, Options(detail_level=2, check=False))
    values = result.traits.values

    assert values["root"]["std:body_mass"] == pytest.approx(0.6)
    assert values["root/torso"]["std:body_mass"] == pytest.approx(0.6)
    assert values["root/torso/abdomen"]["std:body_mass"] == pytest.approx(0.9)
    assert result.resolved.node("root/torso/abdomen").source("width") == FROM_TRAIT


def test_body_mass_changes_humanoid_real_public_params(catalog):
    session = Session(provider=OfflineProvider())
    session.registry = catalog
    graph = CompositionGraph(style="low_poly", detail_level=2)
    graph.set_root("root", "humanoid_anatomical:body")
    graph.traits = [TraitRequest("std:body_mass", 1.0)]

    result = session.build(graph, Options(detail_level=2, check=False))
    assert result.resolved.node("root").source("body_mass") == FROM_TRAIT
    assert result.resolved.node("root/torso").source("shoulder_width") == FROM_TRAIT
    assert result.resolved.node("root/torso/shoulder_l").source("radius") == FROM_TRAIT
    assert result.resolved.node("root/torso/hip_l").source("radius") == FROM_TRAIT
    assert result.resolved.node("root/torso/neck/head").source("head_width") == FROM_TRAIT


def test_mixed_plugin_graph_leaves_incompatible_robot_unchanged(catalog):
    session = Session(provider=OfflineProvider())
    session.registry = catalog
    graph = CompositionGraph(style="low_poly", detail_level=1)
    graph.set_root("fox", "fox_stylized:fox")
    graph.traits = [TraitRequest("body_mass", 0.8)]

    result = session.build(graph, Options(detail_level=1, check=False))
    assert result.resolved.node("fox/body/head").source("head_size") == FROM_TRAIT

    registry = Registry()
    registry.register_component(component(
        "demo:robot_arm",
        params={"width": ParamSpec(0.4, DISTANCE, min=0.1, max=2.0,
                                   semantic_role="girth")},
        role="arm", tags=frozenset({"robot"})))
    for trait in catalog.traits():
        registry.register_trait(trait)
    for rule in catalog.trait_rules("std:body_mass"):
        registry.register_trait_rule(rule)
    registry.freeze()
    graph = CompositionGraph()
    graph.set_root("robot", "demo:robot_arm")
    graph.traits = [TraitRequest("body_mass", 0.8)]
    resolved = resolve(graph, registry)
    traits = resolve_traits(resolved, registry)
    assert not traits.applied
    assert resolved.node("robot").values["width"] == pytest.approx(0.4)
    assert "TRAIT_UNSUPPORTED" in resolved.report.codes()


def test_leafiness_changes_tree_crown_without_structural_change(catalog):
    session = Session(provider=OfflineProvider())
    session.registry = catalog
    low = CompositionGraph(style="low_poly", detail_level=2)
    low.set_root("tree", "tree_stylized:tree")
    low.traits = [TraitRequest("leafiness", 0.2)]
    high = CompositionGraph(style="low_poly", detail_level=2)
    high.set_root("tree", "tree_stylized:tree")
    high.traits = [TraitRequest("leafiness", 1.0)]

    low_result = session.build(low, Options(detail_level=2, check=False))
    high_result = session.build(high, Options(detail_level=2, check=False))

    assert low_result.resolved.node("tree/trunk/crown").values["crown_width"] < \
        high_result.resolved.node("tree/trunk/crown").values["crown_width"]
    assert low_result.resolved.node("tree/trunk/crown").source("crown_height") == FROM_TRAIT
    assert len(low_result.resolved.nodes) == len(high_result.resolved.nodes)


def test_planner_schema_and_vocabulary_include_registered_traits_only(catalog):
    vocabulary = build_vocabulary(catalog)
    names = {t.alias or t.id for t in vocabulary.traits}
    assert {"body_mass", "leafiness"} <= names
    assert "season" not in names

    plan = {"version": "1.1", "traits": [{"trait": "body_mass", "value": 0.7}],
            "root": {"id": "root", "ref": "humanoid_anatomical:body"}}
    graph, report = validate_plan(plan, catalog)
    assert graph is not None, report.describe()
    assert graph.traits[0].trait == "body_mass"

    bad = {"version": "1.1", "traits": [{"trait": "mega_fatness", "value": 1}],
           "root": {"id": "root", "ref": "humanoid_anatomical:body"}}
    graph, report = validate_plan(bad, catalog)
    assert graph is None
    assert "TRAIT_NOT_FOUND" in report.codes()


def test_graph_and_my3d_roundtrip_preserve_traits(tmp_path, catalog):
    graph = CompositionGraph(style="low_poly", detail_level=2)
    graph.set_root("root", "humanoid_anatomical:body")
    graph.traits = [TraitRequest("body_mass", 0.7)]

    restored = CompositionGraph.from_dict(graph.to_dict())
    assert restored.traits == graph.traits

    session = Session(provider=OfflineProvider())
    session.registry = catalog
    result = session.build(graph, Options(detail_level=2, check=False))
    session.history.append(Version(label="trait", plan=graph,
                                   scene=result.scene(catalog), result=result))
    session.cursor = 0
    path = session.save_project(tmp_path / "trait_project")

    reopened = Session(provider=OfflineProvider())
    reopened.registry = catalog
    reopened.open_project(path)
    assert reopened.current_plan.traits == graph.traits


def test_structural_traits_are_not_exposed_by_v1_rule_api():
    fields = set(TraitRule.__dataclass_fields__)
    forbidden = {"add_node", "remove_node", "replace_child", "rewrite_graph"}
    assert not fields & forbidden


def test_core_trait_runtime_has_no_domain_branches():
    source = (Path(__file__).resolve().parent.parent / "app" / "core" /
              "traits.py").read_text(encoding="utf-8")
    for forbidden in ("body_mass", "leafiness", "humanoid", "tree"):
        assert ('"%s"' % forbidden) not in source
        assert ("'%s'" % forbidden) not in source
