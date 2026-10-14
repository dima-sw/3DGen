"""V4: real data-only GLBs cross the ordinary composition pipeline end to end."""
from __future__ import annotations

import json
from pathlib import Path
import zipfile

import numpy as np
import pytest
import trimesh

from app.ai.provider import OfflineProvider
from app.build.exporter import export
from app.core import project
from app.core.archetypes import MATCH_SUBJECT, ConceptResolver
from app.core.component import BuildContext, Component, Piece
from app.core.planner.planner import MockPlanner
from app.core.registry import load
from app.core.session import Options, Session
from tests.data_plugin_fixtures import (write_json, write_knight_plugin,
                                       write_vehicle_plugin)

BUILTINS = Path(__file__).resolve().parents[1] / "app" / "plugins"


def session_for(registry, scripts=None):
    return Session(registry=registry, provider=OfflineProvider(),
                   planner=MockPlanner(scripts=scripts or {}))


def plan_for(ref="mesh_fixture:knight", *, detail=2, children=None, effects=None,
             params=None):
    root = {"id": "subject", "ref": ref}
    if children is not None:
        root["children"] = children
    if effects is not None:
        root["effects"] = effects
    if params is not None:
        root["params"] = params
    return {"version": "1.3", "style": "low_poly", "detail_level": detail,
            "seed": 7, "root": root}


def mixed_plan(direction="mesh_head"):
    if direction == "mesh_head":
        return plan_for("humanoid:body", children=[{
            "id": "head", "ref": "mesh_fixture:head", "on": "torso",
            "at": {"capability": "head_mount"}, "insert": 0.0,
        }])
    return plan_for("mesh_fixture:body", children=[{
        "id": "head", "ref": "humanoid:head",
        "at": {"capability": "head_mount"}, "insert": 0.0,
        "params": {"length": 0.3, "girth": 0.14},
    }])


@pytest.fixture
def installed(tmp_path):
    folder = write_knight_plugin(tmp_path)
    registry = load([BUILTINS, folder]).freeze()
    assert registry.report.ok, registry.report.describe()
    return folder, registry


def test_a_real_glb_becomes_an_ordinary_component_piece_and_scene(installed):
    folder, registry = installed
    assert (folder / "meshes/head.glb").read_bytes()[:4] == b"glTF"
    component = registry.component("mesh_fixture:head")
    assert type(component) is Component
    piece = component.build({"width": 1.0}, BuildContext())
    assert type(piece) is Piece
    assert isinstance(piece.mesh, trimesh.Trimesh)
    assert piece.triangles == 12
    assert piece.socket("base").direction.tolist() == [0.0, -1.0, 0.0]

    result = session_for(registry).build(plan_for())
    assert result.ok and result.report.ok, result.report.describe()
    assert result.triangles == 24
    assert result.scene().triangle_count == result.triangles
    assert result.scene().by_id("subject").material.base_color == "#cf7934"


@pytest.mark.parametrize("detail, expected", [
    (1, {"subject"}), (2, {"subject", "subject/head"}),
    (3, {"subject", "subject/head", "subject/head/crest"}),
])
def test_recursive_data_children_use_existing_attachment_detail_levels(installed,
                                                                      detail, expected):
    _, registry = installed
    result = session_for(registry).build(plan_for(detail=detail))
    assert result.ok and result.report.ok, result.report.describe()
    assert {node.id for node in result.build.walk()} == expected
    assert result.triangles == 12 * len(expected)
    if detail == 3:
        assert result.resolved.node("subject/head/crest").link.parent == "subject/head"


@pytest.mark.parametrize("direction", ["mesh_head", "mesh_body"])
def test_capabilities_mount_mesh_and_procedural_parts_in_both_directions(installed,
                                                                       direction):
    _, registry = installed
    result = session_for(registry).build(mixed_plan(direction))
    assert result.ok and result.report.ok, result.report.describe()
    head = result.build.node("head")
    assert head is not None and head.mesh is not None
    parent = result.build.node(head.node.link.parent)
    socket = parent.socket_world(head.parent_socket)
    own = head.socket_world("base")
    assert head.node.link.capability == "head_mount"
    assert np.allclose(own.position, socket.position)
    assert np.allclose(own.direction, -socket.direction)
    refs = {node.ref for node in result.build.walk()}
    assert any(ref.startswith("humanoid:") for ref in refs)
    assert any(ref.startswith("mesh_fixture:") for ref in refs)


