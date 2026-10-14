"""Umanoide anatomico procedurale.

Questo plugin non sostituisce `humanoid`: dimostra che un'altra implementazione
puo' fornire gli stessi contratti (`head_mount`, `limb_mount`, `face_mount`)
con una struttura e una geometria diverse. Il core resta cieco al dominio.
"""

from __future__ import annotations

import trimesh

from app.core.authoring import base_socket
from app.core.capability import Capability, Requirement, mount
from app.core.component import Attachment, BuildContext, Component, Piece
from app.core.constraints import CLAMP, Constraint
from app.core.layout import LayoutRegion
from app.core.params import DISTANCE, RATIO, ParamSpec
from app.core.socket import socket
from app.geometry.kernel import block, grow

SIDES = 8
FACE_SIDES = 6


def _merge(*meshes) -> trimesh.Trimesh:
    parts = [m for m in meshes if m is not None]
    return trimesh.util.concatenate(parts) if parts else trimesh.Trimesh()


def _sweep_y(length: float, width: float, depth: float, profile, *,
             squash: float = 0.35, sides: int = SIDES) -> trimesh.Trimesh:
    mesh = grow([(t, width * r) for t, r in profile], sides=sides,
                length=length, axis=1, flat=depth / max(width, 1e-6),
                squash=squash)
    return mesh


def _sweep_x(length: float, radius: float, profile, *,
             flat: float = 0.82, squash: float = 0.22,
             sides: int = SIDES) -> trimesh.Trimesh:
    return grow([(t, radius * r) for t, r in profile], sides=sides,
                length=length, axis=0, flat=flat, squash=squash)


def _joint_mesh(radius: float, *, visible: bool, axis: int = 0) -> trimesh.Trimesh | None:
    if not visible:
        return None
    mesh = grow([(0.0, radius * 0.92), (0.5, radius), (1.0, radius * 0.82)],
                sides=SIDES, length=radius * 1.15, axis=axis, squash=0.18)
    mesh.apply_translation([-radius * 0.22 if axis == 0 else 0.0,
                            -radius * 0.22 if axis == 1 else 0.0,
                            0.0])
    return mesh


def _common_tags(*extra):
    return frozenset({"umanoide", "humanoid", "umano", "human", "persona",
                      "person", "anatomical", "anatomico", *extra})


# --------------------------------------------------------------------------- #
# Radice e torso
# --------------------------------------------------------------------------- #
def _body(v, ctx: BuildContext) -> Piece:
    height = v["height"]
    return Piece(mesh=None, material="skin", tags=("body", "anatomical"), sockets={
        "base": base_socket(height * 0.06, axis="+Y"),
        "core": socket("core", (0, 0, 0), (0, 1, 0), up=(0, 0, 1),
                       radius=height * 0.13, provides="core_mount"),
    })


def _body_children(v, ctx):
    return [Attachment(id="torso", component="torso", level=1, insert=0.0,
                       requirement=Requirement(capability="core_mount"))]


BODY = Component(
    id="body", build=_body, children=_body_children,
    description="corpo completo di umanoide anatomico procedurale con proporzioni umane e arti in catena",
    params={
        "height": ParamSpec(1.8, DISTANCE, min=0.45, max=2.6,
                            semantic_role="length",
                            description="altezza totale di riferimento"),
        "body_mass": ParamSpec(1.0, RATIO, min=0.55, max=1.65,
                               semantic_role="girth",
                               description="massa complessiva della figura"),
    },
    mounts=(mount("core_mount", socket_id="core"),),
    role="body", material="skin",
    tags=_common_tags("body", "corpo", "character", "figura", "full_body",
                      "corpo_intero", "intero"))


def _torso(v, ctx) -> Piece:
    h = v["height"]
    shoulder = v["shoulder_width"]
    hip = v["hip_width"]
    waist = v["waist_width"]
    depth = v["chest_depth"]
    length = v["torso_length"]

    pelvis = _sweep_y(length * 0.34, hip * 0.50, depth * 0.70,
                      [(0, 0.72), (0.35, 1.0), (1, 0.78)], squash=0.42)
    abdomen = _sweep_y(length * 0.38, waist * 0.45, depth * 0.58,
                       [(0, 0.86), (0.55, 0.72), (1, 0.90)], squash=0.35)
    abdomen.apply_translation([0, length * 0.30, 0])
    ribcage = _sweep_y(length * 0.52, shoulder * 0.42, depth * 0.86,
                       [(0, 0.72), (0.30, 0.92), (0.72, 1.0), (1, 0.70)],
                       squash=0.32)
    ribcage.apply_translation([0, length * 0.56, 0])
    mesh = _merge(pelvis, abdomen, ribcage)

    return Piece(mesh=mesh, material="skin", tags=("torso", "body"), sockets={
        "base": base_socket(hip * 0.34, axis="+Y"),
        "neck": socket("neck", (0, length, 0), (0, 1, 0), up=(0, 0, 1),
                       radius=h * 0.034, provides="head_mount"),
        "shoulder_l": socket("shoulder_l", (-shoulder * 0.54, length * 0.88, 0),
                             (-0.24, -0.97, 0.08), up=(0, 0, 1),
                             radius=h * 0.037, provides="limb_mount", side="l",
                             tags=("alto", "upper")),
        "shoulder_r": socket("shoulder_r", (shoulder * 0.54, length * 0.88, 0),
                             (0.24, -0.97, 0.08), up=(0, 0, 1),
                             radius=h * 0.037, provides="limb_mount", side="r",
                             tags=("alto", "upper")),
        "hip_l": socket("hip_l", (-hip * 0.35, length * 0.10, 0),
                        (-0.12, -1, 0.03), up=(0, 0, 1),
                        radius=h * 0.052, provides="limb_mount", side="l",
                        tags=("basso", "lower")),
        "hip_r": socket("hip_r", (hip * 0.35, length * 0.10, 0),
                        (0.12, -1, 0.03), up=(0, 0, 1),
                        radius=h * 0.052, provides="limb_mount", side="r",
                        tags=("basso", "lower")),
        "pelvis_socket": socket("pelvis_socket", (0, 0, 0), (0, 1, 0),
                                up=(0, 0, 1), radius=hip * 0.32,
                                provides="segment", tags=("pelvis", "basso")),
        "abdomen_socket": socket("abdomen_socket", (0, length * 0.28, 0), (0, 1, 0),
                                 up=(0, 0, 1), radius=waist * 0.28,
                                 provides="segment", tags=("abdomen",)),
        "ribcage_socket": socket("ribcage_socket", (0, length * 0.55, 0), (0, 1, 0),
                                 up=(0, 0, 1), radius=shoulder * 0.30,
                                 provides="segment", tags=("ribcage", "alto")),
        "back": socket("back", (0, length * 0.70, -depth * 0.72), (0, 0, -1),
                       up=(0, 1, 0), radius=shoulder * 0.28,
                       provides="gear_mount"),
    })


