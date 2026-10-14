"""Tiny real GLB assets written as data-only plugins for V4 integration tests.

This is test tooling, never plugin code: the resulting directories contain only
JSON and meshes and can be loaded independently of this module.
"""
from __future__ import annotations

import json
from pathlib import Path

import trimesh


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def box_mesh(size=(0.6, 1.0, 0.4)) -> trimesh.Trimesh:
    """A closed twelve-triangle mesh growing from the origin along +Y."""
    mesh = trimesh.creation.box(extents=size)
    mesh.apply_translation((0.0, size[1] / 2.0, 0.0))
    return mesh


def socket_data(name, position, direction=(0, 1, 0), *, capabilities=(),
                radius=0.1, side="", up=(0, 0, 1), tags=()):
    return {"name": name, "position": list(position),
            "direction": list(direction), "up": list(up), "radius": radius,
            "capabilities": list(capabilities), "side": side, "tags": list(tags)}


def write_plugin(root: Path, *, plugin_id="mesh_fixture", version="1.0.0",
                 components=None, meshes=None, materials=None,
                 synonyms=None) -> Path:
    """Write ``root/plugin_id`` and return its directory.

    ``meshes`` maps GLB filenames to real Trimesh/Scene objects; ``components``
    and ``materials`` contain ordinary JSON dictionaries. Mesh paths in the
    component definitions are relative to their own components directory.
    """
    folder = Path(root) / plugin_id
    folder.mkdir(parents=True, exist_ok=True)
    component_paths = []
    for definition in components or []:
        relative = "components/%s.json" % definition["id"].split(":")[-1]
        write_json(folder / relative, definition)
        component_paths.append(relative)
    material_paths = []
    for index, material in enumerate(materials or []):
        relative = "materials/material_%d.json" % index
        write_json(folder / relative, material)
        material_paths.append(relative)
    for name, mesh in (meshes or {}).items():
        destination = folder / "meshes" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        mesh.export(str(destination), file_type="glb")
    write_json(folder / "plugin.json", {
        "id": plugin_id, "version": version, "name": "Mesh fixture",
        "description": "Small low-poly test assets, supplied entirely as data",
        "type": "data", "components": component_paths,
        "materials": material_paths, "synonyms": synonyms or {},
    })
    return folder


def write_knight_plugin(root: Path, *, version="1.0.0") -> Path:
    """A root, macro head and recursive crest plus a separate compatible body."""
    base = socket_data("base", (0, 0, 0), (0, -1, 0))
    head_socket = socket_data("head", (0, 1, 0), capabilities=("head_mount",))
    common = {"material": "fixture_metal", "requires": ["connected", "watertight"],
              "frame": {"growth_axis": "+Y", "front": "+Z", "up": "+Y"}}
    components = [
        {**common, "id": "mesh_fixture:knight", "name": "Knight",
         "description": "A complete armored knight warrior figure",
         "mesh": "../meshes/body.glb", "role": "character",
         "tags": ["knight", "warrior", "armored", "figure"],
         "provides": ["warrior"],
         "mounts": [{"capability": "head_mount", "socket_id": "head"}],
         "sockets": [base, head_socket],
         "params": {"uniform_scale": {"default": 1.0, "min": 0.1, "max": 3.0,
                                       "transform": "uniform_scale"}},
         "children": [{"id": "head", "component": "mesh_fixture:head", "level": 2,
                       "insert": 0.0, "requirement": {"capability": "head_mount"}}]},
        {**common, "id": "mesh_fixture:body", "description": "A humanoid torso",
         "mesh": "../meshes/body.glb", "role": "body", "tags": ["body", "humanoid"],
         "mounts": [{"capability": "head_mount", "socket_id": "head"}],
         "sockets": [base, head_socket,
                     socket_data("corner", (0.3, 1, 0.2), capabilities=("probe",))]},
        {**common, "id": "mesh_fixture:head", "description": "A helmeted head",
         "mesh": "../meshes/head.glb", "role": "head", "tags": ["head", "humanoid"],
         "provides": ["head_mount"],
         "mounts": [{"capability": "crest_mount", "socket_id": "crest"}],
         "sockets": [base, socket_data("crest", (0, 0.4, 0),
                                       capabilities=("crest_mount",))],
         "params": {"width": {"default": 1.0, "min": 0.2, "max": 3.0,
                              "transform": "scale_x"}},
         "children": [{"id": "crest", "component": "mesh_fixture:crest", "level": 3,
                       "insert": 0.0, "requirement": {"capability": "crest_mount"}}]},
        {**common, "id": "mesh_fixture:crest", "description": "A small crest",
         "mesh": "../meshes/crest.glb", "role": "detail", "tags": ["crest"],
         "provides": ["crest_mount"], "sockets": [base]},
    ]
    return write_plugin(root, version=version, components=components,
                        meshes={"body.glb": box_mesh(),
                                "head.glb": box_mesh((0.3, 0.4, 0.25)),
                                "crest.glb": box_mesh((0.1, 0.16, 0.08))},
                        materials=[{"name": "fixture_metal", "base_color": "#cf7934",
                                    "roughness": 0.8, "metallic": 0.15}],
                        synonyms={"knight": ["paladin", "cavaliere"]})


