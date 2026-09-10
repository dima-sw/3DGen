"""La testa e cio' che ci sta sopra: cranio, occhi, naso, bocca, orecchie, capelli.

Stessa geometria del plugin procedurale collaudato. Il muso non e' una bozza
fusa nel cranio ma un blocco davanti: nel low poly una sporgenza deve avere
degli spigoli, altrimenti sparisce nell'ombreggiatura piatta.
"""
from app.core.authoring import base_socket
from app.core.capability import Capability, Requirement, mount
from app.core.component import Attachment, Component, Piece
from app.core.params import DISTANCE, RATIO, ParamSpec
from app.core.socket import socket
from app.geometry.kernel import block, grow

LATI = 6


def _testa(v, ctx) -> Piece:
    lung, girth, flat = v["length"], v["girth"], v["flat"]
    mesh = grow([(0.00, girth * 0.52), (0.16, girth * 0.86), (0.42, girth * 1.0),
                 (0.72, girth * 0.98), (0.92, girth * 0.80), (1.0, girth * 0.50)],
                sides=LATI, length=lung, axis=1, flat=flat, squash=v["squash"])
    if v["muzzle"] > 0.01:
        muso = block((girth * 1.05, lung * 0.30, girth * flat * v["muzzle"]),
                     sides=4, squash=1.0, axis=2)
        muso.apply_translation([0.0, lung * 0.46,
                                girth * flat * (0.72 + v["muzzle"] * 0.5)])
        mesh = mesh + muso

    davanti = girth * flat
    return Piece(mesh=mesh, material="skin", tags=("head",), sockets={
        "base": base_socket(girth * 0.5, axis="+Y"),
        "cima": socket("cima", (0, lung * 0.94, 0), (0, 1, 0), up=(0, 0, 1),
                       radius=girth * 0.7, provides="hair_mount"),
        "viso": socket("viso", (0, lung * 0.58, davanti * 0.85), (0, 0, 1),
                       up=(0, 1, 0), radius=girth * 0.7, provides="face_mount"),
        "occhio_l": socket("occhio_l", (-girth * 0.40, lung * 0.62, davanti * 0.80),
                           (-0.25, 0.05, 1), up=(0, 1, 0), radius=girth * 0.22,
                           provides="face_mount", side="l", tags=("occhio",)),
        "occhio_r": socket("occhio_r", (girth * 0.40, lung * 0.62, davanti * 0.80),
                           (0.25, 0.05, 1), up=(0, 1, 0), radius=girth * 0.22,
                           provides="face_mount", side="r", tags=("occhio",)),
        "naso": socket("naso", (0, lung * 0.48, davanti * 0.88), (0, -0.1, 1),
                       up=(0, 1, 0), radius=girth * 0.18, provides="face_mount",
                       tags=("naso",)),
        "bocca": socket("bocca", (0, lung * 0.30, davanti * 0.80), (0, -0.25, 1),
                        up=(0, 1, 0), radius=girth * 0.26, provides="face_mount",
                        tags=("bocca",)),
        "orecchio_l": socket("orecchio_l", (-girth * 0.95, lung * 0.58, 0),
                             (-1, 0, 0), up=(0, 1, 0), radius=girth * 0.22,
                             provides="face_mount", side="l", tags=("orecchio",)),
        "orecchio_r": socket("orecchio_r", (girth * 0.95, lung * 0.58, 0),
                             (1, 0, 0), up=(0, 1, 0), radius=girth * 0.22,
                             provides="face_mount", side="r", tags=("orecchio",)),
    })


def _figli_della_testa(v, ctx):
    girth = v["girth"]
    figli = [Attachment(id="naso", component="nose", level=3, insert=0.35,
                        requirement=Requirement(capability="face_mount",
                                                tags=("naso",)),
                        params={"size": girth * 0.24}),
             Attachment(id="bocca", component="mouth", level=3, insert=0.5,
                        requirement=Requirement(capability="face_mount",
                                                tags=("bocca",)),
                        params={"width": girth * 0.5})]
    for lato in ("l", "r"):
        figli.append(Attachment(
            id="occhio_" + lato, component="eye", level=3, insert=0.45,
            material="eye",
            requirement=Requirement(capability="face_mount", side=lato,
                                    tags=("occhio",)),
            params={"size": girth * 0.26 * v["eye_size"]}))
        figli.append(Attachment(
            id="orecchio_" + lato, component="ear", level=3, insert=0.4,
            requirement=Requirement(capability="face_mount", side=lato,
                                    tags=("orecchio",)),
            params={"size": girth * 0.32}))
    if v["hair"] > 0.01:
        figli.append(Attachment(
            id="capelli", component="hair", level=3, insert=0.55, material="hair",
            requirement=Requirement(capability="hair_mount"),
            params={"girth": girth * 1.06, "length": v["length"] * 0.5,
                    "spike": v["hair"]}))
    return figli


