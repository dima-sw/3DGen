"""Solido parametrico di base: fallback quando nessun template specializzato calza."""
from __future__ import annotations

from typing import Any

from app.core.spec import ComponentSpec, MaterialSpec
from app.geometry.templates import ParamDef, Template, register
from app.geometry.templates._common import C, rounding, sections, smoothness

PARAMS = {
    "shape":     ParamDef("box", choices=["box", "rounded_box", "sphere", "cylinder",
                                          "cone", "capsule", "torus"],
                          desc="forma del solido"),
    "width":     ParamDef(1.0, 0.02, 20.0, desc="dimensione lungo X"),
    "height":    ParamDef(1.0, 0.02, 20.0, desc="dimensione lungo Y"),
    "depth":     ParamDef(1.0, 0.02, 20.0, desc="dimensione lungo Z"),
    "count":     ParamDef(1, 1, 24, desc="numero di copie affiancate"),
    "spacing":   ParamDef(1.5, 0.5, 6.0, desc="distanza fra le copie, in multipli di larghezza"),
    "on_ground": ParamDef(True, desc="appoggia il solido sul piano invece di centrarlo"),
}

MATERIALS = {"surface": MaterialSpec(name="surface", base_color="#9aa3ad", roughness=0.55, metallic=0.1)}


def build(p: dict[str, Any]) -> list[ComponentSpec]:
    style = p.get("_density", 1.0)
    sec = sections(style, 28)
    sub = smoothness(style)
    w, h, d = p["width"], p["height"], p["depth"]
    shape = p["shape"]
    n = int(p["count"])
    parts: list[ComponentSpec] = []

    for i in range(n):
        x = (i - (n - 1) / 2) * w * p["spacing"]
        y = h / 2 if p["on_ground"] else 0.0
        if shape == "box":
            params, prim = {"size": (w, h, d)}, "box"
        elif shape == "rounded_box":
            params = {"size": (w, h, d), "radius": rounding(style, min(w, h, d) * 0.12), "subdiv": sub}
            prim = "rounded_box"
        elif shape == "sphere":
            params, prim = {"radius": min(w, h, d) / 2, "subdiv": max(1, sub)}, "sphere"
        elif shape == "cylinder":
            params, prim = {"radius": min(w, d) / 2, "height": h, "sections": sec}, "cylinder"
        elif shape == "cone":
            params, prim = {"radius": min(w, d) / 2, "height": h, "sections": sec}, "cone"
        elif shape == "capsule":
            params, prim = {"radius": min(w, d) / 2, "height": h, "count": max(6, sec // 2)}, "capsule"
        else:
            params, prim = {"radius": min(w, d) / 2, "tube": h / 2, "sections": sec}, "torus"
        parts.append(C("shape_%d" % i, prim, params, pos=(x, y, 0.0),
                       mat="surface", name="Solido %d" % (i + 1), tags=["main", "shape"]))
    return parts


register(Template(
    name="primitive", category="base",
    description="Solido geometrico semplice, anche ripetuto in serie. Fallback generico",
    params=PARAMS, materials=MATERIALS, build=build,
    primary_material="surface",
    keywords=["cubo", "cube", "sfera", "sphere", "cilindro", "cylinder", "cono", "cone",
              "toro", "torus", "scatola", "box", "solido", "forma", "primitiva"],
))
