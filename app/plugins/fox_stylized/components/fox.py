"""Deliberately authored low-poly fox.

The geometry is local to this plugin.  It uses the existing kernel for a few
faceted volumes, and hand-authored planar helpers where the silhouette is the
design decision.  The graph stays semantic: paws, cheek planes and muzzle
planes are submeshes, not extra components.
"""
from __future__ import annotations

from typing import Iterable

import numpy as np
import trimesh

from app.core.authoring import base_socket
from app.core.capability import Capability, Requirement, mount
from app.core.component import Attachment, Component, Piece
from app.core.layout import LayoutRegion
from app.core.params import DISTANCE, RATIO, STRING, ParamSpec
from app.core.socket import socket
from app.geometry.kernel import block, faces_per_normal, grow, ring, sweep


SIDES = 6


def _triangulate(quads: Iterable[tuple[int, int, int, int]]) -> list[tuple[int, int, int]]:
    faces: list[tuple[int, int, int]] = []
    for a, b, c, d in quads:
        faces.extend(((a, b, c), (a, c, d)))
    return faces


def _mesh(vertices, faces) -> trimesh.Trimesh:
    mesh = trimesh.Trimesh(vertices=np.asarray(vertices, dtype=float),
                           faces=np.asarray(faces, dtype=np.int64),
                           process=False)
    mesh.merge_vertices()
    mesh.remove_unreferenced_vertices()
    mesh.fix_normals()
    return mesh


def _join(*meshes: trimesh.Trimesh) -> trimesh.Trimesh:
    valid = [m for m in meshes if m is not None and len(m.faces)]
    if not valid:
        return trimesh.Trimesh(process=False)
    mesh = trimesh.util.concatenate(valid)
    mesh.process(validate=False)
    mesh.fix_normals()
    return mesh


def _box(size: tuple[float, float, float], center: tuple[float, float, float],
         axis: int = 1, taper: float = 1.0) -> trimesh.Trimesh:
    mesh = block(size, sides=4, squash=1.0, taper=taper, axis=axis)
    mesh.apply_translation(center)
    return mesh


def _sectioned_body(body_length: float, torso_height: float, leg_length: float,
                    chunkiness: float) -> trimesh.Trimesh:
    """A small number of rectangular stations, with a lifted belly line."""
    half_z = body_length * 0.50
    width = torso_height * (0.42 + 0.09 * chunkiness)
    stations = [
        (-half_z, width * 0.78, leg_length + torso_height * 0.18,
         leg_length + torso_height * 0.82),
        (-body_length * 0.27, width * 0.98, leg_length + torso_height * 0.10,
         leg_length + torso_height * 0.96),
        (body_length * 0.12, width * 1.08, leg_length + torso_height * 0.08,
         leg_length + torso_height * 1.00),
        (half_z, width * 0.88, leg_length + torso_height * 0.16,
         leg_length + torso_height * 0.86),
    ]
    vertices = []
    for z, half_x, bottom, top in stations:
        vertices.extend(((-half_x, bottom, z), (half_x, bottom, z),
                         (half_x, top, z), (-half_x, top, z)))
    quads: list[tuple[int, int, int, int]] = []
    for i in range(len(stations) - 1):
        a, b = i * 4, (i + 1) * 4
        quads.extend(((a, b, b + 1, a + 1),
                      (a + 1, b + 1, b + 2, a + 2),
                      (a + 2, b + 2, b + 3, a + 3),
                      (a + 3, b + 3, b, a)))
    quads.extend(((0, 1, 2, 3), (12, 15, 14, 13)))
    return _mesh(vertices, _triangulate(quads))


def _wedge_z(z0: float, z1: float, base_width: float, base_bottom: float,
             base_top: float, tip_width: float, tip_bottom: float,
             tip_top: float) -> trimesh.Trimesh:
    """A tapered rectangular wedge with designed planes along +Z."""
    vertices = [
        (-base_width, base_bottom, z0), (base_width, base_bottom, z0),
        (base_width, base_top, z0), (-base_width, base_top, z0),
        (-tip_width, tip_bottom, z1), (tip_width, tip_bottom, z1),
        (tip_width, tip_top, z1), (-tip_width, tip_top, z1),
    ]
    quads = [(0, 1, 2, 3), (4, 7, 6, 5),
             (0, 4, 5, 1), (1, 5, 6, 2),
             (2, 6, 7, 3), (3, 7, 4, 0)]
    return _mesh(vertices, _triangulate(quads))