def _torso_children(v, ctx):
    if ctx.detail_level <= 1:
        children = [
            Attachment(id="head", component="head", level=1, insert=0.15,
                       requirement=Requirement(capability="head_mount")),
        ]
        for side in ("l", "r"):
            children.append(Attachment(
                id="arm_" + side, component="arm", level=1, insert=0.65,
                requirement=Requirement(capability="limb_mount", side=side,
                                        tags=("alto",))))
            children.append(Attachment(
                id="leg_" + side, component="leg", level=1, insert=0.55,
                requirement=Requirement(capability="limb_mount", side=side,
                                        tags=("basso",))))
        return children

    children = [
        Attachment(id="pelvis", component="pelvis", level=2, replaces_parent=True,
                   insert=0.0,
                   requirement=Requirement(capability="segment", tags=("pelvis",)),
                   params={"height": v["height"], "width": v["hip_width"],
                           "depth": v["chest_depth"] * 0.72,
                           "length": v["torso_length"] * 0.34}),
        Attachment(id="abdomen", component="abdomen", level=2, replaces_parent=True,
                   insert=0.0,
                   requirement=Requirement(capability="segment", tags=("abdomen",)),
                   params={"height": v["height"], "width": v["waist_width"],
                           "depth": v["chest_depth"] * 0.60,
                           "length": v["torso_length"] * 0.38}),
        Attachment(id="ribcage", component="ribcage", level=2, replaces_parent=True,
                   insert=0.0,
                   requirement=Requirement(capability="segment", tags=("ribcage",)),
                   params={"height": v["height"], "width": v["shoulder_width"],
                           "depth": v["chest_depth"],
                           "length": v["torso_length"] * 0.52}),
        Attachment(id="neck", component="neck", level=2, insert=0.18,
                   requirement=Requirement(capability="head_mount"),
                   params={"height": v["height"]}),
    ]
    for side in ("l", "r"):
        children.append(Attachment(
            id="shoulder_" + side, component="shoulder", level=2, insert=0.40,
            replaces="arm_" + side,
            requirement=Requirement(capability="limb_mount", side=side,
                                    tags=("alto",)),
            params={"height": v["height"], "side": side}))
        children.append(Attachment(
            id="hip_" + side, component="hip", level=2, insert=0.25,
            replaces="leg_" + side,
            requirement=Requirement(capability="limb_mount", side=side,
                                    tags=("basso",)),
            params={"height": v["height"], "side": side}))
    return children


def _torso_layout_regions(v, ctx):
    shoulder = v["shoulder_width"]
    length = v["torso_length"]
    h = v["height"]
    common = {
        "allows_role": "arm",
        "allows_tags": ("arm",),
        "default_policy": "fan",
        "allowed_policies": ("fan",),
        "capacity": 4,
        "spread_angle": 36.0,
        "min_spacing": h * 0.025,
        "min_scale": 0.78,
        "max_scale": 1.0,
        "allow_scale_to_fit": False,
        "symmetry_group": "arms",
        "up": (0.0, 0.0, 1.0),
        "axis": (0.0, 0.0, 1.0),
        "elevation_span": h * 0.03,
        "depth_offset": h * 0.015,
    }
    return [
        LayoutRegion(id="left_arm_region", anchor_socket="shoulder_l", side="l",
                     center=(-shoulder * 0.54, length * 0.88, 0.0),
                     direction=(-0.24, -0.97, 0.08), **common),
        LayoutRegion(id="right_arm_region", anchor_socket="shoulder_r", side="r",
                     center=(shoulder * 0.54, length * 0.88, 0.0),
                     direction=(0.24, -0.97, 0.08), **common),
    ]


