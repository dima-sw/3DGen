"""Deliberately authored low-poly tree.

The tree is a small semantic graph with geometry local to this plugin.  The
trunk and visible major branches are geometry-bearing components, while the
few crown lobes remain submeshes of one crown component.  This keeps the
composition readable without turning every leaf-like mass into a node.
"""
from __future__ import annotations

from math import cos, radians

import numpy as np
import trimesh

from app.core.authoring import base_socket, tip_socket
from app.core.capability import Capability, Requirement, mount
from app.core.component import Attachment, Component, Piece
from app.core.params import DISTANCE, RATIO, ParamSpec
from app.core.socket import socket
from app.geometry.kernel import faces_per_normal, grow, ring, sweep


SIDES = 6


def _empty() -> trimesh.Trimesh:
    return trimesh.Trimesh(process=False)


def _mesh(vertices, faces) -> trimesh.Trimesh:
    mesh = trimesh.Trimesh(vertices=np.asarray(vertices, dtype=float),
                           faces=np.asarray(faces, dtype=np.int64),
                           process=False)
    mesh.merge_vertices()
    mesh.remove_unreferenced_vertices()
    mesh.fix_normals()
    return mesh


def _join(*meshes: trimesh.Trimesh) -> trimesh.Trimesh:
    valid = [mesh for mesh in meshes if mesh is not None and len(mesh.faces)]
    if not valid:
        return _empty()
    mesh = trimesh.util.concatenate(valid)
    mesh.process(validate=False)
    mesh.fix_normals()
    return mesh


def _rotate_y(vector: tuple[float, float, float], angle: float) -> tuple[float, float, float]:
    x, y, z = vector
    turn = radians(angle)
    return (x * cos(turn) + z * sin(turn), y, -x * sin(turn) + z * cos(turn))


def _trunk_mesh(height: float, width: float, taper: float, lean: float,
                asymmetry: float, detail: int) -> tuple[trimesh.Trimesh, int, int]:
    """Few broad trunk stations, with a deterministic lean and base flare."""
    rings = []
    stations = (0.0, 0.22, 0.52, 0.82, 1.0)
    for index, fraction in enumerate(stations):
        radius = width * (1.18 - 0.72 * taper * fraction)
        radius_x = radius * (1.05 + asymmetry * 0.07 * (1.0 - fraction))
        radius_z = radius * (0.86 - asymmetry * 0.04 * fraction)
        centre = (lean * height * fraction,
                  height * fraction,
                  asymmetry * width * (0.10 * fraction))
        rings.append(ring(SIDES, centre[1], radius_x, radius_z,
                          centre=(centre[0], 0.0, centre[2]),
                          twist=0.0, squash=0.78))
    primary = sweep(rings, cap_start=True, cap_end=True)

    secondary = _empty()
    if detail >= 2:
        # Three planar wedges make the base flare legible without pretending
        # to be a botanical root system.
        flares = []
        for angle, length_scale, width_scale in (
                (-28.0, 2.00, 0.78), (22.0, 1.75, 0.70),
                (154.0, 1.45, 0.62)):
            length = width * length_scale
            half = width * width_scale * 0.42
            vertices = [
                (0.0, 0.02, -half), (0.0, 0.02, half),
                (0.0, width * 0.38, half * 0.62),
                (0.0, width * 0.38, -half * 0.62),
                (length, 0.02, -half * 0.25), (length, 0.02, half * 0.25),
            ]
            faces = [(0, 1, 2), (0, 2, 3), (4, 5, 2), (4, 2, 3),
                     (0, 4, 3), (1, 2, 5), (0, 1, 5), (0, 5, 4)]
            flare = _mesh(vertices, faces)
            flare.apply_transform(trimesh.transformations.rotation_matrix(
                radians(angle), (0.0, 1.0, 0.0)))
            flares.append(flare)
        secondary = _join(*flares)
    return _join(primary, secondary), len(primary.faces), len(secondary.faces)


def _branch_mesh(length: float, radius: float, rise: float, depth: float,
                 asymmetry: float) -> trimesh.Trimesh:
    mesh = grow([(0.0, radius * 1.22), (0.30, radius * 1.05),
                 (0.68, radius * 0.66), (1.0, radius * 0.24)],
                sides=5, length=length, axis=0, squash=0.80, flat=0.78)
    mesh.apply_transform(trimesh.transformations.rotation_matrix(
        radians(rise), (0.0, 0.0, 1.0)))
    mesh.apply_transform(trimesh.transformations.rotation_matrix(
        radians(depth + asymmetry * 4.0), (0.0, 1.0, 0.0)))
    return mesh


