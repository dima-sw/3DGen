"""Generatore parametrico di veicoli a 4 ruote.

Un unico modello parametrico copre berlina, SUV, fuoristrada, pickup, van,
camion, sportiva e bus: cambiano proporzioni, sbalzi, linea di cintura e
accessori. La silhouette laterale (compresi i passaruota) e un profilo 2D
estruso: e questo che rende i veicoli riconoscibili senza AI di mesh.
"""
from __future__ import annotations

import math
from typing import Any

from app.core.spec import ComponentSpec, MaterialSpec
from app.geometry.templates import ParamDef, Template, register
from app.geometry.templates._common import C, rounding, sections, smoothness

# proporzioni per sottotipo: (belt_ratio, hood_ratio, cab_ratio, overhang_ratio)
STYLE_PROPS: dict[str, tuple[float, float, float, float]] = {
    "sedan":   (0.52, 0.24, 0.44, 0.19),
    "suv":     (0.50, 0.19, 0.48, 0.16),
    "offroad": (0.56, 0.20, 0.44, 0.13),
    "pickup":  (0.50, 0.20, 0.34, 0.15),
    "van":     (0.46, 0.08, 0.66, 0.10),
    "truck":   (0.52, 0.14, 0.30, 0.10),
    "sport":   (0.60, 0.28, 0.36, 0.17),
    "bus":     (0.40, 0.04, 0.88, 0.08),
}

PARAMS = {
    "body_style":       ParamDef("suv", choices=list(STYLE_PROPS), desc="sottotipo di carrozzeria"),
    "length":           ParamDef(4.4, 2.6, 12.0, desc="lunghezza in metri"),
    "width":            ParamDef(1.85, 1.3, 2.6, desc="larghezza in metri"),
    "height":           ParamDef(1.8, 1.0, 3.6, desc="altezza totale in metri"),
    "wheel_radius":     ParamDef(0.38, 0.20, 0.85, desc="raggio ruota, grande = fuoristrada"),
    "wheel_width":      ParamDef(0.26, 0.10, 0.55, desc="larghezza pneumatico"),
    "ground_clearance": ParamDef(0.24, 0.04, 0.75, desc="altezza da terra del pianale"),
    "door_count":       ParamDef(4, 0, 6, desc="numero di porte totali"),
    "axle_count":       ParamDef(2, 2, 4, desc="numero di assi: 2 = quattro ruote, 3 = sei"),
    "has_bed":          ParamDef(False, desc="cassone aperto posteriore"),
    "has_roof":         ParamDef(True, desc="false = tetto aperto, cabrio"),
    "has_windows":      ParamDef(True, desc="vetri laterali e lunotto"),
    "has_roll_bar":     ParamDef(False, desc="roll bar, tipico dei fuoristrada aperti"),
    "has_bull_bar":     ParamDef(False, desc="paraurti tubolare anteriore"),
    "has_roof_rack":    ParamDef(False, desc="portapacchi sul tetto"),
    "has_spare_wheel":  ParamDef(False, desc="ruota di scorta posteriore"),
    "has_spoiler":      ParamDef(False, desc="alettone posteriore"),
    "has_gun_mount":    ParamDef(False, desc="supporto arma sul tetto, veicoli militari"),
    "has_snorkel":      ParamDef(False, desc="snorkel di aspirazione laterale"),
    "fender_flare":     ParamDef(0.03, 0.0, 0.18, desc="sporgenza dei parafanghi"),
    "windshield_tilt":  ParamDef(18.0, 0.0, 45.0, desc="inclinazione parabrezza in gradi"),
}