def _triangular_prism(center_x: float, base_width: float, height: float,
                      depth: float) -> trimesh.Trimesh:
    """One triangular ear with a triangle in both front and side silhouette."""
    x0, x1 = center_x - depth * 0.5, center_x + depth * 0.5
    vertices = [
        (x0, 0.0, -base_width * 0.5),
        (x0, 0.0, base_width * 0.5),
        (x0, height, 0.0),
        (x1, 0.0, -base_width * 0.5),
        (x1, 0.0, base_width * 0.5),
        (x1, height, 0.0),
    ]
    faces = [(0, 1, 2), (5, 4, 3), (0, 3, 4), (0, 4, 1),
             (1, 4, 5), (1, 5, 2), (2, 5, 3), (2, 3, 0)]
    return _mesh(vertices, faces)


def _rectangular_stations(length: float, widths: list[float], depths: list[float],
                          centres: list[float]) -> trimesh.Trimesh:
    """Tapered four-sided leg stations, not a sampled cylinder."""
    levels = np.linspace(0.0, length, len(widths))
    vertices = []
    for y, width, depth, centre in zip(levels, widths, depths, centres):
        vertices.extend(((-width, y, centre - depth),
                         (width, y, centre - depth),
                         (width, y, centre + depth),
                         (-width, y, centre + depth)))
    quads: list[tuple[int, int, int, int]] = []
    for i in range(len(widths) - 1):
        a, b = i * 4, (i + 1) * 4
        quads.extend(((a, b, b + 1, a + 1),
                      (a + 1, b + 1, b + 2, a + 2),
                      (a + 2, b + 2, b + 3, a + 3),
                      (a + 3, b + 3, b, a)))
    quads.extend(((0, 3, 2, 1),
                   ((len(widths) - 1) * 4,
                    (len(widths) - 1) * 4 + 1,
                    (len(widths) - 1) * 4 + 2,
                    (len(widths) - 1) * 4 + 3)))
    return _mesh(vertices, _triangulate(quads))


def _tail_plume(length: float, volume: float, torso_height: float,
                detail: int) -> trimesh.Trimesh:
    """Bent, broad-middle plume with non-uniform stations."""
    count = 6 if detail >= 2 else 4
    fractions = np.linspace(0.0, 1.0, count)
    radii = [volume * torso_height * value for value in
             (0.52, 0.68, 0.62, 0.48, 0.30, 0.10)[:count]]
    rings = []
    for fraction, radius in zip(fractions, radii):
        x = fraction * length
        lift = torso_height * (0.03 + 0.22 * fraction + 0.035 * np.sin(fraction * np.pi))
        # ring() is authored in X/Z around a Y station. Swap its axes so the
        # plume grows along +X with a real Y/Z cross-section.
        current = ring(6, x, radius * 0.72, radius, squash=0.82)
        current[:, [0, 1]] = current[:, [1, 0]]
        current[:, 1] += lift
        rings.append(current)
    return sweep(rings, cap_start=True, cap_end=True)


FOX_PARAMS = {
    "body_length": ParamSpec(1.00, DISTANCE, min=0.72, max=1.45,
                              semantic_role="length"),
    "torso_height": ParamSpec(0.52, DISTANCE, min=0.36, max=0.78,
                               semantic_role="girth"),
    "head_size": ParamSpec(0.46, DISTANCE, min=0.34, max=0.66,
                            semantic_role="girth"),
    "leg_length": ParamSpec(0.72, DISTANCE, min=0.48, max=1.05,
                             semantic_role="length"),
    "tail_length": ParamSpec(1.05, DISTANCE, min=0.72, max=1.55,
                              semantic_role="length"),
    "tail_volume": ParamSpec(1.00, RATIO, min=0.72, max=1.38,
                              semantic_role="girth"),
    "ear_size": ParamSpec(1.00, RATIO, min=0.78, max=1.36,
                           semantic_role="length"),
    "muzzle_length": ParamSpec(0.42, DISTANCE, min=0.28, max=0.62,
                                semantic_role="length"),
    "chunkiness": ParamSpec(0.90, RATIO, min=0.72, max=1.18,
                             semantic_role="girth"),
}