TORSO = Component(
    id="torso", build=_torso, children=_torso_children,
    description="torso anatomico con bacino, vita, cassa toracica, spalle e anche",
    params={
        "height": ParamSpec(1.8, DISTANCE, min=0.45, max=2.6,
                            semantic_role="length", derived="root.height"),
        "torso_length": ParamSpec(0.57, DISTANCE, min=0.18, max=1.2,
                                  semantic_role="length",
                                  derived="root.height * 0.318"),
        "shoulder_width": ParamSpec(0.42, DISTANCE, min=0.12, max=0.80,
                                    semantic_role="girth",
                                    derived="root.height * 0.235"),
        "hip_width": ParamSpec(0.31, DISTANCE, min=0.10, max=0.62,
                               semantic_role="girth",
                               derived="root.height * 0.173"),
        "waist_width": ParamSpec(0.25, DISTANCE, min=0.08, max=0.55,
                                 semantic_role="girth",
                                 derived="root.height * 0.140"),
        "chest_depth": ParamSpec(0.20, DISTANCE, min=0.07, max=0.42,
                                 semantic_role="girth",
                                 derived="root.height * 0.112"),
        "muscularity": ParamSpec(1.0, RATIO, min=0.55, max=1.60,
                                 semantic_role="girth"),
    },
    constraints=(Constraint("shoulder_width >= hip_width * 0.95",
                            severity=CLAMP, target="shoulder_width",
                            to="hip_width * 0.95",
                            message="le spalle non devono sparire rispetto al bacino"),),
    provides=(Capability("core_mount"),),
    mounts=(mount("head_mount", socket_id="neck"),
            mount("limb_mount", socket_id="shoulder_l", side="l", tags=("alto",),
                  capacity=0),
            mount("limb_mount", socket_id="shoulder_r", side="r", tags=("alto",),
                  capacity=0),
            mount("limb_mount", socket_id="hip_l", side="l", tags=("basso",)),
            mount("limb_mount", socket_id="hip_r", side="r", tags=("basso",)),
            mount("segment", socket_id="pelvis_socket", tags=("pelvis", "basso")),
            mount("segment", socket_id="abdomen_socket", tags=("abdomen",)),
            mount("segment", socket_id="ribcage_socket", tags=("ribcage", "alto")),
            mount("gear_mount", socket_id="back")),
    role="torso", material="skin", requires=frozenset({"connected"}),
    layout_regions=_torso_layout_regions,
    tags=_common_tags("torso", "busto", "anatomy"))


def _torso_piece(profile, tag):
    def build(v, ctx):
        mesh = _sweep_y(v["length"], v["width"] * 0.50, v["depth"] * 0.50,
                        profile, squash=0.36)
        return Piece(mesh=mesh, material="skin", tags=(tag, "torso"), sockets={
            "base": base_socket(v["width"] * 0.25, axis="+Y"),
            "tip": socket("tip", (0, v["length"], 0), (0, 1, 0), up=(0, 0, 1),
                          radius=v["width"] * 0.22, provides="segment"),
        })
    return build


_TORSO_PARAMS = {
    "height": ParamSpec(1.8, DISTANCE, min=0.45, max=2.6,
                        semantic_role="length"),
    "length": ParamSpec(0.22, DISTANCE, min=0.04, max=0.8,
                        semantic_role="length"),
    "width": ParamSpec(0.28, DISTANCE, min=0.04, max=1.0,
                       semantic_role="girth"),
    "depth": ParamSpec(0.18, DISTANCE, min=0.03, max=0.8,
                       semantic_role="girth"),
}

PELVIS = Component(
    id="pelvis", build=_torso_piece([(0, 0.70), (0.35, 1.0), (1, 0.82)], "pelvis"),
    description="bacino anatomico, piu' largo in alto e inclinato",
    params=dict(_TORSO_PARAMS), provides=(Capability("segment"),),
    role="torso", material="skin", tags=_common_tags("pelvis", "bacino"))

ABDOMEN = Component(
    id="abdomen", build=_torso_piece([(0, 0.90), (0.55, 0.72), (1, 0.96)], "abdomen"),
    description="addome e vita, restringimento tra bacino e cassa toracica",
    params=dict(_TORSO_PARAMS), provides=(Capability("segment"),),
    role="torso", material="skin", tags=_common_tags("abdomen", "waist", "vita"))

RIBCAGE = Component(
    id="ribcage", build=_torso_piece([(0, 0.72), (0.28, 0.95), (0.78, 1.0), (1, 0.62)], "ribcage"),
    description="cassa toracica con massa delle spalle e volume del petto",
    params=dict(_TORSO_PARAMS), provides=(Capability("segment"),),
    role="torso", material="skin", tags=_common_tags("ribcage", "chest", "petto"))


def _neck(v, ctx):
    h = v["height"]
    length = h * 0.047
    girth = h * 0.036
    mesh = grow([(0, girth * 0.9), (1, girth * 0.76)], sides=SIDES,
                length=length, axis=1, squash=0.18)
    return Piece(mesh=mesh, material="skin", tags=("neck",), sockets={
        "base": base_socket(girth, axis="+Y"),
        "tip": socket("tip", (0, length, 0), (0, 1, 0), up=(0, 0, 1),
                      radius=girth * 0.82, provides="head_mount"),
    })


def _neck_children(v, ctx):
    return [Attachment(id="head", component="head", level=2, insert=0.36,
                       requirement=Requirement(capability="head_mount"),
                       params={"height": v["height"]})]


NECK = Component(
    id="neck", build=_neck, children=_neck_children,
    description="collo anatomico, nodo reale fra torso e testa",
    params={"height": ParamSpec(1.8, DISTANCE, min=0.45, max=2.6,
                                semantic_role="length", derived="root.height")},
    provides=(Capability("head_mount"),),
    mounts=(mount("head_mount", socket_id="tip"),),
    role="neck", material="skin", tags=_common_tags("neck", "collo"))


