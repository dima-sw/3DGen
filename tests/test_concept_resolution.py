from __future__ import annotations

import json

import pytest

from app.core.archetypes import (ArchetypeSpec, ConceptResolver,
                                 ImplementationBinding)
from app.core.component import Attachment, Component, Piece
from app.core.params import ParamSpec
from app.core.planner.planner import MockPlanner
from app.core.planner.schema import plan_schema
from app.core.planner.vocabulary import build_vocabulary
from app.core.registry import Registry
from app.core.session import Options, Session
from app.core.traits import ParamPatch, TraitMatch, TraitRule, TraitSpec


LYNX_PLAN = {
    "version": "1.3", "style": "low_poly", "seed": 17,
    "concept": {
        "requested": "lynx",
        "archetypes": ["archetype_metadata:felid"],
        "adaptations": [
            {"param": "tail_length", "value": 0.76},
            {"param": "ear_size", "value": 1.28},
            {"description": "large paws"},
            {"trait": "std:ear_super_lynx_factor", "value": 1.0},
        ],
    },
}


def registry() -> Registry:
    result = Registry()
    result.load_directory("app/plugins")
    return result


def session_for(prompt: str, plan: dict, reg: Registry | None = None):
    planner = MockPlanner(scripts={prompt: plan})
    session = Session(registry=reg or registry(), planner=planner)
    return session, planner


def test_lynx_semantic_plan_selects_root_only_in_backend():
    session, planner = session_for("lince", LYNX_PLAN)
    result = session.generate("lince", Options(check=False, repair=False), remember=False)
    resolution = result.concept_resolution
    assert result.report.ok and result.build is not None
    assert "root" not in planner.calls[0].previous if planner.calls[0].previous else True
    assert resolution.selected_binding == "archetype_metadata:fox_quadruped"
    assert resolution.selected_root_implementation == "fox_stylized:fox"
    assert resolution.provenance["match"] == "ancestor/body-plan proxy"
    assert result.plan.node(result.plan.root_id).overrides["ear_size"] == 1.28


def test_unknown_adaptation_is_honestly_unsupported():
    session, _ = session_for("lince", LYNX_PLAN)
    result = session.generate("lince", Options(check=False, repair=False), remember=False)
    unsupported = result.concept_resolution.unsupported
    assert any(item.get("trait") == "std:ear_super_lynx_factor" for item in unsupported)
    assert result.concept_resolution.materialized_params == {
        "tail_length": 0.76, "ear_size": 1.28}


def test_conflicting_adaptations_are_not_last_write_wins():
    result = ConceptResolver(registry()).resolve(
        "lynx", archetypes=("archetype_metadata:felid",),
        adaptations=({"param": "ear_size", "value": 0.9},
                     {"param": "ear_size", "value": 1.2}))
    assert "ADAPTATION_CONFLICT" in {d["code"] for d in result.diagnostics}
    assert result.conflicts
    assert not result.ok


def test_exact_binding_ranks_before_ancestor_proxy():
    reg = registry()
    reg.register_implementation_binding(ImplementationBinding(
        "test:exact_felid", "fox_stylized:fox", ("archetype_metadata:felid",)))
    result = ConceptResolver(reg).resolve(
        "lynx", archetypes=("archetype_metadata:felid",),
        adaptations=({"param": "ear_size", "value": 1.2},))
    assert result.selected_binding == "test:exact_felid"
    assert result.coverage[0]["candidate"] in {
        "archetype_metadata:fox_quadruped", "test:exact_felid"}


def test_eagle_is_unrepresentable_without_invented_root():
    plan = {"version": "1.3", "concept": {
        "requested": "eagle", "archetypes": ["archetype_metadata:raptor"]}}
    session, _ = session_for("aquila", plan)
    result = session.generate("aquila", Options(check=False), remember=False)
    assert result.build is None
    assert result.plan is None
    assert result.concept_resolution.selected_root_implementation == ""
    assert "IMPLEMENTATION_NOT_FOUND" in result.report.codes()


def test_direct_component_resolution_bypasses_fallback():
    plan = ConceptResolver(registry()).resolve("fox_stylized:fox")
    assert plan.ok
    assert plan.selected_root_implementation == "fox_stylized:fox"
    assert plan.selected_binding == ""
    assert plan.provenance["match"] == "direct implementation"