def write_vehicle_plugin(root: Path) -> Path:
    """A mesh body with ordinary procedural wheels and static layout regions."""
    sockets = [socket_data("base", (0, 0, 0), (0, -1, 0))]
    mounts, children, regions = [], [], []
    for side, x, direction in (("l", -0.65, (-1, 0, 0)),
                                ("r", 0.65, (1, 0, 0))):
        name = "wheel_" + side
        sockets.append(socket_data(name, (x, 0.32, 0), direction,
                                   capabilities=("wheel_mount",), side=side,
                                   up=(0, 1, 0), radius=0.29))
        mounts.append({"capability": "wheel_mount", "socket_id": name,
                       "side": side, "capacity": 0})
        children.append({"id": name, "component": "vehicle_stylized:wheel", "level": 1,
                         "requirement": {"capability": "wheel_mount", "side": side},
                         "params": {"diameter": 0.58, "width": 0.2}, "insert": 0.0})
        regions.append({"id": name + "_region", "anchor_socket": name,
                        "allows_role": "wheel", "allows_capability": "wheel_mount",
                        "side": side, "symmetry_group": "wheels", "capacity": 8,
                        "span": 2.18, "min_spacing": 0.06, "default_policy": "linear",
                        "allowed_policies": ["linear"], "allow_scale_to_fit": True,
                        "min_scale": 0.7, "max_scale": 1.0,
                        "center": [x, 0.32, 0], "direction": list(direction),
                        "up": [0, 1, 0], "axis": [0, 0, 1]})
    return write_plugin(root, plugin_id="mesh_vehicle", components=[{
        "id": "mesh_vehicle:body", "mesh": "../meshes/body.glb",
        "description": "Vehicle body with procedural wheel attachments",
        "role": "vehicle", "tags": ["vehicle", "body"], "provides": ["vehicle"],
        "mounts": mounts, "sockets": sockets, "children": children,
        "layout_regions": regions,
    }], meshes={"body.glb": box_mesh((1.3, 0.65, 2.3))})


def box_along_x(size=(1.0, 0.3, 0.3)) -> trimesh.Trimesh:
    """A closed twelve-triangle mesh growing from the origin along +X."""
    mesh = trimesh.creation.box(extents=size)
    mesh.apply_translation((size[0] / 2.0, 0.0, 0.0))
    return mesh


def write_variable_plugin(root: Path, *, plugin_id="mesh_variable") -> Path:
    """[V5] Mesh-backed components whose parameters carry semantic meaning.

    Two kinds of declared parameter, which are the two strategies the loader
    accepts:

    * ``head`` declares transform scales that also declare a ``semantic_role``,
      so an installed semantic trait reaches an imported mesh through the
      ordinary rule machinery;
    * ``tail`` declares ``curvature``, which drives the installed ``fx:bend``
      through the ordinary effect pipeline instead of scaling anything.
    """
    base_y = socket_data("base", (0, 0, 0), (0, -1, 0))
    base_x = socket_data("base", (0, 0, 0), (-1, 0, 0), up=(0, 1, 0))
    components = [
        {"id": "%s:head" % plugin_id, "name": "Variable head",
         "description": "An imported head whose width, height and scale are declared",
         "mesh": "../meshes/head.glb", "role": "head",
         "tags": ["head", "humanoid"], "provides": ["head_mount"],
         "sockets": [base_y,
                     socket_data("tip", (0, 0.4, 0), capabilities=("crest_mount",))],
         "params": {
             "width": {"default": 1.0, "min": 0.2, "max": 3.0,
                       "transform": "scale_x", "semantic_role": "width"},
             "height": {"default": 1.0, "min": 0.2, "max": 3.0,
                        "transform": "scale_y", "semantic_role": "height"},
             "size": {"default": 1.0, "min": 0.2, "max": 3.0,
                      "transform": "uniform_scale", "semantic_role": "scale"}},
         "frame": {"growth_axis": "+Y", "front": "+Z", "up": "+Y"}},
        {"id": "%s:tail" % plugin_id, "name": "Variable tail",
         "description": "An imported tail whose curvature drives an installed effect",
         "mesh": "../meshes/tail.glb", "role": "tail", "tags": ["tail"],
         "provides": ["tail_mount", "crest_mount"],
         "sockets": [base_x,
                     socket_data("tip", (1.0, 0, 0), (1, 0, 0), up=(0, 1, 0),
                                 capabilities=("anchor",)),
                     # esattamente su un vertice del blocco: serve a misurare
                     # che vertici e innesti si muovono con la stessa mappa
                     socket_data("corner", (1.0, 0.15, 0.15), (1, 0, 0),
                                 up=(0, 1, 0), capabilities=("probe",))],
         "params": {
             "length": {"default": 1.0, "min": 0.2, "max": 3.0,
                        "transform": "scale_x", "semantic_role": "length"},
             "curvature": {"default": 0.0, "min": -1.0, "max": 1.0,
                           "semantic_role": "curvature",
                           "effect": {"type": "fx:bend", "parameter": "amount",
                                      "scope": "part", "neutral": 0.0}}},
         "frame": {"growth_axis": "+X", "front": "+Z", "up": "+Y"}},
        {"id": "%s:host" % plugin_id, "description": "A body that accepts both",
         "mesh": "../meshes/body.glb", "role": "body", "tags": ["body"],
         "provides": ["core_mount"],
         "mounts": [{"capability": "head_mount", "socket_id": "head"},
                    {"capability": "tail_mount", "socket_id": "tail"}],
         "sockets": [base_y,
                     socket_data("head", (0, 1, 0), capabilities=("head_mount",)),
                     socket_data("tail", (0, 0, -0.2), (0, 0, -1), up=(0, 1, 0),
                                 capabilities=("tail_mount",))],
         "frame": {"growth_axis": "+Y", "front": "+Z", "up": "+Y"}},
    ]
    return write_plugin(root, plugin_id=plugin_id, components=components,
                        meshes={"head.glb": box_mesh((0.3, 0.4, 0.25)),
                                "tail.glb": box_along_x(),
                                "body.glb": box_mesh()})
