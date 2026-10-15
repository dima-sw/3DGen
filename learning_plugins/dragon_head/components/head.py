from app.core.capability import Capability, Requirement, mount
from app.core.component import Attachment, Component, Piece
from app.core.params import DISTANCE, ParamSpec
from app.core.socket import socket
from app.geometry.kernel import ring, sweep


def _build(values, ctx) -> Piece:
    girth = values["girth"]
    length = values["length"]

    rings = [
        ring(6, 0.00 * length, 0.55 * girth, 0.48 * girth),
        ring(6, 0.16 * length, 0.85 * girth, 0.68 * girth),
        ring(6, 0.40 * length, 1.00 * girth, 0.78 * girth),
        ring(6, 0.68 * length, 0.98 * girth, 0.80 * girth),
        ring(6, 0.88 * length, 0.82 * girth, 0.70 * girth),
        ring(6, 1.00 * length, 0.60 * girth, 0.52 * girth),
    ]
    mesh = sweep(rings, cap_start=True, cap_end=True)

    return Piece(
        mesh=mesh,
        tags=("dragon", "head", "reptile"),
        sockets={
            "base": socket(
                "base",
                (0.0, 0.0, 0.0),
                (0.0, -1.0, 0.0),
                up=(0.0, 0.0, 1.0),
                radius=0.50 * girth,
            ),
            "eye": socket(
                "eye",
                (0.0, 0.63 * length, 0.74 * girth),
                (0.0, 0.0, 1.0),
                up=(0.0, 1.0, 0.0),
                radius=0.25 * girth,
                provides="face_mount",
            ),
            "snout": socket(
                "snout",
                (0.0, 0.48 * length, 0.77 * girth),
                (0.0, 0.0, 1.0),
                up=(0.0, 1.0, 0.0),
                radius=0.42 * girth,
                provides="snout_mount",
            ),
            "horn": socket(
                "horn",
                (0.0, 0.88 * length, 0.0),
                (0.0, 1.0, 0.0),
                up=(0.0, 0.0, 1.0),
                radius=0.20 * girth,
                provides="horn_mount",
            ),
            "tooth": socket(
                "tooth",
                (0.0, 0.33 * length, 0.73 * girth),
                (0.0, -0.30, 1.0),
                up=(0.0, 1.0, 0.0),
                radius=0.12 * girth,
                provides="tooth_mount",
            ),
        },
    )


def _children(values, ctx):
    return [
        Attachment(
            id="eye",
            component="creature:bulging_eye",
            requirement=Requirement(capability="face_mount"),
            own_socket="base",
            level=2,
        ),
        Attachment(
            id="eye_2",
            component="creature:bulging_eye",
            requirement=Requirement(capability="face_mount"),
            own_socket="base",
            level=2,
        ),
    ]


HEAD = Component(
    id="head",
    build=_build,
    children=_children,
    description="The dragon head, acting as the parent composition for the principal facial parts.",
    params={
        "girth": ParamSpec(
            0.36,
            DISTANCE,
            min=0.05,
            max=2.0,
            semantic_role="girth",
            description="Overall thickness and width scale of the head.",
        ),
        "length": ParamSpec(
            0.65,
            DISTANCE,
            min=0.08,
            max=3.0,
            semantic_role="length",
            description="Overall base-to-crown length of the head.",
        ),
    },
    provides=(Capability("head_mount"),),
    mounts=(
        mount("face_mount", socket_id="eye", capacity=2),
        mount("snout_mount", socket_id="snout", capacity=1),
        mount("horn_mount", socket_id="horn", capacity=2),
        mount("tooth_mount", socket_id="tooth", capacity=6),
    ),
    role="head",
    tags=frozenset(
        {"dragon", "head", "creature", "fantasy", "reptile", "cartoon", "low_poly"}
    ),
    styles=frozenset({"low_poly"}),
)