HEAD = Component(
    id="head", build=_testa, children=_figli_della_testa,
    description="una testa umana, con occhi, naso, bocca, orecchie e capelli",
    params={
        "length": ParamSpec(0.243, DISTANCE, min=0.03, max=2.0,
                            semantic_role="length", derived="root.height * 0.1537"),
        "girth": ParamSpec(0.112, DISTANCE, min=0.01, max=1.0,
                           semantic_role="girth", derived="length * 0.46"),
        "flat": ParamSpec(0.90, RATIO, min=0.5, max=1.4),
        "squash": ParamSpec(0.45, RATIO, min=0.0, max=1.0),
        "muzzle": ParamSpec(0.18, RATIO, min=0.0, max=1.2,
                            description="sporgenza del viso"),
        "eye_size": ParamSpec(1.0, RATIO, min=0.3, max=3.0),
        "hair": ParamSpec(0.6, RATIO, min=0.0, max=1.5),
    },
    provides=(Capability("head_mount"),),
    mounts=(mount("face_mount", socket_id="viso"),
            mount("face_mount", socket_id="naso", tags=("naso",)),
            mount("face_mount", socket_id="bocca", tags=("bocca",)),
            mount("face_mount", socket_id="occhio_l", side="l", tags=("occhio",)),
            mount("face_mount", socket_id="occhio_r", side="r", tags=("occhio",)),
            mount("face_mount", socket_id="orecchio_l", side="l", tags=("orecchio",)),
            mount("face_mount", socket_id="orecchio_r", side="r", tags=("orecchio",)),
            mount("hair_mount", socket_id="cima")),
    role="head", material="skin", tags=frozenset({"umanoide", "humanoid", "testa", "head"}))


# --------------------------------------------------------------------------- #
# I dettagli del viso
# --------------------------------------------------------------------------- #
def _occhio(v, ctx) -> Piece:
    s = v["size"]
    mesh = block((s, s * 1.1, s * 0.55), sides=6, squash=0.15, axis=2)
    return Piece(mesh=mesh, material="eye", tags=("eye", "detail"),
                 sockets={"base": base_socket(s * 0.5, axis="+Z")})


def _naso(v, ctx) -> Piece:
    s = v["size"]
    mesh = grow([(0.0, s * 0.55), (0.6, s * 0.5), (1.0, s * 0.22)],
                sides=4, length=s * 1.5, axis=2, squash=0.6)
    return Piece(mesh=mesh, material="skin", tags=("nose", "detail"), sockets={
        "base": base_socket(s * 0.55, axis="+Z"),
        "punta": socket("punta", (0, 0, s * 1.5), (0, 0, 1), up=(0, 1, 0),
                        radius=s * 0.22, provides="anchor"),
    })


def _bocca(v, ctx) -> Piece:
    w = v["width"]
    mesh = block((w, w * 0.22, w * 0.30), sides=4, squash=1.0, axis=2)
    return Piece(mesh=mesh, material="mouth", tags=("mouth", "detail"),
                 sockets={"base": base_socket(w * 0.3, axis="+Z")})


def _orecchio(v, ctx) -> Piece:
    s = v["size"]
    mesh = block((s * 0.35, s * 1.2, s * 0.7), sides=5, squash=0.4, axis=0)
    return Piece(mesh=mesh, material="skin", tags=("ear", "detail"),
                 sockets={"base": base_socket(s * 0.4, axis="+X")})


def _capelli(v, ctx) -> Piece:
    girth, lung, spike = v["girth"], v["length"], v["spike"]
    mesh = grow([(0.0, girth * 1.02), (0.45, girth * 1.06), (0.80, girth * 0.86),
                 (1.0, girth * 0.30 * (1 + spike))],
                sides=LATI, length=lung, axis=1, flat=0.92, squash=0.4)
    return Piece(mesh=mesh, material="hair", tags=("hair", "detail"), sockets={
        "base": base_socket(girth, axis="+Y"),
        "cima": socket("cima", (0, lung, 0), (0, 1, 0), up=(0, 0, 1),
                       radius=girth * 0.6, provides="gear_mount"),
    })


EYE = Component(
    id="eye", build=_occhio, description="un occhio",
    params={"size": ParamSpec(0.029, DISTANCE, min=0.002, max=0.5,
                              semantic_role="girth")},
    provides=(Capability("face_mount"),),
    role="", material="eye", tags=frozenset({"umanoide", "humanoid", "viso", "face", "occhio", "eye"}))

NOSE = Component(
    id="nose", build=_naso, description="un naso",
    params={"size": ParamSpec(0.027, DISTANCE, min=0.002, max=0.5,
                              semantic_role="girth")},
    provides=(Capability("face_mount"),),
    mounts=(mount("anchor", socket_id="punta"),),
    role="face", material="skin", tags=frozenset({"umanoide", "humanoid", "viso", "face"}))

MOUTH = Component(
    id="mouth", build=_bocca, description="una bocca",
    params={"width": ParamSpec(0.056, DISTANCE, min=0.005, max=0.5,
                               semantic_role="girth")},
    provides=(Capability("face_mount"),),
    role="", material="mouth", tags=frozenset({"umanoide", "humanoid", "viso", "face"}))

EAR = Component(
    id="ear", build=_orecchio, description="un orecchio",
    params={"size": ParamSpec(0.036, DISTANCE, min=0.003, max=0.5,
                              semantic_role="girth")},
    provides=(Capability("face_mount"),),
    role="", material="skin", tags=frozenset({"umanoide", "humanoid", "viso", "face"}))

HAIR = Component(
    id="hair", build=_capelli,
    description="i capelli: una calotta con una punta, non una sfera",
    params={"girth": ParamSpec(0.119, DISTANCE, min=0.01, max=1.0,
                               semantic_role="girth"),
            "length": ParamSpec(0.121, DISTANCE, min=0.01, max=1.0,
                                semantic_role="length"),
            "spike": ParamSpec(0.6, RATIO, min=0.0, max=1.5)},
    provides=(Capability("hair_mount"),),
    mounts=(mount("gear_mount", socket_id="cima"),),
    role="head", material="hair", tags=frozenset({"umanoide", "humanoid", "capelli", "hair"}))
