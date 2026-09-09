"""Generatori parametrici di arredo: sedia e tavolo."""
from __future__ import annotations

from typing import Any

from app.core.spec import ComponentSpec, MaterialSpec
from app.geometry.templates import ParamDef, Template, register
from app.geometry.templates._common import C, rounding, sections, smoothness

WOOD = MaterialSpec(name="wood", base_color="#8a5a33", roughness=0.62, metallic=0.0)
METAL = MaterialSpec(name="metal", base_color="#8d949c", roughness=0.32, metallic=0.9)
FABRIC = MaterialSpec(name="fabric", base_color="#3f4a5c", roughness=0.95, metallic=0.0)


def _legs(cid: str, w: float, d: float, h: float, thick: float, style: str,
          round_legs: bool, mat: str, y0: float = 0.0) -> list[ComponentSpec]:
    out: list[ComponentSpec] = []
    sec = sections(style, 16)
    for i, (sx, sz) in enumerate(((-1, -1), (1, -1), (-1, 1), (1, 1))):
        px = sx * (w / 2 - thick)
        pz = sz * (d / 2 - thick)
        if round_legs:
            out.append(C("%s_%d" % (cid, i), "cylinder",
                         {"radius": thick * 0.6, "height": h, "sections": sec},
                         pos=(px, y0 + h / 2, pz), mat=mat, name="Gamba %d" % (i + 1), tags=["leg"]))
        else:
            out.append(C("%s_%d" % (cid, i), "box", {"size": (thick, h, thick)},
                         pos=(px, y0 + h / 2, pz), mat=mat, name="Gamba %d" % (i + 1), tags=["leg"]))
    return out


# --------------------------------------------------------------------------- #
# Sedia
# --------------------------------------------------------------------------- #
CHAIR_PARAMS = {
    "seat_height":  ParamDef(0.45, 0.25, 0.85, desc="altezza della seduta"),
    "seat_width":   ParamDef(0.45, 0.28, 0.9, desc="larghezza della seduta"),
    "seat_depth":   ParamDef(0.45, 0.28, 0.9, desc="profondita della seduta"),
    "back_height":  ParamDef(0.5, 0.0, 1.1, desc="altezza dello schienale, 0 = sgabello"),
    "leg_thickness": ParamDef(0.05, 0.02, 0.12, desc="spessore delle gambe"),
    "round_legs":   ParamDef(False, desc="gambe cilindriche invece che squadrate"),
    "has_armrests": ParamDef(False, desc="braccioli"),
    "has_cushion":  ParamDef(True, desc="cuscino imbottito sulla seduta"),
    "back_slats":   ParamDef(3, 0, 8, desc="numero di doghe verticali dello schienale"),
}


def build_chair(p: dict[str, Any]) -> list[ComponentSpec]:
    style = p.get("_density", 1.0)
    sub = smoothness(style)
    w, d, sh = p["seat_width"], p["seat_depth"], p["seat_height"]
    th = p["leg_thickness"]
    parts = _legs("leg", w, d, sh, th, style, p["round_legs"], "wood")

    parts.append(C("seat", "rounded_box",
                   {"size": (w, 0.05, d), "radius": rounding(style, 0.015), "subdiv": sub},
                   pos=(0, sh, 0), mat="wood", name="Seduta", tags=["seat", "main"]))
    if p["has_cushion"]:
        parts.append(C("cushion", "rounded_box",
                       {"size": (w * 0.92, 0.06, d * 0.92), "radius": rounding(style, 0.025), "subdiv": sub},
                       pos=(0, sh + 0.055, 0), mat="fabric", name="Cuscino", tags=["cushion"]))

    bh = p["back_height"]
    if bh > 0.05:
        for i, sx in enumerate((-1, 1)):
            parts.append(C("back_post_%d" % i, "box", {"size": (th, bh, th)},
                           pos=(sx * (w / 2 - th), sh + bh / 2, -d / 2 + th / 2),
                           mat="wood", name="Montante %d" % (i + 1), tags=["back"]))
        parts.append(C("back_top", "rounded_box",
                       {"size": (w - th, 0.06, th), "radius": rounding(style, 0.02), "subdiv": sub},
                       pos=(0, sh + bh, -d / 2 + th / 2), mat="wood", name="Traversa", tags=["back"]))
        n = int(p["back_slats"])
        for i in range(n):
            sx = (i - (n - 1) / 2) * ((w - 3 * th) / max(n, 1))
            parts.append(C("back_slat_%d" % i, "box", {"size": (th * 0.7, bh * 0.8, th * 0.5)},
                           pos=(sx, sh + bh * 0.45, -d / 2 + th / 2),
                           mat="wood", name="Doga %d" % (i + 1), tags=["back"]))

    if p["has_armrests"]:
        for i, sx in enumerate((-1, 1)):
            parts.append(C("arm_%d" % i, "rounded_box",
                           {"size": (th, 0.04, d * 0.7), "radius": rounding(style, 0.015), "subdiv": sub},
                           pos=(sx * (w / 2 - th * 0.5), sh + 0.22, -d * 0.05),
                           mat="wood", name="Bracciolo %d" % (i + 1), tags=["armrest"]))
            parts.append(C("arm_post_%d" % i, "box", {"size": (th * 0.7, 0.2, th * 0.7)},
                           pos=(sx * (w / 2 - th * 0.5), sh + 0.11, d * 0.28),
                           mat="wood", name="Supporto bracciolo", tags=["armrest"]))
    return parts


