import numpy as np
import trimesh

from app.core.authoring import base_socket
from app.core.capability import Capability
from app.core.component import Component, Piece
from app.core.params import DISTANCE, RATIO, ParamSpec


def _build(values, ctx) -> Piece:
    scale = float(values["scale"])
    length = float(values["length"]) * scale
    width = float(values["width"]) * scale
    height = float(values["height"]) * scale
    girth = float(values["girth"]) * scale

    outline = (
        (0.00, 0.20, 0.00),
        (0.20, 0.34, 0.30),
        (0.50, 0.31, 0.62),
        (0.78, 0.20, 0.86),
        (1.00, 0.00, 0.42),
        (0.80, -0.07, 0.32),
        (0.63, -0.27, 0.48),
        (0.43, -0.13, 0.35),
        (0.23, -0.31, 0.18),
        (0.00, -0.20, 0.00)
    )

    half_t = max(girth * 0.5, 0.0001)
    top = []
    bottom = []

    for u, chord, camber_weight in outline:
        x = u * length
        z = chord * width
        y_mid = camber_weight * height
        top.append((x, y_mid + half_t, z))
        bottom.append((x, y_mid - half_t, z))

    n = len(outline)
    vertices = top + bottom

    centre_x = 0.43 * length
    centre_z = 0.01 * width
    centre_y = 0.48 * height

    top_centre = len(vertices)
    vertices.append((centre_x, centre_y + half_t, centre_z))

    bottom_centre = len(vertices)
    vertices.append((centre_x, centre_y - half_t, centre_z))

    faces = []

    for i in range(n):
        j = (i + 1) % n
        faces.append((top_centre, i, j))
        faces.append((bottom_centre, n + j, n + i))

    for i in range(n):
        j = (i + 1) % n
        faces.append((i, n + i, n + j))
        faces.append((i, n + j, j))

    mesh = trimesh.Trimesh(
        vertices=np.asarray(vertices, dtype=float),
        faces=np.asarray(faces, dtype=np.int64),
        process=False
    )
    mesh.fix_normals()

    socket_radius = max(0.02, min(width * 0.16, height * 0.32 + girth))

    return Piece(
        mesh=mesh,
        material="default",
        tags=("dragon", "wing", "membrane", "flight", "low_poly"),
        sockets={
            "base": base_socket(socket_radius, axis="+X")
        }
    )


WING = Component(
    id="wing",
    build=_build,
    description="A reusable cartoon low-poly dragon wing with a tapered bat-like membrane, scalloped trailing edge and faceted camber.",
    params={
        "length": ParamSpec(
            1.40,
            DISTANCE,
            min=0.30,
            max=4.00,
            semantic_role="length",
            description="span from shoulder to wing tip"
        ),
        "width": ParamSpec(
            0.85,
            DISTANCE,
            min=0.15,
            max=2.50,
            semantic_role="width",
            description="membrane chord and breadth"
        ),
        "height": ParamSpec(
            0.34,
            DISTANCE,
            min=0.05,
            max=1.20,
            semantic_role="height",
            description="upward camber and ridge relief"
        ),
        "girth": ParamSpec(
            0.055,
            DISTANCE,
            min=0.015,
            max=0.30,
            semantic_role="girth",
            description="physical membrane thickness"
        ),
        "scale": ParamSpec(
            1.0,
            RATIO,
            min=0.40,
            max=2.50,
            semantic_role="scale",
            description="uniform overall scale"
        )
    },
    provides=(Capability("wing_mount"),),
    role="wing",
    material="default",
    styles=frozenset({"low_poly"}),
    tags=frozenset({
        "dragon",
        "wing",
        "ala",
        "fantasy",
        "flight",
        "membrane",
        "batlike",
        "cartoon",
        "low_poly"
    })
)