# --------------------------------------------------------------------------- #
# Arti in catena
# --------------------------------------------------------------------------- #
def _whole_arm(v, ctx):
    length = v["length"]
    girth = v["girth"]
    mesh = _sweep_x(length, girth,
                    [(0, 0.82), (0.12, 1.25), (0.42, 1.02), (0.70, 0.78), (1, 0.52)],
                    flat=0.72)
    return Piece(mesh=mesh, material="skin", tags=("arm", "limb"), sockets={
        "base": base_socket(girth * 0.9, axis="+X"),
        "tip": socket("tip", (length, 0, 0), (1, 0, 0), up=(0, 1, 0),
                      radius=girth * 0.48, provides="limb_mount"),
    })


def _whole_leg(v, ctx):
    length = v["length"]
    girth = v["girth"]
    mesh = _sweep_x(length, girth,
                    [(0, 1.12), (0.28, 1.04), (0.55, 0.78), (0.82, 0.66), (1, 0.50)],
                    flat=0.80)
    return Piece(mesh=mesh, material="skin", tags=("leg", "limb"), sockets={
        "base": base_socket(girth, axis="+X"),
        "tip": socket("tip", (length, 0, 0), (1, 0, 0), up=(0, 1, 0),
                      radius=girth * 0.45, provides="limb_mount"),
    })


ARM = Component(
    id="arm", build=_whole_arm,
    description="braccio anatomico semplificato per detail 1",
    params={"length": ParamSpec(0.70, DISTANCE, min=0.10, max=1.3,
                                semantic_role="length",
                                derived="root.height * 0.39"),
            "girth": ParamSpec(0.052, DISTANCE, min=0.01, max=0.22,
                               semantic_role="girth",
                               derived="root.height * 0.029")},
    provides=(Capability("limb_mount"),),
    mounts=(mount("limb_mount", socket_id="tip"),),
    role="arm", material="skin", tags=_common_tags("arm", "braccio", "limb"))

LEG = Component(
    id="leg", build=_whole_leg,
    description="gamba anatomica semplificata per detail 1",
    params={"length": ParamSpec(0.92, DISTANCE, min=0.18, max=1.5,
                                semantic_role="length",
                                derived="root.height * 0.616"),
            "girth": ParamSpec(0.080, DISTANCE, min=0.01, max=0.28,
                               semantic_role="girth",
                               derived="root.height * 0.044")},
    provides=(Capability("limb_mount"),),
    mounts=(mount("limb_mount", socket_id="tip"),),
    role="leg", material="skin", tags=_common_tags("leg", "gamba", "limb"))


def _joint(v, ctx):
    r = v["radius"]
    length = v["length"]
    mesh = _joint_mesh(r, visible=ctx.detail_level >= 3, axis=0)
    return Piece(mesh=mesh, material="skin", tags=(v["kind"], "joint"), sockets={
        "base": base_socket(r, axis="+X"),
        "tip": socket("tip", (length, 0, 0), (1, 0, 0), up=(0, 1, 0),
                      radius=r * 0.82, provides="segment"),
    })


def _single_child(name, component, **params):
    return [Attachment(id=name, component=component, level=2, insert=0.0,
                       requirement=Requirement(capability="segment"), params=params)]


def _shoulder_children(v, ctx):
    return _single_child("upper_arm", "upper_arm",
                         length=v["height"] * 0.178, radius=v["height"] * 0.031)


def _upper_arm_children(v, ctx):
    return _single_child("elbow", "elbow",
                         radius=v["radius"] * 0.78, length=v["radius"] * 0.90)


def _elbow_children(v, ctx):
    return _single_child("forearm", "forearm",
                         length=v["height"] * 0.158, radius=v["height"] * 0.025)


def _forearm_children(v, ctx):
    return _single_child("wrist", "wrist",
                         radius=v["radius"] * 0.64, length=v["radius"] * 0.70)


def _wrist_children(v, ctx):
    return _single_child("hand", "hand",
                         length=v["height"] * 0.095, radius=v["height"] * 0.025)


def _hip_children(v, ctx):
    return _single_child("thigh", "thigh",
                         length=v["height"] * 0.230, radius=v["height"] * 0.050)


def _thigh_children(v, ctx):
    return _single_child("knee", "knee",
                         radius=v["radius"] * 0.66, length=v["radius"] * 0.88)


def _knee_children(v, ctx):
    return _single_child("calf", "calf",
                         length=v["height"] * 0.215, radius=v["height"] * 0.040)


def _calf_children(v, ctx):
    return _single_child("ankle", "ankle",
                         radius=v["radius"] * 0.52, length=v["radius"] * 0.68)


def _ankle_children(v, ctx):
    return _single_child("foot", "foot",
                         length=v["height"] * 0.135, radius=v["height"] * 0.035)


_JOINT_PARAMS = {
    "height": ParamSpec(1.8, DISTANCE, min=0.45, max=2.6,
                        semantic_role="length", derived="root.height"),
    "radius": ParamSpec(0.05, DISTANCE, min=0.004, max=0.25,
                        semantic_role="girth"),
    "length": ParamSpec(0.04, DISTANCE, min=0.0, max=0.25,
                        semantic_role="length"),
    "kind": ParamSpec("joint", "string"),
    "side": ParamSpec("", "string"),
}