def _root(v, ctx) -> Piece:
    return Piece(mesh=None, material="fox_orange", tags=("fox", "animal"),
                 sockets={
                     "base": base_socket(0.22, axis="+Y"),
                     "body_mount": socket("body_mount", (0.0, 0.0, 0.0),
                                          (0.0, 1.0, 0.0), up=(0.0, 0.0, 1.0),
                                          radius=v["torso_height"] * 0.50,
                                          provides="core_mount"),
                 })


def _root_children(v, ctx):
    return [Attachment(id="body", component="body", level=1, insert=0.0,
                       requirement=Requirement(capability="core_mount"),
                       params=v)]


def _body(v, ctx) -> Piece:
    primary = _sectioned_body(v["body_length"], v["torso_height"],
                              v["leg_length"], v["chunkiness"])
    secondary = trimesh.Trimesh(process=False)
    if ctx.detail_level >= 2:
        width = v["torso_height"] * (0.42 + 0.09 * v["chunkiness"])
        chest = _box((width * 1.35, v["torso_height"] * 0.42,
                      v["body_length"] * 0.34),
                     (0.0, v["leg_length"] + v["torso_height"] * 0.66,
                      v["body_length"] * 0.27), axis=1, taper=0.82)
        hip = _box((width * 1.12, v["torso_height"] * 0.34,
                    v["body_length"] * 0.27),
                   (0.0, v["leg_length"] + v["torso_height"] * 0.52,
                    -v["body_length"] * 0.30), axis=1, taper=0.78)
        neck = _wedge_z(v["body_length"] * 0.08,
                        v["body_length"] * 0.30,
                        width * 0.62, v["leg_length"] + v["torso_height"] * 0.62,
                        v["leg_length"] + v["torso_height"] * 1.02,
                        width * 0.40, v["leg_length"] + v["torso_height"] * 0.72,
                        v["leg_length"] + v["torso_height"] * 0.94)
        secondary = _join(chest, hip, neck)
    mesh = _join(primary, secondary)
    body_len, torso, legs = v["body_length"], v["torso_height"], v["leg_length"]
    width = torso * (0.42 + 0.09 * v["chunkiness"])
    leg_x = width * 0.70
    front_z, rear_z = body_len * 0.28, -body_len * 0.28
    top_y = legs + torso * 0.88
    return Piece(mesh=mesh, material="fox_orange", tags=("body", "torso", "fox"),
                 sockets={
                     "base": base_socket(width * 0.65, axis="+Y"),
                     "head": socket("head", (0.0, top_y, body_len * 0.22),
                                    (0.0, 1.0, 0.0), up=(0.0, 0.0, 1.0),
                                    radius=v["head_size"] * 0.45,
                                    provides="head_mount"),
                     "front_l": socket("front_l", (-leg_x, legs, front_z),
                                        (0.0, -1.0, 0.0), up=(0.0, 0.0, 1.0),
                                        radius=width * 0.35, provides="limb_mount",
                                        side="l", tags=("front",)),
                     "front_r": socket("front_r", (leg_x, legs, front_z),
                                        (0.0, -1.0, 0.0), up=(0.0, 0.0, 1.0),
                                        radius=width * 0.35, provides="limb_mount",
                                        side="r", tags=("front",)),
                     "rear_l": socket("rear_l", (-leg_x * 0.92, legs, rear_z),
                                       (0.0, -1.0, 0.0), up=(0.0, 0.0, 1.0),
                                       radius=width * 0.38, provides="limb_mount",
                                       side="l", tags=("rear",)),
                     "rear_r": socket("rear_r", (leg_x * 0.92, legs, rear_z),
                                       (0.0, -1.0, 0.0), up=(0.0, 0.0, 1.0),
                                       radius=width * 0.38, provides="limb_mount",
                                       side="r", tags=("rear",)),
                     "tail_socket": socket("tail_socket",
                                            (0.0, legs + torso * 0.55, -body_len * 0.48),
                                            (-0.18, 0.24, -0.95),
                                            up=(0.0, 1.0, 0.0),
                                            radius=torso * 0.38, tags=("tail",)),
                     "back": socket("back", (0.0, top_y * 0.96, -body_len * 0.08),
                                    (0.0, 1.0, 0.0), up=(0.0, 0.0, 1.0),
                                    radius=width * 0.38, provides="gear_mount",
                                    tags=("back", "gear")),
                 }, metadata={
                     "faces_per_normal": faces_per_normal(mesh),
                     "hierarchy_triangles": {
                         "primary": len(primary.faces),
                         "secondary": len(secondary.faces),
                         "accents": 0,
                     },
                 })