register(Template(
    name="chair", category="arredo",
    description="Sedia, poltroncina o sgabello parametrico",
    params=CHAIR_PARAMS,
    materials={"wood": WOOD, "metal": METAL, "fabric": FABRIC},
    build=build_chair,
    primary_material="wood",
    keywords=["sedia", "chair", "sgabello", "stool", "poltrona", "seduta"],
))


# --------------------------------------------------------------------------- #
# Tavolo
# --------------------------------------------------------------------------- #
TABLE_PARAMS = {
    "width":        ParamDef(1.4, 0.4, 4.0, desc="larghezza del piano"),
    "depth":        ParamDef(0.8, 0.3, 2.0, desc="profondita del piano"),
    "height":       ParamDef(0.75, 0.3, 1.2, desc="altezza del piano da terra"),
    "top_thickness": ParamDef(0.05, 0.015, 0.15, desc="spessore del piano"),
    "leg_thickness": ParamDef(0.07, 0.02, 0.2, desc="spessore delle gambe"),
    "round_legs":   ParamDef(False, desc="gambe cilindriche"),
    "round_top":    ParamDef(False, desc="piano circolare invece che rettangolare"),
    "has_apron":    ParamDef(True, desc="fascia sotto il piano"),
    "has_shelf":    ParamDef(False, desc="ripiano inferiore"),
}


def build_table(p: dict[str, Any]) -> list[ComponentSpec]:
    style = p.get("_density", 1.0)
    sub = smoothness(style)
    sec = sections(style, 32)
    w, d, h = p["width"], p["depth"], p["height"]
    tt, th = p["top_thickness"], p["leg_thickness"]
    parts: list[ComponentSpec] = []

    if p["round_top"]:
        r = max(w, d) / 2
        parts.append(C("top", "cylinder", {"radius": r, "height": tt, "sections": sec},
                       pos=(0, h - tt / 2, 0), mat="wood", name="Piano", tags=["top", "main"]))
        parts.append(C("column", "cylinder",
                       {"radius": th * 1.6, "height": h - tt, "sections": max(8, sec // 2)},
                       pos=(0, (h - tt) / 2, 0), mat="wood", name="Colonna", tags=["leg"]))
        parts.append(C("base", "cylinder",
                       {"radius": r * 0.5, "height": 0.05, "sections": sec},
                       pos=(0, 0.025, 0), mat="wood", name="Base", tags=["base"]))
        return parts

    parts.append(C("top", "rounded_box",
                   {"size": (w, tt, d), "radius": rounding(style, 0.012), "subdiv": sub},
                   pos=(0, h - tt / 2, 0), mat="wood", name="Piano", tags=["top", "main"]))
    parts += _legs("leg", w, d, h - tt, th, style, p["round_legs"], "wood")

    if p["has_apron"]:
        ay = h - tt - 0.06
        parts.append(C("apron_front", "box", {"size": (w - 2 * th, 0.08, th * 0.6)},
                       pos=(0, ay, d / 2 - th), mat="wood", name="Fascia anteriore", tags=["apron"]))
        parts.append(C("apron_back", "box", {"size": (w - 2 * th, 0.08, th * 0.6)},
                       pos=(0, ay, -d / 2 + th), mat="wood", name="Fascia posteriore", tags=["apron"]))
        for i, sx in enumerate((-1, 1)):
            parts.append(C("apron_side_%d" % i, "box", {"size": (th * 0.6, 0.08, d - 2 * th)},
                           pos=(sx * (w / 2 - th), ay, 0), mat="wood",
                           name="Fascia laterale %d" % (i + 1), tags=["apron"]))
    if p["has_shelf"]:
        parts.append(C("shelf", "box", {"size": (w - 2.6 * th, 0.03, d - 2.6 * th)},
                       pos=(0, h * 0.25, 0), mat="wood", name="Ripiano", tags=["shelf"]))
    return parts


register(Template(
    name="table", category="arredo",
    description="Tavolo, scrivania o tavolino parametrico",
    params=TABLE_PARAMS,
    materials={"wood": WOOD, "metal": METAL, "fabric": FABRIC},
    build=build_table,
    primary_material="wood",
    keywords=["tavolo", "table", "scrivania", "desk", "tavolino", "banco"],
))