def test_transform_parameters_rebuild_deterministically_without_mutating_source(installed):
    _, registry = installed
    session = session_for(registry)
    plain = session.build(plan_for("mesh_fixture:head", detail=1))
    wide = session.build(plan_for("mesh_fixture:head", detail=1, params={"width": 2.0}))
    repeat = session.build(plan_for("mesh_fixture:head", detail=1))
    assert wide.report.ok, wide.report.describe()
    assert np.allclose(wide.mesh().extents, plain.mesh().extents * [2, 1, 1])
    assert np.array_equal(plain.mesh().vertices, repeat.mesh().vertices)
    assert np.array_equal(plain.mesh().faces, repeat.mesh().faces)


def test_installing_data_adds_semantic_knowledge_and_rebuilds_the_session_index(tmp_path):
    registry = load([BUILTINS])
    session = session_for(registry)
    before = session.component_index()
    assert "mesh_fixture:knight" not in dict(before.search("knight"))

    folder = write_knight_plugin(tmp_path)
    registry.load_plugin(folder)
    assert not before.is_current(registry)
    after = session.component_index()
    assert after is not before
    assert "mesh_fixture:knight" in dict(after.search("knight"))
    assert "mesh_fixture:knight" in session.shortlist("knight").ids
    entry = next(c for c in session.vocabulary(prompt="knight").components
                 if c.id == "mesh_fixture:knight")
    assert entry.id == "mesh_fixture:knight"


def test_unknown_paladin_degrades_to_data_knight_without_binding_or_archetype(installed):
    _, registry = installed
    assert not [b for b in registry.implementation_bindings()
                if "mesh_fixture" in str(b)]
    assert not [a for a in registry.archetypes() if a.id.startswith("mesh_fixture:")]
    resolution = ConceptResolver(registry).resolve("paladin", style="low_poly")
    assert resolution.selected_root_implementation == "mesh_fixture:knight"
    assert resolution.match == MATCH_SUBJECT
    assert resolution.approximate and resolution.confidence > 0
    result = session_for(registry).build({"version": "1.3", "style": "low_poly",
                                         "concept": {"requested": "paladin"}})
    assert result.ok and result.degradation()
    assert result.resolved.node(result.resolved.root).ref == "mesh_fixture:knight"


def test_removing_a_data_plugin_invalidates_retrieval_and_loses_its_synonyms(installed):
    _, registry = installed
    session = session_for(registry)
    before = session.component_index()
    # A Session snapshot is immutable; rescan installed directories to observe removal.
    session.registry = load([BUILTINS]).freeze()
    assert not before.is_current(session.registry)
    after = session.component_index()
    assert after is not before
    assert "mesh_fixture:knight" not in after.index.ids
    assert "mesh_fixture:knight" not in dict(after.search("knight"))
    assert "knight" not in session.registry.synonyms()
    assert ConceptResolver(session.registry).resolve("paladin").selected_root_implementation \
        != "mesh_fixture:knight"


@pytest.mark.parametrize("change", ["version", "mesh", "metadata"])
def test_data_version_or_content_change_invalidates_semantic_fingerprint(installed, change):
    folder, registry = installed
    index = session_for(registry).component_index()
    if change == "version":
        path = folder / "plugin.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["version"] = "2.0.0"
        write_json(path, data)
    elif change == "metadata":
        path = folder / "components/knight.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["description"] += " carrying heraldic armor"
        write_json(path, data)
    else:
        path = folder / "meshes/body.glb"
        mesh = trimesh.load(path, force="mesh")
        mesh.apply_scale(1.2)
        path.write_bytes(mesh.export(file_type="glb"))
    updated = load([BUILTINS, folder]).freeze()
    assert updated.report.ok, updated.report.describe()
    assert not index.is_current(updated)
    assert "mesh_fixture:knight" in dict(session_for(updated).component_index().search("knight"))


@pytest.mark.parametrize("count", [4, 6])
def test_existing_wheel_count_and_layout_work_on_a_data_body(tmp_path, count):
    folder = write_vehicle_plugin(tmp_path)
    registry = load([BUILTINS, folder]).freeze()
    assert registry.report.ok, registry.report.describe()
    plan = plan_for("mesh_vehicle:body", detail=1)
    plan["structural_traits"] = [{"trait": "vehicle:wheel_count", "value": count,
                                  "mode": "exact"}]
    result = session_for(registry).build(plan)
    assert result.ok and result.report.ok, result.report.describe()
    wheels = [node for node in result.build.walk() if node.node.component.role == "wheel"]
    assert len(wheels) == count
    assert all(node.ref == "vehicle_stylized:wheel" for node in wheels)
    assert result.structural.applied
    assert len(result.layout.placements) == count
    assert len({tuple(node.socket_world("base").position) for node in wheels}) == count
    assert result.build.node("subject").ref == "mesh_vehicle:body"