MATERIALS = {
    "body":      MaterialSpec(name="body", base_color="#3d6b4a", roughness=0.42, metallic=0.35),
    "glass":     MaterialSpec(name="glass", base_color="#8fb6cc", roughness=0.08, metallic=0.0, opacity=0.45),
    "tire":      MaterialSpec(name="tire", base_color="#1b1b1e", roughness=0.92, metallic=0.0),
    "rim":       MaterialSpec(name="rim", base_color="#6e737a", roughness=0.35, metallic=0.85),
    "trim":      MaterialSpec(name="trim", base_color="#232529", roughness=0.75, metallic=0.1),
    "chrome":    MaterialSpec(name="chrome", base_color="#c9ced6", roughness=0.15, metallic=1.0),
    "light":     MaterialSpec(name="light", base_color="#f7f3d8", roughness=0.1, metallic=0.0),
    "light_red": MaterialSpec(name="light_red", base_color="#c02a22", roughness=0.15, metallic=0.0),
}


def _arch(cz: float, cy: float, r: float, y_floor: float, steps: int = 12,
          max_dz: float = 1e9) -> list[tuple[float, float]]:
    """Punti del passaruota scavato nel profilo laterale, da retro verso avanti.

    max_dz limita la semiapertura dell'arco: senza questo vincolo, ruote molto
    grandi produrrebbero archi che si sovrappongono fra loro o che escono dal
    corpo, generando un profilo auto-intersecante e quindi una mesh rotta.
    """
    dy = cy - y_floor
    if abs(dy) >= r:
        r = abs(dy) + 1e-3
    dz = math.sqrt(max(r * r - dy * dy, 1e-6))
    if dz > max_dz:                       # riduci il raggio invece di sfondare
        dz = max(max_dz, 1e-3)
        r = math.sqrt(dz * dz + dy * dy)
    phi = math.atan2(dy, dz)
    a0, a1 = math.pi + phi, -phi
    return [(cz + r * math.cos(a0 + (a1 - a0) * i / steps),
             cy + r * math.sin(a0 + (a1 - a0) * i / steps)) for i in range(steps + 1)]


def _body_profile(L: float, y_floor: float, y_belt: float,
                  axles: list[float], arch_r: float,
                  wheel_cy: float, steps: int) -> list[tuple[float, float]]:
    """Silhouette laterale del corpo inferiore, in coordinate (z, y).

    Gli archi non devono ne' toccarsi fra loro ne' uscire dalle estremita':
    da qui il limite su max_dz, calcolato asse per asse.
    """
    ordered = sorted(axles)
    p: list[tuple[float, float]] = [(-L / 2, y_floor)]
    for index, z in enumerate(ordered):
        room_back = (z + L / 2) - 0.04 if index == 0 else (z - ordered[index - 1]) / 2 - 0.03
        room_front = (L / 2 - z) - 0.04 if index == len(ordered) - 1 \
            else (ordered[index + 1] - z) / 2 - 0.03
        p += _arch(z, wheel_cy, arch_r, y_floor, steps,
                   max_dz=max(min(room_back, room_front), 0.02))
    p += [(L / 2, y_floor), (L / 2, y_belt - 0.06), (L / 2 - 0.07, y_belt),
          (-L / 2 + 0.07, y_belt), (-L / 2, y_belt - 0.06)]
    return p