SHOULDER = Component(
    id="shoulder", build=_joint, children=_shoulder_children,
    description="spalla/deltoide, primo nodo reale della catena del braccio",
    params={**_JOINT_PARAMS, "radius": ParamSpec(0.054, DISTANCE, min=0.006, max=0.25,
                                                semantic_role="girth",
                                                derived="root.height * 0.030"),
            "kind": ParamSpec("shoulder", "string")},
    provides=(Capability("limb_mount"),), mounts=(mount("segment", socket_id="tip"),),
    role="arm", material="skin", tags=_common_tags("shoulder", "spalla", "arm"))

HIP = Component(
    id="hip", build=_joint, children=_hip_children,
    description="anca, primo nodo reale della catena della gamba",
    params={**_JOINT_PARAMS, "radius": ParamSpec(0.072, DISTANCE, min=0.008, max=0.28,
                                                semantic_role="girth",
                                                derived="root.height * 0.040"),
            "kind": ParamSpec("hip", "string")},
    provides=(Capability("limb_mount"),), mounts=(mount("segment", socket_id="tip"),),
    role="leg", material="skin", tags=_common_tags("hip", "anca", "leg"))


def _limb_segment(profile, tag, role):
    def build(v, ctx):
        mesh = _sweep_x(v["length"], v["radius"], profile,
                        flat=v.get("flat", 0.80), squash=0.20)
        return Piece(mesh=mesh, material="skin", tags=(tag, "limb"), sockets={
            "base": base_socket(v["radius"], axis="+X"),
            "tip": socket("tip", (v["length"], 0, 0), (1, 0, 0), up=(0, 1, 0),
                          radius=v["radius"] * profile[-1][1], provides="segment"),
        })
    return build


_SEGMENT_PARAMS = {
    "height": ParamSpec(1.8, DISTANCE, min=0.45, max=2.6,
                        semantic_role="length", derived="root.height"),
    "length": ParamSpec(0.25, DISTANCE, min=0.03, max=0.8,
                        semantic_role="length"),
    "radius": ParamSpec(0.04, DISTANCE, min=0.004, max=0.25,
                        semantic_role="girth"),
    "flat": ParamSpec(0.80, RATIO, min=0.35, max=1.2),
}

UPPER_ARM = Component(
    id="upper_arm",
    build=_limb_segment([(0, 0.78), (0.18, 1.16), (0.70, 0.92), (1, 0.72)],
                        "upper_arm", "arm"),
    children=_upper_arm_children,
    description="omero con deltoide e restringimento verso il gomito",
    params=dict(_SEGMENT_PARAMS), provides=(Capability("segment"),),
    mounts=(mount("segment", socket_id="tip"),),
    role="arm", material="skin", tags=_common_tags("upper_arm", "omero", "arm"))

ELBOW = Component(
    id="elbow", build=_joint, children=_elbow_children,
    description="gomito: nodo gerarchico reale tra omero e avambraccio",
    params={**_JOINT_PARAMS, "kind": ParamSpec("elbow", "string")},
    provides=(Capability("segment"),), mounts=(mount("segment", socket_id="tip"),),
    role="arm", material="skin", tags=_common_tags("elbow", "gomito", "arm"))

FOREARM = Component(
    id="forearm",
    build=_limb_segment([(0, 0.98), (0.35, 0.88), (0.78, 0.70), (1, 0.52)],
                        "forearm", "arm"),
    children=_forearm_children,
    description="avambraccio con massa prossimale e polso stretto",
    params=dict(_SEGMENT_PARAMS), provides=(Capability("segment"),),
    mounts=(mount("segment", socket_id="tip"),),
    role="arm", material="skin", tags=_common_tags("forearm", "avambraccio", "arm"))

WRIST = Component(
    id="wrist", build=_joint, children=_wrist_children,
    description="polso: nodo gerarchico reale prima della mano",
    params={**_JOINT_PARAMS, "kind": ParamSpec("wrist", "string")},
    provides=(Capability("segment"),), mounts=(mount("segment", socket_id="tip"),),
    role="hand", material="skin", tags=_common_tags("wrist", "polso", "hand"))

THIGH = Component(
    id="thigh",
    build=_limb_segment([(0, 1.04), (0.25, 1.10), (0.72, 0.84), (1, 0.66)],
                        "thigh", "leg"),
    children=_thigh_children,
    description="coscia anatomica con massa alta e restringimento al ginocchio",
    params=dict(_SEGMENT_PARAMS), provides=(Capability("segment"),),
    mounts=(mount("segment", socket_id="tip"),),
    role="leg", material="skin", tags=_common_tags("thigh", "coscia", "leg"))

KNEE = Component(
    id="knee", build=_joint, children=_knee_children,
    description="ginocchio: nodo gerarchico reale tra coscia e polpaccio",
    params={**_JOINT_PARAMS, "kind": ParamSpec("knee", "string")},
    provides=(Capability("segment"),), mounts=(mount("segment", socket_id="tip"),),
    role="leg", material="skin", tags=_common_tags("knee", "ginocchio", "leg"))

CALF = Component(
    id="calf",
    build=_limb_segment([(0, 0.86), (0.32, 1.04), (0.70, 0.78), (1, 0.48)],
                        "calf", "leg"),
    children=_calf_children,
    description="polpaccio con volume posteriore e caviglia stretta",
    params=dict(_SEGMENT_PARAMS), provides=(Capability("segment"),),
    mounts=(mount("segment", socket_id="tip"),),
    role="leg", material="skin", tags=_common_tags("calf", "polpaccio", "leg"))

