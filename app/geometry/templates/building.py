"""Generatore parametrico di edifici semplici."""
from __future__ import annotations

from typing import Any

from app.core.spec import ComponentSpec, MaterialSpec
from app.geometry.templates import ParamDef, Template, register
from app.geometry.templates._common import C, sections

MATERIALS = {
    "wall":   MaterialSpec(name="wall", base_color="#d8cdb8", roughness=0.85, metallic=0.0),
    "roof":   MaterialSpec(name="roof", base_color="#8c3b2c", roughness=0.8, metallic=0.0),
    "wood":   MaterialSpec(name="wood", base_color="#6b4526", roughness=0.7, metallic=0.0),
    "glass":  MaterialSpec(name="glass", base_color="#9fc4d8", roughness=0.06, metallic=0.0, opacity=0.5),
    "stone":  MaterialSpec(name="stone", base_color="#8f8d88", roughness=0.9, metallic=0.0),
}

PARAMS = {
    "width":        ParamDef(8.0, 2.0, 40.0, desc="larghezza dell edificio"),
    "depth":        ParamDef(6.0, 2.0, 40.0, desc="profondita dell edificio"),
    "floor_height": ParamDef(2.8, 2.0, 5.0, desc="altezza di un piano"),
    "floors":       ParamDef(1, 1, 12, desc="numero di piani"),
    "roof_type":    ParamDef("gable", choices=["gable", "flat", "hip"], desc="tipo di tetto"),
    "roof_height":  ParamDef(2.0, 0.2, 6.0, desc="altezza del tetto"),
    "roof_overhang": ParamDef(0.35, 0.0, 1.2, desc="sporgenza della gronda"),
    "windows_per_side": ParamDef(3, 0, 10, desc="finestre per lato lungo"),
    "has_door":     ParamDef(True, desc="porta di ingresso"),
    "has_chimney":  ParamDef(True, desc="comignolo"),
    "has_porch":    ParamDef(False, desc="portico di ingresso"),
    "has_foundation": ParamDef(True, desc="zoccolo di fondazione in pietra"),
}