def _body_children(v, ctx):
    head_params = {"head_size": v["head_size"],
                   "ear_size": v["ear_size"],
                   "muzzle_length": v["muzzle_length"],
                   "chunkiness": v["chunkiness"]}
    leg_params = {"leg_length": v["leg_length"],
                  "torso_height": v["torso_height"],
                  "chunkiness": v["chunkiness"]}
    return [
        Attachment(id="head", component="head", level=1, insert=0.18,
                   requirement=Requirement(capability="head_mount"),
                   params=head_params),
        Attachment(id="front_l", component="leg", level=1, insert=0.20,
                   requirement=Requirement(capability="limb_mount", side="l",
                                           tags=("front",)), params=leg_params),
        Attachment(id="front_r", component="leg", level=1, insert=0.20,
                   requirement=Requirement(capability="limb_mount", side="r",
                                           tags=("front",)), params=leg_params),
        Attachment(id="rear_l", component="leg", level=1, insert=0.20,
                   requirement=Requirement(capability="limb_mount", side="l",
                                           tags=("rear",)),
                   params={**leg_params, "hind": 1.0}),
        Attachment(id="rear_r", component="leg", level=1, insert=0.20,
                   requirement=Requirement(capability="limb_mount", side="r",
                                           tags=("rear",)),
                   params={**leg_params, "hind": 1.0}),
        Attachment(id="tail", component="tail", level=1, insert=0.22,
                   requirement=Requirement(capability="limb_mount",
                                           tags=("tail",)),
                   params={"body_length": v["body_length"],
                           "torso_height": v["torso_height"],
                           "tail_length": v["tail_length"],
                           "tail_volume": v["tail_volume"],
                           "chunkiness": v["chunkiness"]}),
    ]


def _body_layout_regions(v, ctx):
    body_len = v["body_length"]
    torso = v["torso_height"]
    legs = v["leg_length"]
    return [
        LayoutRegion(
            id="rear_tail_region",
            anchor_socket="tail_socket",
            allows_role="tail",
            allows_tags=("tail",),
            default_policy="fan",
            allowed_policies=("fan",),
            capacity=12,
            spread_angle=140.0,
            min_spacing=torso * 0.08,
            min_scale=0.82,
            max_scale=1.05,
            allow_scale_to_fit=False,
            center=(0.0, legs + torso * 0.55, -body_len * 0.48),
            direction=(-0.18, 0.24, -0.95),
            up=(0.0, 1.0, 0.0),
            axis=(0.0, 1.0, 0.0),
            elevation_span=torso * 0.18,
            depth_offset=torso * 0.10,
        )
    ]