ANKLE = Component(
    id="ankle", build=_joint, children=_ankle_children,
    description="caviglia: nodo gerarchico reale prima del piede",
    params={**_JOINT_PARAMS, "kind": ParamSpec("ankle", "string")},
    provides=(Capability("segment"),), mounts=(mount("segment", socket_id="tip"),),
    role="foot", material="skin", tags=_common_tags("ankle", "caviglia", "foot"))


def _hand(v, ctx):
    length = v["length"]
    r = v["radius"]
    palm = block((length * 0.70, r * 1.55, r * 2.25), sides=4, axis=0)
    palm.apply_translation([length * 0.35, 0, 0])
    thumb = block((length * 0.40, r * 0.62, r * 0.55), sides=4, axis=0)
    thumb.apply_translation([length * 0.42, r * 0.88, -r * 0.82])
    meshes = [palm, thumb]
    if ctx.detail_level >= 3:
        offsets = [-0.78, -0.26, 0.26, 0.74]
        scales = [0.78, 0.92, 1.0, 0.72]
        for off, scale in zip(offsets, scales):
            finger = grow([(0, r * 0.18), (0.78, r * 0.16), (1, r * 0.11)],
                          sides=5, length=length * 0.42 * scale, axis=0,
                          squash=0.18)
            finger.apply_translation([length * 0.74, -r * 0.18, off * r])
            meshes.append(finger)
    mesh = _merge(*meshes)
    return Piece(mesh=mesh, material="skin", tags=("hand", "extremity"), sockets={
        "base": base_socket(r, axis="+X"),
        "palm": socket("palm", (length * 0.62, 0, 0), (1, 0, 0), up=(0, 1, 0),
                       radius=r * 0.70, provides="anchor"),
    })


HAND = Component(
    id="hand", build=_hand,
    description="mano riconoscibile con palmo, pollice e dita a detail alto",
    params=dict(_SEGMENT_PARAMS), provides=(Capability("segment"),),
    mounts=(mount("anchor", socket_id="palm"),),
    role="hand", material="skin", tags=_common_tags("hand", "mano", "extremity"))


def _foot(v, ctx):
    length = v["length"]
    r = v["radius"]
    heel = block((r * 1.25, length * 0.42, r * 1.55), sides=4, axis=1)
    heel.apply_translation([r * 0.08, length * 0.03, 0])
    mid = block((r * 1.05, length * 0.70, r * 1.28), sides=4, taper=0.86, axis=1)
    mid.apply_translation([r * 0.12, length * 0.44, 0])
    toe = block((r * 1.38, length * 0.58, r * 1.95), sides=4, taper=1.18, axis=1)
    toe.apply_translation([r * 0.18, length * 0.92, 0])
    mesh = _merge(heel, mid, toe)
    return Piece(mesh=mesh, material="skin", tags=("foot", "extremity"), sockets={
        "base": base_socket(r, axis="+X"),
        "toe": socket("toe", (r * 0.18, length * 1.22, 0), (0, 1, 0),
                      up=(1, 0, 0), radius=r * 0.52, provides="anchor"),
    })


FOOT = Component(
    id="foot", build=_foot,
    description="piede con tallone, arco accennato e avampiede",
    params=dict(_SEGMENT_PARAMS), provides=(Capability("segment"),),
    mounts=(mount("anchor", socket_id="toe"),),
    role="foot", material="skin", tags=_common_tags("foot", "piede", "extremity"))


# --------------------------------------------------------------------------- #
# Testa e volto
# --------------------------------------------------------------------------- #
def _head(v, ctx):
    hh, hw, hd = v["head_height"], v["head_width"], v["head_depth"]
    cranium = _sweep_y(hh * 0.72, hw * 0.50, hd * 0.50,
                       [(0, 0.70), (0.30, 1.0), (0.76, 0.96), (1, 0.62)],
                       squash=0.25, sides=10)
    cranium.apply_translation([0, hh * 0.26, 0])
    jaw = block((v["jaw_width"], hh * 0.30, hd * 0.70), sides=4, taper=0.76, axis=1)
    jaw.apply_translation([0, hh * 0.12, hd * 0.05])
    brow = block((v["cheek_width"], hh * 0.12, hd * 0.30), sides=4, taper=0.92, axis=2)
    brow.apply_translation([0, hh * 0.50, hd * 0.43])
    chin = block((v["jaw_width"] * 0.62, hh * 0.08, hd * 0.36), sides=4, axis=2)
    chin.apply_translation([0, hh * 0.04, hd * 0.47])
    mesh = _merge(cranium, jaw, brow, chin)
    front = hd * 0.54
    return Piece(mesh=mesh, material="skin", tags=("head",), sockets={
        "base": base_socket(hw * 0.30, axis="+Y"),
        "crown": socket("crown", (0, hh * 0.92, 0), (0, 1, 0), up=(0, 0, 1),
                        radius=hw * 0.38, provides="hair_mount"),
        "face": socket("face", (0, hh * 0.48, front), (0, 0, 1), up=(0, 1, 0),
                       radius=hw * 0.38, provides="face_mount"),
        "eye_l": socket("eye_l", (-v["eye_spacing"] * 0.5, hh * 0.56, front),
                        (-0.12, 0.03, 1), up=(0, 1, 0), radius=v["eye_size"],
                        provides="face_mount", side="l", tags=("occhio", "eye")),
        "eye_r": socket("eye_r", (v["eye_spacing"] * 0.5, hh * 0.56, front),
                        (0.12, 0.03, 1), up=(0, 1, 0), radius=v["eye_size"],
                        provides="face_mount", side="r", tags=("occhio", "eye")),
        "nose": socket("nose", (0, hh * 0.43, front * 1.02), (0, -0.05, 1),
                       up=(0, 1, 0), radius=v["nose_width"] * 0.48,
                       provides="face_mount", tags=("naso", "nose")),
        "mouth": socket("mouth", (0, hh * 0.24, front * 0.98), (0, -0.18, 1),
                        up=(0, 1, 0), radius=v["mouth_width"] * 0.32,
                        provides="face_mount", tags=("bocca", "mouth")),
        "ear_l": socket("ear_l", (-hw * 0.55, hh * 0.50, -hd * 0.02), (-1, 0, 0),
                        up=(0, 1, 0), radius=v["ear_size"] * 0.45,
                        provides="face_mount", side="l", tags=("orecchio", "ear")),
        "ear_r": socket("ear_r", (hw * 0.55, hh * 0.50, -hd * 0.02), (1, 0, 0),
                        up=(0, 1, 0), radius=v["ear_size"] * 0.45,
                        provides="face_mount", side="r", tags=("orecchio", "ear")),
    })