def _lobe_mesh(width: float, height: float, depth: float, skew: float,
               offset_x: float, offset_z: float) -> trimesh.Trimesh:
    rings = []
    for fraction, scale in ((0.0, 0.40), (0.28, 0.92), (0.66, 1.0), (1.0, 0.30)):
        y = fraction * height
        x = offset_x + skew * height * (fraction - 0.35)
        z = offset_z
        rings.append(ring(SIDES, y, width * scale, depth * scale,
                          centre=(x, 0.0, z), twist=0.0,
                          squash=0.74))
    return sweep(rings, cap_start=True, cap_end=True)


def _fruit_mesh(radius: float) -> trimesh.Trimesh:
    return grow([(0.0, radius), (0.55, radius * 0.92), (1.0, radius * 0.38)],
                sides=5, length=radius * 1.35, axis=1, squash=0.70,
                flat=0.86)


TREE_PARAMS = {
    "height": ParamSpec(3.20, DISTANCE, min=1.60, max=6.00,
                         semantic_role="length"),
    "trunk_width": ParamSpec(0.46, DISTANCE, min=0.22, max=1.10,
                              semantic_role="girth"),
    "trunk_taper": ParamSpec(0.72, RATIO, min=0.35, max=0.95,
                              semantic_role="ratio"),
    "crown_width": ParamSpec(2.55, DISTANCE, min=1.10, max=5.00,
                              semantic_role="length"),
    "crown_height": ParamSpec(1.70, DISTANCE, min=0.80, max=3.50,
                               semantic_role="length"),
    "branch_spread": ParamSpec(1.00, RATIO, min=0.65, max=1.35,
                                semantic_role="ratio"),
    "asymmetry": ParamSpec(0.72, RATIO, min=0.00, max=1.00,
                            semantic_role="ratio"),
    "lean": ParamSpec(0.10, RATIO, min=-0.28, max=0.28,
                       semantic_role="ratio"),
}


def _trunk_height(v: dict) -> float:
    """Reserve the upper fifth of the requested height for the crown mount."""
    return v["height"] * 0.80


def _crown_height(v: dict) -> float:
    """Keep the dominant lobe inside the requested overall height."""
    return min(v["crown_height"], v["height"] * 0.43)


def _tree(v, ctx) -> Piece:
    return Piece(mesh=None, material="wood", tags=("tree", "nature", "stylized"),
                 sockets={
                     "base": base_socket(v["trunk_width"] * 1.45, axis="+Y"),
                     "trunk_mount": socket("trunk_mount", (0.0, 0.0, 0.0),
                                            (0.0, 1.0, 0.0),
                                            up=(0.0, 0.0, 1.0),
                                            radius=v["trunk_width"],
                                            provides="core_mount"),
                 }, metadata={"subject": "tree"})


def _tree_children(v, ctx):
    return [Attachment(id="trunk", component="trunk", level=1, insert=0.0,
                       requirement=Requirement(capability="core_mount"),
                       params=v)]


def _trunk(v, ctx) -> Piece:
    trunk_height = _trunk_height(v)
    mesh, primary_faces, secondary_faces = _trunk_mesh(
        trunk_height, v["trunk_width"], v["trunk_taper"], v["lean"],
        v["asymmetry"], ctx.detail_level)
    height = trunk_height
    width = v["trunk_width"]
    crown_base = v["height"] - _crown_height(v) * 0.72
    lean_x = v["lean"] * height
    branch_y = height * 0.48
    branch_radius = width * 0.40
    return Piece(mesh=mesh, material="wood", tags=("trunk", "tree", "primary"),
                 sockets={
                     "base": base_socket(width * 1.20, axis="+Y"),
                     "branch_l": socket("branch_l", (lean_x * 0.20, branch_y,
                                                       width * 0.02),
                                         (-0.72, 0.48, 0.12),
                                         up=(0.0, 1.0, 0.0), radius=branch_radius,
                                         provides="branch_mount", side="l",
                                         tags=("major", "left")),
                     "branch_r": socket("branch_r", (lean_x * 0.28, branch_y * 1.04,
                                                       -width * 0.03),
                                         (0.72, 0.50, -0.16),
                                         up=(0.0, 1.0, 0.0), radius=branch_radius,
                                         provides="branch_mount", side="r",
                                         tags=("major", "right")),
                     "branch_upper": socket("branch_upper", (lean_x * 0.52,
                                                               height * 0.72, 0.0),
                                             (0.90, 0.25, 0.12),
                                             up=(0.0, 1.0, 0.0),
                                             radius=width * 0.31,
                                             provides="branch_mount", side="top",
                                             tags=("major", "upper")),
                     "branch_rear": socket("branch_rear", (lean_x * 0.34,
                                                             height * 0.38,
                                                             -width * 0.18),
                                           (-0.10, 0.40, -0.82),
                                           up=(0.0, 1.0, 0.0),
                                           radius=width * 0.27,
                                           provides="branch_mount", side="back",
                                           tags=("secondary", "rear")),
                     "crown": socket("crown", (lean_x * 0.70, crown_base, 0.0),
                                      (0.0, 1.0, 0.0), up=(0.0, 0.0, 1.0),
                                      radius=v["crown_width"] * 0.28,
                                      provides="crown_mount"),
                 }, metadata={
                     "faces_per_normal": faces_per_normal(mesh),
                     "hierarchy_triangles": {
                         "primary": primary_faces,
                         "secondary": secondary_faces,
                         "accents": 0,
                     },
                 })