def build(p: dict[str, Any]) -> list[ComponentSpec]:
    style = p.get("_density", 1.0)
    sec = sections(style, 20)
    W, D = p["width"], p["depth"]
    fh, floors = p["floor_height"], int(p["floors"])
    H = fh * floors
    parts: list[ComponentSpec] = []

    if p["has_foundation"]:
        parts.append(C("foundation", "box", {"size": (W + 0.3, 0.4, D + 0.3)},
                       pos=(0, 0.2, 0), mat="stone", name="Fondazione", tags=["foundation"]))
    y0 = 0.4 if p["has_foundation"] else 0.0

    parts.append(C("walls", "box", {"size": (W, H, D)},
                   pos=(0, y0 + H / 2, 0), mat="wall", name="Muri", tags=["wall", "main"]))

    for f in range(floors):
        if f > 0:
            parts.append(C("band_%d" % f, "box", {"size": (W + 0.08, 0.12, D + 0.08)},
                           pos=(0, y0 + f * fh, 0), mat="stone",
                           name="Marcapiano %d" % f, tags=["band"]))
        n = int(p["windows_per_side"])
        wy = y0 + f * fh + fh * 0.55
        for i in range(n):
            wx = (i - (n - 1) / 2) * (W * 0.8 / max(n, 1))
            for side, sz in (("f", 1), ("b", -1)):
                parts.append(C("win_%s_%d_%d" % (side, f, i), "box",
                               {"size": (W * 0.8 / max(n, 1) * 0.5, fh * 0.42, 0.08)},
                               pos=(wx, wy, sz * (D / 2 + 0.01)), mat="glass",
                               name="Finestra", tags=["window", "glass"]))
                parts.append(C("winframe_%s_%d_%d" % (side, f, i), "box",
                               {"size": (W * 0.8 / max(n, 1) * 0.58, fh * 0.5, 0.05)},
                               pos=(wx, wy, sz * (D / 2 + 0.005)), mat="wood",
                               name="Telaio", tags=["window"]))

    if p["has_door"]:
        parts.append(C("door", "box", {"size": (0.95, fh * 0.75, 0.1)},
                       pos=(0, y0 + fh * 0.375, D / 2 + 0.02), mat="wood",
                       name="Porta", tags=["door"]))
        parts.append(C("door_knob", "sphere", {"radius": 0.05, "subdiv": 2},
                       pos=(0.32, y0 + fh * 0.4, D / 2 + 0.08), mat="stone",
                       name="Maniglia", tags=["door"]))

    over = p["roof_overhang"]
    rh = p["roof_height"]
    roof_type = p["roof_type"]
    ry = y0 + H

    if roof_type == "flat":
        parts.append(C("roof", "box", {"size": (W + over, 0.25, D + over)},
                       pos=(0, ry + 0.12, 0), mat="roof", name="Tetto piano", tags=["roof"]))
        parts.append(C("parapet", "box", {"size": (W + over, 0.45, D + over)},
                       pos=(0, ry + 0.25, 0), mat="wall", name="Parapetto", tags=["roof"]))
    elif roof_type == "hip":
        parts.append(C("roof", "hexahedron",
                       {"bottom": (W + over, D + over), "top": (W * 0.18, D * 0.18), "height": rh},
                       pos=(0, ry + rh / 2, 0), mat="roof", name="Tetto a padiglione", tags=["roof"]))
    else:
        hw = (W + over) / 2
        parts.append(C("roof", "prism",
                       {"profile": [(-(D + over) / 2, 0.0), ((D + over) / 2, 0.0), (0.0, rh)],
                        "depth": W + over},
                       pos=(0, ry, 0), mat="roof", name="Tetto a capanna", tags=["roof"]))
        for side, sz in (("f", 1), ("b", -1)):
            parts.append(C("gable_%s" % side, "prism",
                           {"profile": [(-W / 2, 0.0), (W / 2, 0.0), (0.0, rh * (1 - over / max(D, 0.1)))],
                            "depth": 0.12},
                           pos=(0, ry, sz * D / 2), rot=(0, 90, 0), mat="wall",
                           name="Timpano", tags=["roof"]))
        _ = hw

    if p["has_chimney"] and roof_type != "flat":
        parts.append(C("chimney", "box", {"size": (0.6, rh * 0.9 + 0.5, 0.6)},
                       pos=(W * 0.28, ry + rh * 0.55, -D * 0.18), mat="stone",
                       name="Comignolo", tags=["chimney"]))
        parts.append(C("chimney_cap", "box", {"size": (0.75, 0.12, 0.75)},
                       pos=(W * 0.28, ry + rh * 1.0 + 0.28, -D * 0.18), mat="stone",
                       name="Cappello camino", tags=["chimney"]))

    if p["has_porch"]:
        pd = 1.6
        parts.append(C("porch_floor", "box", {"size": (W * 0.6, 0.14, pd)},
                       pos=(0, y0 + 0.07, D / 2 + pd / 2), mat="wood",
                       name="Pavimento portico", tags=["porch"]))
        parts.append(C("porch_roof", "box", {"size": (W * 0.62, 0.1, pd + 0.2)},
                       pos=(0, y0 + fh * 0.95, D / 2 + pd / 2), mat="roof",
                       name="Tettoia", tags=["porch"]))
        for i, sx in enumerate((-1, 1)):
            parts.append(C("porch_post_%d" % i, "cylinder",
                           {"radius": 0.08, "height": fh * 0.9, "sections": max(6, sec // 2)},
                           pos=(sx * W * 0.28, y0 + fh * 0.47, D / 2 + pd - 0.15),
                           mat="wood", name="Colonna portico", tags=["porch"]))
    return parts


register(Template(
    name="house", category="edifici",
    description="Edificio parametrico: casa, villetta, palazzo, capanno",
    params=PARAMS, materials=MATERIALS, build=build,
    primary_material="wall",
    keywords=["casa", "house", "edificio", "building", "villa", "palazzo", "capanna", "baita", "cottage"],
))
