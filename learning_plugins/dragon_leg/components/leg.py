from app.core.capability import Capability
from app.core.component import Component, Piece
from app.core.params import DISTANCE, ParamSpec
from app.core.socket import socket
from app.geometry.kernel import grow


def _build(values, ctx) -> Piece:
    girth = values["girth"]
    length = values["length"]

    mesh = grow(
        [
            (0.00, 0.52 * girth),
            (0.24, 0.58 * girth),
            (0.52, 0.46 * girth),
            (0.78, 0.36 * girth),
            (1.00, 0.30 * girth),
        ],
        sides=4,
        length=length,
        axis=1,
        squash=0.08,
        flat=0.86,
        twist=0.10,
    )

    return Piece(
        mesh=mesh,
        tags=("dragon", "leg", "limb", "reptile", "stance"),
        sockets={
            "base": socket(
                "base",
                (0.0, 0.0, 0.0),
                (0.0, -1.0, 0.0),
                up=(0.0, 0.0, 1.0),
                radius=max(0.46 * girth, 0.001),
            ),
        },
    )


LEG = Component(
    id="leg",
    build=_build,
    description="A weight-bearing reptilian limb reused four times around the dragon body.",
    params={
        "girth": ParamSpec(
            0.24,
            DISTANCE,
            min=0.02,
            max=2.0,
            semantic_role="girth",
            description="Overall thickness and sturdiness of the dragon leg.",
        ),
        "length": ParamSpec(
            0.72,
            DISTANCE,
            min=0.05,
            max=4.0,
            semantic_role="length",
            description="Overall base-to-end length of the dragon leg.",
        ),
    },
    provides=(Capability("leg_mount"),),
    role="leg",
    tags=frozenset({
        "dragon",
        "leg",
        "limb",
        "reptile",
        "creature",
        "fantasy",
        "stance",
        "cartoon",
        "low_poly",
    }),
    styles=frozenset({"low_poly"}),
)
