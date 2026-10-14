from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.build.assembler import build
from app.build.validate import validate
from app.core.capability import Requirement
from app.core.effect import apply_effects
from app.core.graph import CompositionGraph
from app.core.registry import load
from app.core.resolver import resolve
from app.core.authoring import verify_frame


PLUGIN_ROOT = Path(__file__).resolve().parent.parent / "app" / "plugins"


@pytest.fixture(scope="module")
def registry():
    catalog = load([PLUGIN_ROOT])
    assert not catalog.report.errors(), catalog.report.describe()
    return catalog.freeze()


def fox(detail: int = 3, **params) -> CompositionGraph:
    graph = CompositionGraph(detail_level=detail, seed=17)
    graph.set_root("fox", "fox_stylized:fox", **params)
    return graph


def built(registry, graph):
    resolved = resolve(graph, registry)
    assert resolved.ok, resolved.report.describe()
    return build(apply_effects(resolved, registry), report=resolved.report)


def paths(out) -> set[str]:
    return {node.node.path for node in out.walk()}


def test_registry_loads_fox_palette_and_general_contracts(registry):
    assert registry.plugin("fox_stylized") is not None
    assert registry.component("fox_stylized:fox") is not None
    assert registry.component("fox_stylized:body") is not None
    assert registry.knows_material("fox_orange")
    assert registry.knows_material("fox_cream")
    for capability in ("animal", "core_mount", "head_mount", "limb_mount",
                       "face_mount", "gear_mount"):
        assert capability in registry.capabilities()


def test_detail_1_is_a_complete_iconic_fox(registry):
    out = built(registry, fox(1))
    expected = {
        "fox", "fox/body", "fox/body/head", "fox/body/head/ears",
        "fox/body/front_l", "fox/body/front_r",
        "fox/body/rear_l", "fox/body/rear_r", "fox/body/tail",
    }
    assert expected == paths(out)
    assert out.triangles >= 220
    assert out.node("fox/body/head/ears").triangles > 0
    assert out.node("fox/body/tail").triangles > 0


def test_detail_2_adds_structure_without_accents(registry):
    level_1 = built(registry, fox(1))
    level_2 = built(registry, fox(2))
    assert paths(level_2) == paths(level_1)
    assert level_2.triangles > level_1.triangles
    for path in ("fox/body", "fox/body/head", "fox/body/head/ears",
                 "fox/body/front_l", "fox/body/tail"):
        hierarchy = level_2.node(path).piece.metadata["hierarchy_triangles"]
        assert hierarchy["secondary"] > 0, path
        assert hierarchy["accents"] == 0, path


def test_detail_3_adds_only_characteristic_accents(registry):
    out = built(registry, fox(3))
    assert {
        "fox/body/head/ears/inner_l",
        "fox/body/head/ears/inner_r",
        "fox/body/head/eye_l",
        "fox/body/head/eye_r",
        "fox/body/head/nose",
        "fox/body/tail/tail_tip",
    } <= paths(out)
    assert out.triangles < 700
    accents = sum(node.piece.metadata.get("hierarchy_triangles", {}).get("accents", 0)
                  for node in out.geometry())
    primary = sum(node.piece.metadata.get("hierarchy_triangles", {}).get("primary", 0)
                  for node in out.geometry())
    assert accents < primary * 0.25


def test_ear_size_changes_ear_geometry(registry):
    low = built(registry, fox(3, ear_size=0.80))
    high = built(registry, fox(3, ear_size=1.34))
    low_height = float(low.node("fox/body/head/ears").mesh.extents[1])
    high_height = float(high.node("fox/body/head/ears").mesh.extents[1])
    assert high_height > low_height * 1.5


def test_sockets_have_truthful_frames_and_negative_space(registry):
    out = built(registry, fox(2))
    body = out.node("fox/body")
    frame_report = verify_frame(body.piece, "+Y", name="fox_stylized:body")
    assert not frame_report.errors(), frame_report.describe()
    for socket_name in ("head", "front_l", "front_r", "rear_l", "rear_r",
                        "tail_socket", "back"):
        socket = body.sockets[socket_name]
        assert np.all(np.isfinite(socket.position))
        assert np.linalg.norm(socket.direction) > 0.9
    body_min, body_max = body.mesh.bounds
    front_l = out.node("fox/body/front_l").mesh.bounds
    front_r = out.node("fox/body/front_r").mesh.bounds
    assert body_min[1] > 0.0
    assert front_l[0][0] < front_r[0][0]
    assert body_min[1] < body_max[1]