def _trunk_children(v, ctx):
    spread = v["branch_spread"]
    common = {"length": v["crown_width"] * 0.52 * spread,
              "radius": v["trunk_width"] * 0.30,
              "asymmetry": v["asymmetry"]}
    children = [
        Attachment(id="branch_l", component="branch", level=1, insert=0.18,
                   requirement=Requirement(capability="branch_mount", side="l",
                                           tags=("major",)),
                   params={**common, "rise": 12.0, "depth": 4.0, "accent": 1.0}),
        Attachment(id="branch_r", component="branch", level=1, insert=0.18,
                   requirement=Requirement(capability="branch_mount", side="r",
                                           tags=("major",)),
                   params={**common, "rise": 20.0, "depth": -7.0}),
        Attachment(id="branch_upper", component="branch", level=1, insert=0.15,
                   requirement=Requirement(capability="branch_mount", side="top",
                                           tags=("major",)),
                   params={**common, "length": v["crown_width"] * 0.34 * spread,
                           "radius": v["trunk_width"] * 0.23,
                           "rise": 34.0, "depth": 8.0}),
        Attachment(id="crown", component="crown", level=1, insert=0.08,
                   requirement=Requirement(capability="crown_mount"), params=v),
    ]
    if ctx.detail_level >= 2:
        children.append(Attachment(
            id="branch_rear", component="branch", level=2, insert=0.16,
            requirement=Requirement(capability="branch_mount", side="back",
                                    tags=("secondary",)),
            params={**common, "length": v["crown_width"] * 0.30 * spread,
                    "radius": v["trunk_width"] * 0.14,
                    "rise": 28.0, "depth": -18.0}))
    return children


def _branch(v, ctx) -> Piece:
    mesh = _branch_mesh(v["length"], v["radius"], v["rise"], v["depth"],
                        v["asymmetry"])
    return Piece(mesh=mesh, material="wood", tags=("branch", "tree", "visible"),
                 sockets={
                     "base": base_socket(v["radius"] * 1.15, axis="+X"),
                     "tip": tip_socket(v["length"], v["radius"] * 0.35,
                                        axis="+X", provides="branch_mount",
                                        tags=("tip", "branch")),
                 }, metadata={
                     "faces_per_normal": faces_per_normal(mesh),
                     "hierarchy_triangles": {
                         "primary": len(mesh.faces),
                         "secondary": 0,
                         "accents": 0,
                     },
                 })


def _branch_children(v, ctx):
    if ctx.detail_level < 3 or not v.get("accent", 0.0):
        return []
    return [Attachment(id="fruit", component="fruit", level=3, insert=0.05,
                       requirement=Requirement(capability="branch_mount",
                                               tags=("tip",)),
                       params={"radius": v["radius"] * 1.80})]


