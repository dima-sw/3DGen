"""Quanto puo' cambiare ogni parametro fra una variante e l'altra.

Sta in un unico posto invece che sparso nei template perche' e' una scelta di
prodotto, non di geometria: qui si decide quanto due generazioni dello stesso
prompt devono somigliarsi.

Numeri = ampiezza del disturbo. Booleani e scelte = probabilita' di cambiare.
Un parametro assente da queste tabelle non varia mai: e' il caso di tutto cio'
che definisce *cosa* e' l'oggetto (body_style, weapon_type, floors, door_count).
"""
from __future__ import annotations

from app.core.logging_setup import get

log = get("templates.variation")

PROFILES: dict[str, dict[str, float]] = {
    "vehicle": {
        "length": 0.07, "width": 0.06, "height": 0.07,
        "wheel_radius": 0.10, "wheel_width": 0.12, "ground_clearance": 0.14,
        "fender_flare": 0.45, "windshield_tilt": 0.25,
        "has_roof_rack": 0.22, "has_spare_wheel": 0.22, "has_bull_bar": 0.18,
        "has_snorkel": 0.10, "has_spoiler": 0.12,
    },
    "house": {
        "width": 0.12, "depth": 0.12, "floor_height": 0.07,
        "roof_height": 0.16, "roof_overhang": 0.35, "windows_per_side": 0.25,
        "has_chimney": 0.25, "has_porch": 0.20, "has_foundation": 0.15,
    },
    "humanoid": {
        "height": 0.06, "head_scale": 0.10, "shoulder_width": 0.10,
        "leg_ratio": 0.06, "arm_thickness": 0.14,
        "has_antenna": 0.30, "has_backpack": 0.25, "has_shoulder_pads": 0.25,
    },
    "weapon": {
        "blade_length": 0.12, "blade_width": 0.16, "blade_thickness": 0.22,
        "grip_length": 0.14, "guard_width": 0.18,
        "has_fuller": 0.30, "has_gem": 0.18, "has_pommel": 0.10,
    },
    "chair": {
        "seat_height": 0.08, "seat_width": 0.10, "seat_depth": 0.10,
        "back_height": 0.16, "leg_thickness": 0.22, "back_slats": 0.35,
        "round_legs": 0.35, "has_armrests": 0.25, "has_cushion": 0.30,
    },
    "table": {
        "width": 0.12, "depth": 0.12, "height": 0.06,
        "top_thickness": 0.25, "leg_thickness": 0.25,
        "round_legs": 0.30, "round_top": 0.15, "has_apron": 0.25, "has_shelf": 0.25,
    },
    "tree": {
        "height": 0.16, "trunk_radius": 0.22, "canopy_size": 0.16, "lean": 0.9,
        "branch_levels": 0.35, "branches_per_level": 0.35, "seed": 1.0,
    },
    "rock": {"size": 0.22, "count": 0.6, "roughness": 0.3, "seed": 1.0},
    "primitive": {"width": 0.18, "height": 0.18, "depth": 0.18,
                  "count": 0.3, "spacing": 0.2, "shape": 0.25},
}

# Colori plausibili per il materiale principale, quando l'utente non ne chiede uno.
PALETTES: dict[str, list[str]] = {
    "vehicle": ["#b02a1f", "#1f3f7a", "#141518", "#e2e2df", "#8d9298", "#2f7a3a",
                "#4a5533", "#d8b022", "#7a3b1e", "#2b6d78"],
    "house": ["#d8cdb8", "#c9b79b", "#e0dcd3", "#b8a09a",
              "#9fb0a6", "#d5c0a1", "#bfa98f"],
    "humanoid": ["#7d848c", "#8c9098", "#5c6672", "#9aa3ad", "#6f7a63",
                 "#b0b6bd", "#4f545c"],
    "weapon": ["#c3c9d1", "#b9c0c8", "#a8b0b8", "#cdd3da", "#9aa2ab"],
    "chair": ["#8a5a33", "#6b4526", "#a8783f", "#5a4331", "#c39b6b", "#3f3a35"],
    "table": ["#8a5a33", "#6b4526", "#a8783f", "#5a4331", "#c39b6b", "#3f3a35"],
    "tree": ["#3f7a35", "#4c8a3c", "#356b30", "#5c8f3a", "#2f6b3e", "#6b8f3a"],
    "rock": ["#7b7770", "#8a857c", "#6d6a65", "#94908a", "#5f5c58"],
    "primitive": ["#9aa3ad", "#b0574a", "#4a7ab0", "#5aa06a", "#c9a227", "#7b5ba6"],
}


def apply(templates: dict) -> None:
    """Innesta profili e tavolozze nei template gia' registrati."""
    for name, profile in PROFILES.items():
        tmpl = templates.get(name)
        if tmpl is None:
            continue
        for key, amount in profile.items():
            spec = tmpl.params.get(key)
            if spec is None:
                log.warning("profilo di variazione: '%s' non esiste in '%s'", key, name)
                continue
            spec.vary = float(amount)
    for name, palette in PALETTES.items():
        tmpl = templates.get(name)
        if tmpl is not None:
            tmpl.palette = list(palette)