def _head(v, ctx) -> Piece:
    size = v["head_size"]
    muzzle = v["muzzle_length"]
    chunk = v["chunkiness"]
    cranial = grow([(0.0, size * 0.27), (0.24, size * 0.42),
                    (0.72, size * 0.46), (1.0, size * 0.32)],
                   sides=SIDES, length=size * 0.82, axis=1,
                   squash=0.80, flat=0.78)
    cheek = _wedge_z(size * 0.22, size * 0.54,
                     size * (0.34 + chunk * 0.04), size * 0.18,
                     size * 0.59, size * 0.10, size * 0.29, size * 0.46)
    primary = _join(cranial, cheek)
    secondary = trimesh.Trimesh(process=False)
    if ctx.detail_level >= 2:
        lower = _wedge_z(size * 0.44, size * 0.44 + muzzle * 0.92,
                         size * 0.23, size * 0.18,
                         size * 0.31, size * 0.08, size * 0.20,
                         size * 0.28)
        secondary = lower
    mesh = _join(primary, secondary)
    # The cheek surface at the eye band is the authored mounting plane.  The
    # previous value placed the socket inside the cranial volume.
    eye_z = size * 0.34
    eye_y = size * 0.51
    eye_x = size * 0.20
    eye_radius = size * 0.055
    muzzle_tip_z = size * 0.44 + muzzle * 0.92
    muzzle_tip_y = size * 0.24
    return Piece(mesh=mesh, material="fox_orange", tags=("head", "fox", "muzzle"),
                 sockets={
                     "base": base_socket(size * 0.35, axis="+Y"),
                     "ears": socket("ears", (0.0, size * 0.76, 0.0),
                                    (0.0, 1.0, 0.0), up=(0.0, 0.0, 1.0),
                                    radius=size * 0.28, provides="hair_mount"),
                     "eye_l": socket("eye_l", (-eye_x, eye_y, eye_z),
                                      (-0.18, 0.03, 1.0), up=(0.0, 1.0, 0.0),
                                      radius=eye_radius, provides="face_mount",
                                      side="l", tags=("eye", "accent")),
                     "eye_r": socket("eye_r", (eye_x, eye_y, eye_z),
                                      (0.18, 0.03, 1.0), up=(0.0, 1.0, 0.0),
                                      radius=eye_radius, provides="face_mount",
                                      side="r", tags=("eye", "accent")),
                     "nose": socket("nose", (0.0, muzzle_tip_y, muzzle_tip_z),
                                     (0.0, 0.0, 1.0), up=(0.0, 1.0, 0.0),
                                     radius=size * 0.075, provides="face_mount",
                                     tags=("nose", "accent")),
                 }, metadata={
                     "faces_per_normal": faces_per_normal(mesh),
                     "hierarchy_triangles": {
                         "primary": len(primary.faces),
                         "secondary": len(secondary.faces),
                         "accents": 0,
                     },
                 })


def _head_children(v, ctx):
    children = [
        Attachment(id="ears", component="ears", level=1, insert=0.10,
                   requirement=Requirement(capability="hair_mount"),
                   params={"head_size": v["head_size"],
                           "ear_size": v.get("ear_size", 1.0),
                           "chunkiness": v["chunkiness"]}),
    ]
    for side in ("l", "r"):
        children.append(Attachment(
            id="eye_" + side, component="face_accents", level=3, insert=0.25,
            requirement=Requirement(capability="face_mount", side=side,
                                    tags=("eye", "accent")),
            params={"head_size": v["head_size"],
                    "muzzle_length": v["muzzle_length"],
                    "part": "eye_" + side}))
    children.append(Attachment(
        id="nose", component="face_accents", level=3, insert=0.20,
        requirement=Requirement(capability="face_mount", tags=("nose", "accent")),
        params={"head_size": v["head_size"],
                "muzzle_length": v["muzzle_length"],
                "part": "nose"}))
    return children


