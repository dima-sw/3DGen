"""Generatore parametrico di armi bianche: spade, asce, mazze."""
from __future__ import annotations

from typing import Any

from app.core.spec import ComponentSpec, MaterialSpec
from app.geometry.templates import ParamDef, Template, register
from app.geometry.templates._common import C, sections

MATERIALS = {
    "blade":   MaterialSpec(name="blade", base_color="#c3c9d1", roughness=0.16, metallic=1.0),
    "guard":   MaterialSpec(name="guard", base_color="#b08d3f", roughness=0.3, metallic=0.9),
    "grip":    MaterialSpec(name="grip", base_color="#4a2f22", roughness=0.9, metallic=0.0),
    "gem":     MaterialSpec(name="gem", base_color="#b2312f", roughness=0.08, metallic=0.2, opacity=0.85),
    "wood":    MaterialSpec(name="wood", base_color="#6b4526", roughness=0.75, metallic=0.0),
    "fuller":  MaterialSpec(name="fuller", base_color="#8d949c", roughness=0.3, metallic=1.0),
}

PARAMS = {
    "weapon_type":  ParamDef("sword", choices=["sword", "dagger", "axe", "mace", "spear"],
                             desc="tipo di arma"),
    "blade_length": ParamDef(0.85, 0.15, 2.4, desc="lunghezza della lama o dell asta"),
    "blade_width":  ParamDef(0.09, 0.02, 0.35, desc="larghezza della lama"),
    "blade_thickness": ParamDef(0.018, 0.005, 0.08, desc="spessore della lama"),
    "grip_length":  ParamDef(0.22, 0.08, 0.8, desc="lunghezza dell impugnatura"),
    "guard_width":  ParamDef(0.26, 0.0, 0.7, desc="larghezza dell elsa, 0 = assente"),
    "has_pommel":   ParamDef(True, desc="pomolo in fondo all impugnatura"),
    "has_fuller":   ParamDef(True, desc="sguscio centrale della lama"),
    "has_gem":      ParamDef(False, desc="gemma incastonata nel pomolo"),
    "curved":       ParamDef(False, desc="lama curva, tipo sciabola"),
}


def build(p: dict[str, Any]) -> list[ComponentSpec]:
    style = p.get("_density", 1.0)
    sec = sections(style, 20)
    wt = p["weapon_type"]
    bl, bw, bt = p["blade_length"], p["blade_width"], p["blade_thickness"]
    gl, gw = p["grip_length"], p["guard_width"]
    parts: list[ComponentSpec] = []

    # impugnatura, sempre presente, alla base (y da 0 a gl)
    parts.append(C("grip", "cylinder", {"radius": bw * 0.32, "height": gl, "sections": max(6, sec)},
                   pos=(0, gl / 2, 0), mat="grip", name="Impugnatura", tags=["grip", "main"]))
    for i in range(4):
        parts.append(C("grip_wrap_%d" % i, "torus",
                       {"radius": bw * 0.36, "tube": bw * 0.05, "sections": max(8, sec)},
                       pos=(0, gl * (0.18 + 0.21 * i), 0),
                       mat="guard", name="Legatura", tags=["grip"]))

    if p["has_pommel"]:
        parts.append(C("pommel", "sphere", {"radius": bw * 0.45, "subdiv": 2},
                       pos=(0, -bw * 0.2, 0), mat="guard", name="Pomolo", tags=["pommel"]))
        if p["has_gem"]:
            parts.append(C("gem", "sphere", {"radius": bw * 0.2, "subdiv": 2},
                           pos=(0, -bw * 0.35, bw * 0.3), mat="gem", name="Gemma", tags=["gem"]))

    if gw > 0.01 and wt in ("sword", "dagger"):
        parts.append(C("guard", "rounded_box",
                       {"size": (gw, bw * 0.35, bt * 3.2), "radius": bt, "subdiv": 2},
                       pos=(0, gl + bw * 0.15, 0), mat="guard", name="Elsa", tags=["guard"]))

    y_base = gl + bw * 0.3

    if wt in ("sword", "dagger"):
        tip = bl * 0.18
        prof = [(-bw / 2, y_base), (bw / 2, y_base),
                (bw * 0.46, y_base + bl - tip), (0.0, y_base + bl), (-bw * 0.46, y_base + bl - tip)]
        parts.append(C("blade", "prism", {"profile": prof, "depth": bt},
                       rot=(0, 90, 0), mat="blade", name="Lama", tags=["blade", "main"]))
        if p["has_fuller"]:
            parts.append(C("fuller", "box", {"size": (bw * 0.22, bl * 0.78, bt * 1.1)},
                           pos=(0, y_base + bl * 0.42, 0), mat="fuller",
                           name="Sguscio", tags=["blade"]))
    elif wt == "spear":
        parts.append(C("shaft", "cylinder",
                       {"radius": bw * 0.22, "height": bl * 0.8, "sections": max(6, sec)},
                       pos=(0, y_base + bl * 0.4, 0), mat="wood", name="Asta", tags=["shaft", "main"]))
        prof = [(-bw / 2, 0.0), (bw / 2, 0.0), (0.0, bl * 0.28)]
        parts.append(C("head", "prism", {"profile": prof, "depth": bt * 2},
                       pos=(0, y_base + bl * 0.8, 0), rot=(0, 90, 0),
                       mat="blade", name="Punta", tags=["blade"]))
    elif wt == "axe":
        parts.append(C("shaft", "cylinder",
                       {"radius": bw * 0.22, "height": bl, "sections": max(6, sec)},
                       pos=(0, y_base + bl / 2, 0), mat="wood", name="Manico", tags=["shaft", "main"]))
        prof = [(0.0, -bw * 1.1), (bw * 1.9, -bw * 1.5), (bw * 2.1, bw * 1.5), (0.0, bw * 1.1)]
        parts.append(C("head", "prism", {"profile": prof, "depth": bt * 2.5},
                       pos=(0, y_base + bl * 0.9, 0), rot=(0, 90, 0),
                       mat="blade", name="Testa ascia", tags=["blade"]))
    else:  # mace
        parts.append(C("shaft", "cylinder",
                       {"radius": bw * 0.22, "height": bl, "sections": max(6, sec)},
                       pos=(0, y_base + bl / 2, 0), mat="wood", name="Manico", tags=["shaft", "main"]))
        parts.append(C("head", "sphere", {"radius": bw * 1.2, "subdiv": 2},
                       pos=(0, y_base + bl, 0), mat="blade", name="Testa mazza", tags=["blade"]))
        for i in range(8):
            import math
            a = i * math.pi / 4
            parts.append(C("spike_%d" % i, "cone",
                           {"radius": bw * 0.28, "height": bw * 0.7, "sections": max(5, sec // 3)},
                           pos=(bw * 1.35 * math.cos(a), y_base + bl, bw * 1.35 * math.sin(a)),
                           rot=(0, 0, -90 if math.cos(a) > 0 else 90),
                           mat="blade", name="Punta", tags=["spike"]))
    return parts


register(Template(
    name="weapon", category="armi",
    description="Arma bianca parametrica: spada, pugnale, ascia, mazza, lancia",
    params=PARAMS, materials=MATERIALS, build=build,
    primary_material="blade",
    keywords=["spada", "sword", "pugnale", "dagger", "ascia", "axe", "mazza", "mace",
              "lancia", "spear", "arma", "weapon", "katana", "sciabola"],
))
