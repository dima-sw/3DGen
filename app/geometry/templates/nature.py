"""Generatori naturali: alberi e rocce, con ramificazione ricorsiva."""
from __future__ import annotations

import math
import random
from typing import Any

from app.core.spec import ComponentSpec, MaterialSpec
from app.geometry.templates import ParamDef, Template, register
from app.geometry.templates._common import C, sections, smoothness

MATERIALS = {
    "bark":   MaterialSpec(name="bark", base_color="#5b4130", roughness=0.95, metallic=0.0),
    "leaves": MaterialSpec(name="leaves", base_color="#3f7a35", roughness=0.85, metallic=0.0),
    "rock":   MaterialSpec(name="rock", base_color="#7b7770", roughness=0.92, metallic=0.0),
}

PARAMS = {
    "height":       ParamDef(5.0, 0.5, 25.0, desc="altezza totale dell albero"),
    "trunk_radius": ParamDef(0.22, 0.03, 1.5, desc="raggio del tronco alla base"),
    "branch_levels": ParamDef(2, 0, 4, desc="livelli di ramificazione ricorsiva"),
    "branches_per_level": ParamDef(4, 2, 7, desc="rami per livello"),
    "canopy_style": ParamDef("blob", choices=["blob", "conifer", "palm", "bare"],
                             desc="forma della chioma"),
    "canopy_size":  ParamDef(1.0, 0.3, 2.5, desc="fattore di dimensione della chioma"),
    "lean":         ParamDef(0.0, -25.0, 25.0, desc="inclinazione del tronco in gradi"),
    "seed":         ParamDef(7, 0, 100000, desc="seme casuale, cambia la variante"),
}