def _head_children(v, ctx):
    children = [
        Attachment(id="nose", component="nose", level=2, insert=0.22,
                   requirement=Requirement(capability="face_mount", tags=("nose",)),
                   params={"length": v["nose_length"], "width": v["nose_width"]}),
        Attachment(id="mouth", component="mouth", level=2, insert=0.30,
                   requirement=Requirement(capability="face_mount", tags=("mouth",)),
                   params={"width": v["mouth_width"]}),
    ]
    for side in ("l", "r"):
        children.append(Attachment(
            id="eye_" + side, component="eye", level=2, insert=0.36,
            requirement=Requirement(capability="face_mount", side=side,
                                    tags=("eye",)),
            params={"size": v["eye_size"]}))
        children.append(Attachment(
            id="ear_" + side, component="ear", level=2, insert=0.28,
            requirement=Requirement(capability="face_mount", side=side,
                                    tags=("ear",)),
            params={"size": v["ear_size"]}))
    if ctx.detail_level >= 3:
        children.append(Attachment(
            id="hair", component="hair", level=3, insert=0.45,
            requirement=Requirement(capability="hair_mount"),
            params={"width": v["head_width"], "height": v["head_height"] * 0.22}))
    return children


HEAD = Component(
    id="head", build=_head, children=_head_children,
    description="testa anatomica: cranio, mandibola, zigomi, occhi, naso, bocca e orecchie",
    params={
        "height": ParamSpec(1.8, DISTANCE, min=0.45, max=2.6,
                            semantic_role="length", derived="root.height"),
        "head_height": ParamSpec(0.24, DISTANCE, min=0.08, max=0.42,
                                 semantic_role="length",
                                 derived="root.height * 0.134"),
        "head_width": ParamSpec(0.16, DISTANCE, min=0.05, max=0.32,
                                semantic_role="girth",
                                derived="head_height * 0.66"),
        "head_depth": ParamSpec(0.19, DISTANCE, min=0.05, max=0.36,
                                semantic_role="girth",
                                derived="head_height * 0.78"),
        "jaw_width": ParamSpec(0.11, DISTANCE, min=0.03, max=0.26,
                               semantic_role="girth",
                               derived="head_width * 0.68"),
        "cheek_width": ParamSpec(0.15, DISTANCE, min=0.04, max=0.32,
                                 semantic_role="girth",
                                 derived="head_width * 0.92"),
        "eye_spacing": ParamSpec(0.082, DISTANCE, min=0.02, max=0.20,
                                 semantic_role="girth",
                                 derived="head_width * 0.52"),
        "eye_size": ParamSpec(0.020, DISTANCE, min=0.006, max=0.06,
                              semantic_role="girth",
                              derived="head_width * 0.13"),
        "nose_length": ParamSpec(0.043, DISTANCE, min=0.006, max=0.11,
                                 semantic_role="girth",
                                 derived="head_depth * 0.23"),
        "nose_width": ParamSpec(0.032, DISTANCE, min=0.006, max=0.09,
                                semantic_role="girth",
                                derived="head_width * 0.20"),
        "mouth_width": ParamSpec(0.066, DISTANCE, min=0.01, max=0.16,
                                 semantic_role="girth",
                                 derived="head_width * 0.42"),
        "ear_size": ParamSpec(0.055, DISTANCE, min=0.01, max=0.14,
                              semantic_role="girth",
                              derived="head_height * 0.23"),
    },
    constraints=(Constraint("eye_spacing < head_width * 0.75", severity=CLAMP,
                            target="eye_spacing", to="head_width * 0.70",
                            message="gli occhi devono restare dentro il cranio"),),
    provides=(Capability("head_mount"),),
    mounts=(mount("face_mount", socket_id="face"),
            mount("face_mount", socket_id="eye_l", side="l", tags=("eye", "occhio")),
            mount("face_mount", socket_id="eye_r", side="r", tags=("eye", "occhio")),
            mount("face_mount", socket_id="nose", tags=("nose", "naso")),
            mount("face_mount", socket_id="mouth", tags=("mouth", "bocca")),
            mount("face_mount", socket_id="ear_l", side="l", tags=("ear", "orecchio")),
            mount("face_mount", socket_id="ear_r", side="r", tags=("ear", "orecchio")),
            mount("hair_mount", socket_id="crown")),
    role="head", material="skin", requires=frozenset({"connected"}),
    tags=_common_tags("head", "testa", "face", "viso"))


