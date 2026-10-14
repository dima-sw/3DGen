"""Stylized low-poly compact car.

The plugin keeps all vehicle-specific geometry local: no core primitive and no
kernel helper is added for wheel arches, panels or car bodies.
"""
from __future__ import annotations

import numpy as np
import trimesh

from app.core.authoring import base_socket
from app.core.capability import Capability, Requirement, mount
from app.core.component import Attachment, Component, Piece
from app.core.layout import LayoutRegion
from app.core.params import DISTANCE, RATIO, ParamSpec
from app.core.socket import socket
from app.geometry.kernel import block, faces_per_normal, grow

WHEEL_SIDES = 8


def _triangulate_quads(quads: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int]]:
    faces: list[tuple[int, int, int]] = []
    for a, b, c, d in quads:
        faces.append((a, b, c))
        faces.append((a, c, d))
    return faces


def _sectioned_body(length: float, width: float, height: float,
                   taper: float, chunkiness: float) -> trimesh.Trimesh:
    """Three rectangular stations along Z: rear, waist, tapered front."""
    taper = max(0.0, min(0.48, taper))
    w0 = width * (0.86 + 0.04 * chunkiness)
    stations = [
        (-length * 0.50, w0 * 0.46, height * 0.82),
        (-length * 0.10, w0 * 0.52, height * 1.00),
        (length * 0.50, w0 * (0.52 - taper * 0.34), height * (0.66 + 0.10 * chunkiness)),
    ]

    vertices: list[tuple[float, float, float]] = []
    for z, half_w, top in stations:
        vertices.extend([
            (-half_w, 0.0, z),
            (half_w, 0.0, z),
            (half_w, top, z),
            (-half_w, top, z),
        ])

    quads: list[tuple[int, int, int, int]] = []
    for i in range(len(stations) - 1):
        a = i * 4
        b = (i + 1) * 4
        quads.extend([
            (a + 0, b + 0, b + 1, a + 1),  # bottom
            (a + 1, b + 1, b + 2, a + 2),  # right side
            (a + 2, b + 2, b + 3, a + 3),  # top / hood plane
            (a + 3, b + 3, b + 0, a + 0),  # left side
        ])
    quads.extend([
        (0, 1, 2, 3),
        (8, 11, 10, 9),
    ])
    mesh = trimesh.Trimesh(vertices=np.asarray(vertices, dtype=float),
                           faces=np.asarray(_triangulate_quads(quads), dtype=np.int64),
                           process=False)
    mesh.merge_vertices()
    mesh.fix_normals()
    return mesh


def _cabin_mesh(length: float, width: float, height: float,
                cabin_ratio: float) -> trimesh.Trimesh:
    half_w = width * (0.31 + cabin_ratio * 0.10)
    top_w = half_w * 0.70
    rear = -length * 0.42
    front = length * 0.32
    roof_rear = -length * 0.30
    roof_front = length * 0.18
    vertices = np.asarray([
        (-half_w, 0.0, rear),
        (half_w, 0.0, rear),
        (half_w, 0.0, front),
        (-half_w, 0.0, front),
        (-top_w, height, roof_rear),
        (top_w, height, roof_rear),
        (top_w, height, roof_front),
        (-top_w, height, roof_front),
    ], dtype=float)
    quads = [
        (0, 1, 2, 3),  # base
        (4, 7, 6, 5),  # roof
        (3, 2, 6, 7),  # windshield
        (0, 4, 5, 1),  # rear glass plane
        (0, 3, 7, 4),  # left side
        (1, 5, 6, 2),  # right side
    ]
    mesh = trimesh.Trimesh(vertices=vertices,
                           faces=np.asarray(_triangulate_quads(quads), dtype=np.int64),
                           process=False)
    mesh.fix_normals()
    return mesh


def _panel(width: float, height: float, depth: float, axis: int) -> trimesh.Trimesh:
    return block((width, height, depth), sides=4, axis=axis)