def _ears(v, ctx) -> Piece:
    size = v["head_size"]
    scale = v["ear_size"]
    width = size * (0.34 + 0.03 * v["chunkiness"])
    height = size * 0.62 * scale
    left = _triangular_prism(-size * 0.27, width, height, size * 0.12)
    right = _triangular_prism(size * 0.27, width, height, size * 0.12)
    primary = _join(left, right)
    secondary = trimesh.Trimesh(process=False)
    if ctx.detail_level >= 2:
        bases = [_box((width * 0.72, height * 0.18, size * 0.14),
                      (-size * 0.27, height * 0.10, 0.0), axis=1, taper=0.76),
                 _box((width * 0.72, height * 0.18, size * 0.14),
                      (size * 0.27, height * 0.10, 0.0), axis=1, taper=0.76)]
        secondary = _join(*bases)
    mesh = _join(primary, secondary)
    return Piece(mesh=mesh, material="fox_orange", tags=("ears", "fox", "silhouette"),
                 sockets={
                     "base": base_socket(size * 0.28, axis="+Y"),
                     "inner_l": socket("inner_l", (-size * 0.27, height * 0.28, size * 0.07),
                                         (0.0, 1.0, 0.0), up=(0.0, 0.0, 1.0),
                                         radius=width * 0.35, provides="face_mount",
                                         side="l", tags=("inner_ear",)),
                     "inner_r": socket("inner_r", (size * 0.27, height * 0.28, size * 0.07),
                                         (0.0, 1.0, 0.0), up=(0.0, 0.0, 1.0),
                                         radius=width * 0.35, provides="face_mount",
                                         side="r", tags=("inner_ear",)),
                 }, metadata={
                     "faces_per_normal": faces_per_normal(mesh),
                     "hierarchy_triangles": {
                         "primary": len(primary.faces),
                         "secondary": len(secondary.faces),
                         "accents": 0,
                     },
                 })


def _inner_ear(v, ctx) -> Piece:
    size = v["head_size"]
    mesh = _triangular_prism(0.0, size * 0.14, size * 0.40,
                             size * 0.025)
    return Piece(mesh=mesh, material="fox_dark", tags=("inner_ear", "accent"),
                 sockets={"base": base_socket(size * 0.10, axis="+Y")})


def _legs(v, ctx) -> Piece:
    length = v["leg_length"]
    torso = v["torso_height"]
    chunk = v["chunkiness"]
    width = torso * (0.075 + 0.018 * chunk)
    depth = torso * (0.070 + 0.015 * chunk)
    hind = bool(v.get("hind", 0.0))
    centres = [0.0, -0.018 if hind else 0.018,
               -0.045 if hind else 0.028, -0.035 if hind else 0.018]
    primary = _rectangular_stations(length,
                                    [width * 1.05, width * 1.12,
                                     width * 0.80, width * 0.62],
                                    [depth * 1.12, depth, depth * 0.82, depth * 0.76],
                                    centres)
    secondary = trimesh.Trimesh(process=False)
    if ctx.detail_level >= 2:
        paw = _box((width * 2.5, length * 0.16, depth * 2.45),
                   (0.0, length * 0.08, -0.01), axis=1, taper=0.86)
        secondary = paw
    mesh = _join(primary, secondary)
    return Piece(mesh=mesh, material="fox_orange", tags=("leg", "limb", "fox"),
                 sockets={
                     "base": base_socket(max(width, depth) * 1.20, axis="+Y"),
                     "paw_anchor": socket("paw_anchor", (0.0, length * 0.12, 0.0),
                                           (0.0, 1.0, 0.0), up=(0.0, 0.0, 1.0),
                                           radius=width, provides="anchor"),
                 }, metadata={
                     "faces_per_normal": faces_per_normal(mesh),
                     "hierarchy_triangles": {
                         "primary": len(primary.faces),
                         "secondary": len(secondary.faces),
                         "accents": 0,
                     },
                 })


def _tail(v, ctx) -> Piece:
    length = v["tail_length"]
    volume = v["tail_volume"]
    torso = v["torso_height"]
    primary = _tail_plume(length, volume, torso, ctx.detail_level)
    secondary = trimesh.Trimesh(process=False)
    if ctx.detail_level >= 2:
        # A broad angular shoulder keeps the tail from reading as a cone.
        shoulder = _box((torso * volume * 1.05, torso * volume * 0.48,
                          torso * volume * 0.72),
                        (length * 0.18, torso * 0.07, 0.0), axis=0, taper=0.76)
        secondary = shoulder
    mesh = _join(primary, secondary)
    return Piece(mesh=mesh, material="fox_orange", tags=("tail", "plume", "fox"),
                 sockets={
                     "base": base_socket(torso * volume * 0.40, axis="+X"),
                     "tip": socket("tip", (length, torso * 0.28, 0.0),
                                   (1.0, 0.0, 0.0), up=(0.0, 1.0, 0.0),
                                   radius=torso * volume * 0.10,
                                   tags=("tail_tip",)),
                 }, metadata={
                     "faces_per_normal": faces_per_normal(mesh),
                     "hierarchy_triangles": {
                         "primary": len(primary.faces),
                         "secondary": len(secondary.faces),
                         "accents": 0,
                     },
                 })


