from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.build.assembler import build
from app.build.validate import validate
from app.core.authoring import verify_frame
from app.core.capability import Requirement
from app.core.effect import apply_effects
from app.core.graph import CompositionGraph
from app.core.registry import load
from app.core.resolver import resolve


PLUGIN_ROOT = Path(__file__).resolve().parent.parent / "app" / "plugins"


@pytest.fixture(scope="module")
def registry():
    catalog = load([PLUGIN_ROOT])
    assert not catalog.report.errors(), catalog.report.describe()
    return catalog.freeze()


def tree(detail: int = 3, **params) -> CompositionGraph:
    graph = CompositionGraph(detail_level=detail, seed=17)
    graph.set_root("tree", "tree_stylized:tree", **params)
    return graph


def built(registry, graph):
    resolved = resolve(graph, registry)
    assert resolved.ok, resolved.report.describe()
    return build(apply_effects(resolved, registry), report=resolved.report)


def paths(out) -> set[str]:
    return {node.node.path for node in out.walk()}


def test_registry_loads_tree_palette_and_generic_contracts(registry):
    assert registry.plugin("tree_stylized") is not None
    assert registry.component("tree_stylized:tree") is not None
    assert registry.component("tree_stylized:branch") is not None
    for material in ("wood", "leaf", "tree_leaf_shadow", "tree_accent"):
        assert registry.knows_material(material)
    for capability in ("building", "core_mount", "branch_mount", "crown_mount"):
        assert capability in registry.capabilities()


def test_detail_1_has_visible_trunk_split_and_crown_lobes(registry):
    out = built(registry, tree(1))
    assert paths(out) == {
        "tree", "tree/trunk", "tree/trunk/branch_l", "tree/trunk/branch_r",
        "tree/trunk/branch_upper", "tree/trunk/crown",
    }
    assert all(out.node(path).triangles > 0 for path in paths(out)
               if path != "tree")
    crown = out.node("tree/trunk/crown")
    assert crown.piece.metadata["crown_lobe_count"] == 3
    assert len(crown.mesh.split(only_watertight=False)) == 3
    assert out.node("tree/trunk/branch_l").triangles >= 30
    assert out.node("tree/trunk/branch_r").triangles >= 30


def test_detail_2_adds_only_secondary_structure(registry):
    level_1 = built(registry, tree(1))
    level_2 = built(registry, tree(2))
    assert paths(level_1) < paths(level_2)
    assert "tree/trunk/branch_rear" in paths(level_2)
    assert level_2.triangles > level_1.triangles
    assert out_hierarchy(level_2)["secondary"] > 0
    assert level_2.node("tree/trunk/crown").piece.metadata["crown_lobe_count"] == 4


def test_detail_3_adds_one_small_semantic_accent(registry):
    out = built(registry, tree(3))
    assert paths(out) - paths(built(registry, tree(2))) == {
        "tree/trunk/branch_l/fruit",
    }
    hierarchy = out_hierarchy(out)
    assert hierarchy["accents"] > 0
    assert hierarchy["accents"] < hierarchy["primary"] * 0.15
    assert out.node("tree/trunk/branch_l/fruit").ref == "tree_stylized:fruit"


def out_hierarchy(out) -> dict[str, int]:
    totals = {"primary": 0, "secondary": 0, "accents": 0}
    for node in out.geometry():
        values = node.piece.metadata.get("hierarchy_triangles", {})
        for key in totals:
            totals[key] += int(values.get(key, 0))
    return totals