@pytest.mark.parametrize("params", [
    {},
    {"muzzle_length": 0.29},
    {"muzzle_length": 0.61},
    {"head_size": 0.35},
    {"head_size": 0.65},
])
def test_face_accents_are_mounted_on_head_surfaces(registry, params):
    out = built(registry, fox(3, **params))
    head = out.node("fox/body/head")
    for name in ("eye_l", "eye_r", "nose"):
        child = out.node("fox/body/head/" + name)
        parent_socket = head.socket_world(child.parent_socket)
        child_base = child.socket_world("base")
        expected_insert = parent_socket.radius * child.node.link.insert
        assert np.isclose(np.linalg.norm(parent_socket.position - child_base.position),
                          expected_insert, atol=1e-7), name
        assert np.all(np.isfinite(child.mesh.vertices))
        assert float(child.piece.mesh.bounds[0][2]) >= -1e-9
        projection = (child.mesh.vertices - parent_socket.position) \
            @ parent_socket.direction
        assert float(projection.min()) < 0.0, name
        outward = projection[projection > 0.0]
        local_depth = float(child.piece.mesh.bounds[1][2] -
                            child.piece.mesh.bounds[0][2])
        assert len(outward) >= len(projection) * 0.25, name
        assert float(outward.max()) > local_depth * 0.25, name
        assert child.material == ("fox_eye" if name.startswith("eye_")
                                  else "fox_dark")
        assert not verify_frame(child.piece, "+Z", name=name).errors()

    left = head.socket_world("eye_l")
    right = head.socket_world("eye_r")
    assert np.isclose(left.position[0], -right.position[0], atol=1e-8)
    assert left.position[2] > 0.0 and right.position[2] > 0.0
    assert head.socket_world("nose").position[2] > max(left.position[2], right.position[2])


def test_cross_plugin_back_accessory_uses_gear_mount(registry):
    graph = fox(3)
    graph.attach("back_helmet", "accessories:helmet", on="body",
                 requirement=Requirement(capability="gear_mount"),
                 radius=0.20, height=0.18, crest=0.0)
    out = built(registry, graph)
    accessory = out.node("back_helmet")
    assert accessory is not None
    assert accessory.ref == "accessories:helmet"
    assert accessory.parent_socket == "back"


@pytest.mark.parametrize("params", [
    {"tail_length": 0.75},
    {"tail_length": 1.05},
    {"tail_length": 1.50},
    {"tail_volume": 0.74},
    {"tail_volume": 1.34},
    {"ear_size": 0.80},
    {"ear_size": 1.34},
    {"muzzle_length": 0.29},
    {"muzzle_length": 0.61},
    {"head_size": 0.35},
    {"head_size": 0.65},
    {"body_length": 0.74, "torso_height": 0.40},
    {"body_length": 1.42, "leg_length": 0.98},
    {"leg_length": 0.50},
    {"leg_length": 1.03},
    {"chunkiness": 0.74},
    {"chunkiness": 1.16},
    {"body_length": 1.35, "tail_length": 1.42, "ear_size": 1.22},
    {"torso_height": 0.42, "leg_length": 1.00, "muzzle_length": 0.54},
    {"torso_height": 0.74, "chunkiness": 1.10, "tail_volume": 1.25},
])
def test_public_parameter_matrix_is_finite_valid_and_deterministic(registry, params):
    signatures = []
    for _ in range(2):
        out = built(registry, fox(3, **params))
        report = validate(out, style=registry.style("low_poly"))
        forbidden = {"DECLARED_SOCKET_MISSING", "PARENT_SOCKET_NOT_FOUND",
                     "OWN_SOCKET_NOT_FOUND", "JOINT_GAP", "COMPONENT_BUILD_FAILED",
                     "NON_FINITE_BOUNDS"}
        assert not (forbidden & set(report.codes())), report.describe()
        assert np.all(np.isfinite(out.size))
        assert all(0.01 < float(size) < 20.0 for size in out.size)
        signatures.append((tuple(np.round(out.size, 6)), len(out.nodes), out.triangles))
    assert signatures[0] == signatures[1]


def test_default_validation_and_vocabulary_are_clean(registry):
    out = built(registry, fox(3))
    report = validate(out, style=registry.style("low_poly"))
    assert not report.errors(), report.describe()
    fox_component = registry.component("fox_stylized:fox")
    assert set(fox_component.params) == {
        "body_length", "torso_height", "head_size", "leg_length",
        "tail_length", "tail_volume", "ear_size", "muzzle_length", "chunkiness",
    }
    assert {"fox", "volpe", "quadruped", "stylized"} <= fox_component.tags