def _tail_children(v, ctx):
    return [Attachment(id="tail_tip", component="tail_tip", level=3,
                       insert=0.15,
                       requirement=Requirement(capability="anchor",
                                               tags=("tail_tip",)),
                       params={"radius": v["torso_height"] * v["tail_volume"] * 0.11,
                               "length": v["torso_height"] * 0.30})]


def _face_accents(v, ctx) -> Piece:
    size = v["head_size"]
    muzzle = v["muzzle_length"]
    part = v.get("part", "nose")
    if part in ("eye_l", "eye_r"):
        eye_size = size * 0.075
        eye_depth = eye_size * 1.10
        mesh = _box((eye_size * 1.6, eye_size * 1.2, eye_depth),
                    (0.0, 0.0, eye_depth * 0.5), axis=2)
    else:
        nose_depth = muzzle * 0.18
        mesh = _box((size * 0.13, size * 0.11, nose_depth),
                    (0.0, 0.0, nose_depth * 0.5), axis=2, taper=0.65)
    material = "fox_eye" if part in ("eye_l", "eye_r") else "fox_dark"
    return Piece(mesh=mesh, material=material, tags=("face", part, "accent", "fox"),
                 sockets={"base": base_socket(size * 0.20, axis="+Z")},
                 metadata={"hierarchy_triangles": {
                     "primary": 0, "secondary": 0, "accents": len(mesh.faces)}})


def _tail_tip(v, ctx) -> Piece:
    mesh = _box((v["length"], v["radius"] * 1.6, v["radius"] * 1.7),
                (v["length"] * 0.5, 0.0, 0.0), axis=0, taper=0.52)
    return Piece(mesh=mesh, material="fox_cream", tags=("tail_tip", "accent"),
                 sockets={"base": base_socket(v["radius"] * 0.8, axis="+X")},
                 metadata={"hierarchy_triangles": {
                     "primary": 0, "secondary": 0, "accents": len(mesh.faces)}})


FOX = Component(
    id="fox", build=_root, children=_root_children, params=FOX_PARAMS,
    provides=(Capability("animal"),),
    mounts=(mount("core_mount", socket_id="body_mount"),),
    role="animal", material="fox_orange",
    description="a complete angular tapered elongated stylized low-poly fox",
    tags=frozenset({"animal", "fox", "volpe", "quadruped", "low_poly", "stylized"}))

BODY = Component(
    id="body", build=_body, children=_body_children, params=FOX_PARAMS,
    provides=(Capability("core_mount"),),
    mounts=(mount("head_mount", socket_id="head"),
            mount("limb_mount", socket_id="front_l", side="l", tags=("front",)),
            mount("limb_mount", socket_id="front_r", side="r", tags=("front",)),
            mount("limb_mount", socket_id="rear_l", side="l", tags=("rear",)),
            mount("limb_mount", socket_id="rear_r", side="r", tags=("rear",)),
            mount("limb_mount", socket_id="tail_socket", tags=("tail",),
                  capacity=0),
            mount("gear_mount", socket_id="back", tags=("back", "gear"))),
    role="torso", material="fox_orange", layout_regions=_body_layout_regions,
    description="the lifted angular torso of the fox with four stance sockets",
    tags=frozenset({"animal", "fox", "body", "torso", "quadruped"}))

HEAD = Component(
    id="head", build=_head, children=_head_children,
    params={"head_size": FOX_PARAMS["head_size"],
            "ear_size": FOX_PARAMS["ear_size"],
            "muzzle_length": FOX_PARAMS["muzzle_length"],
            "chunkiness": FOX_PARAMS["chunkiness"]},
    provides=(Capability("head_mount"),),
    mounts=(mount("hair_mount", socket_id="ears"),
            mount("face_mount", socket_id="eye_l", side="l",
                  tags=("eye", "accent")),
            mount("face_mount", socket_id="eye_r", side="r",
                  tags=("eye", "accent")),
            mount("face_mount", socket_id="nose", tags=("nose", "accent"))),
    role="head", material="fox_orange",
    description="a faceted fox head with a pointed integrated muzzle",
    tags=frozenset({"animal", "fox", "head", "muzzle", "pointed"}))