def build(p: dict[str, Any]) -> list[ComponentSpec]:
    style = p.get("_density", 1.0)
    sec = sections(style, 14)
    sub = smoothness(style)
    rng = random.Random(int(p["seed"]))

    H = p["height"]
    tr = p["trunk_radius"]
    canopy = p["canopy_style"]
    cs = p["canopy_size"]
    trunk_h = H * (0.62 if canopy == "conifer" else 0.55 if canopy != "palm" else 0.82)
    parts: list[ComponentSpec] = []

    parts.append(C("trunk", "cylinder", {"radius": tr, "height": trunk_h, "sections": max(5, sec)},
                   pos=(0, trunk_h / 2, 0), rot=(0, 0, p["lean"] * 0.4),
                   mat="bark", name="Tronco", tags=["trunk", "main"]))
    parts.append(C("root_flare", "cone",
                   {"radius": tr * 1.9, "height": tr * 2.4, "sections": max(5, sec)},
                   pos=(0, tr * 1.2, 0), mat="bark",
                   name="Ceppo", tags=["trunk"]))

    levels = int(p["branch_levels"])
    per = int(p["branches_per_level"])
    tips: list[tuple[float, float, float, float]] = []  # x, y, z, raggio

    # conifere e palme non mostrano rami sporgenti: sarebbero monconi nella chioma
    if canopy in ("blob", "bare"):
        for lv in range(levels):
            t = 0.55 + 0.35 * (lv / max(levels, 1))
            by = trunk_h * t
            blen = H * 0.22 * (1 - 0.25 * lv)
            br = tr * (0.45 - 0.1 * lv)
            for i in range(per):
                a = (i / per) * math.tau + rng.uniform(-0.3, 0.3) + lv * 0.7
                tilt = rng.uniform(28, 52)
                dx, dz = math.cos(a), math.sin(a)
                cx = dx * blen * 0.5 * math.sin(math.radians(tilt))
                cz = dz * blen * 0.5 * math.sin(math.radians(tilt))
                cy = by + blen * 0.5 * math.cos(math.radians(tilt))
                parts.append(C("branch_%d_%d" % (lv, i), "cylinder",
                               {"radius": max(br, 0.012), "height": blen, "sections": max(4, sec // 2)},
                               pos=(cx, cy, cz),
                               rot=(tilt * dz, 0.0, -tilt * dx),
                               mat="bark", name="Ramo %d.%d" % (lv, i), tags=["branch"]))
                tips.append((cx * 2, by + blen * math.cos(math.radians(tilt)), cz * 2, blen))

    if canopy == "blob":
        parts.append(C("canopy_main", "sphere",
                       {"radius": H * 0.26 * cs, "subdiv": max(1, sub)},
                       pos=(0, trunk_h + H * 0.16 * cs, 0), mat="leaves",
                       name="Chioma", tags=["canopy", "main"]))
        for i, (tx, ty, tz, bl) in enumerate(tips):
            parts.append(C("canopy_%d" % i, "sphere",
                           {"radius": max(bl * 0.55 * cs, 0.1), "subdiv": max(1, sub - 1)},
                           pos=(tx, ty + bl * 0.15, tz), mat="leaves",
                           name="Fogliame %d" % i, tags=["canopy"]))
    elif canopy == "conifer":
        n = 4 + levels
        for i in range(n):
            f = i / n
            parts.append(C("cone_%d" % i, "cone",
                           {"radius": H * 0.24 * cs * (1 - f * 0.72), "height": H * 0.26,
                            "sections": max(5, sec)},
                           pos=(0, trunk_h * 0.55 + H * 0.42 * f, 0), mat="leaves",
                           name="Palco %d" % (i + 1), tags=["canopy"]))
    elif canopy == "palm":
        for i in range(7):
            a = i * math.tau / 7
            parts.append(C("frond_%d" % i, "prism",
                           {"profile": [(0.0, 0.0), (H * 0.3 * cs, H * 0.05 * cs),
                                        (H * 0.34 * cs, -H * 0.02 * cs), (0.0, -H * 0.03 * cs)],
                            "depth": 0.03},
                           pos=(0, trunk_h, 0), rot=(0, math.degrees(a), -22),
                           mat="leaves", name="Foglia %d" % (i + 1), tags=["canopy"]))
    return parts


register(Template(
    name="tree", category="natura",
    description="Albero parametrico con ramificazione: latifoglia, conifera, palma, secco",
    params=PARAMS, materials=MATERIALS, build=build,
    primary_material="leaves",
    keywords=["albero", "tree", "pianta", "conifera", "pino", "palma", "quercia", "bosco"],
))


ROCK_PARAMS = {
    "size":      ParamDef(1.0, 0.1, 8.0, desc="dimensione media del masso"),
    "count":     ParamDef(1, 1, 12, desc="numero di massi nel gruppo"),
    "roughness": ParamDef(0.5, 0.0, 1.0, desc="irregolarita della forma"),
    "seed":      ParamDef(3, 0, 100000, desc="seme casuale"),
}


def build_rock(p: dict[str, Any]) -> list[ComponentSpec]:
    style = p.get("_density", 1.0)
    sub = smoothness(style)
    rng = random.Random(int(p["seed"]))
    s = p["size"]
    parts: list[ComponentSpec] = []
    for i in range(int(p["count"])):
        r = s * rng.uniform(0.45, 1.0) * (1.0 if i == 0 else 0.6)
        ang = rng.uniform(0, math.tau)
        dist = 0.0 if i == 0 else s * rng.uniform(0.6, 1.6)
        parts.append(C("rock_%d" % i, "sphere",
                       {"radius": r, "subdiv": max(1, sub - 1)},
                       pos=(math.cos(ang) * dist, r * 0.62, math.sin(ang) * dist),
                       scale=(rng.uniform(0.8, 1.3), rng.uniform(0.55, 0.95), rng.uniform(0.8, 1.3)),
                       rot=(rng.uniform(0, 40), rng.uniform(0, 360), rng.uniform(0, 40)),
                       mat="rock", name="Masso %d" % (i + 1), tags=["rock", "main"]))
    return parts


register(Template(
    name="rock", category="natura",
    description="Masso o gruppo di rocce",
    params=ROCK_PARAMS, materials=MATERIALS, build=build_rock,
    primary_material="rock",
    keywords=["roccia", "rock", "masso", "sasso", "pietra", "boulder"],
))