def test_existing_bend_deforms_data_vertices_and_sockets_by_the_same_map(installed):
    _, registry = installed
    session = session_for(registry)
    plain = session.build(plan_for("mesh_fixture:body", detail=1))
    bent = session.build(plan_for("mesh_fixture:body", detail=1, effects=[{
        "type": "fx:bend", "scope": "part", "along": "Y", "axis": "Z", "amount": 0.45,
    }]))
    assert bent.ok and bent.report.ok, bent.report.describe()
    before, after = plain.build.node("subject"), bent.build.node("subject")
    assert after.deformed
    assert not np.allclose(before.mesh.vertices, after.mesh.vertices)
    assert not np.allclose(before.sockets["corner"].position, after.sockets["corner"].position)
    index = np.flatnonzero(np.all(np.isclose(before.mesh.vertices,
                                            before.sockets["corner"].position), axis=1))
    assert len(index) == 1
    assert np.allclose(after.mesh.vertices[index[0]], after.sockets["corner"].position)
    assert not np.allclose(before.sockets["head"].direction, after.sockets["head"].direction)
    repeated = session.build(plan_for("mesh_fixture:body", detail=1))
    assert np.array_equal(before.mesh.vertices, repeated.mesh().vertices)


@pytest.mark.parametrize("extension", ["glb", "obj", "stl", "ply"])
def test_mixed_scene_exports_through_existing_exporters(installed, tmp_path, extension):
    _, registry = installed
    result = session_for(registry).build(mixed_plan())
    assert result.ok and result.report.ok, result.report.describe()
    destination = tmp_path / ("mixed." + extension)
    export(result.scene(), destination, save_plan=False)
    assert destination.stat().st_size > 0
    loaded = trimesh.load(destination, force="scene")
    assert sum(len(mesh.faces) for mesh in loaded.geometry.values()) == result.triangles
    assert np.all(np.isfinite(loaded.bounds))
    assert np.allclose(loaded.bounds, result.scene().bounds(), atol=1e-6)


def test_my3d_round_trip_regenerates_mixed_geometry_without_embedding_mesh(installed, tmp_path):
    folder, registry = installed
    original = session_for(registry, {"fixture": mixed_plan()})
    first = original.generate("fixture", Options(repair=False))
    assert first.ok and first.report.ok, first.report.describe()
    saved = original.save_project(tmp_path / "mixed.my3d")
    with zipfile.ZipFile(saved) as archive:
        assert not any(name.endswith((".glb", ".gltf", ".bin")) for name in archive.namelist())
        metadata = json.loads(archive.read("project.json"))
        assert metadata["plugins"]["mesh_fixture"] == "1.0.0"
    resumed = session_for(load([BUILTINS, folder]).freeze())
    resumed.open_project(saved)
    assert resumed.current_plan.to_dict() == original.current_plan.to_dict()
    assert resumed.scene.triangle_count == original.scene.triangle_count
    assert np.allclose(resumed.result.mesh().vertices, first.mesh().vertices)
    assert np.array_equal(resumed.result.mesh().faces, first.mesh().faces)
    assert resumed.result.scene().by_id("head").material.base_color == "#cf7934"


def test_my3d_reports_missing_data_plugin_and_preserves_rebuildable_history(installed, tmp_path):
    _, registry = installed
    original = session_for(registry, {
        "procedural": plan_for("humanoid:body"), "mixed": mixed_plan(),
    })
    original.generate("procedural", Options(repair=False))
    original.generate("mixed", Options(repair=False))
    path = original.save_project(tmp_path / "missing.my3d")
    resumed = session_for(load([BUILTINS]).freeze())
    resumed.open_project(path)
    assert "mesh_fixture@1.0.0" in resumed.missing_plugins
    assert resumed.scene.triangle_count > 0
    assert all(not node.ref.startswith("mesh_fixture:")
               for node in resumed.result.build.walk())


@pytest.mark.parametrize("change, code", [
    ("version", "PLUGIN_VERSION_CHANGED"), ("mesh", "PLUGIN_CONTENT_CHANGED"),
])
def test_my3d_reports_data_version_or_asset_change(installed, tmp_path, change, code):
    folder, registry = installed
    original = session_for(registry, {"fixture": plan_for(detail=1)})
    original.generate("fixture", Options(repair=False))
    path = original.save_project(tmp_path / "changed.my3d")
    if change == "version":
        manifest = folder / "plugin.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["version"] = "2.0.0"
        write_json(manifest, data)
    else:
        mesh_path = folder / "meshes/body.glb"
        mesh = trimesh.load(mesh_path, force="mesh")
        mesh.apply_scale([1.1, 1, 1])
        mesh_path.write_bytes(mesh.export(file_type="glb"))
    updated = load([BUILTINS, folder]).freeze()
    assert project.read_info(path).changed_plugins(updated)
    resumed = session_for(updated)
    resumed.open_project(path)
    assert resumed.result.ok
    assert code in {diagnostic.code for diagnostic in resumed.result.diagnostics}
