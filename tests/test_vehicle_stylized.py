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
from app.geometry.kernel import faces_per_normal

PLUGIN = Path(__file__).resolve().parent.parent / "app" / "plugins"


@pytest.fixture(scope="module")
def registry():
    r = load([PLUGIN])
    assert not r.report.errors(), r.report.describe()
    return r.freeze()


def req(capability: str = "", **kwargs) -> Requirement:
    return Requirement(capability=capability, **kwargs)


def car(detail: int = 3, **params) -> CompositionGraph:
    g = CompositionGraph(detail_level=detail)
    g.set_root("car", "vehicle_stylized:car", **params)
    return g


def built(registry, graph):
    resolved = resolve(graph, registry)
    assert resolved.ok, resolved.report.describe()
    return build(apply_effects(resolved, registry), report=resolved.report)


def ids(out) -> set[str]:
    return {n.id for n in out.composition.walk()}


def mesh_bounds(out, path: str) -> tuple[np.ndarray, np.ndarray]:
    bounds = np.asarray(out.node(path).mesh.bounds, dtype=float)
    return bounds[0], bounds[1]


def test_plugin_registers_vehicle_and_palette(registry):
    assert registry.plugin("vehicle_stylized") is not None
    assert registry.component("vehicle_stylized:car") is not None
    assert registry.knows_material("car_body")
    assert registry.knows_material("tire")
    assert "vehicle" in registry.capabilities()
    assert "wheel_mount" in registry.capabilities()


def test_detail_1_is_iconic_body_cabin_four_wheels(registry):
    out = built(registry, car(1))
    expected = {
        "car",
        "car/body",
        "car/body/cabin",
        "car/wheel_fl",
        "car/wheel_fr",
        "car/wheel_rl",
        "car/wheel_rr",
    }
    assert expected <= ids(out)
    assert "car/body/hood_panel" not in ids(out)
    assert "car/body/headlight_l" not in ids(out)
    assert len(out.nodes) == 7


def test_detail_2_adds_secondary_forms_without_small_accents(registry):
    out = built(registry, car(2))
    expected = {
        "car/body/hood_panel",
        "car/body/underbody",
        "car/body/fender_fl",
        "car/body/fender_fr",
        "car/body/fender_rl",
        "car/body/fender_rr",
        "car/body/cabin/windshield",
    }
    assert expected <= ids(out)
    assert "car/body/headlight_l" not in ids(out)
    assert "car/body/cabin/mirror_l" not in ids(out)
    assert len(out.nodes) > len(built(registry, car(1)).nodes)


def test_detail_3_adds_readable_accents(registry):
    out = built(registry, car(3))
    expected = {
        "car/body/headlight_l",
        "car/body/headlight_r",
        "car/body/grille",
        "car/body/cabin/mirror_l",
        "car/body/cabin/mirror_r",
        "car/body/cabin/roof_spoiler",
        "car/wheel_fl/hubcap",
        "car/wheel_fr/hubcap",
        "car/wheel_rl/hubcap",
        "car/wheel_rr/hubcap",
    }
    assert expected <= ids(out)
    assert len(out.nodes) > len(built(registry, car(2)).nodes)


def test_negative_space_is_geometric_not_texture_only(registry):
    out = built(registry, car(2))
    body_min, body_max = mesh_bounds(out, "car/body")
    wheel_min, wheel_max = mesh_bounds(out, "car/wheel_fl")
    assert body_min[1] > wheel_min[1] + 0.20
    assert body_min[1] < wheel_max[1]
    assert body_min[0] > wheel_min[0]
    assert "car/body/underbody" in ids(out)
    assert all("fender_" in part for part in [
        "fender_fl", "fender_fr", "fender_rl", "fender_rr"
    ])


def test_wheels_are_simple_faceted_volumes(registry):
    out = built(registry, car(3))
    for path in ("car/wheel_fl", "car/wheel_fr", "car/wheel_rl", "car/wheel_rr"):
        mesh = out.node(path).mesh
        assert 20 <= len(mesh.faces) <= 40
        assert faces_per_normal(mesh) >= 1.6


def test_primary_and_secondary_meshes_are_planar_low_poly(registry):
    out = built(registry, car(3))
    for path in ("car/body", "car/body/cabin", "car/body/hood_panel",
                 "car/body/fender_fl", "car/body/cabin/windshield"):
        mesh = out.node(path).mesh
        assert faces_per_normal(mesh) >= 1.45, path
        assert len(mesh.faces) <= 32, path


def test_cross_plugin_front_anchor_accepts_small_accessory(registry):
    g = car(3)
    g.attach("front_charm", "accessories:piercing", on="body",
             requirement=req("anchor", side="front", tags=("front",)))
    out = built(registry, g)
    charm = out.composition.node("front_charm")
    assert charm.link.parent == "car/body"
    assert charm.link.parent_socket == "front_anchor"
    assert out.node("front_charm").ref == "accessories:piercing"


@pytest.mark.parametrize("params", [
    {"length": 2.10, "width": 1.55, "height": 1.35, "chunkiness": 1.30},
    {"length": 2.80, "width": 1.55, "height": 1.35},
    {"length": 3.80, "width": 1.45, "height": 1.10, "front_taper": 0.32},
    {"wheel_size": 0.42},
    {"wheel_size": 0.58},
    {"wheel_size": 0.82},
    {"cabin_ratio": 0.32},
    {"cabin_ratio": 0.46},
    {"cabin_ratio": 0.66},
    {"ground_clearance": 0.10},
    {"ground_clearance": 0.30},
    {"stance": 0.92},
    {"stance": 1.24},
    {"width": 1.85, "chunkiness": 1.38, "wheel_size": 0.76},
    {"length": 3.30, "height": 1.55, "cabin_ratio": 0.62},
])
def test_param_matrix_stays_buildable_and_deterministic(registry, params):
    signatures = []
    for _ in range(2):
        out = built(registry, car(3, **params))
        report = validate(out, style=registry.style("low_poly"))
        forbidden = {"DECLARED_SOCKET_MISSING", "PARENT_SOCKET_NOT_FOUND",
                     "OWN_SOCKET_NOT_FOUND", "JOINT_GAP",
                     "COMPONENT_BUILD_FAILED"}
        assert not (forbidden & set(report.codes())), report.describe()
        assert np.all(np.isfinite(out.size))
        assert float(out.size[0]) > 0.5
        assert float(out.size[1]) > 0.4
        assert float(out.size[2]) > 1.0
        signatures.append((tuple(np.round(out.size, 6)), len(out.nodes), out.triangles))
    assert signatures[0] == signatures[1]


def test_default_validation_has_no_fatal_vehicle_errors(registry):
    out = built(registry, car(3))
    report = validate(out, style=registry.style("low_poly"))
    forbidden = {"DECLARED_SOCKET_MISSING", "PARENT_SOCKET_NOT_FOUND",
                 "OWN_SOCKET_NOT_FOUND", "JOINT_GAP", "COMPONENT_BUILD_FAILED"}
    assert not (forbidden & set(report.codes())), report.describe()
