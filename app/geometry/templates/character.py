"""Generatore parametrico di figure umanoidi e robot.

La struttura segue una gerarchia anatomica (testa, torso, braccia, gambe):
e' la base su cui, in una fase successiva, si potra' innestare uno scheletro
per il rigging.
"""
from __future__ import annotations

from typing import Any

from app.core.spec import ComponentSpec, MaterialSpec
from app.geometry.templates import ParamDef, Template, register
from app.geometry.templates import humanoid_body
from app.geometry.templates._common import C, rounding, sections, smoothness

MATERIALS = {
    "armor":  MaterialSpec(name="armor", base_color="#7d848c", roughness=0.35, metallic=0.85),
    "joint":  MaterialSpec(name="joint", base_color="#2b2e33", roughness=0.6, metallic=0.4),
    "accent": MaterialSpec(name="accent", base_color="#c2591f", roughness=0.45, metallic=0.3),
    "visor":  MaterialSpec(name="visor", base_color="#39c2d6", roughness=0.1, metallic=0.2, opacity=0.9),
    "skin":   MaterialSpec(name="skin", base_color="#c99a72", roughness=0.7, metallic=0.0),
}

PARAMS = {
    "height":        ParamDef(1.8, 0.5, 6.0, desc="altezza totale in metri"),
    "build":         ParamDef("normal", choices=["slim", "normal", "heavy", "bulky"],
                              desc="corporatura"),
    "head_scale":    ParamDef(1.0, 0.5, 2.2, desc="fattore di scala della testa"),
    "shoulder_width": ParamDef(1.0, 0.6, 2.0, desc="fattore di larghezza spalle"),
    "leg_ratio":     ParamDef(0.48, 0.3, 0.62, desc="frazione di altezza occupata dalle gambe"),
    "mechanical":    ParamDef(True, desc="aspetto robotico con giunti sferici visibili"),
    "has_visor":     ParamDef(True, desc="visiera luminosa al posto del volto"),
    "has_backpack":  ParamDef(False, desc="zaino o reattore dorsale"),
    "has_antenna":   ParamDef(False, desc="antenna sulla testa"),
    "has_shoulder_pads": ParamDef(True, desc="spallacci"),
    "arm_thickness": ParamDef(1.0, 0.5, 2.2, desc="fattore di spessore delle braccia"),
}

BUILD_FACTOR = {"slim": 0.82, "normal": 1.0, "heavy": 1.18, "bulky": 1.4}