def _eye(v, ctx):
    s = v["size"]
    eyeball = grow([(0, s * 0.70), (0.5, s), (1, s * 0.58)], sides=FACE_SIDES,
                   length=s * 0.72, axis=2, squash=0.18)
    iris = block((s * 0.64, s * 0.64, s * 0.08), sides=6, axis=2)
    iris.apply_translation([0, 0, s * 0.72])
    return Piece(mesh=_merge(eyeball, iris), material="eye", tags=("eye", "detail"),
                 sockets={"base": base_socket(s * 0.75, axis="+Z")})


EYE = Component(
    id="eye", build=_eye, description="occhio con bulbo e piano dell'iride",
    params={"size": ParamSpec(0.02, DISTANCE, min=0.004, max=0.08,
                              semantic_role="girth")},
    provides=(Capability("face_mount"),),
    role="face", material="eye", tags=_common_tags("eye", "occhio", "face"))


def _nose(v, ctx):
    width = v["width"]
    length = v["length"]
    bridge = grow([(0, width * 0.36), (0.78, width * 0.30), (1, width * 0.18)],
                  sides=5, length=length, axis=2, squash=0.25)
    tip = block((width * 0.80, width * 0.50, width * 0.34), sides=4, axis=2)
    tip.apply_translation([0, -width * 0.05, length * 0.88])
    return Piece(mesh=_merge(bridge, tip), material="skin", tags=("nose", "detail"),
                 sockets={
                     "base": base_socket(width * 0.42, axis="+Z"),
                     "tip": socket("tip", (0, -width * 0.05, length * 1.04),
                                   (0, -0.1, 1), up=(0, 1, 0),
                                   radius=width * 0.22, provides="anchor"),
                 })


NOSE = Component(
    id="nose", build=_nose, description="naso con dorso, punta e aggancio in punta",
    params={"length": ParamSpec(0.04, DISTANCE, min=0.004, max=0.14,
                                semantic_role="girth"),
            "width": ParamSpec(0.03, DISTANCE, min=0.004, max=0.10,
                               semantic_role="girth")},
    provides=(Capability("face_mount"),),
    mounts=(mount("anchor", socket_id="tip"),),
    role="face", material="skin", tags=_common_tags("nose", "naso", "face"))


def _mouth(v, ctx):
    w = v["width"]
    upper = block((w, w * 0.13, w * 0.12), sides=4, axis=2)
    upper.apply_translation([0, w * 0.08, 0])
    lower = block((w * 0.92, w * 0.16, w * 0.12), sides=4, axis=2)
    lower.apply_translation([0, -w * 0.08, 0])
    return Piece(mesh=_merge(upper, lower), material="mouth", tags=("mouth", "detail"),
                 sockets={"base": base_socket(w * 0.32, axis="+Z")})


MOUTH = Component(
    id="mouth", build=_mouth, description="bocca con labbro superiore e inferiore",
    params={"width": ParamSpec(0.06, DISTANCE, min=0.008, max=0.18,
                               semantic_role="girth")},
    provides=(Capability("face_mount"),),
    role="face", material="mouth", tags=_common_tags("mouth", "bocca", "face"))


def _ear(v, ctx):
    s = v["size"]
    outer = grow([(0, s * 0.36), (0.52, s * 0.50), (1, s * 0.24)],
                 sides=FACE_SIDES, length=s * 1.20, axis=1, flat=0.34, squash=0.28)
    inner = block((s * 0.18, s * 0.56, s * 0.10), sides=4, axis=2)
    inner.apply_translation([0, s * 0.40, s * 0.10])
    return Piece(mesh=_merge(outer, inner), material="skin", tags=("ear", "detail"),
                 sockets={"base": base_socket(s * 0.36, axis="+X")})


EAR = Component(
    id="ear", build=_ear, description="orecchio con padiglione e cavita' accennata",
    params={"size": ParamSpec(0.05, DISTANCE, min=0.008, max=0.16,
                              semantic_role="girth")},
    provides=(Capability("face_mount"),),
    role="face", material="skin", tags=_common_tags("ear", "orecchio", "face"))


def _hair(v, ctx):
    mesh = _sweep_y(v["height"], v["width"] * 0.55, v["width"] * 0.48,
                    [(0, 0.94), (0.52, 1.0), (0.90, 0.70), (1, 0.36)],
                    squash=0.30)
    return Piece(mesh=mesh, material="hair", tags=("hair", "detail"), sockets={
        "base": base_socket(v["width"] * 0.42, axis="+Y"),
        "top": socket("top", (0, v["height"], 0), (0, 1, 0), up=(0, 0, 1),
                      radius=v["width"] * 0.25, provides="gear_mount"),
    })


HAIR = Component(
    id="hair", build=_hair, description="massa di capelli come calotta modellata",
    params={"width": ParamSpec(0.16, DISTANCE, min=0.03, max=0.40,
                               semantic_role="girth"),
            "height": ParamSpec(0.08, DISTANCE, min=0.01, max=0.20,
                                semantic_role="length")},
    provides=(Capability("hair_mount"),),
    mounts=(mount("gear_mount", socket_id="top"),),
    role="head", material="hair", tags=_common_tags("hair", "capelli"))
