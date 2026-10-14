from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.build.assembler import build
from app.build.validate import validate
from app.core.authoring import verify_frame
from app.core.capability import Requirement
from app.core.effect import apply_effects
from app.core.errors import Report
from app.core.graph import CompositionGraph
from app.core.registry import load
from app.core.resolver import resolve

PLUGIN = Path(__file__).resolve().parent.parent / "app" / "plugins"


@pytest.fixture(scope="module")
def registry():
    r = load([PLUGIN])
    assert not r.report.errors(), r.report.describe()
    return r.freeze()


def req(capability: str = "", **kwargs) -> Requirement:
    return Requirement(capability=capability, **kwargs)


def anatomical(detail: int = 3, height: float = 1.8) -> CompositionGraph:
    g = CompositionGraph(detail_level=detail)
    g.set_root("corpo", "humanoid_anatomical:body", height=height)
    return g


def anatomical_custom(detail: int = 3, height: float = 1.8, *,
                      torso: dict | None = None,
                      head: dict | None = None) -> CompositionGraph:
    g = CompositionGraph(detail_level=detail)
    g.set_root("corpo", "humanoid_anatomical:body", height=height)
    g.add_child("torso", "humanoid_anatomical:torso", "corpo",
                requirement=req("core_mount"), level=1, **(torso or {}))
    if head:
        g.add_child("neck", "humanoid_anatomical:neck", "torso",
                    requirement=req("head_mount"), level=2)
        g.add_child("head", "humanoid_anatomical:head", "neck",
                    requirement=req("head_mount"), level=2, **head)
    return g


def built(registry, graph):
    resolved = resolve(graph, registry)
    assert resolved.ok, resolved.report.describe()
    return build(apply_effects(resolved, registry), report=resolved.report)


def refs(out) -> list[str]:
    return [n.ref for n in out.composition.walk()]


def ids(out) -> set[str]:
    return {n.id for n in out.composition.walk()}


def centroid(out, path: str) -> np.ndarray:
    mesh = out.node(path).mesh
    return np.asarray(mesh.vertices, dtype=float).mean(axis=0)


def test_plugin_is_loaded_without_core_changes(registry):
    assert registry.plugin("humanoid_anatomical") is not None
    assert registry.component("humanoid_anatomical:body") is not None
    assert registry.component("humanoid:body") is not None


def test_body_generates_normally(registry):
    out = built(registry, anatomical(3))
    assert out.meshes()
    assert out.triangles > 900
    assert "humanoid_anatomical:head" in refs(out)
    assert "COMPONENT_BUILD_FAILED" not in out.report.codes()


def test_detail_level_adds_real_anatomical_chains(registry):
    low = built(registry, anatomical(1))
    high = built(registry, anatomical(3))
    assert len(high.nodes) > len(low.nodes)
    expected = {
        "corpo/torso/shoulder_l/upper_arm/elbow/forearm/wrist/hand",
        "corpo/torso/hip_l/thigh/knee/calf/ankle/foot",
        "corpo/torso/neck/head/nose",
    }
    assert expected <= ids(high)


def test_limb_chains_are_real_parent_child_links(registry):
    out = built(registry, anatomical(3))
    chains = [
        ("corpo/torso/shoulder_l",
         "corpo/torso/shoulder_l/upper_arm",
         "corpo/torso/shoulder_l/upper_arm/elbow",
         "corpo/torso/shoulder_l/upper_arm/elbow/forearm",
         "corpo/torso/shoulder_l/upper_arm/elbow/forearm/wrist",
         "corpo/torso/shoulder_l/upper_arm/elbow/forearm/wrist/hand"),
        ("corpo/torso/hip_l",
         "corpo/torso/hip_l/thigh",
         "corpo/torso/hip_l/thigh/knee",
         "corpo/torso/hip_l/thigh/knee/calf",
         "corpo/torso/hip_l/thigh/knee/calf/ankle",
         "corpo/torso/hip_l/thigh/knee/calf/ankle/foot"),
    ]
    for chain in chains:
        for parent, child in zip(chain, chain[1:]):
            node = out.composition.node(child)
            assert node.link.parent == parent
            assert out.node(child).parent == parent


@pytest.mark.parametrize("detail", [1, 2, 3])
@pytest.mark.parametrize("height", [1.5, 1.8, 2.0])
def test_requested_height_is_total_model_height(registry, detail, height):
    out = built(registry, anatomical(detail, height))
    assert out.size[1] == pytest.approx(height, rel=0.01)