def test_dune_buggy_and_bonsai_use_only_public_params():
    cases = {
        "buggy": ({"requested": "dune buggy",
                   "archetypes": ["archetype_metadata:car_like"],
                   "adaptations": [{"param": "wheel_size", "value": 0.82},
                                   {"description": "open cabin"}]},
                  "vehicle_stylized:car", {"wheel_size": 0.82}),
        "bonsai": ({"requested": "bonsai",
                    "archetypes": ["archetype_metadata:tree"],
                    "adaptations": [{"param": "height", "value": 1.8},
                                    {"param": "branch_spread", "value": 1.2}]},
                   "tree_stylized:tree", {"height": 1.8, "branch_spread": 1.2}),
    }
    for prompt, (concept, root, params) in cases.items():
        session, _ = session_for(prompt, {"version": "1.3", "concept": concept})
        result = session.generate(prompt, Options(check=False), remember=False)
        assert result.report.ok and result.concept_resolution.selected_root_implementation == root
        assert result.concept_resolution.materialized_params == params


def test_generic_wheeled_vehicle_discovers_car_specialization():
    concept = {
        "requested": "dune buggy",
        "archetypes": ["archetype_metadata:wheeled_vehicle"],
        "adaptations": [{"param": "wheel_size", "value": 0.82}],
    }
    session, _ = session_for("buggy generico", {"version": "1.3",
                                                  "concept": concept})
    result = session.generate("buggy generico", Options(check=False), remember=False)
    resolution = result.concept_resolution
    assert result.report.ok and result.build is not None
    assert resolution.selected_root_implementation == "vehicle_stylized:car"
    assert resolution.provenance["match"] == \
        "descendant/specialization implementation"


def test_descendant_discovery_excludes_siblings_and_supports_multiple_parents():
    reg = registry()
    for spec in (
        ArchetypeSpec("test:base"),
        ArchetypeSpec("test:car", parents=("test:base",)),
        ArchetypeSpec("test:truck", parents=("test:base",)),
        ArchetypeSpec("test:electric"),
        ArchetypeSpec("test:hybrid", parents=("test:car", "test:electric")),
    ):
        assert reg.register_archetype(spec)
    reg.register_implementation_binding(ImplementationBinding(
        "test:car_impl", "vehicle_stylized:car", ("test:car",)))
    reg.register_implementation_binding(ImplementationBinding(
        "test:truck_impl", "tree_stylized:tree", ("test:truck",)))
    reg.register_implementation_binding(ImplementationBinding(
        "test:hybrid_impl", "fox_stylized:fox", ("test:hybrid",)))

    base = ConceptResolver(reg).resolve(
        "base", archetypes=("test:base",),
        adaptations=({"param": "wheel_size", "value": 0.9},))
    assert base.selected_binding == "test:car_impl"
    assert {item["candidate"] for item in base.coverage} >= {
        "test:car_impl", "test:truck_impl", "test:hybrid_impl"}
    repeated = ConceptResolver(reg).resolve(
        "base", archetypes=("test:base",),
        adaptations=({"param": "wheel_size", "value": 0.9},))
    assert json.dumps(base.to_dict(), sort_keys=True) == json.dumps(
        repeated.to_dict(), sort_keys=True)
    car = ConceptResolver(reg).resolve("car", archetypes=("test:car",))
    assert "test:truck_impl" not in {item["candidate"] for item in car.coverage}
    electric = ConceptResolver(reg).resolve(
        "electric", archetypes=("test:electric",))
    assert electric.selected_binding == "test:hybrid_impl"
    assert electric.provenance["match"] == \
        "descendant/specialization implementation"


def test_subtree_trait_preflight_reports_partial_coverage_and_materialization():
    reg = Registry()
    reg.register_component(Component(
        "test:root", lambda values, ctx: Piece(), role="body",
        children=lambda values, ctx: [
            Attachment("a", "test:supported"),
            Attachment("b", "test:unsupported"),
        ]))
    reg.register_component(Component(
        "test:supported", lambda values, ctx: Piece(), role="torso",
        params={"width": ParamSpec(1.0, semantic_role="girth")}))
    reg.register_component(Component(
        "test:unsupported", lambda values, ctx: Piece(), role="limb",
        params={"length": ParamSpec(1.0, semantic_role="length")}))
    reg.register_trait(TraitSpec("test:mass", value=ParamSpec(1.0)))
    reg.register_trait_rule(TraitRule(
        "test:mass_torso", "test:mass",
        match=TraitMatch(roles=("torso",), param_roles=("girth",)),
        patches=(ParamPatch(expression="self.width * value", param="width"),)))
    reg.register_archetype(ArchetypeSpec("test:subject"))
    reg.register_implementation_binding(ImplementationBinding(
        "test:subject_root", "test:root", ("test:subject",)))

    plan = ConceptResolver(reg).resolve(
        "subject", archetypes=("test:subject",),
        adaptations=({"trait": "test:mass", "value": 1.2},))
    supported = plan.coverage[0]["supported"][0]
    details = supported["coverage_details"]
    assert plan.ok and plan.materialized_traits[-1]["trait"] == "test:mass"
    assert details["coverage"] == "partially_supported"
    assert details["materialized"] is True
    assert [item["path"] for item in details["where_supported"]] == \
        ["root/a"]
    assert {item["path"] for item in details["where_unsupported"]} == \
        {"root", "root/b"}