def build(p: dict[str, Any]) -> list[ComponentSpec]:
    style = p.get("_density", 1.0)
    sec = sections(style, 20)
    sub = smoothness(style)
    mech = p["mechanical"]
    body_mat = "armor" if mech else "skin"

    H = p["height"]
    bf = BUILD_FACTOR.get(p["build"], 1.0)
    leg_h = H * p["leg_ratio"]
    torso_h = H * 0.30
    head_h = H * 0.13 * p["head_scale"]
    neck_h = H * 0.035

    hip_w = H * 0.115 * bf
    shoulder_w = H * 0.14 * bf * p["shoulder_width"]
    torso_d = H * 0.09 * bf
    limb_r = H * 0.033 * bf * p["arm_thickness"]

    y_hip = leg_h
    y_shoulder = y_hip + torso_h
    parts: list[ComponentSpec] = []

    # --- gambe ------------------------------------------------------------- #
    thigh_h, shin_h = leg_h * 0.5, leg_h * 0.42
    for side, sx in (("l", -1), ("r", 1)):
        px = sx * hip_w * 0.5
        parts.append(C("foot_" + side, "rounded_box",
                       {"size": (limb_r * 2.1, leg_h * 0.06, limb_r * 3.4),
                        "radius": rounding(style, 0.02), "subdiv": sub},
                       pos=(px, leg_h * 0.03, limb_r * 0.7), mat=body_mat,
                       name="Piede " + side.upper(), tags=["leg", "foot", side]))
        parts.append(C("shin_" + side, "capsule",
                       {"radius": limb_r * 0.82, "height": shin_h, "count": max(6, sec // 2)},
                       pos=(px, leg_h * 0.06 + shin_h / 2, 0),
                       mat=body_mat, name="Stinco " + side.upper(), tags=["leg", side]))
        parts.append(C("thigh_" + side, "capsule",
                       {"radius": limb_r * 1.0, "height": thigh_h, "count": max(6, sec // 2)},
                       pos=(px, leg_h - thigh_h / 2, 0),
                       mat=body_mat, name="Coscia " + side.upper(), tags=["leg", side]))
        if mech:
            parts.append(C("knee_" + side, "sphere", {"radius": limb_r * 1.05, "subdiv": sub},
                           pos=(px, leg_h * 0.06 + shin_h, 0), mat="joint",
                           name="Ginocchio " + side.upper(), tags=["joint", side]))
            parts.append(C("hip_joint_" + side, "sphere", {"radius": limb_r * 1.1, "subdiv": sub},
                           pos=(px, y_hip, 0), mat="joint",
                           name="Anca " + side.upper(), tags=["joint", side]))

    # --- torso ------------------------------------------------------------- #
    parts.append(C("pelvis", "rounded_box",
                   {"size": (hip_w * 1.25, torso_h * 0.3, torso_d * 1.05),
                    "radius": rounding(style, 0.04), "subdiv": sub},
                   pos=(0, y_hip + torso_h * 0.14, 0), mat=body_mat,
                   name="Bacino", tags=["torso"]))
    parts.append(C("torso", "hexahedron",
                   {"bottom": (hip_w * 1.15, torso_d), "top": (shoulder_w, torso_d * 1.15),
                    "height": torso_h * 0.82},
                   pos=(0, y_hip + torso_h * 0.3 + torso_h * 0.41, 0), mat=body_mat,
                   name="Torso", tags=["torso", "main"]))
    parts.append(C("chest_plate", "rounded_box",
                   {"size": (shoulder_w * 0.78, torso_h * 0.34, torso_d * 0.34),
                    "radius": rounding(style, 0.03), "subdiv": sub},
                   pos=(0, y_shoulder - torso_h * 0.24, torso_d * 0.5), mat="accent",
                   name="Pettorale", tags=["torso"]))

    # --- testa ------------------------------------------------------------- #
    parts.append(C("neck", "cylinder",
                   {"radius": limb_r * 0.75, "height": neck_h * 2, "sections": max(6, sec // 2)},
                   pos=(0, y_shoulder + neck_h * 0.4, 0), mat="joint", name="Collo", tags=["head"]))
    y_head = y_shoulder + neck_h + head_h / 2
    parts.append(C("head", "rounded_box",
                   {"size": (head_h * 0.78, head_h, head_h * 0.85),
                    "radius": rounding(style, head_h * 0.18), "subdiv": sub},
                   pos=(0, y_head, 0), mat=body_mat, name="Testa", tags=["head", "main"]))
    if p["has_visor"]:
        parts.append(C("visor", "rounded_box",
                       {"size": (head_h * 0.62, head_h * 0.26, head_h * 0.16),
                        "radius": rounding(style, head_h * 0.05), "subdiv": sub},
                       pos=(0, y_head + head_h * 0.08, head_h * 0.42), mat="visor",
                       name="Visiera", tags=["head", "visor"]))
    else:
        for side, sx in (("l", -1), ("r", 1)):
            parts.append(C("eye_" + side, "sphere", {"radius": head_h * 0.08, "subdiv": 2},
                           pos=(sx * head_h * 0.19, y_head + head_h * 0.08, head_h * 0.4),
                           mat="visor", name="Occhio " + side.upper(), tags=["head"]))
    if p["has_antenna"]:
        parts.append(C("antenna", "cylinder",
                       {"radius": head_h * 0.03, "height": head_h * 0.8, "sections": 8},
                       pos=(head_h * 0.25, y_head + head_h * 0.85, 0), mat="joint",
                       name="Antenna", tags=["head"]))
        parts.append(C("antenna_tip", "sphere", {"radius": head_h * 0.07, "subdiv": 2},
                       pos=(head_h * 0.25, y_head + head_h * 1.25, 0), mat="accent",
                       name="Punta antenna", tags=["head"]))

    # --- braccia ----------------------------------------------------------- #
    upper_h, fore_h = torso_h * 0.52, torso_h * 0.46
    for side, sx in (("l", -1), ("r", 1)):
        px = sx * (shoulder_w / 2 + limb_r * 1.05)   # staccate dal torso, altrimenti si fondono
        if p["has_shoulder_pads"]:
            parts.append(C("pad_" + side, "rounded_box",
                           {"size": (limb_r * 2.3, limb_r * 1.7, limb_r * 2.6),
                            "radius": rounding(style, limb_r * 0.4), "subdiv": sub},
                           pos=(px, y_shoulder - limb_r * 0.2, 0), mat="accent",
                           name="Spallaccio " + side.upper(), tags=["arm", "pad", side]))
        if mech:
            parts.append(C("shoulder_" + side, "sphere", {"radius": limb_r * 0.95, "subdiv": sub},
                           pos=(px, y_shoulder - limb_r * 0.5, 0), mat="joint",
                           name="Spalla " + side.upper(), tags=["joint", side]))
        y_elbow = y_shoulder - limb_r * 0.5 - upper_h
        parts.append(C("upperarm_" + side, "capsule",
                       {"radius": limb_r * 0.72, "height": upper_h, "count": max(6, sec // 2)},
                       pos=(px, y_elbow + upper_h / 2, 0), mat=body_mat,
                       name="Braccio " + side.upper(), tags=["arm", side]))
        if mech:
            parts.append(C("elbow_" + side, "sphere", {"radius": limb_r * 0.78, "subdiv": sub},
                           pos=(px, y_elbow, 0), mat="joint",
                           name="Gomito " + side.upper(), tags=["joint", side]))
        parts.append(C("forearm_" + side, "capsule",
                       {"radius": limb_r * 0.62, "height": fore_h, "count": max(6, sec // 2)},
                       pos=(px, y_elbow - fore_h / 2, 0), mat=body_mat,
                       name="Avambraccio " + side.upper(), tags=["arm", side]))
        parts.append(C("hand_" + side, "rounded_box",
                       {"size": (limb_r * 1.15, limb_r * 1.5, limb_r * 0.75),
                        "radius": rounding(style, limb_r * 0.25), "subdiv": sub},
                       pos=(px, y_elbow - fore_h - limb_r * 0.65, 0), mat="joint",
                       name="Mano " + side.upper(), tags=["arm", "hand", side]))

    if p["has_backpack"]:
        parts.append(C("backpack", "rounded_box",
                       {"size": (shoulder_w * 0.7, torso_h * 0.55, torso_d * 0.55),
                        "radius": rounding(style, 0.03), "subdiv": sub},
                       pos=(0, y_shoulder - torso_h * 0.3, -torso_d * 0.75), mat="joint",
                       name="Zaino", tags=["backpack"]))
        for side, sx in (("l", -1), ("r", 1)):
            parts.append(C("thruster_" + side, "cylinder",
                           {"radius": limb_r * 0.55, "height": torso_h * 0.3, "sections": max(6, sec // 2)},
                           pos=(sx * shoulder_w * 0.22, y_shoulder - torso_h * 0.55, -torso_d * 0.85),
                           mat="accent", name="Propulsore " + side.upper(), tags=["backpack"]))
    return parts


register(Template(
    name="humanoid", category="personaggi",
    description="Figura umanoide o robot parametrico con gerarchia anatomica",
    params=PARAMS, materials=MATERIALS, build=build,
    assembly=humanoid_body.assembly,
    primary_material="armor",
    keywords=["robot", "umanoide", "humanoid", "personaggio", "character", "mech",
              "androide", "cavaliere", "knight", "soldato", "figura", "omino"],
))