def _crown(v, ctx) -> Piece:
    width = v["crown_width"]
    height = _crown_height(v)
    asym = v["asymmetry"]
    lobes = [
        ("dominant", width * 0.52, height * 0.72, width * 0.30,
         0.10 + asym * 0.08, 0.05, 0.02, "leaf"),
        ("medium_left", width * 0.38, height * 0.54, width * 0.25,
         -0.18, -width * 0.42, width * 0.24, "leaf"),
        ("medium_right", width * 0.34, height * 0.50, width * 0.23,
         0.28 + asym * 0.08, width * 0.48, -width * 0.18, "leaf"),
    ]
    if ctx.detail_level >= 2:
        lobes.append(("rear_support", width * 0.29, height * 0.42,
                      width * 0.21, -0.08, width * 0.06, -width * 0.30,
                      "tree_leaf_shadow"))
    meshes = [_lobe_mesh(w, h, d, skew, x, z)
              for _, w, h, d, skew, x, z, _ in lobes]
    mesh = _join(*meshes)
    lobe_triangles = {name: len(part.faces) for (name, *_), part in zip(lobes, meshes)}
    primary_names = {"dominant", "medium_left", "medium_right"}
    primary_faces = sum(count for name, count in lobe_triangles.items()
                        if name in primary_names)
    secondary_faces = sum(count for name, count in lobe_triangles.items()
                          if name not in primary_names)
    return Piece(mesh=mesh, material="leaf", tags=("crown", "foliage", "tree"),
                 sockets={
                     "base": base_socket(width * 0.27, axis="+Y"),
                     "accent_anchor": socket("accent_anchor",
                                              (width * 0.10, height * 0.72, 0.0),
                                              (0.0, 1.0, 0.0),
                                              up=(0.0, 0.0, 1.0), radius=width * 0.12,
                                              provides="anchor", tags=("crown",)),
                 }, metadata={
                     "faces_per_normal": faces_per_normal(mesh),
                     "hierarchy_triangles": {
                         "primary": primary_faces,
                         "secondary": secondary_faces,
                         "accents": 0,
                     },
                     "crown_lobes": lobe_triangles,
                     "crown_lobe_count": len(lobes),
                 })


def _fruit(v, ctx) -> Piece:
    mesh = _fruit_mesh(v["radius"])
    return Piece(mesh=mesh, material="tree_accent", tags=("fruit", "accent", "tree"),
                 sockets={"base": base_socket(v["radius"] * 0.80, axis="+Y")},
                 metadata={
                     "faces_per_normal": faces_per_normal(mesh),
                     "hierarchy_triangles": {
                         "primary": 0,
                         "secondary": 0,
                         "accents": len(mesh.faces),
                     },
                 })


TRUNK = Component(
    id="trunk", build=_trunk, children=_trunk_children, params=TREE_PARAMS,
    provides=(Capability("core_mount"),),
    mounts=(mount("branch_mount", socket_id="branch_l", side="l",
                  tags=("major", "left")),
            mount("branch_mount", socket_id="branch_r", side="r",
                  tags=("major", "right")),
            mount("branch_mount", socket_id="branch_upper", side="top",
                  tags=("major", "upper")),
            mount("branch_mount", socket_id="branch_rear", side="back",
                  tags=("secondary", "rear")),
            mount("crown_mount", socket_id="crown")),
    role="tree_trunk", material="wood",
    tags=frozenset({"tree", "trunk", "wood", "low_poly"}))

BRANCH = Component(
    id="branch", build=_branch, children=_branch_children,
    params={"length": ParamSpec(1.0, DISTANCE, min=0.25, max=4.0,
                                  semantic_role="length"),
            "radius": ParamSpec(0.12, DISTANCE, min=0.035, max=0.50,
                                 semantic_role="girth"),
            "rise": ParamSpec(15.0, DISTANCE, min=-35.0, max=65.0),
            "depth": ParamSpec(0.0, DISTANCE, min=-45.0, max=45.0),
            "asymmetry": ParamSpec(0.0, RATIO, min=0.0, max=1.0),
            "accent": ParamSpec(0.0, RATIO, min=0.0, max=1.0)},
    provides=(Capability("branch_mount"),),
    mounts=(mount("branch_mount", socket_id="tip", tags=("tip", "branch"),
                  capacity=0),),
    role="tree_branch", material="wood",
    tags=frozenset({"tree", "branch", "major", "low_poly"}))

CROWN = Component(
    id="crown", build=_crown, params=TREE_PARAMS,
    provides=(Capability("crown_mount"),),
    mounts=(mount("anchor", socket_id="accent_anchor", tags=("crown",),
                  capacity=0),),
    role="tree_crown", material="leaf",
    tags=frozenset({"tree", "crown", "foliage", "low_poly"}))

FRUIT = Component(
    id="fruit", build=_fruit,
    params={"radius": ParamSpec(0.10, DISTANCE, min=0.035, max=0.40,
                                 semantic_role="girth")},
    provides=(Capability("branch_mount"),), role="tree_accent",
    material="tree_accent", tags=frozenset({"tree", "fruit", "accent"}))

TREE = Component(
    id="tree", build=_tree, children=_tree_children, params=TREE_PARAMS,
    provides=(Capability("building"),),
    mounts=(mount("surface", socket_id="base", side="bottom"),
            mount("core_mount", socket_id="trunk_mount")),
    role="tree", material="wood",
    description="a chunky asymmetric stylized tree with visible branches",
    tags=frozenset({"tree", "nature", "low_poly", "stylized", "benchmark"}))