def test_socket_frames_and_plugin_negative_space_proxies(registry):
    out = built(registry, tree(2))
    trunk = out.node("tree/trunk")
    crown = out.node("tree/trunk/crown")
    assert not verify_frame(trunk.piece, "+Y", name="tree_stylized:trunk").errors()
    assert not verify_frame(crown.piece, "+Y", name="tree_stylized:crown").errors()

    left = out.node("tree/trunk/branch_l")
    right = out.node("tree/trunk/branch_r")
    rear = out.node("tree/trunk/branch_rear")
    assert not verify_frame(left.piece, "+X", name="tree_stylized:branch").errors()
    assert not verify_frame(right.piece, "+X", name="tree_stylized:branch").errors()
    assert left.mesh.bounds[0][0] < trunk.mesh.bounds[0][0]
    assert right.mesh.bounds[1][0] > trunk.mesh.bounds[1][0]
    assert rear.mesh.bounds[0][2] < trunk.mesh.bounds[0][2]
    assert left.mesh.bounds[0][1] < crown.mesh.bounds[0][1]
    assert left.mesh.bounds[1][1] > trunk.mesh.bounds[0][1]
    assert len(crown.mesh.split(only_watertight=False)) >= 4

    for node in out.geometry():
        assert np.all(np.isfinite(node.mesh.vertices))
        assert np.all(np.isfinite(node.mesh.bounds))


@pytest.mark.parametrize("params", [
    {},
    {"height": 1.65},
    {"height": 5.80},
    {"trunk_width": 0.24},
    {"trunk_width": 1.04},
    {"trunk_taper": 0.38},
    {"trunk_taper": 0.92},
    {"crown_width": 1.15},
    {"crown_width": 4.80},
    {"crown_height": 0.82},
    {"crown_height": 3.20},
    {"branch_spread": 0.68},
    {"branch_spread": 1.30},
    {"asymmetry": 0.02},
    {"asymmetry": 0.98},
    {"lean": -0.24},
    {"lean": 0.24},
    {"height": 2.10, "crown_width": 1.40, "trunk_width": 0.28},
    {"height": 5.40, "crown_width": 4.50, "branch_spread": 1.25,
     "asymmetry": 0.90},
    {"height": 3.80, "crown_height": 2.80, "trunk_taper": 0.45,
     "lean": -0.18},
])
def test_public_parameter_matrix_is_finite_valid_and_deterministic(registry, params):
    signatures = []
    for _ in range(2):
        out = built(registry, tree(3, **params))
        report = validate(out, style=registry.style("low_poly"))
        forbidden = {"DECLARED_SOCKET_MISSING", "PARENT_SOCKET_NOT_FOUND",
                     "OWN_SOCKET_NOT_FOUND", "JOINT_GAP", "COMPONENT_BUILD_FAILED",
                     "NON_FINITE_BOUNDS"}
        assert not (forbidden & set(report.codes())), report.describe()
        assert np.all(np.isfinite(out.size))
        assert all(0.01 < float(size) < 20.0 for size in out.size)
        signatures.append((tuple(np.round(out.size, 6)), out.triangles,
                           tuple(np.round(out.bounds.ravel(), 6))))
    assert signatures[0] == signatures[1]


@pytest.mark.parametrize("height", [2.0, 3.2, 5.2])
def test_height_parameter_tracks_overall_bounds(registry, height):
    out = built(registry, tree(2, height=height))
    actual = float(out.size[1])
    assert abs(actual - height) / height < 0.08


def test_cross_plugin_nest_and_bird_attach_to_tree_branch(registry):
    graph = tree(3)
    graph.attach("nest", "nature:nest", on="trunk/branch_r",
                 requirement=Requirement(capability="branch_mount"),
                 scale_mode="none", radius=0.25, height=0.12)
    graph.attach("bird", "nature:bird", "nest",
                 requirement=Requirement(capability="perch_mount"),
                 scale_mode="none", length=0.30, girth=0.10, beak=0.06)
    out = built(registry, graph)
    nest = out.node("nest")
    bird = out.node("bird")
    assert nest is not None and nest.ref == "nature:nest"
    assert bird is not None and bird.ref == "nature:bird"
    assert bird.parent_socket == "dentro"
    assert "PARTS_INTERPENETRATE" not in validate(
        out, style=registry.style("low_poly")).codes()
