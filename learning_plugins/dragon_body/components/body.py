from app.core.capability import Capability
from app.core.component import Component, Piece
from app.core.params import DISTANCE, ParamSpec
from app.core.socket import socket
from app.geometry.kernel import ring, sweep


def _build(values, ctx) -> Piece:
    girth = values["girth"]
    length = values["length"]

    rings = [
        ring(6, 0.00 * length, 0.58 * girth, 0.48 * girth),
        ring(6, 0.16 * length, 0.82 * girth, 0.66 * girth),
        ring(6, 0.38 * length, 1.00 * girth, 0.78 * girth),
        ring(6, 0.62 * length, 0.96 * girth, 0.76 * girth),
        ring(6, 0.84 * length, 0.76 * girth, 0.62 * girth),
        ring(6, 1.00 * length, 0.52 * girth, 0.44 * girth),
    ]

    mesh = sweep(rings, cap_start=True, cap_end=True)

    return Piece(
        mesh=mesh,
        tags=("dragon", "body", "torso", "reptile"),
        sockets={
            "base": socket(
                "base",
                (0.0, 0.0, 0.0),
                (0.0, -1.0, 0.0),
                up=(0.0, 0.0, 1.0),
                radius=max(0.48 * girth, 0.001),
            ),
        },
    )


BODY = Component(
    id="body",
    build=_build,
    description="The main torso and central mass of the dragon.",
    params={
        "girth": ParamSpec(
            0.72,
            DISTANCE,
            min=0.05,
            max=5.0,
            semantic_role="girth",
            description="Overall thickness and bulk of the dragon torso.",
        ),
        "length": ParamSpec(
            1.30,
            DISTANCE,
            min=0.10,
            max=8.0,
            semantic_role="length",
            description="Overall longitudinal length of the dragon torso.",
        ),
    },
    provides=(Capability("body_mount"),),
    role="body",
    tags=frozenset({
        "dragon",
        "body",
        "torso",
        "creature",
        "fantasy",
        "reptile",
        "cartoon",
        "low_poly",
    }),
    styles=frozenset({"low_poly"}),
)