def build(p: dict[str, Any]) -> list[ComponentSpec]:
    style = p.get("_density", 1.0)
    sec = sections(style, 28)
    sub = smoothness(style)

    sub_style = p["body_style"]
    belt_r, hood_r, cab_r, over_r = STYLE_PROPS.get(sub_style, STYLE_PROPS["suv"])

    L, W, H = p["length"], p["width"], p["height"]
    wr, ww = p["wheel_radius"], p["wheel_width"]
    clear = min(p["ground_clearance"], wr * 0.92)
    flare = p["fender_flare"]

    y_floor = clear
    wheel_cy = wr
    body_h = (H - clear) * belt_r
    y_belt = y_floor + body_h

    # La linea di cintura deve stare sopra il passaruota, altrimenti l'arco
    # taglierebbe tutto il fianco. Con ruote molto grandi si alza la carrozzeria
    # (e, se serve, l'intero veicolo) invece di produrre geometria rotta.
    min_belt = wheel_cy + wr * 1.18 + 0.04
    if y_belt < min_belt:
        y_belt = min_belt
        body_h = y_belt - y_floor
    H = max(H, y_belt + 0.32)
    cab_h = max(H - y_belt, 0.3)

    overhang = L * over_r
    z_fa = L / 2 - overhang
    z_ra = -L / 2 + overhang
    # Assi distribuiti uniformemente fra il primo e l'ultimo: due assi danno il
    # veicolo classico, tre le sei ruote, quattro gli otto.
    n_axles = max(int(p["axle_count"]), 2)
    axles = [z_ra + (z_fa - z_ra) * i / (n_axles - 1) for i in range(n_axles)]
    arch_r = wr * 1.18

    hood_len = L * hood_r
    cab_len = L * cab_r
    z_cab_front = z_fa - hood_len * 0.55
    z_cab_center = z_cab_front - cab_len / 2
    x_wheel = W / 2 - ww / 2 + flare
    parts: list[ComponentSpec] = []

    # --- corpo inferiore -------------------------------------------------- #
    parts.append(C("body", "prism",
                   {"profile": _body_profile(L, y_floor, y_belt, axles, arch_r, wheel_cy,
                                             6 if style in ("lowpoly", "blocky") else 14),
                    "depth": W},
                   mat="body", name="Carrozzeria", tags=["body", "main"]))

    parts.append(C("chassis", "box", {"size": (W * 0.72, max(clear * 0.55, 0.06), L * 0.86)},
                   pos=(0, clear * 0.45, 0), mat="trim", name="Telaio", tags=["chassis"]))

    # --- cabina ----------------------------------------------------------- #
    # A tetto chiuso la cabina e' un volume pieno; a tetto aperto restano solo
    # il montante del parabrezza e il roll bar, altrimenti sembrerebbe un hard top.
    if cab_h > 0.2 and p["has_roof"]:
        parts.append(C("cabin", "hexahedron",
                       {"bottom": (W * 0.96, cab_len), "top": (W * 0.88, cab_len * 0.74),
                        "height": cab_h, "top_offset": (0.0, -cab_len * 0.06)},
                       pos=(0, y_belt + cab_h / 2, z_cab_center),
                       mat="body", name="Cabina", tags=["cabin"]))
    elif cab_h > 0.2:
        for side, sx in (("l", -1), ("r", 1)):
            parts.append(C("tub_" + side, "box",
                           {"size": (0.05, cab_h * 0.34, cab_len * 1.05)},
                           pos=(sx * (W / 2 - 0.025), y_belt + cab_h * 0.17, z_cab_center),
                           mat="body", name="Fiancata " + side.upper(), tags=["cabin", "tub"]))
        parts.append(C("tub_rear", "box", {"size": (W, cab_h * 0.34, 0.05)},
                       pos=(0, y_belt + cab_h * 0.17, z_cab_center - cab_len * 0.52),
                       mat="body", name="Paratia posteriore", tags=["cabin", "tub"]))
        parts.append(C("dashboard", "box", {"size": (W * 0.9, cab_h * 0.16, 0.28)},
                       pos=(0, y_belt + cab_h * 0.1, z_cab_front - 0.2),
                       mat="trim", name="Cruscotto", tags=["interior"]))
        for side, sx in (("l", -1), ("r", 1)):
            parts.append(C("seat_" + side, "box",
                           {"size": (W * 0.3, cab_h * 0.28, 0.34)},
                           pos=(sx * W * 0.22, y_belt + cab_h * 0.14, z_cab_center - cab_len * 0.05),
                           mat="trim", name="Sedile " + side.upper(), tags=["interior", "seat"]))
            parts.append(C("seatback_" + side, "box",
                           {"size": (W * 0.3, cab_h * 0.46, 0.09)},
                           pos=(sx * W * 0.22, y_belt + cab_h * 0.35, z_cab_center - cab_len * 0.2),
                           mat="trim", name="Schienale " + side.upper(), tags=["interior", "seat"]))

    if p["has_roof"] and cab_h > 0.2:
        parts.append(C("roof", "rounded_box",
                       {"size": (W * 0.9, 0.07, cab_len * 0.8), "radius": rounding(style, 0.03), "subdiv": sub},
                       pos=(0, y_belt + cab_h + 0.01, z_cab_center - cab_len * 0.05),
                       mat="body", name="Tetto", tags=["roof"]))

    # --- vetri ------------------------------------------------------------ #
    if cab_h > 0.25:
        tilt = p["windshield_tilt"]
        wind_h = cab_h * 0.72
        parts.append(C("windshield", "box", {"size": (W * 0.8, wind_h, 0.035)},
                       pos=(0, y_belt + cab_h * 0.55,
                            z_cab_front - 0.03 - wind_h * 0.5 * math.sin(math.radians(tilt))),
                       rot=(-tilt, 0, 0), mat="glass", name="Parabrezza", tags=["glass"]))
        if not p["has_roof"]:
            wz = z_cab_front - 0.03 - wind_h * 0.5 * math.sin(math.radians(tilt))
            for side, sx in (("l", -1), ("r", 1)):
                parts.append(C("wind_post_" + side, "box",
                               {"size": (0.05, wind_h * 1.02, 0.06)},
                               pos=(sx * W * 0.4, y_belt + cab_h * 0.55, wz),
                               rot=(-tilt, 0, 0), mat="body",
                               name="Montante parabrezza " + side.upper(), tags=["cabin", "frame"]))
            parts.append(C("wind_top", "box", {"size": (W * 0.82, 0.06, 0.07)},
                           pos=(0, y_belt + cab_h * 0.55 + wind_h * 0.5 * math.cos(math.radians(tilt)),
                                wz - wind_h * 0.5 * math.sin(math.radians(tilt))),
                           rot=(-tilt, 0, 0), mat="body",
                           name="Traversa parabrezza", tags=["cabin", "frame"]))
        if p["has_windows"] and p["has_roof"]:
            for side, sx in (("l", -1), ("r", 1)):
                parts.append(C("window_" + side, "box",
                               {"size": (0.03, cab_h * 0.52, cab_len * 0.74)},
                               pos=(sx * W * 0.455, y_belt + cab_h * 0.56, z_cab_center - cab_len * 0.04),
                               mat="glass", name="Finestrino " + side.upper(), tags=["glass"]))
            parts.append(C("rear_window", "box", {"size": (W * 0.74, cab_h * 0.55, 0.035)},
                           pos=(0, y_belt + cab_h * 0.58, z_cab_center - cab_len * 0.46),
                           rot=(tilt * 0.7, 0, 0), mat="glass", name="Lunotto", tags=["glass"]))

    # --- ruote ------------------------------------------------------------ #
    wheel_slots: list[tuple[str, int, float]] = []
    for index, cz in enumerate(axles):
        # il primo asse resta "f" e l'ultimo "r": i nomi storici non cambiano
        if index == 0:
            letter = "r"
        elif index == len(axles) - 1:
            letter = "f"
        else:
            letter = "m%d" % index
        for side, sx in (("l", -1), ("r", 1)):
            wheel_slots.append((letter + side, sx, cz))

    for tag, sx, cz in wheel_slots:
        px = sx * x_wheel
        parts.append(C("tire_" + tag, "tube",
                       {"radius": wr, "inner": wr * 0.6, "height": ww, "sections": sec},
                       pos=(px, wheel_cy, cz), rot=(0, 0, 90), mat="tire",
                       name="Pneumatico " + tag.upper(), tags=["wheel", "tire", tag]))
        parts.append(C("rim_" + tag, "cylinder",
                       {"radius": wr * 0.61, "height": ww * 0.9, "sections": sec},
                       pos=(px, wheel_cy, cz), rot=(0, 0, 90), mat="rim",
                       name="Cerchio " + tag.upper(), tags=["wheel", "rim", tag]))
        parts.append(C("hub_" + tag, "cylinder",
                       {"radius": wr * 0.2, "height": ww * 1.06, "sections": max(6, sec // 2)},
                       pos=(px, wheel_cy, cz), rot=(0, 0, 90), mat="chrome",
                       name="Mozzo " + tag.upper(), tags=["wheel", tag]))

    for index, cz in enumerate(axles):
        tag = "front" if index == len(axles) - 1 else ("rear" if index == 0 else "mid%d" % index)
        parts.append(C("axle_" + tag, "cylinder",
                       {"radius": max(wr * 0.11, 0.04), "height": W * 0.86, "sections": max(6, sec // 3)},
                       pos=(0, wheel_cy, cz), rot=(0, 0, 90), mat="trim",
                       name="Assale " + tag, tags=["axle"]))

    # --- paraurti, griglia, luci ------------------------------------------ #
    bump_y = y_floor + body_h * 0.28
    for tag, cz in (("front", L / 2 + 0.05), ("rear", -L / 2 - 0.05)):
        parts.append(C("bumper_" + tag, "rounded_box",
                       {"size": (W * 1.01, body_h * 0.42, 0.2), "radius": rounding(style, 0.05), "subdiv": sub},
                       pos=(0, bump_y, cz), mat="trim", name="Paraurti " + tag, tags=["bumper"]))

    grille_y = y_belt - body_h * 0.34
    parts.append(C("grille", "box", {"size": (W * 0.66, body_h * 0.42, 0.05)},
                   pos=(0, grille_y, L / 2 + 0.015), mat="trim", name="Griglia", tags=["grille"]))
    n_slats = 5 if style in ("lowpoly", "blocky") else 7
    for i in range(n_slats):
        gx = (i - (n_slats - 1) / 2) * (W * 0.6 / n_slats)
        parts.append(C("grille_slat_%d" % i, "box",
                       {"size": (W * 0.6 / n_slats * 0.42, body_h * 0.36, 0.06)},
                       pos=(gx, grille_y, L / 2 + 0.03), mat="chrome",
                       name="Lamella %d" % i, tags=["grille"]))

    for side, sx in (("l", -1), ("r", 1)):
        parts.append(C("headlight_" + side, "cylinder",
                       {"radius": min(0.13, body_h * 0.3), "height": 0.07, "sections": max(6, sec // 2)},
                       pos=(sx * W * 0.34, grille_y + body_h * 0.06, L / 2 + 0.03),
                       rot=(90, 0, 0), mat="light", name="Faro " + side.upper(), tags=["light"]))
        parts.append(C("taillight_" + side, "box", {"size": (0.2, body_h * 0.28, 0.05)},
                       pos=(sx * W * 0.35, y_belt - body_h * 0.3, -L / 2 - 0.02),
                       mat="light_red", name="Stop " + side.upper(), tags=["light"]))

    # --- specchietti, porte, scarico -------------------------------------- #
    if cab_h > 0.25:
        for side, sx in (("l", -1), ("r", 1)):
            parts.append(C("mirror_arm_" + side, "cylinder",
                           {"radius": 0.018, "height": 0.11, "sections": 8},
                           pos=(sx * (W * 0.5 + 0.05), y_belt + cab_h * 0.62, z_cab_front - 0.06),
                           rot=(0, 0, 90), mat="trim", name="Braccio specchio " + side, tags=["mirror"]))
            parts.append(C("mirror_" + side, "box", {"size": (0.05, 0.09, 0.14)},
                           pos=(sx * (W * 0.5 + 0.11), y_belt + cab_h * 0.62, z_cab_front - 0.06),
                           mat="trim", name="Specchietto " + side.upper(), tags=["mirror"]))

    doors_per_side = max(0, int(p["door_count"]) // 2)
    for side, sx in (("l", -1), ("r", 1)):
        for d in range(doors_per_side):
            dz = z_cab_center + cab_len * (0.5 - (d + 0.5) / max(doors_per_side, 1)) * 0.95
            parts.append(C("door_seam_%s%d" % (side, d), "box",
                           {"size": (0.02, body_h * 0.8, 0.015)},
                           pos=(sx * (W / 2 + 0.002), y_floor + body_h * 0.55, dz),
                           mat="trim", name="Linea porta %s%d" % (side, d), tags=["door"]))
            parts.append(C("handle_%s%d" % (side, d), "box", {"size": (0.03, 0.04, 0.16)},
                           pos=(sx * (W / 2 + 0.015), y_belt - body_h * 0.22, dz - cab_len * 0.16),
                           mat="chrome", name="Maniglia %s%d" % (side, d), tags=["door"]))

    parts.append(C("exhaust", "cylinder", {"radius": 0.045, "height": 0.22, "sections": max(6, sec // 3)},
                   pos=(W * 0.28, y_floor * 0.55 + 0.04, -L / 2 - 0.06), rot=(90, 0, 0),
                   mat="chrome", name="Scarico", tags=["exhaust"]))

    # --- accessori opzionali ---------------------------------------------- #
    if p["has_roll_bar"] or (not p["has_roof"] and cab_h > 0.3):
        bar_r = 0.045
        top_y = y_belt + cab_h * 0.86
        for sx in (-1, 1):
            for cz in (z_cab_center + cab_len * 0.34, z_cab_center - cab_len * 0.34):
                cid = "rollbar_v_%s_%s" % ("l" if sx < 0 else "r", "f" if cz > z_cab_center else "b")
                parts.append(C(cid, "cylinder",
                               {"radius": bar_r, "height": cab_h * 0.86, "sections": max(6, sec // 3)},
                               pos=(sx * W * 0.4, y_belt + cab_h * 0.43, cz), mat="trim",
                               name="Roll bar", tags=["rollbar"]))
        for cz in (z_cab_center + cab_len * 0.34, z_cab_center - cab_len * 0.34):
            cid = "rollbar_h_%s" % ("f" if cz > z_cab_center else "b")
            parts.append(C(cid, "cylinder",
                           {"radius": bar_r, "height": W * 0.8, "sections": max(6, sec // 3)},
                           pos=(0, top_y, cz), rot=(0, 0, 90), mat="trim",
                           name="Roll bar trasversale", tags=["rollbar"]))

    if p["has_bull_bar"]:
        parts.append(C("bullbar_h", "cylinder", {"radius": 0.05, "height": W * 0.92, "sections": max(6, sec // 3)},
                       pos=(0, y_floor + body_h * 0.45, L / 2 + 0.2), rot=(0, 0, 90),
                       mat="trim", name="Bull bar", tags=["bullbar"]))
        for sx in (-1, 1):
            parts.append(C("bullbar_v_" + ("l" if sx < 0 else "r"), "cylinder",
                           {"radius": 0.04, "height": body_h * 0.75, "sections": max(6, sec // 3)},
                           pos=(sx * W * 0.3, y_floor + body_h * 0.4, L / 2 + 0.2),
                           mat="trim", name="Montante bull bar", tags=["bullbar"]))

    if p["has_roof_rack"] and p["has_roof"]:
        ry = y_belt + cab_h + 0.08
        parts.append(C("rack_base", "box", {"size": (W * 0.84, 0.03, cab_len * 0.78)},
                       pos=(0, ry, z_cab_center), mat="trim", name="Portapacchi", tags=["rack"]))
        for sx in (-1, 1):
            parts.append(C("rack_rail_" + ("l" if sx < 0 else "r"), "box",
                           {"size": (0.035, 0.09, cab_len * 0.78)},
                           pos=(sx * W * 0.41, ry + 0.05, z_cab_center), mat="trim",
                           name="Sponda portapacchi", tags=["rack"]))

    if p["has_spare_wheel"]:
        parts.append(C("spare_tire", "tube",
                       {"radius": wr, "inner": wr * 0.6, "height": ww * 0.9, "sections": sec},
                       pos=(0, y_belt * 0.92, -L / 2 - ww * 0.6), rot=(90, 0, 0),
                       mat="tire", name="Ruota di scorta", tags=["spare"]))
        parts.append(C("spare_rim", "cylinder", {"radius": wr * 0.6, "height": ww * 0.8, "sections": sec},
                       pos=(0, y_belt * 0.92, -L / 2 - ww * 0.6), rot=(90, 0, 0),
                       mat="rim", name="Cerchio scorta", tags=["spare"]))

    if p["has_spoiler"]:
        parts.append(C("spoiler", "box", {"size": (W * 0.86, 0.05, 0.26)},
                       pos=(0, y_belt + cab_h * (1.05 if p["has_roof"] else 0.5), -L / 2 + 0.14),
                       mat="trim", name="Alettone", tags=["spoiler"]))
        for sx in (-1, 1):
            parts.append(C("spoiler_leg_" + ("l" if sx < 0 else "r"), "box", {"size": (0.05, 0.14, 0.1)},
                           pos=(sx * W * 0.34, y_belt + cab_h * 0.95 - 0.05, -L / 2 + 0.14),
                           mat="trim", name="Supporto alettone", tags=["spoiler"]))

    if p["has_gun_mount"]:
        base_y = y_belt + (cab_h if p["has_roof"] else cab_h * 0.9)
        parts.append(C("gun_ring", "tube", {"radius": 0.3, "inner": 0.24, "height": 0.09, "sections": sec},
                       pos=(0, base_y + 0.04, z_cab_center), mat="trim", name="Ralla", tags=["weapon"]))
        parts.append(C("gun_post", "cylinder", {"radius": 0.05, "height": 0.42, "sections": max(6, sec // 3)},
                       pos=(0, base_y + 0.26, z_cab_center), mat="trim", name="Supporto", tags=["weapon"]))
        parts.append(C("gun_body", "box", {"size": (0.1, 0.12, 0.5)},
                       pos=(0, base_y + 0.5, z_cab_center + 0.1), mat="trim", name="Arma", tags=["weapon"]))
        parts.append(C("gun_barrel", "cylinder", {"radius": 0.028, "height": 0.62, "sections": max(6, sec // 3)},
                       pos=(0, base_y + 0.5, z_cab_center + 0.62), rot=(90, 0, 0),
                       mat="trim", name="Canna", tags=["weapon"]))

    if p["has_snorkel"]:
        parts.append(C("snorkel", "cylinder",
                       {"radius": 0.055, "height": cab_h * 0.9 + body_h * 0.5, "sections": max(6, sec // 3)},
                       pos=(W * 0.46, y_belt + cab_h * 0.35, z_cab_front + hood_len * 0.35),
                       mat="trim", name="Snorkel", tags=["snorkel"]))

    if sub_style == "pickup" or p["has_bed"]:
        bed_front = z_cab_center - cab_len / 2
        bed_len = abs(bed_front - (-L / 2))
        bed_z = (bed_front + (-L / 2)) / 2
        wall_h = body_h * 0.55
        for sx in (-1, 1):
            parts.append(C("bed_wall_" + ("l" if sx < 0 else "r"), "box",
                           {"size": (0.06, wall_h, bed_len)},
                           pos=(sx * (W / 2 - 0.03), y_belt + wall_h / 2, bed_z),
                           mat="body", name="Sponda cassone", tags=["bed"]))
        parts.append(C("bed_tail", "box", {"size": (W * 0.98, wall_h, 0.06)},
                       pos=(0, y_belt + wall_h / 2, -L / 2 + 0.04), mat="body",
                       name="Portellone", tags=["bed"]))

    return parts


register(Template(
    name="vehicle",
    category="veicoli",
    description="Veicolo a 4 ruote parametrico: berlina, SUV, fuoristrada, pickup, van, camion, sportiva, bus",
    params=PARAMS,
    materials=MATERIALS,
    build=build,
    primary_material="body",
    keywords=["auto", "macchina", "car", "jeep", "suv", "fuoristrada", "offroad", "camion", "truck",
              "pickup", "van", "furgone", "bus", "autobus", "sportiva", "berlina", "veicolo", "vehicle"],
))