EARS = Component(
    id="ears", build=_ears, children=lambda v, ctx: [
        Attachment(id="inner_l", component="inner_ear", level=3, insert=0.10,
                   requirement=Requirement(capability="face_mount", side="l",
                                           tags=("inner_ear",)),
                   params={"head_size": v["head_size"]}),
        Attachment(id="inner_r", component="inner_ear", level=3, insert=0.10,
                   requirement=Requirement(capability="face_mount", side="r",
                                           tags=("inner_ear",)),
                   params={"head_size": v["head_size"]}),
    ],
    params={"head_size": FOX_PARAMS["head_size"],
            "ear_size": FOX_PARAMS["ear_size"],
            "chunkiness": FOX_PARAMS["chunkiness"]},
    provides=(Capability("hair_mount"), Capability("face_mount")),
    mounts=(mount("face_mount", socket_id="inner_l", side="l", tags=("inner_ear",)),
            mount("face_mount", socket_id="inner_r", side="r", tags=("inner_ear",))),
    role="ears", material="fox_orange",
    description="paired tall triangular planar ears",
    tags=frozenset({"animal", "fox", "ears", "silhouette"}))

LEG = Component(
    id="leg", build=_legs,
    params={"leg_length": FOX_PARAMS["leg_length"],
            "torso_height": FOX_PARAMS["torso_height"],
            "chunkiness": FOX_PARAMS["chunkiness"],
            "hind": ParamSpec(0.0, RATIO, min=0.0, max=1.0)},
    provides=(Capability("limb_mount"),),
    mounts=(mount("anchor", socket_id="paw_anchor"),),
    role="limb", material="fox_orange",
    description="a slender tapered four-sided fox leg with an optional planar paw",
    tags=frozenset({"animal", "fox", "leg", "limb", "stance"}))

TAIL = Component(
    id="tail", build=_tail, children=_tail_children,
    params={"body_length": FOX_PARAMS["body_length"],
            "torso_height": FOX_PARAMS["torso_height"],
            "tail_length": FOX_PARAMS["tail_length"],
            "tail_volume": FOX_PARAMS["tail_volume"],
            "layout_envelope": ParamSpec(0.22, DISTANCE, min=0.05, max=0.80,
                                          semantic_role="girth"),
            "chunkiness": FOX_PARAMS["chunkiness"]},
    provides=(Capability("limb_mount"),),
    mounts=(mount("anchor", socket_id="tip", tags=("tail_tip",)),),
    role="tail", material="fox_orange",
    description="a lifted broad-middle angular plume tail",
    tags=frozenset({"animal", "fox", "tail", "plume", "silhouette"}))

INNER_EAR = Component(
    id="inner_ear", build=_inner_ear,
    params={"head_size": FOX_PARAMS["head_size"]},
    provides=(Capability("face_mount"),), role="accent", material="fox_dark",
    tags=frozenset({"animal", "fox", "ear", "accent"}))

FACE_ACCENTS = Component(
    id="face_accents", build=_face_accents,
    params={"head_size": FOX_PARAMS["head_size"],
            "muzzle_length": FOX_PARAMS["muzzle_length"],
            "part": ParamSpec("nose", STRING,
                               choices=("eye_l", "eye_r", "nose"))},
    provides=(Capability("face_mount"),), role="accent", material="fox_dark",
    tags=frozenset({"animal", "fox", "face", "eyes", "nose", "accent"}))

TAIL_TIP = Component(
    id="tail_tip", build=_tail_tip,
    params={"radius": ParamSpec(0.05, DISTANCE, min=0.005, max=0.5,
                                 semantic_role="girth"),
            "length": ParamSpec(0.15, DISTANCE, min=0.01, max=1.0,
                                 semantic_role="length")},
    provides=(Capability("anchor"),), role="accent", material="fox_cream",
    tags=frozenset({"animal", "fox", "tail", "tip", "accent"}))