@pytest.mark.parametrize(("joint", "parent", "descendant"), [
    ("corpo/torso/shoulder_l/upper_arm/elbow",
     "corpo/torso/shoulder_l/upper_arm",
     "corpo/torso/shoulder_l/upper_arm/elbow/forearm/wrist/hand"),
    ("corpo/torso/shoulder_l/upper_arm/elbow/forearm/wrist",
     "corpo/torso/shoulder_l/upper_arm/elbow/forearm",
     "corpo/torso/shoulder_l/upper_arm/elbow/forearm/wrist/hand"),
    ("corpo/torso/hip_l/thigh/knee",
     "corpo/torso/hip_l/thigh",
     "corpo/torso/hip_l/thigh/knee/calf/ankle/foot"),
    ("corpo/torso/hip_l/thigh/knee/calf/ankle",
     "corpo/torso/hip_l/thigh/knee/calf",
     "corpo/torso/hip_l/thigh/knee/calf/ankle/foot"),
])
def test_subtree_rotate_pivots_on_the_named_joint(registry, joint, parent,
                                                  descendant):
    before = built(registry, anatomical(3))
    g = anatomical(3)
    g.effect("rotate", scope="subtree:" + joint, axis="Z", angle=35.0)
    after = built(registry, g)

    assert np.allclose(before.node(joint).socket_world("base").position,
                       after.node(joint).socket_world("base").position,
                       atol=1e-6)
    assert np.allclose(centroid(before, parent), centroid(after, parent), atol=1e-6)
    assert float(np.linalg.norm(centroid(before, descendant)
                                - centroid(after, descendant))) > 1e-3
    assert "JOINT_GAP" not in after.report.codes(), after.report.describe()


def test_all_declared_attachments_have_expected_seams(registry):
    out = built(registry, anatomical(3))
    tolerance = max(float(out.size[1]) * 1e-5, 1e-6)
    for node in out.walk():
        link = node.node.link
        parent = out.node(node.parent) if link else None
        if link is None or parent is None:
            continue
        target = parent.socket_world(link.parent_socket)
        own = node.socket_world(link.own_socket)
        distance = float(np.linalg.norm(target.position - own.position))
        expected = target.radius * float(link.insert)
        assert distance == pytest.approx(expected, abs=tolerance), node.id
        assert float(target.direction @ own.direction) < -0.95, node.id


def test_verify_frame_has_no_structural_errors(registry):
    out = built(registry, anatomical(3))
    axis_y = {"body", "torso", "pelvis", "abdomen", "ribcage", "neck",
              "head", "hair"}
    axis_z = {"eye", "nose", "mouth"}
    report = Report()
    for node in out.walk():
        component_id = node.component.id.split(":")[-1]
        axis = "+Y" if component_id in axis_y else "+Z" if component_id in axis_z else "+X"
        verify_frame(node.piece, axis, name="%s:%s" % (node.id, node.component.id),
                     report=report)
    assert not report.errors(), report.describe()


def test_param_robustness_matrix_stays_buildable_and_coherent(registry):
    configs = [
        anatomical(detail, height)
        for detail in (1, 2, 3)
        for height in (1.5, 1.8, 2.0)
    ]
    configs += [
        anatomical_custom(3, 1.8, torso={"shoulder_width": 0.36}),
        anatomical_custom(3, 1.8, torso={"shoulder_width": 0.52}),
        anatomical_custom(3, 1.8, torso={"hip_width": 0.24}),
        anatomical_custom(3, 1.8, torso={"hip_width": 0.40}),
        anatomical_custom(3, 1.8, torso={"waist_width": 0.20, "chest_depth": 0.18}),
        anatomical_custom(3, 1.8, torso={"waist_width": 0.32, "chest_depth": 0.26}),
        anatomical_custom(3, 1.5, head={"head_height": 0.20}),
        anatomical_custom(3, 1.5, head={"head_height": 0.23}),
        anatomical_custom(3, 2.0, head={"head_height": 0.25}),
        anatomical_custom(3, 2.0, head={"head_height": 0.29}),
        anatomical_custom(2, 1.8, torso={"shoulder_width": 0.50, "hip_width": 0.34}),
        anatomical_custom(2, 1.8, torso={"shoulder_width": 0.34, "hip_width": 0.36}),
    ]
    assert 15 <= len(configs) <= 25
    for graph in configs:
        height = graph.nodes[graph.root_id].overrides["height"]
        out = built(registry, graph)
        report = validate(out, style=registry.style("low_poly"))
        assert not report.errors(), report.describe()
        assert "JOINT_GAP" not in report.codes(), report.describe()
        assert 0.94 <= float(out.size[1] / height) <= 1.06


def test_default_anatomical_body_is_deterministic(registry):
    signatures = set()
    for _ in range(3):
        out = built(registry, anatomical(3))
        signatures.add((tuple(np.round(out.size, 6)), len(out.nodes), out.triangles))
    assert len(signatures) == 1


def test_anatomical_head_can_replace_the_old_head(registry):
    g = CompositionGraph(detail_level=2)
    g.set_root("corpo", "humanoid:body", height=1.8)
    g.add_child("torso", "humanoid:torso", "corpo", requirement=req("core_mount"))
    g.add_child("testa", "humanoid:head", "torso", requirement=req("head_mount"))
    g.swap("testa", "humanoid_anatomical:head")
    out = built(registry, g)
    assert out.node("testa").ref == "humanoid_anatomical:head"
    assert "humanoid:head" not in refs(out)


