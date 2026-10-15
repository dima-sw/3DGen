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
            (0.00, 0.62 * girth),
            (0.22, 0.54 * girth),
            (0.48, 0.40 * girth),
            (0.74, 0.25 * girth),
            (1.00, 0.08 * girth),
        ],
        sides=4,
        length=length,
        axis=1,
        squash=0.10,
        flat=0.82,
        point_end=True,
        twist=0.12,
    )

    return Piece(
        mesh=mesh,
        tags=("dragon", "tail", "reptile", "silhouette"),
        sockets={
            "base": socket(
                "base",
                (0.0, 0.0, 0.0),
                (0.0, -1.0, 0.0),
                up=(0.0, 0.0, 1.0),
                radius=max(0.54 * girth, 0.001),
            ),
        },
    )


TAIL = Component(
    id="tail",
    build=_build,
    description="A long tapering tail extending behind the dragon body and contributing strongly to the silhouette.",
    params={
        "girth": ParamSpec(
            0.34,
            DISTANCE,
            min=0.02,
            max=3.0,
            semantic_role="girth",
            description="Thickness and volume of the dragon tail near its base.",
        ),
        "length": ParamSpec(
            1.65,
            DISTANCE,
            min=0.10,
            max=10.0,
            semantic_role="length",
            description="Overall base-to-tip length of the dragon tail.",
        ),
    },
    provides=(Capability("tail_mount"),),
    role="tail",
    tags=frozenset({
        "dragon",
        "tail",
        "reptile",
        "creature",
        "fantasy",
        "silhouette",
        "cartoon",
        "low_poly",
    }),
    styles=frozenset({"low_poly"}),
)
