"""V4: the data-only loader, read as a contract rather than as a feature.

Three things are checked here and nowhere else: a JSON definition becomes the
*existing* models (`Component`, `Piece`, `Socket`, `ParamSpec`, `Attachment`,
`MaterialSpec`), a declaration that is wrong is refused with a code instead of
being guessed at, and nothing in a data plugin directory is ever executed.

The integration file `test_data_plugin_integration.py` covers the pipeline;
this one covers the boundary.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np
import pytest
import trimesh

from app.core import data_plugin
from app.core.component import BuildContext, Component
from app.core.data_plugin import (DataPluginError, load_component, load_material,
                                  safe_path)
from app.core.errors import Report
from app.core.layout import LayoutRegion
from app.core.material import MaterialSpec
from app.core.params import ParamSpec
from app.core.registry import Registry, load
from app.core.socket import Socket
from tests.data_plugin_fixtures import (box_mesh, socket_data, write_json,
                                        write_plugin)

BUILTINS = Path(__file__).resolve().parents[1] / "app" / "plugins"


def definition(**overrides) -> dict:
    data = {"id": "unit:part", "description": "A unit test part",
            "mesh": "../meshes/part.glb", "role": "part", "tags": ["part"],
            "sockets": [socket_data("base", (0, 0, 0), (0, -1, 0))]}
    data.update(overrides)
    return {k: v for k, v in data.items() if v is not None}


def written(tmp_path, *, geometry=None, meshes=None, **overrides) -> Path:
    """Write a one-component data plugin and return its directory.

    The definition always lands in ``components/part.json``, whatever ``id`` it
    declares: the manifest names the file, so a malformed id must still be read
    from where the manifest says it is.
    """
    folder = write_plugin(tmp_path, plugin_id="unit",
                          components=[definition()],
                          meshes=meshes if meshes is not None
                          else {"part.glb": geometry if geometry is not None
                                else box_mesh()})
    write_json(folder / "components/part.json", definition(**overrides))
    return folder


def component_of(tmp_path, **overrides) -> Component:
    folder = written(tmp_path, **overrides)
    return load_component(folder / "components/part.json", folder)


def refused(tmp_path, *, code=None, **overrides):
    folder = written(tmp_path, **overrides)
    with pytest.raises(DataPluginError) as caught:
        load_component(folder / "components/part.json", folder)
    if code is not None:
        assert caught.value.code == code, caught.value.message
    return caught.value


# --------------------------------------------------------------------------- #
# 1-2. the manifest and the definition, valid
# --------------------------------------------------------------------------- #
def test_a_data_manifest_installs_components_without_declaring_python(tmp_path):
    folder = written(tmp_path, provides=["unit_part"])
    registry = load([folder])
    info = registry.plugin("unit")
    assert info is not None and info.kind == "data"
    assert info.sources == ()                       # nessun modulo dichiarato
    assert info.data_components == ("components/part.json",)
    assert info.fingerprint and len(info.fingerprint) == 64
    assert registry.component("unit:part") is not None


def test_a_valid_definition_becomes_the_existing_models(tmp_path):
    component = component_of(
        tmp_path, provides=["unit_part"], requires=["connected"],
        styles=["low_poly"], material="unit_metal",
        mounts=[{"capability": "probe_mount", "socket_id": "tip", "side": "l"}],
        sockets=[socket_data("base", (0, 0, 0), (0, -1, 0)),
                 socket_data("tip", (0, 1, 0), (0, 1, 0), capabilities=("probe",),
                             side="l", tags=("upper",), radius=0.2)],
        params={"height": {"default": 1.0, "min": 0.5, "max": 2.0,
                           "semantic_role": "length", "transform": "scale_y"}})
    assert type(component) is Component
    assert component.plugin == "unit" and component.role == "part"
    assert [c.name for c in component.provides] == ["unit_part"]
    assert component.accepts("probe_mount", "l")
    assert component.requires == frozenset({"connected"})
    assert component.styles == frozenset({"low_poly"})
    assert type(component.params["height"]) is ParamSpec
    assert component.params["height"].semantic_role == "length"
    piece = component.build({}, BuildContext())
    assert type(piece.socket("tip")) is Socket
    assert piece.material == "unit_metal"
    assert piece.triangles == 12


def test_the_display_name_feeds_search_without_a_parallel_field(tmp_path):
    component = component_of(tmp_path, name="Unit Part", description="a probe")
    assert component.name == "part"                 # resta derivato dall'id
    assert component.description == "Unit Part. a probe"


@pytest.mark.parametrize("overrides, where", [
    ({"id": "part"}, "qualificato"),
    ({"id": "unit:"}, "qualificato"),
    ({"mesh": None}, "mesh"),
    ({"sockets": [socket_data("base", (0, 0, 0)), socket_data("base", (0, 1, 0))]},
     "duplicat"),
    ({"tags": ["ok", 3]}, "tags"),
    ({"role": 7}, "role"),
    ({"requires": "connected"}, "requires"),
])
def test_a_malformed_definition_is_refused_with_a_message(tmp_path, overrides, where):
    error = refused(tmp_path, **overrides)
    assert where in error.message


def test_an_unsupported_field_is_refused_instead_of_ignored(tmp_path):
    error = refused(tmp_path, code="DATA_SCHEMA_INVALID", skeleton="../rig.json")
    assert "skeleton" in error.message


def test_duplicate_json_keys_are_refused(tmp_path):
    folder = written(tmp_path)
    path = folder / "components/part.json"
    path.write_text('{"id": "unit:part", "id": "unit:other", '
                    '"mesh": "../meshes/part.glb"}', encoding="utf-8")
    with pytest.raises(DataPluginError) as caught:
        load_component(path, folder)
    assert "duplicata" in caught.value.message


@pytest.mark.parametrize("raw, code", [
    ("{not json", "DATA_JSON_INVALID"),
    ('{"id": "unit:part", "mesh": "../meshes/part.glb", "params": NaN}',
     "DATA_JSON_INVALID"),
    ('{"id": "unit:part", "mesh": "../meshes/part.glb", "params": Infinity}',
     "DATA_JSON_INVALID"),
    ('[{"id": "unit:part"}]', "DATA_SCHEMA_INVALID"),
])
def test_invalid_json_is_refused(tmp_path, raw, code):
    folder = written(tmp_path)
    path = folder / "components/part.json"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(DataPluginError) as caught:
        load_component(path, folder)
    assert caught.value.code == code


@pytest.mark.parametrize("manifest, code", [
    ({"type": "sandbox"}, "INVALID_MANIFEST"),
    ({"components": "components/part.json"}, "INVALID_MANIFEST"),
    ({"components": ["components/absent.json"]}, "INVALID_MANIFEST"),
    ({"components": ["components/part.py"]}, "INVALID_MANIFEST"),
    ({"components": ["../../components/part.json"]}, "DATA_PATH_UNSAFE"),
    ({"sources": ["plugin.py"]}, "INVALID_MANIFEST"),
    ({"effects": ["effects/fx.py"]}, "INVALID_MANIFEST"),
])
def test_a_malformed_data_manifest_is_refused(tmp_path, manifest, code):
    folder = written(tmp_path)
    data = json.loads((folder / "plugin.json").read_text(encoding="utf-8"))
    data.update(manifest)
    write_json(folder / "plugin.json", data)
    registry = Registry()
    assert registry.load_plugin(folder) is None
    assert code in registry.report.codes()
    assert registry.component("unit:part") is None


# --------------------------------------------------------------------------- #
# 3. path confinement
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("hostile", [
    # Il percorso della mesh e' relativo alla cartella del file componente,
    # quindi `../meshes/x.glb` e' il caso normale: questi escono dal plugin.
    "../../secret.glb", "../../../secret.glb", "/etc/passwd", "C:/Windows/win.ini",
    "\\\\server\\share\\mesh.glb", "components/../../../secret.glb",
    "meshes/../../../secret.glb", "mesh\x00.glb", "file:///secret.glb",
    "..\\..\\secret.glb",
])
def test_path_traversal_and_absolute_paths_are_blocked(tmp_path, hostile):
    outside = tmp_path / "secret.glb"
    outside.write_bytes(box_mesh().export(file_type="glb"))
    error = refused(tmp_path, code="DATA_PATH_UNSAFE", mesh=hostile)
    assert "plugin" in error.message or "relativa" in error.message


def test_a_mesh_path_relative_to_the_component_file_stays_inside(tmp_path):
    """`../secret.glb` risale di una cartella e resta dentro: caso legittimo."""
    folder = written(tmp_path, mesh="../secret.glb")
    (folder / "secret.glb").write_bytes(box_mesh().export(file_type="glb"))
    assert load_component(folder / "components/part.json", folder) is not None


def test_an_empty_mesh_declaration_is_a_schema_error_not_a_path_one(tmp_path):
    assert "mesh" in refused(tmp_path, code="DATA_SCHEMA_INVALID", mesh="").message


def test_a_relative_path_inside_the_plugin_is_allowed(tmp_path):
    folder = written(tmp_path)
    assert safe_path(folder, "meshes/part.glb").is_file()
    assert safe_path(folder, "components/../meshes/part.glb").is_file()
    with pytest.raises(DataPluginError):
        safe_path(folder, "../meshes/part.glb")


def test_a_gltf_uri_cannot_leave_the_plugin_or_reach_the_network(tmp_path):
    secret = tmp_path / "secret.bin"
    secret.write_bytes(b"\0" * 16)
    folder = written(tmp_path, meshes={})
    document = {"asset": {"version": "2.0"}, "scenes": [{"nodes": []}],
                "buffers": [{"byteLength": 16, "uri": "../../secret.bin"}]}
    write_json(folder / "meshes/part.gltf", document)
    data = definition(mesh="../meshes/part.gltf")
    write_json(folder / "components/part.json", data)
    with pytest.raises(DataPluginError) as caught:
        load_component(folder / "components/part.json", folder)
    assert caught.value.code == "DATA_PATH_UNSAFE"

    document["buffers"][0]["uri"] = "https://example.invalid/secret.bin"
    write_json(folder / "meshes/part.gltf", document)
    with pytest.raises(DataPluginError) as caught:
        load_component(folder / "components/part.json", folder)
    assert caught.value.code == "DATA_PATH_UNSAFE"


# --------------------------------------------------------------------------- #
# 4-7. mesh loading
# --------------------------------------------------------------------------- #
def test_a_missing_mesh_file_is_reported_as_missing(tmp_path):
    folder = written(tmp_path)
    (folder / "meshes/part.glb").unlink()
    with pytest.raises(DataPluginError) as caught:
        load_component(folder / "components/part.json", folder)
    assert caught.value.code == "DATA_FILE_MISSING"


@pytest.mark.parametrize("payload", [
    b"", b"not a gltf file at all", b"glTF" + b"\0" * 8,
    b"glTF" + (99).to_bytes(4, "little") + b"\0" * 12,
])
def test_an_invalid_glb_is_refused_without_a_traceback(tmp_path, payload):
    folder = written(tmp_path)
    (folder / "meshes/part.glb").write_bytes(payload)
    with pytest.raises(DataPluginError) as caught:
        load_component(folder / "components/part.json", folder)
    assert caught.value.code in ("DATA_MESH_INVALID", "DATA_MESH_EMPTY")


def test_an_unsupported_mesh_format_names_what_is_supported(tmp_path):
    folder = written(tmp_path, meshes={})
    (folder / "meshes").mkdir(exist_ok=True)
    (folder / "meshes/part.obj").write_bytes(box_mesh().export(file_type="obj").encode())
    write_json(folder / "components/part.json", definition(mesh="../meshes/part.obj"))
    with pytest.raises(DataPluginError) as caught:
        load_component(folder / "components/part.json", folder)
    assert caught.value.code == "DATA_MESH_FORMAT"
    assert "GLB/glTF" in caught.value.message


def test_an_empty_mesh_is_refused_at_load_instead_of_building_nothing(tmp_path):
    empty = trimesh.Trimesh(vertices=np.zeros((0, 3)), faces=np.zeros((0, 3), dtype=int))
    scene = trimesh.Scene()
    scene.add_geometry(empty, geom_name="empty")
    folder = written(tmp_path, meshes={})
    (folder / "meshes").mkdir(exist_ok=True)
    (folder / "meshes/part.glb").write_bytes(scene.export(file_type="glb"))
    with pytest.raises(DataPluginError) as caught:
        load_component(folder / "components/part.json", folder)
    assert caught.value.code == "DATA_MESH_EMPTY"


def test_a_single_mesh_keeps_its_triangles_and_bounds(tmp_path):
    component = component_of(tmp_path)
    piece = component.build({}, BuildContext())
    assert piece.triangles == 12
    assert np.allclose(piece.mesh.bounds[0], [-0.3, 0.0, -0.2])
    assert np.allclose(piece.mesh.bounds[1], [0.3, 1.0, 0.2])


def test_a_multi_node_glb_merges_every_primitive_with_its_transform(tmp_path):
    scene = trimesh.Scene()
    scene.add_geometry(box_mesh((0.4, 0.4, 0.4)), node_name="low", geom_name="low")
    high = trimesh.transformations.translation_matrix((0.0, 1.0, 0.0))
    scene.add_geometry(box_mesh((0.2, 0.2, 0.2)), node_name="high", geom_name="high",
                       transform=high)
    folder = written(tmp_path, meshes={})
    (folder / "meshes").mkdir(exist_ok=True)
    (folder / "meshes/part.glb").write_bytes(scene.export(file_type="glb"))
    piece = load_component(folder / "components/part.json", folder).build(
        {}, BuildContext())
    assert piece.triangles == 24                   # due scatole, niente perso
    assert piece.mesh.body_count == 2
    # il nodo traslato resta dove lo ha messo l'autore: 1.0 + 0.2 di altezza
    assert np.isclose(piece.mesh.bounds[1][1], 1.2)
    assert np.isclose(piece.mesh.bounds[0][1], 0.0)


def test_the_source_mesh_is_loaded_once_and_never_mutated_by_a_build(tmp_path):
    component = component_of(tmp_path, params={
        "grow": {"default": 1.0, "max": 4.0, "transform": "uniform_scale"}})
    first = component.build({"grow": 3.0}, BuildContext())
    second = component.build({}, BuildContext())
    assert np.isclose(first.mesh.extents[1], 3.0)
    assert np.isclose(second.mesh.extents[1], 1.0)
    assert first.mesh is not second.mesh


# --------------------------------------------------------------------------- #
# 8. sockets declared in data
# --------------------------------------------------------------------------- #
def test_sockets_are_ordinary_sockets_with_the_declared_frame(tmp_path):
    component = component_of(tmp_path, sockets=[
        socket_data("base", (0, 0, 0), (0, -1, 0)),
        socket_data("left", (-0.3, 0.5, 0), (-1, 0, 0), capabilities=("arm_mount",),
                    side="l", tags=("upper", "limb"), radius=0.17, up=(0, 1, 0)),
    ])
    piece = component.build({}, BuildContext())
    left = piece.socket("left")
    assert type(left) is Socket
    assert np.allclose(left.position, [-0.3, 0.5, 0.0])
    assert np.allclose(left.direction, [-1.0, 0.0, 0.0])
    assert left.radius == pytest.approx(0.17)
    assert left.side == "l"
    assert set(left.tags) == {"upper", "limb"}
    assert [c.name for c in left.capabilities] == ["arm_mount"]


@pytest.mark.parametrize("socket, code", [
    (socket_data("base", (0, 0, 0), (0, 0, 0)), "DATA_FRAME_INVALID"),
    (socket_data("base", (0, 0, 0), (0, 1, 0), up=(0, 2, 0)), "DATA_FRAME_INVALID"),
    (socket_data("base", (0, 0), (0, 1, 0)), "DATA_SCHEMA_INVALID"),
    (socket_data("base", (0, 0, 0), (0, 1, 0), radius=0.0), "DATA_SCHEMA_INVALID"),
    (socket_data("base", (0, 0, 0), (0, 1, 0), side="up"), "DATA_SCHEMA_INVALID"),
    (socket_data("", (0, 0, 0), (0, 1, 0)), "DATA_SCHEMA_INVALID"),
])
def test_an_unusable_socket_frame_is_refused(tmp_path, socket, code):
    refused(tmp_path, code=code, sockets=[socket])


def test_a_declared_growth_axis_is_verified_and_never_silently_corrected(tmp_path):
    report = Report()
    wide = component_of(tmp_path, geometry=box_mesh((2.0, 0.2, 0.2)),
                        frame={"growth_axis": "+Y", "front": "+Z", "up": "+Y"})
    piece = wide.build({}, BuildContext(report=report))
    assert "GROWTH_AXIS_MISMATCH" in report.codes()
    assert "GROWTH_AXIS_MISMATCH" in piece.metadata["frame_diagnostics"]
    # nessuna rotazione magica: la geometria resta quella dichiarata dall'autore
    assert np.isclose(piece.mesh.extents[0], 2.0)
    assert piece.metadata["frame"]["growth_axis"] == "+Y"

    clean = Report()
    tall = component_of(tmp_path, frame={"growth_axis": "+Y"})
    tall.build({}, BuildContext(report=clean))
    assert not clean.codes()


@pytest.mark.parametrize("frame", [
    {"growth_axis": "up"}, {"front": "+Z", "up": "+Z"}, {"growth_axis": "+W"},
])
def test_an_unusable_frame_declaration_is_refused(tmp_path, frame):
    refused(tmp_path, code="DATA_FRAME_INVALID", frame=frame)


# --------------------------------------------------------------------------- #
# 9. parameters: declared transforms only
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("transform, expected, radius", [
    # Il raggio e' quello del disco dell'innesto: scalare lungo la **normale**
    # del disco non lo cambia, scalarne il piano lo cambia come la radice
    # dell'area. L'innesto 'tip' guarda +X.
    ("scale_x", [2.0, 1.0, 1.0], 1.0), ("scale_y", [1.0, 2.0, 1.0], 2.0 ** 0.5),
    ("scale_z", [1.0, 1.0, 2.0], 2.0 ** 0.5), ("uniform_scale", [2.0, 2.0, 2.0], 2.0),
])
def test_a_transform_parameter_scales_mesh_and_sockets_together(tmp_path, transform,
                                                                expected, radius):
    component = component_of(tmp_path, sockets=[
        socket_data("base", (0, 0, 0), (0, -1, 0)),
        socket_data("tip", (0.3, 1.0, 0.2), (1, 0, 0), radius=0.1)],
        params={"amount": {"default": 1.0, "max": 4.0, "transform": transform}})
    plain = component.build({}, BuildContext())
    scaled = component.build({"amount": 2.0}, BuildContext())
    assert np.allclose(scaled.mesh.extents / plain.mesh.extents, expected)
    assert np.allclose(scaled.socket("tip").position,
                       plain.socket("tip").position * expected)
    assert scaled.socket("tip").radius == pytest.approx(
        plain.socket("tip").radius * radius)


@pytest.mark.parametrize("params, code", [
    ({"width": {"default": 1.0}}, "DATA_PARAM_UNSUPPORTED"),
    ({"width": {"default": 1.0, "transform": "rebuild"}}, "DATA_PARAM_UNSUPPORTED"),
    ({"width": {"default": 1.0, "transform": "bend"}}, "DATA_PARAM_UNSUPPORTED"),
    ({"width": {"default": 1.0, "type": "enum", "transform": "scale_x"}},
     "DATA_PARAM_UNSUPPORTED"),
    ({"width": {"default": 0.0, "transform": "scale_x"}}, "DATA_SCHEMA_INVALID"),
    ({"width": {"default": -1.0, "transform": "scale_x"}}, "DATA_SCHEMA_INVALID"),
    ({"width": {"default": 5.0, "max": 2.0, "transform": "scale_x"}},
     "DATA_SCHEMA_INVALID"),
    ({"width": {"default": 1.0, "min": 2.0, "max": 1.0, "transform": "scale_x"}},
     "DATA_SCHEMA_INVALID"),
    ({"width": {"default": 1.0, "derived": "parent.height", "transform": "scale_x"}},
     "DATA_SCHEMA_INVALID"),
])
def test_a_parameter_without_a_deterministic_meaning_is_refused(tmp_path, params, code):
    refused(tmp_path, code=code, params=params)


def test_a_non_positive_value_at_build_time_is_refused_not_mirrored(tmp_path):
    component = component_of(tmp_path, params={
        "width": {"default": 1.0, "transform": "scale_x"}})
    with pytest.raises(DataPluginError):
        component.build({"width": -2.0}, BuildContext())


# --------------------------------------------------------------------------- #
# 10. materials
# --------------------------------------------------------------------------- #
def test_a_material_file_becomes_a_material_spec(tmp_path):
    folder = write_plugin(tmp_path, plugin_id="unit", components=[definition()],
                          meshes={"part.glb": box_mesh()},
                          materials=[{"name": "unit_metal", "base_color": "#334455",
                                      "roughness": 0.4, "metallic": 0.9}])
    spec = load_material(folder / "materials/material_0.json", folder)
    assert type(spec) is MaterialSpec
    assert spec.base_color == "#334455"
    assert load([folder]).material("unit_metal").metallic == pytest.approx(0.9)


def test_an_explicit_material_wins_over_the_colors_in_the_glb(tmp_path):
    colored = box_mesh()
    colored.visual.face_colors = [10, 200, 30, 255]
    component = component_of(tmp_path, geometry=colored, material="unit_metal")
    assert component.material == "unit_metal"
    assert component.build({}, BuildContext()).material == "unit_metal"


def test_without_an_explicit_material_the_imported_colors_are_preserved(tmp_path):
    colored = box_mesh()
    colored.visual.face_colors = [10, 200, 30, 255]
    component = component_of(tmp_path, geometry=colored)
    piece = component.build({}, BuildContext())
    assert piece.material == ""                    # nessun nome: vince la mesh
    assert np.allclose(piece.mesh.visual.face_colors[0][:3], [10, 200, 30])


def test_with_neither_a_material_nor_colors_the_fallback_is_used(tmp_path):
    component = component_of(tmp_path)
    assert component.material == "default"
    assert component.build({}, BuildContext()).material == "default"


@pytest.mark.parametrize("material, message", [
    ({"name": "", "base_color": "#334455"}, "name"),
    ({"name": "unit_metal", "roughness": 5.0}, "Materiale"),
    ({"name": "unit_metal", "roughness": "molto"}, "roughness"),
    ({"name": "unit_metal", "shader": "pbr"}, "shader"),
])
def test_a_malformed_material_is_refused(tmp_path, material, message):
    folder = write_plugin(tmp_path, plugin_id="unit", components=[definition()],
                          meshes={"part.glb": box_mesh()}, materials=[material])
    with pytest.raises(DataPluginError) as caught:
        load_material(folder / "materials/material_0.json", folder)
    assert message in caught.value.message


# --------------------------------------------------------------------------- #
# 11. children and layout regions
# --------------------------------------------------------------------------- #
def test_children_are_ordinary_attachments_with_their_own_detail_level(tmp_path):
    component = component_of(tmp_path, children=[
        {"id": "tip", "component": "unit:other", "level": 3, "optional": True,
         "insert": 0.0, "scale_mode": "socket", "material": "unit_metal",
         "requirement": {"capability": "probe", "side": "l"},
         "params": {"length": 0.4, "label": "upper", "flag": True,
                    "offset": [0.1, 0.2, 0.3]}, "tags": ["detail"]}])
    attachments = component.children({}, BuildContext())
    assert len(attachments) == 1
    child = attachments[0]
    assert child.component == "unit:other" and child.level == 3
    assert child.requirement.capability == "probe" and child.requirement.side == "l"
    assert child.insert == 0.0 and child.material == "unit_metal"
    assert child.params["label"] == "upper"
    assert component.expand({}, BuildContext(detail_level=2)) == []
    assert len(component.expand({}, BuildContext(detail_level=3))) == 1


def test_each_build_gets_its_own_children_so_a_rewrite_cannot_leak(tmp_path):
    component = component_of(tmp_path, children=[
        {"id": "tip", "component": "unit:other", "level": 1}])
    first = component.children({}, BuildContext())
    first[0].params["mutated"] = True
    assert "mutated" not in component.children({}, BuildContext())[0].params


@pytest.mark.parametrize("children, where", [
    ([{"id": "tip"}], "component"),
    ([{"id": "tip", "component": "unit:other", "level": 0}], "level"),
    ([{"id": "tip", "component": "unit:other"},
      {"id": "tip", "component": "unit:third"}], "duplicat"),
    ([{"id": "tip", "component": "unit:other", "scale_mode": "stretch"}], "scale_mode"),
    ([{"id": "tip", "component": "unit:other", "params": {"n": {"expr": "1+1"}}}],
     "params"),
    ([{"id": "tip", "component": "unit:other", "build": "rig.py"}], "build"),
])
def test_a_malformed_child_is_refused(tmp_path, children, where):
    assert where in refused(tmp_path, children=children).message


def test_layout_regions_declared_in_data_are_ordinary_layout_regions(tmp_path):
    component = component_of(
        tmp_path,
        sockets=[socket_data("base", (0, 0, 0), (0, -1, 0)),
                 socket_data("left", (-0.3, 0.3, 0), (-1, 0, 0), side="l")],
        layout_regions=[{"id": "left_region", "anchor_socket": "left", "side": "l",
                         "allows_role": "wheel", "capacity": 4, "span": 1.2,
                         "min_spacing": 0.05, "default_policy": "linear",
                         "allowed_policies": ["linear"], "center": [-0.3, 0.3, 0],
                         "direction": [-1, 0, 0], "up": [0, 1, 0], "axis": [0, 0, 1]}])
    regions = component.layout_regions
    assert len(regions) == 1 and type(regions[0]) is LayoutRegion
    assert regions[0].validate() == []
    assert regions[0].anchor_socket == "left"


@pytest.mark.parametrize("region, where", [
    ({"id": "r", "anchor_socket": "absent"}, "ancoraggio"),
    ({"id": "", "span": 1.0}, "id"),
    ({"id": "r", "span": -1.0}, "layout_region"),
    ({"id": "r", "min_scale": 2.0, "max_scale": 1.0}, "layout_region"),
    ({"id": "r", "policy": "linear"}, "policy"),
])
def test_a_malformed_layout_region_is_refused(tmp_path, region, where):
    assert where in refused(tmp_path, layout_regions=[region]).message


# --------------------------------------------------------------------------- #
# 17. the quality gate is the existing one, driven by `requires`
# --------------------------------------------------------------------------- #
def test_requires_is_the_only_policy_for_imported_geometry(tmp_path):
    open_box = box_mesh()
    open_box.update_faces(np.arange(len(open_box.faces)) > 1)     # un buco vero
    relaxed = component_of(tmp_path, geometry=open_box)
    assert relaxed.requires == frozenset()
    strict = component_of(tmp_path, geometry=open_box, requires=["watertight"])
    assert strict.requires == frozenset({"watertight"})
    assert not strict.build({}, BuildContext()).mesh.is_watertight


def test_non_finite_vertices_are_refused_before_the_pipeline_sees_them(tmp_path):
    broken = box_mesh()
    broken.vertices[0] = [np.nan, 0.0, 0.0]
    folder = written(tmp_path, meshes={})
    (folder / "meshes").mkdir(exist_ok=True)
    (folder / "meshes/part.glb").write_bytes(broken.export(file_type="glb"))
    with pytest.raises(DataPluginError) as caught:
        load_component(folder / "components/part.json", folder)
    assert caught.value.code in ("DATA_MESH_INVALID", "DATA_MESH_EMPTY",
                                 "DATA_JSON_INVALID")


# --------------------------------------------------------------------------- #
# 22. no Python from a data plugin, ever
# --------------------------------------------------------------------------- #
def test_a_data_plugin_never_imports_or_executes_its_own_python(tmp_path, monkeypatch):
    folder = written(tmp_path)
    (folder / "boom.py").write_text("raise SystemExit('eseguito')\n", encoding="utf-8")
    (folder / "components/boom.py").write_text("import os; os.remove(__file__)\n",
                                               encoding="utf-8")
    data = json.loads((folder / "plugin.json").read_text(encoding="utf-8"))
    data["metadata"] = {"build": "boom.py", "entry_point": "boom:build"}
    write_json(folder / "plugin.json", data)

    before = set(sys.modules)
    calls = []
    monkeypatch.setattr(data_plugin, "safe_path", _watch(calls, data_plugin.safe_path))
    registry = load([folder])

    assert registry.report.ok, registry.report.describe()
    assert registry.component("unit:part") is not None
    assert registry.plugin("unit").sources == ()
    assert not [name for name in set(sys.modules) - before if "boom" in name]
    assert all(not str(path).endswith(".py") for path in calls)
    assert (folder / "components/boom.py").is_file()         # niente e' girato


def _watch(calls, original):
    def wrapper(root, relative, base=None):
        result = original(root, relative, base=base)
        calls.append(result)
        return result
    return wrapper


def test_the_loader_imports_no_plugin_module_and_touches_no_sys_path(tmp_path):
    folder = written(tmp_path)
    path_before = list(sys.path)
    load([folder])
    assert sys.path == path_before
    assert str(folder) not in sys.path


def test_a_data_plugin_cannot_declare_python_sources_at_all(tmp_path):
    folder = written(tmp_path)
    data = json.loads((folder / "plugin.json").read_text(encoding="utf-8"))
    data["components"] = ["components/part.json", "components/extra.py"]
    write_json(folder / "plugin.json", data)
    (folder / "components/extra.py").write_text("x = 1\n", encoding="utf-8")
    registry = Registry()
    assert registry.load_plugin(folder) is None
    assert "INVALID_MANIFEST" in registry.report.codes()


def test_the_whole_plugin_is_refused_when_one_definition_is_broken(tmp_path):
    folder = write_plugin(tmp_path, plugin_id="unit",
                          components=[definition(),
                                      definition(id="unit:other", mesh="../absent.glb")],
                          meshes={"part.glb": box_mesh()})
    registry = Registry()
    assert registry.load_plugin(folder) is None
    assert registry.component("unit:part") is None       # atomico, non a metà
    assert "DATA_FILE_MISSING" in registry.report.codes()


def test_a_data_plugin_cannot_shadow_an_installed_component_id(tmp_path):
    folder = write_plugin(tmp_path, plugin_id="unit",
                          components=[definition(id="humanoid:head")],
                          meshes={"part.glb": box_mesh()})
    registry = load([BUILTINS, folder])
    assert registry.plugin("unit") is None
    assert "COMPONENT_ID_MISMATCH" in registry.report.codes()
    assert registry.component("humanoid:head").plugin == "humanoid"