def test_old_head_can_mount_on_the_new_body(registry):
    g = CompositionGraph(detail_level=1)
    g.set_root("corpo", "humanoid_anatomical:body", height=1.8)
    g.add_child("torso", "humanoid_anatomical:torso", "corpo",
                requirement=req("core_mount"), level=1)
    g.add_child("testa", "humanoid:head", "torso", requirement=req("head_mount"),
                level=1)
    out = built(registry, g)
    assert out.node("testa").ref == "humanoid:head"
    assert out.composition.node("testa").link.parent_socket == "neck"


def test_compatible_creature_head_replaces_anatomical_head(registry):
    g = CompositionGraph(detail_level=2)
    g.set_root("corpo", "humanoid_anatomical:body", height=1.8)
    g.add_child("torso", "humanoid_anatomical:torso", "corpo",
                requirement=req("core_mount"), level=1)
    g.add_child("testa_drago", "humanoid_anatomical:head", "torso",
                requirement=req("head_mount"), level=1)
    g.swap("testa_drago", "creature:dragon_head")
    out = built(registry, g)
    assert out.node("testa_drago").ref == "creature:dragon_head"


def test_compatible_external_limb_replaces_anatomical_limb(registry):
    g = CompositionGraph(detail_level=1)
    g.set_root("corpo", "humanoid_anatomical:body", height=1.8)
    g.add_child("torso", "humanoid_anatomical:torso", "corpo",
                requirement=req("core_mount"), level=1)
    g.add_child("gamba_l", "humanoid_anatomical:leg", "torso",
                requirement=req("limb_mount", side="l", tags=frozenset({"basso"})),
                level=1)
    g.swap("gamba_l", "weapon:sword")
    out = built(registry, g)
    assert out.node("gamba_l").ref == "weapon:sword"
    assert out.composition.node("gamba_l").link.parent_socket == "hip_l"


def test_accessory_attaches_to_internal_part_with_on_path(registry):
    g = CompositionGraph(detail_level=1)
    g.set_root("corpo", "humanoid_anatomical:body", height=1.8)
    g.attach("piercing", "accessories:piercing", on="head/nose",
             requirement=req("anchor"))
    out = built(registry, g)
    assert out.composition.node("piercing").link.parent == "corpo/torso/head/nose"
    assert refs(out).count("humanoid_anatomical:nose") == 1


def test_external_accessory_attaches_to_deep_distal_hand(registry):
    g = anatomical(3)
    hand_path = "torso/shoulder_l/upper_arm/elbow/forearm/wrist/hand"
    g.attach("gemma", "accessories:piercing", on=hand_path, requirement=req("anchor"))
    out = built(registry, g)
    assert out.composition.node("gemma").link.parent == "corpo/" + hand_path
    assert out.composition.node("gemma").link.parent_socket == "palm"
    assert "JOINT_GAP" not in out.report.codes(), out.report.describe()


def test_old_humanoid_still_works(registry):
    g = CompositionGraph(detail_level=3)
    g.set_root("corpo", "humanoid:body", height=1.8)
    g.add_child("torso", "humanoid:torso", "corpo", requirement=req("core_mount"))
    g.add_child("testa", "humanoid:head", "torso", requirement=req("head_mount"))
    out = built(registry, g)
    assert "humanoid:head" in refs(out)
    assert "humanoid_anatomical:head" not in refs(out)


def test_vocabulary_distinguishes_the_two_humanoids(registry):
    from app.core.planner.vocabulary import build_vocabulary

    vocabulary = build_vocabulary(registry)
    old = vocabulary.component("humanoid:body")
    new = vocabulary.component("humanoid_anatomical:body")
    assert old is not None and new is not None
    assert "anatom" in new.description.lower()
    assert old.id != new.id


def test_vocabulary_and_mock_planner_can_select_anatomical_body(registry):
    from app.core.planner.planner import MockPlanner, PlanRequest
    from app.core.planner.vocabulary import build_vocabulary

    vocabulary = build_vocabulary(registry)
    response = MockPlanner().plan(PlanRequest(
        prompt="a full body anatomical humanoid",
        vocabulary=vocabulary,
        detail_level=3,
        seed=2,
    ))
    assert response.plan["root"]["ref"] == "humanoid_anatomical:body"


def test_quality_gate_has_no_fatal_joint_or_socket_errors(registry):
    out = built(registry, anatomical(3))
    report = validate(out, style=registry.style("low_poly"))
    forbidden = {"DECLARED_SOCKET_MISSING", "PARENT_SOCKET_NOT_FOUND",
                 "OWN_SOCKET_NOT_FOUND", "JOINT_GAP"}
    assert not (forbidden & set(report.codes())), report.describe()