def _base_box(size: tuple[float, float, float], axis: int) -> trimesh.Trimesh:
    """A rectangular prism whose base face is on the local origin plane."""
    sx, sy, sz = (float(v) for v in size)
    bounds = [[-sx * 0.5, sx * 0.5], [-sy * 0.5, sy * 0.5], [-sz * 0.5, sz * 0.5]]
    length = (sx, sy, sz)[axis]
    bounds[axis] = [0.0, length]
    x0, x1 = bounds[0]
    y0, y1 = bounds[1]
    z0, z1 = bounds[2]
    vertices = np.asarray([
        (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
        (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1),
    ], dtype=float)
    quads = [
        (0, 3, 2, 1), (4, 5, 6, 7),
        (0, 1, 5, 4), (1, 2, 6, 5),
        (2, 3, 7, 6), (3, 0, 4, 7),
    ]
    mesh = trimesh.Trimesh(vertices=vertices,
                           faces=np.asarray(_triangulate_quads(quads), dtype=np.int64),
                           process=False)
    mesh.fix_normals()
    return mesh


def _car(v, ctx) -> Piece:
    length = v["length"]
    width = v["width"]
    height = v["height"]
    wheel_d = v["wheel_size"]
    radius = wheel_d * 0.5
    tire_w = max(width * 0.13, wheel_d * 0.28)
    body_y = radius + v["ground_clearance"]
    body_h = height * (0.30 + 0.05 * v["chunkiness"])
    cabin_h = height * (0.36 + 0.22 * v["cabin_ratio"])
    track_half = width * v["stance"] * 0.50
    wheelbase_half = length * 0.31
    return Piece(mesh=None, tags=("car", "vehicle", "stylized"), sockets={
        "base": base_socket(width * 0.5, axis="+Y"),
        "body": socket("body", (0.0, body_y, 0.0), (0.0, 1.0, 0.0),
                       up=(0.0, 0.0, 1.0), radius=width * 0.45,
                       provides="vehicle_mount", tags=("body",)),
        "wheel_fl": socket("wheel_fl", (-track_half, radius, wheelbase_half),
                           (-1.0, 0.0, 0.0), up=(0.0, 1.0, 0.0),
                           radius=radius, provides="wheel_mount", side="l",
                           tags=("front",)),
        "wheel_fr": socket("wheel_fr", (track_half, radius, wheelbase_half),
                           (1.0, 0.0, 0.0), up=(0.0, 1.0, 0.0),
                           radius=radius, provides="wheel_mount", side="r",
                           tags=("front",)),
        "wheel_rl": socket("wheel_rl", (-track_half, radius, -wheelbase_half),
                           (-1.0, 0.0, 0.0), up=(0.0, 1.0, 0.0),
                           radius=radius, provides="wheel_mount", side="l",
                           tags=("rear",)),
        "wheel_rr": socket("wheel_rr", (track_half, radius, -wheelbase_half),
                           (1.0, 0.0, 0.0), up=(0.0, 1.0, 0.0),
                           radius=radius, provides="wheel_mount", side="r",
                           tags=("rear",)),
    }, metadata={
        "wheel_radius": radius,
        "tire_width": tire_w,
        "body_height": body_h,
        "cabin_height": cabin_h,
        "wheelbase_half": wheelbase_half,
    })


def _car_children(v, ctx):
    radius = v["wheel_size"] * 0.5
    tire_w = max(v["width"] * 0.13, v["wheel_size"] * 0.28)
    wheel_params = {"diameter": v["wheel_size"], "width": tire_w}
    return [
        Attachment(id="body", component="body", level=1, insert=0.0,
                   requirement=Requirement(capability="vehicle_mount", tags=("body",)),
                   params=v),
        Attachment(id="wheel_fl", component="wheel", level=1, insert=0.0,
                   requirement=Requirement(capability="wheel_mount", side="l",
                                           tags=("front",)),
                   params=wheel_params),
        Attachment(id="wheel_fr", component="wheel", level=1, insert=0.0,
                   requirement=Requirement(capability="wheel_mount", side="r",
                                           tags=("front",)),
                   params=wheel_params),
        Attachment(id="wheel_rl", component="wheel", level=1, insert=0.0,
                   requirement=Requirement(capability="wheel_mount", side="l",
                                           tags=("rear",)),
                   params=wheel_params),
        Attachment(id="wheel_rr", component="wheel", level=1, insert=0.0,
                   requirement=Requirement(capability="wheel_mount", side="r",
                                           tags=("rear",)),
                   params=wheel_params),
    ]


def _car_layout_regions(v, ctx):
    radius = v["wheel_size"] * 0.5
    track_half = v["width"] * v["stance"] * 0.50
    span = v["length"] * 0.95
    spacing = v["wheel_size"] * 0.10
    common = {
        "allows_role": "wheel",
        "allows_tags": ("wheel",),
        "default_policy": "linear",
        "allowed_policies": ("linear",),
        "capacity": 8,
        "span": span,
        "min_spacing": spacing,
        "min_scale": 0.70,
        "max_scale": 1.0,
        "allow_scale_to_fit": True,
        "symmetry_group": "wheels",
        "axis": (0.0, 0.0, 1.0),
        "up": (0.0, 1.0, 0.0),
    }
    return [
        LayoutRegion(id="left_wheel_region", anchor_socket="wheel_fl", side="l",
                     center=(-track_half, radius, 0.0),
                     direction=(-1.0, 0.0, 0.0), **common),
        LayoutRegion(id="right_wheel_region", anchor_socket="wheel_fr", side="r",
                     center=(track_half, radius, 0.0),
                     direction=(1.0, 0.0, 0.0), **common),
    ]


def _body(v, ctx) -> Piece:
    body_h = v["height"] * (0.30 + 0.05 * v["chunkiness"])
    mesh = _sectioned_body(v["length"], v["width"], body_h,
                           v["front_taper"], v["chunkiness"])
    length = v["length"]
    width = v["width"]
    wheelbase = length * 0.31
    side_x = width * 0.43
    return Piece(mesh=mesh, material="car_body",
                 tags=("body", "car", "vehicle"), sockets={
        "base": base_socket(width * 0.45, axis="+Y"),
        "cabin": socket("cabin", (0.0, body_h * 0.92, -length * 0.05),
                        (0.0, 1.0, 0.0), up=(0.0, 0.0, 1.0),
                        radius=width * 0.30, provides="vehicle_mount",
                        tags=("cabin",)),
        "hood": socket("hood", (0.0, body_h * 0.88, length * 0.28),
                       (0.0, 1.0, 0.0), up=(0.0, 0.0, 1.0),
                       radius=width * 0.24, provides="vehicle_mount",
                       tags=("hood", "panel")),
        "underbody": socket("underbody", (0.0, 0.02, 0.0),
                            (0.0, -1.0, 0.0), up=(0.0, 0.0, 1.0),
                            radius=width * 0.32, provides="vehicle_mount",
                            tags=("underbody",)),
        "fender_fl": socket("fender_fl", (-side_x, body_h * 0.08, wheelbase),
                            (-1.0, 0.0, 0.0), up=(0.0, 1.0, 0.0),
                            radius=v["wheel_size"] * 0.40, provides="vehicle_mount",
                            side="l", tags=("fender", "front")),
        "fender_fr": socket("fender_fr", (side_x, body_h * 0.08, wheelbase),
                            (1.0, 0.0, 0.0), up=(0.0, 1.0, 0.0),
                            radius=v["wheel_size"] * 0.40, provides="vehicle_mount",
                            side="r", tags=("fender", "front")),
        "fender_rl": socket("fender_rl", (-side_x, body_h * 0.08, -wheelbase),
                            (-1.0, 0.0, 0.0), up=(0.0, 1.0, 0.0),
                            radius=v["wheel_size"] * 0.40, provides="vehicle_mount",
                            side="l", tags=("fender", "rear")),
        "fender_rr": socket("fender_rr", (side_x, body_h * 0.08, -wheelbase),
                            (1.0, 0.0, 0.0), up=(0.0, 1.0, 0.0),
                            radius=v["wheel_size"] * 0.40, provides="vehicle_mount",
                            side="r", tags=("fender", "rear")),
        "headlight_l": socket("headlight_l", (-width * 0.25, body_h * 0.45,
                                              length * 0.525),
                              (0.0, 0.0, 1.0), up=(0.0, 1.0, 0.0),
                              radius=width * 0.08, provides="vehicle_mount",
                              side="l", tags=("headlight", "front")),
        "headlight_r": socket("headlight_r", (width * 0.25, body_h * 0.45,
                                              length * 0.525),
                              (0.0, 0.0, 1.0), up=(0.0, 1.0, 0.0),
                              radius=width * 0.08, provides="vehicle_mount",
                              side="r", tags=("headlight", "front")),
        "grille": socket("grille", (0.0, body_h * 0.32, length * 0.528),
                         (0.0, 0.0, 1.0), up=(0.0, 1.0, 0.0),
                         radius=width * 0.12, provides="vehicle_mount",
                         tags=("grille", "front")),
        "front_anchor": socket("front_anchor", (0.0, body_h * 0.25, length * 0.525),
                               (0.0, 0.0, 1.0), up=(0.0, 1.0, 0.0),
                               radius=width * 0.06, provides="anchor",
                               side="front", tags=("front", "vehicle")),
        "rear_anchor": socket("rear_anchor", (0.0, body_h * 0.36, -length * 0.52),
                              (0.0, 0.0, -1.0), up=(0.0, 1.0, 0.0),
                              radius=width * 0.06, provides="anchor",
                              side="back", tags=("rear", "vehicle")),
    }, metadata={"faces_per_normal": faces_per_normal(mesh)})


def _body_children(v, ctx):
    width = v["width"]
    length = v["length"]
    wheel = v["wheel_size"]
    fender_params = {
        "length": wheel * 0.92,
        "height": wheel * 0.36,
        "thickness": max(width * 0.12, wheel * 0.18),
    }
    return [
        Attachment(id="cabin", component="cabin", level=1, insert=0.05,
                   requirement=Requirement(capability="vehicle_mount", tags=("cabin",)),
                   params=v),
        Attachment(id="hood_panel", component="hood_panel", level=2, insert=0.04,
                   requirement=Requirement(capability="vehicle_mount",
                                           tags=("hood", "panel")),
                   params={"width": width * 0.52, "length": length * 0.34,
                           "thickness": v["height"] * 0.035}),
        Attachment(id="underbody", component="underbody", level=2, insert=0.0,
                   requirement=Requirement(capability="vehicle_mount",
                                           tags=("underbody",)),
                   params={"width": width * 0.68, "length": length * 0.74,
                           "height": v["height"] * 0.07}),
        Attachment(id="fender_fl", component="fender", level=2, insert=0.02,
                   requirement=Requirement(capability="vehicle_mount", side="l",
                                           tags=("fender", "front")),
                   params=fender_params),
        Attachment(id="fender_fr", component="fender", level=2, insert=0.02,
                   requirement=Requirement(capability="vehicle_mount", side="r",
                                           tags=("fender", "front")),
                   params=fender_params),
        Attachment(id="fender_rl", component="fender", level=2, insert=0.02,
                   requirement=Requirement(capability="vehicle_mount", side="l",
                                           tags=("fender", "rear")),
                   params=fender_params),
        Attachment(id="fender_rr", component="fender", level=2, insert=0.02,
                   requirement=Requirement(capability="vehicle_mount", side="r",
                                           tags=("fender", "rear")),
                   params=fender_params),
        Attachment(id="headlight_l", component="headlight", level=3, insert=0.06,
                   requirement=Requirement(capability="vehicle_mount", side="l",
                                           tags=("headlight", "front"))),
        Attachment(id="headlight_r", component="headlight", level=3, insert=0.06,
                   requirement=Requirement(capability="vehicle_mount", side="r",
                                           tags=("headlight", "front"))),
        Attachment(id="grille", component="grille", level=3, insert=0.05,
                   requirement=Requirement(capability="vehicle_mount",
                                           tags=("grille", "front")),
                   params={"width": width * 0.20, "height": v["height"] * 0.10,
                           "thickness": 0.035}),
    ]


def _cabin(v, ctx) -> Piece:
    cabin_h = v["height"] * (0.36 + 0.22 * v["cabin_ratio"])
    mesh = _cabin_mesh(v["length"] * (0.42 + v["cabin_ratio"] * 0.32),
                       v["width"], cabin_h, v["cabin_ratio"])
    length = v["length"]
    width = v["width"]
    return Piece(mesh=mesh, material="glass", tags=("cabin", "glass", "vehicle"),
                 sockets={
        "base": base_socket(width * 0.30, axis="+Y"),
        "windshield": socket("windshield", (0.0, cabin_h * 0.42, length * 0.20),
                             (0.0, 0.20, 1.0), up=(0.0, 1.0, 0.0),
                             radius=width * 0.22, provides="vehicle_mount",
                             tags=("windshield", "glass")),
        "mirror_l": socket("mirror_l", (-width * 0.38, cabin_h * 0.42,
                                        length * 0.10),
                           (-1.0, 0.0, 0.0), up=(0.0, 1.0, 0.0),
                           radius=width * 0.05, provides="vehicle_mount",
                           side="l", tags=("mirror",)),
        "mirror_r": socket("mirror_r", (width * 0.38, cabin_h * 0.42,
                                        length * 0.10),
                           (1.0, 0.0, 0.0), up=(0.0, 1.0, 0.0),
                           radius=width * 0.05, provides="vehicle_mount",
                           side="r", tags=("mirror",)),
        "roof_spoiler": socket("roof_spoiler", (0.0, cabin_h, -length * 0.17),
                               (0.0, 1.0, 0.0), up=(0.0, 0.0, 1.0),
                               radius=width * 0.20, provides="vehicle_mount",
                               tags=("spoiler", "roof")),
        "roof_gear": socket("roof_gear", (0.0, cabin_h, 0.0),
                            (0.0, 1.0, 0.0), up=(0.0, 0.0, 1.0),
                            radius=width * 0.16, provides="gear_mount",
                            side="top", tags=("roof", "vehicle")),
    }, metadata={"faces_per_normal": faces_per_normal(mesh)})


def _cabin_children(v, ctx):
    return [
        Attachment(id="windshield", component="windshield", level=2, insert=0.04,
                   requirement=Requirement(capability="vehicle_mount",
                                           tags=("windshield", "glass")),
                   params={"width": v["width"] * 0.46, "height": v["height"] * 0.24,
                           "thickness": 0.025}),
        Attachment(id="mirror_l", component="mirror", level=3, insert=0.03,
                   requirement=Requirement(capability="vehicle_mount", side="l",
                                           tags=("mirror",))),
        Attachment(id="mirror_r", component="mirror", level=3, insert=0.03,
                   requirement=Requirement(capability="vehicle_mount", side="r",
                                           tags=("mirror",))),
        Attachment(id="roof_spoiler", component="roof_spoiler", level=3,
                   insert=0.02,
                   requirement=Requirement(capability="vehicle_mount",
                                           tags=("spoiler", "roof")),
                   params={"width": v["width"] * 0.46, "height": v["height"] * 0.06,
                           "depth": v["length"] * 0.08}),
    ]


def _wheel(v, ctx) -> Piece:
    radius = v["diameter"] * 0.5
    width = v["width"]
    mesh = grow([(0.0, radius), (1.0, radius)], sides=WHEEL_SIDES,
                length=width, axis=0, flat=1.0, squash=0.20)
    return Piece(mesh=mesh, material="tire", tags=("wheel", "tire", "vehicle"),
                 sockets={
        "base": base_socket(radius, axis="+X"),
        "hub": socket("hub", (width, 0.0, 0.0), (1.0, 0.0, 0.0),
                      up=(0.0, 1.0, 0.0), radius=radius * 0.42,
                      provides="vehicle_mount", tags=("hub",)),
    }, metadata={"faces_per_normal": faces_per_normal(mesh)})


def _wheel_children(v, ctx):
    return [
        Attachment(id="hubcap", component="hubcap", level=3, insert=0.02,
                   requirement=Requirement(capability="vehicle_mount", tags=("hub",)),
                   params={"radius": v["diameter"] * 0.21,
                           "thickness": v["width"] * 0.18}),
    ]


def _fender(v, ctx) -> Piece:
    mesh = _panel(v["thickness"], v["height"], v["length"], axis=0)
    mesh.apply_translation([0.0, v["height"] * 0.35, 0.0])
    return Piece(mesh=mesh, material="car_body_dark",
                 tags=("fender", "wheel_arch", "vehicle"),
                 sockets={"base": base_socket(max(v["height"], v["length"]) * 0.5,
                                              axis="+X")})


def _hood_panel(v, ctx) -> Piece:
    mesh = _panel(v["width"], v["thickness"], v["length"], axis=1)
    mesh.apply_translation([0.0, v["thickness"] * 0.5, 0.0])
    return Piece(mesh=mesh, material="car_body_dark", tags=("hood", "panel"),
                 sockets={"base": base_socket(v["width"] * 0.5, axis="+Y")})


def _underbody(v, ctx) -> Piece:
    mesh = _panel(v["width"], v["height"], v["length"], axis=1)
    mesh.apply_translation([0.0, -v["height"] * 0.5, 0.0])
    return Piece(mesh=mesh, material="dark_accent",
                 tags=("underbody", "negative_space"),
                 sockets={"base": base_socket(v["width"] * 0.5, axis="+Y")})


def _windshield(v, ctx) -> Piece:
    mesh = _panel(v["width"], v["height"], v["thickness"], axis=1)
    mesh.apply_translation([0.0, v["height"] * 0.5, 0.0])
    return Piece(mesh=mesh, material="dark_accent",
                 tags=("windshield", "glass", "panel"),
                 sockets={"base": base_socket(v["width"] * 0.5, axis="+Y")})


def _headlight(v, ctx) -> Piece:
    mesh = _base_box((0.22, 0.10, 0.055), axis=2)
    return Piece(mesh=mesh, material="light_warm",
                 tags=("headlight", "front", "light"),
                 sockets={"base": base_socket(0.08, axis="+Z")})


def _grille(v, ctx) -> Piece:
    mesh = _base_box((v["width"], v["height"], v["thickness"]), axis=2)
    return Piece(mesh=mesh, material="dark_accent", tags=("grille", "front"),
                 sockets={"base": base_socket(v["width"] * 0.5, axis="+Z")})


def _mirror(v, ctx) -> Piece:
    mesh = _panel(0.08, 0.05, 0.05, axis=0)
    return Piece(mesh=mesh, material="dark_accent", tags=("mirror", "accent"),
                 sockets={"base": base_socket(0.045, axis="+X")})


def _roof_spoiler(v, ctx) -> Piece:
    mesh = _panel(v["width"], v["height"], v["depth"], axis=1)
    mesh.apply_translation([0.0, v["height"] * 0.5, 0.0])
    return Piece(mesh=mesh, material="car_body_dark",
                 tags=("spoiler", "roof", "accent"),
                 sockets={"base": base_socket(v["width"] * 0.5, axis="+Y")})


def _hubcap(v, ctx) -> Piece:
    mesh = grow([(0.0, v["radius"]), (1.0, v["radius"] * 0.82)],
                sides=WHEEL_SIDES, length=v["thickness"], axis=0, squash=0.10)
    return Piece(mesh=mesh, material="dark_accent", tags=("hubcap", "wheel"),
                 sockets={"base": base_socket(v["radius"], axis="+X")})


CAR_PARAMS = {
    "length": ParamSpec(2.80, DISTANCE, min=1.40, max=6.00,
                        semantic_role="length"),
    "width": ParamSpec(1.55, DISTANCE, min=0.80, max=3.00,
                       semantic_role="girth"),
    "height": ParamSpec(1.35, DISTANCE, min=0.70, max=2.50,
                        semantic_role="length"),
    "wheel_size": ParamSpec(0.58, DISTANCE, min=0.24, max=1.10,
                            semantic_role="girth"),
    "cabin_ratio": ParamSpec(0.46, RATIO, min=0.30, max=0.70,
                             description="share of car character given to the cabin"),
    "ground_clearance": ParamSpec(0.22, DISTANCE, min=0.08, max=0.55,
                                  semantic_role="length"),
    "stance": ParamSpec(1.08, RATIO, min=0.80, max=1.35,
                        description="how far the wheels sit from the center line"),
    "chunkiness": ParamSpec(1.00, RATIO, min=0.65, max=1.45,
                            description="squat robustness of the body mass"),
    "front_taper": ParamSpec(0.22, RATIO, min=0.00, max=0.45,
                             description="amount of friendly front taper"),
}


CAR = Component(
    id="car", build=_car, children=_car_children, params=CAR_PARAMS,
    provides=(Capability("vehicle"),),
    mounts=(mount("vehicle_mount", socket_id="body", tags=("body",)),
            mount("wheel_mount", socket_id="wheel_fl", side="l", tags=("front",),
                  capacity=0),
            mount("wheel_mount", socket_id="wheel_fr", side="r", tags=("front",),
                  capacity=0),
            mount("wheel_mount", socket_id="wheel_rl", side="l", tags=("rear",),
                  capacity=0),
            mount("wheel_mount", socket_id="wheel_rr", side="r", tags=("rear",),
                  capacity=0)),
    role="vehicle", material="car_body", layout_regions=_car_layout_regions,
    description="a friendly chunky stylized low-poly compact car",
    tags=frozenset({"vehicle", "car", "auto", "low_poly", "stylized", "compact"}))

BODY = Component(
    id="body", build=_body, children=_body_children, params=CAR_PARAMS,
    provides=(Capability("vehicle_mount"),),
    mounts=(mount("vehicle_mount", socket_id="cabin", tags=("cabin",)),
            mount("vehicle_mount", socket_id="hood", tags=("hood", "panel")),
            mount("vehicle_mount", socket_id="underbody", tags=("underbody",)),
            mount("vehicle_mount", socket_id="fender_fl", side="l",
                  tags=("fender", "front")),
            mount("vehicle_mount", socket_id="fender_fr", side="r",
                  tags=("fender", "front")),
            mount("vehicle_mount", socket_id="fender_rl", side="l",
                  tags=("fender", "rear")),
            mount("vehicle_mount", socket_id="fender_rr", side="r",
                  tags=("fender", "rear")),
            mount("vehicle_mount", socket_id="headlight_l", side="l",
                  tags=("headlight", "front")),
            mount("vehicle_mount", socket_id="headlight_r", side="r",
                  tags=("headlight", "front")),
            mount("vehicle_mount", socket_id="grille", tags=("grille", "front")),
            mount("anchor", socket_id="front_anchor", side="front",
                  tags=("front", "vehicle")),
            mount("anchor", socket_id="rear_anchor", side="back",
                  tags=("rear", "vehicle"))),
    role="vehicle_body", material="car_body",
    tags=frozenset({"vehicle", "car", "body", "low_poly"}))

CABIN = Component(
    id="cabin", build=_cabin, children=_cabin_children, params=CAR_PARAMS,
    provides=(Capability("vehicle_mount"),),
    mounts=(mount("vehicle_mount", socket_id="windshield",
                  tags=("windshield", "glass")),
            mount("vehicle_mount", socket_id="mirror_l", side="l", tags=("mirror",)),
            mount("vehicle_mount", socket_id="mirror_r", side="r", tags=("mirror",)),
            mount("vehicle_mount", socket_id="roof_spoiler",
                  tags=("spoiler", "roof")),
            mount("gear_mount", socket_id="roof_gear", side="top",
                  tags=("roof", "vehicle"))),
    role="vehicle_cabin", material="glass",
    tags=frozenset({"vehicle", "car", "cabin", "glass"}))

WHEEL = Component(
    id="wheel", build=_wheel, children=_wheel_children,
    params={"diameter": ParamSpec(0.58, DISTANCE, min=0.24, max=1.10,
                                  semantic_role="girth"),
            "width": ParamSpec(0.20, DISTANCE, min=0.06, max=0.60,
                               semantic_role="girth")},
    provides=(Capability("wheel_mount"),),
    mounts=(mount("vehicle_mount", socket_id="hub", tags=("hub",)),),
    role="wheel", material="tire",
    tags=frozenset({"vehicle", "wheel", "tire", "low_poly"}))

FENDER = Component(
    id="fender", build=_fender,
    params={"length": ParamSpec(0.50, DISTANCE, min=0.10, max=2.00),
            "height": ParamSpec(0.20, DISTANCE, min=0.05, max=1.00),
            "thickness": ParamSpec(0.18, DISTANCE, min=0.03, max=1.00)},
    provides=(Capability("vehicle_mount"),),
    role="wheel_arch", material="car_body_dark",
    tags=frozenset({"vehicle", "fender", "wheel_arch", "low_poly"}))

HOOD_PANEL = Component(
    id="hood_panel", build=_hood_panel,
    params={"width": ParamSpec(0.8, DISTANCE, min=0.10, max=5.0),
            "length": ParamSpec(0.9, DISTANCE, min=0.10, max=5.0),
            "thickness": ParamSpec(0.04, DISTANCE, min=0.005, max=0.2)},
    provides=(Capability("vehicle_mount"),),
    role="panel", material="car_body_dark",
    tags=frozenset({"vehicle", "hood", "panel"}))

UNDERBODY = Component(
    id="underbody", build=_underbody,
    params={"width": ParamSpec(1.0, DISTANCE, min=0.10, max=5.0),
            "length": ParamSpec(1.8, DISTANCE, min=0.10, max=6.0),
            "height": ParamSpec(0.08, DISTANCE, min=0.01, max=0.5)},
    provides=(Capability("vehicle_mount"),),
    role="underbody", material="dark_accent",
    tags=frozenset({"vehicle", "underbody"}))

WINDSHIELD = Component(
    id="windshield", build=_windshield,
    params={"width": ParamSpec(0.7, DISTANCE, min=0.10, max=4.0),
            "height": ParamSpec(0.32, DISTANCE, min=0.05, max=2.0),
            "thickness": ParamSpec(0.03, DISTANCE, min=0.005, max=0.2)},
    provides=(Capability("vehicle_mount"),),
    role="glass_panel", material="dark_accent",
    tags=frozenset({"vehicle", "windshield", "glass"}))

HEADLIGHT = Component(id="headlight", build=_headlight,
                      provides=(Capability("vehicle_mount"),),
                      role="light", material="light_warm",
                      tags=frozenset({"vehicle", "headlight", "light"}))

GRILLE = Component(
    id="grille", build=_grille,
    params={"width": ParamSpec(0.30, DISTANCE, min=0.05, max=2.0),
            "height": ParamSpec(0.14, DISTANCE, min=0.03, max=1.0),
            "thickness": ParamSpec(0.04, DISTANCE, min=0.005, max=0.2)},
    provides=(Capability("vehicle_mount"),),
    role="grille", material="dark_accent",
    tags=frozenset({"vehicle", "grille"}))

MIRROR = Component(id="mirror", build=_mirror,
                   provides=(Capability("vehicle_mount"),),
                   role="mirror", material="dark_accent",
                   tags=frozenset({"vehicle", "mirror", "accent"}))

ROOF_SPOILER = Component(
    id="roof_spoiler", build=_roof_spoiler,
    params={"width": ParamSpec(0.7, DISTANCE, min=0.10, max=4.0),
            "height": ParamSpec(0.08, DISTANCE, min=0.02, max=0.6),
            "depth": ParamSpec(0.20, DISTANCE, min=0.03, max=1.0)},
    provides=(Capability("vehicle_mount"),),
    role="spoiler", material="car_body_dark",
    tags=frozenset({"vehicle", "spoiler", "accent"}))

HUBCAP = Component(
    id="hubcap", build=_hubcap,
    params={"radius": ParamSpec(0.12, DISTANCE, min=0.02, max=0.60),
            "thickness": ParamSpec(0.04, DISTANCE, min=0.005, max=0.20)},
    provides=(Capability("vehicle_mount"),),
    role="hubcap", material="dark_accent",
    tags=frozenset({"vehicle", "hubcap", "wheel"}))