def test_body_mass_extension_is_discovered_below_fox_root():
    plan = ConceptResolver(registry()).resolve(
        "lynx", archetypes=("archetype_metadata:felid",),
        adaptations=({"trait": "std:body_mass", "value": 0.72},))
    item = next(entry for entry in plan.coverage[0]["supported"]
                if entry.get("trait") == "std:body_mass")
    details = item["coverage_details"]
    assert plan.ok and details["materialized"] is True
    assert details["where_supported"]
    assert any(entry["path"].endswith("/head")
               for entry in details["where_supported"])


@pytest.mark.parametrize("root", [
    "fox_stylized:fox", "vehicle_stylized:car", "tree_stylized:tree",
    "humanoid_anatomical:body",
])
def test_direct_installed_roots_remain_unchanged(root):
    plan = ConceptResolver(registry()).resolve(root)
    assert plan.ok and plan.selected_root_implementation == root
    assert plan.provenance["match"] == "direct implementation"


def test_save_load_keeps_resolution_and_never_calls_planner():
    session, _ = session_for("lince", LYNX_PLAN)
    generated = session.generate("lince", Options(check=False), remember=False)
    payload = generated.plan.to_dict()
    planner = MockPlanner()
    restored = Session(registry=session.registry, planner=planner).build(
        payload, Options(check=False))
    assert restored.report.ok and restored.build is not None
    assert planner.calls == []
    assert restored.concept_resolution.to_dict() == generated.concept_resolution.to_dict()


def test_saved_missing_binding_is_not_remapped():
    session, _ = session_for("lince", LYNX_PLAN)
    generated = session.generate("lince", Options(check=False), remember=False)
    payload = generated.plan.to_dict()
    del session.registry._implementation_bindings["archetype_metadata:fox_quadruped"]
    restored = Session(registry=session.registry, planner=MockPlanner()).build(
        payload, Options(check=False))
    assert restored.build is None
    assert "SAVED_BINDING_MISSING" in restored.report.codes()


def test_resolution_is_byte_deterministic():
    resolver = ConceptResolver(registry())
    first = resolver.resolve("lynx", archetypes=("archetype_metadata:felid",),
                             adaptations=LYNX_PLAN["concept"]["adaptations"])
    second = resolver.resolve("lynx", archetypes=("archetype_metadata:felid",),
                              adaptations=LYNX_PLAN["concept"]["adaptations"])
    assert json.dumps(first.to_dict(), sort_keys=True) == json.dumps(
        second.to_dict(), sort_keys=True)


def test_planner_schema_accepts_exactly_one_of_root_or_semantic_concept():
    jsonschema = pytest.importorskip("jsonschema")
    schema = plan_schema()
    assert schema["oneOf"] == [{"required": ["concept"]}, {"required": ["root"]}]
    assert "concept" in schema["properties"]

    root = {"version": "1.0", "root": {"ref": "fox_stylized:fox"}}
    concept = {"version": "1.3", "concept": {"requested": "lynx"}}
    jsonschema.validate(root, schema)
    jsonschema.validate(concept, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**root, **concept}, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"version": "1.3"}, schema)


def test_existing_root_plan_remains_backward_compatible():
    result = Session(registry=registry(), planner=MockPlanner()).build(
        {"version": "1.0", "root": {"id": "tree", "ref": "tree_stylized:tree"}},
        Options(check=False))
    assert result.report.ok and result.build is not None
    assert result.concept_resolution is None


def test_concept_payload_growth_is_measurable():
    data = build_vocabulary(registry()).to_dict()
    full = len(json.dumps(data, sort_keys=True).encode("utf-8"))
    baseline_data = dict(data)
    for key in ("archetypes", "archetype_details", "profiles", "bindings"):
        baseline_data.pop(key, None)
    baseline = len(json.dumps(baseline_data, sort_keys=True).encode("utf-8"))
    assert full > baseline > 0
