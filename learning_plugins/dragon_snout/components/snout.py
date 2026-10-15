from app.core.authoring import base_socket
from app.core.capability import Capability
from app.core.component import Component, Piece
from app.core.params import DISTANCE, RATIO, ParamSpec
from app.geometry.kernel import grow


def _build(values, ctx) -> Piece:
    length = values["length"] * values["scale"]
    width = values["width"] * values["scale"]
    height = values["height"] * values["scale"]
    girth = values["girth"] * values["scale"]

    radius = (width + girth) * 0.25
    flat = height / max(width, 0.001)

    mesh = grow(
        [
            (0.00, radius * 1.00),
            (0.18, radius * 1.05),
            (0.55, radius * 0.88),
            (0.82, radius * 0.70),
            (1.00, radius * 0.52),
        ],
        sides=6,
        length=length,
        axis=1,
        flat=flat,
        squash=0.12,
    )

    return Piece(
        mesh=mesh,
        tags=("dragon", "snout", "muzzle", "reptile"),
        sockets={
            "base": base_socket(max(radius * 0.82, 0.001), axis="+Y"),
        },
    )


SNOUT = Component(
    id="snout",
    build=_build,
    description="The elongated reptilian muzzle projecting from the front of a dragon head.",
    params={
        "girth": ParamSpec(
            0.30,
            DISTANCE,
            min=0.03,
            max=2.0,
            semantic_role="girth",
            description="Overall thickness of the muzzle.",
        ),
        "height": ParamSpec(
            0.24,
            DISTANCE,
            min=0.02,
            max=2.0,
            semantic_role="height",
            description="Vertical thickness of the muzzle.",
        ),
        "length": ParamSpec(
            0.58,
            DISTANCE,
            min=0.05,
            max=4.0,
            semantic_role="length",
            description="Base-to-tip length of the muzzle.",
        ),
        "scale": ParamSpec(
            1.0,
            RATIO,
            min=0.2,
            max=3.0,
            semantic_role="scale",
            description="Uniform overall muzzle scale."
        ),
        "width": ParamSpec(
            0.42,
            DISTANCE,
            min=0.03,
            max=3.0,
            semantic_role="width",
            description="Side-to-side width of the muzzle."
        )
    },
    provides=(Capability("face_mount"),),
    role="snout",
    tags=frozenset({"dragon", "snout", "muzzle", "reptile", "fantasy", "cartoon", "low_poly"}),
    styles=frozenset({"low_poly"})
)
