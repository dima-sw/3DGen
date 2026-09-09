"""Dalla descrizione di una creatura al grafo di parti.

Qui non esistono FishGenerator o WolfGenerator. Esistono **preset di parametri**
sulle stesse ricette generiche del catalogo: una testa di squalo e una di lupo
sono la ricetta `head` con numeri diversi. Aggiungere una specie significa
aggiungere una riga a un dizionario, non una classe.

L'archetipo decide lo scheletro dell'assemblaggio (cosa si attacca a cosa); i
modificatori aggiungono o tolgono appendici. Le combinazioni mai previste —
corpo di lupo con tentacoli e ali — nascono dall'incrocio dei due.
"""
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.logging_setup import get
from app.ai.text import (BIG, SMALL, all_matches, has_any, has_word, measure,
                         normalize, number_before)
from app.core.spec import AssemblySpec, AttachSpec, MaterialSpec, PartSpec

log = get("ai.creature")

# riesportato: il planner lo usa per decidere se ripiegare sull'archetipo
__all__ = ["parse_creature", "build_assembly", "looks_like_creature", "normalize",
           "CreatureSpec", "BODY_PRESETS", "HEAD_PRESETS"]

# --------------------------------------------------------------------------- #
# Preset: dati, non codice
# --------------------------------------------------------------------------- #
# Il profilo del corpo, specie per specie. `peduncle` e la strozzatura davanti
# alla coda, `flat` la compressione laterale, `waist` la rientranza dietro al
# torace, `neck` quanto ci si stringe dove attacca la testa. Sono i numeri che
# distinguono un pesce da un lupo: la forma la fa questa tabella, non il codice.
BODY_PRESETS: dict[str, dict[str, float]] = {
    "fish":      {"length": 0.86, "height": 0.42, "width": 0.17, "taper": 0.50, "belly": 0.22,
                  "peduncle": 0.80, "shoulder": 0.20, "waist": 0.06, "neck": 0.22, "flat": 0.70},
    "shark":     {"length": 1.10, "height": 0.34, "width": 0.24, "taper": 0.60, "belly": 0.08,
                  "peduncle": 0.72, "shoulder": 0.45, "waist": 0.10, "neck": 0.18, "flat": 0.35},
    "wolf":      {"length": 0.72, "height": 0.30, "width": 0.26, "taper": 0.26, "belly": 0.10,
                  "peduncle": 0.28, "shoulder": 0.60, "waist": 0.34, "neck": 0.55, "flat": 0.0},
    "feline":    {"length": 0.66, "height": 0.24, "width": 0.21, "taper": 0.28, "belly": 0.06,
                  "peduncle": 0.34, "shoulder": 0.50, "waist": 0.42, "neck": 0.58, "flat": 0.0},
    "horse":     {"length": 0.95, "height": 0.40, "width": 0.28, "taper": 0.20, "belly": 0.14,
                  "peduncle": 0.22, "shoulder": 0.65, "waist": 0.26, "neck": 0.62, "flat": 0.0},
    "bird":      {"length": 0.42, "height": 0.28, "width": 0.21, "taper": 0.40, "belly": 0.34,
                  "peduncle": 0.45, "shoulder": 0.55, "waist": 0.08, "neck": 0.50, "flat": 0.10},
    "serpent":   {"length": 1.30, "height": 0.19, "width": 0.17, "taper": 0.66, "belly": 0.04,
                  "peduncle": 0.55, "shoulder": 0.10, "waist": 0.04, "neck": 0.25, "flat": 0.20},
    "generic":   {"length": 0.75, "height": 0.32, "width": 0.24, "taper": 0.36, "belly": 0.14,
                  "peduncle": 0.35, "shoulder": 0.40, "waist": 0.22, "neck": 0.45, "flat": 0.10},
}

HEAD_PRESETS: dict[str, dict[str, float]] = {
    "fish":    {"size": 0.26, "snout": 0.45, "snout_size": 0.52, "flat": 0.62,
                "jaw": 0.72, "brow": 0.30, "cranium": 1.05},
    "shark":   {"size": 0.26, "snout": 1.05, "snout_size": 0.38, "flat": 0.72,
                "jaw": 0.85, "brow": 0.25, "cranium": 0.95},
    "wolf":    {"size": 0.20, "snout": 1.00, "snout_size": 0.42, "flat": 0.82,
                "jaw": 0.80, "brow": 0.70, "cranium": 1.0},
    "feline":  {"size": 0.17, "snout": 0.50, "snout_size": 0.46, "flat": 0.95,
                "jaw": 0.70, "brow": 0.75, "cranium": 1.1},
    "horse":   {"size": 0.19, "snout": 1.25, "snout_size": 0.38, "flat": 0.72,
                "jaw": 0.85, "brow": 0.55, "cranium": 0.9},
    "dragon":  {"size": 0.24, "snout": 1.20, "snout_size": 0.44, "flat": 0.78,
                "jaw": 0.95, "brow": 1.05, "cranium": 0.95},
    "bird":    {"size": 0.14, "snout": 1.15, "snout_size": 0.22, "flat": 0.90,
                "jaw": 0.45, "brow": 0.35, "cranium": 1.15},
    "human":   {"size": 0.16, "snout": 0.22, "snout_size": 0.44, "flat": 1.0,
                "jaw": 0.85, "brow": 0.70, "cranium": 1.2},
    "generic": {"size": 0.20, "snout": 0.60, "snout_size": 0.48, "flat": 0.9,
                "jaw": 0.70, "brow": 0.55, "cranium": 1.0},
}

TAIL_PRESETS: dict[str, dict[str, Any]] = {
    "fish":    {"recipe": "blade", "params": {"length": 0.30, "width": 0.20, "thickness": 0.035,
                                              "fork": 0.80, "bend": 0.0, "root": 0.35,
                                              "belly": 0.95, "tip": 1.75}},
    "shark":   {"recipe": "blade", "params": {"length": 0.38, "width": 0.22, "thickness": 0.035,
                                              "fork": 0.95, "bend": 0.15, "root": 0.32,
                                              "belly": 0.90, "tip": 1.95}},
    "long":    {"recipe": "limb", "params": {"length": 0.55, "radius": 0.075, "taper": 0.80,
                                             "bend": 0.9}},
    "short":   {"recipe": "limb", "params": {"length": 0.22, "radius": 0.06, "taper": 0.7,
                                             "bend": 1.2}},
    "fan":     {"recipe": "blade", "params": {"length": 0.24, "width": 0.20, "thickness": 0.03,
                                              "fork": 0.0, "bend": 0.4, "root": 0.35,
                                              "belly": 1.0, "tip": 1.35}},
}

SKIN_COLORS: dict[str, str] = {
    "fish": "#d2762a", "shark": "#6e7d8c", "wolf": "#6d6257", "feline": "#b58445",
    "horse": "#7a5236", "bird": "#8a6d4a", "dragon": "#4a6b46", "serpent": "#5d7a46",
    "human": "#c98a5a", "generic": "#a08466",
}


class CreatureSpec(BaseModel):
    """Descrizione semantica di una creatura, anche impossibile."""

    model_config = ConfigDict(extra="ignore")

    archetype: str = "generic"      # fish | humanoid | quadruped | bird | serpent | generic
    body: str = "generic"           # preset di proporzioni del corpo
    head: str = "generic"           # preset della testa
    tail: str = ""                  # fish | shark | long | short | fan | "" = nessuna
    arms: int = 0
    legs: int = 0
    wings: int = 0
    tentacles: int = 0
    fins: int = 0                   # pinne pettorali/dorsali
    horns: int = 0
    eyes: int = 2
    armor: bool = False
    scale: float = 1.0
    color: str = ""

    def semantic_class(self) -> str:
        return self.archetype


# --------------------------------------------------------------------------- #
# Costruzione dell'assemblaggio
# --------------------------------------------------------------------------- #
def build_assembly(spec: CreatureSpec) -> tuple[AssemblySpec, list[MaterialSpec]]:
    """Traduce la descrizione in un grafo di parti attaccate fra loro."""
    humanoid = spec.archetype == "humanoid"
    parts: list[PartSpec] = []

    if humanoid:
        root = "torso"
        parts.append(PartSpec(id="torso", recipe="torso", tags=["torso", "body"],
                              params={"height": 0.34 * spec.scale, "width": 0.20 * spec.scale,
                                      "depth": 0.13 * spec.scale, "flare": 0.30}))
        head_socket, head_parent = "neck", "torso"
        tail_socket = "tail"
    else:
        root = "corpo"
        body = dict(BODY_PRESETS.get(spec.body, BODY_PRESETS["generic"]))
        for key in ("length", "height", "width"):
            body[key] = body[key] * spec.scale
        body["ring_count"] = max(spec.tentacles, 0)
        parts.append(PartSpec(id="corpo", recipe="body", tags=["body"], params=body))
        head_socket, head_parent = "head", "corpo"
        tail_socket = "tail"

    body_id = root
    head_params = dict(HEAD_PRESETS.get(spec.head, HEAD_PRESETS["generic"]))
    head_params["size"] = _head_size(spec, humanoid, parts[0].params)

    if humanoid:
        # un collo vero evita che la testa si sciolga nelle spalle
        parts.append(PartSpec(id="collo", recipe="limb", tags=["neck"], blend=0.07,
                              params={"length": 0.10 * spec.scale,
                                      "radius": 0.062 * spec.scale, "taper": 0.10,
                                      "muscle": 0.30, "joint": 0.0},
                              attach=AttachSpec(parent="torso", socket="neck")))
        head_parent, head_socket = "collo", "tip"

    parts.append(PartSpec(
        id="testa", recipe="head", tags=["head"], blend=0.10, params=head_params,
        # dal basso serve il socket "neck": con "base" la testa guarderebbe in alto
        attach=AttachSpec(parent=head_parent, socket=head_socket,
                          own_socket="neck" if humanoid else "base")))

    # --- occhi: parti dure, non fuse ------------------------------------- #
    for index, side in enumerate(("l", "r")[:max(0, min(spec.eyes, 2))]):
        parts.append(PartSpec(
            id="occhio_" + side, recipe="eye", tags=["eye", "detail"], hard=True,
            params={"size": head_params["size"] * 0.20},
            attach=AttachSpec(parent="testa", socket="eye_" + side)))

    # --- coda -------------------------------------------------------------- #
    if spec.tail:
        preset = TAIL_PRESETS.get(spec.tail, TAIL_PRESETS["fan"])
        params = {k: (v * spec.scale if k in ("length", "width", "radius") else v)
                  for k, v in preset["params"].items()}
        parts.append(PartSpec(id="coda", recipe=preset["recipe"], tags=["tail"], blend=0.07,
                              params=params,
                              attach=AttachSpec(parent=body_id, socket=tail_socket)))

    # --- arti ------------------------------------------------------------- #
    parts += _arms(spec, body_id, humanoid)
    parts += _legs(spec, body_id, humanoid)
    parts += _wings(spec, body_id, humanoid)
    parts += _tentacles(spec, body_id, humanoid)
    parts += _fins(spec, body_id, humanoid)
    parts += _horns(spec)
    if spec.armor:
        parts += _armor(spec, body_id, humanoid)

    materials = [MaterialSpec(name="skin", roughness=0.55, metallic=0.05,
                              base_color=spec.color or SKIN_COLORS.get(spec.body)
                              or SKIN_COLORS.get(spec.head, "#a08466"))]
    assembly = AssemblySpec(root=root, parts=parts, blend=0.055,
                            symmetry="bilateral", semantic_class=spec.semantic_class())
    log.info("creatura '%s': %d parti (%s)", spec.archetype, len(parts),
             ", ".join(sorted({p.recipe for p in parts})))
    return assembly, materials


# socket disponibili per gli arti, in ordine di preferenza
HUMANOID_ARM_SOCKETS = ["shoulder_l", "shoulder_r", "shoulder_low_l", "shoulder_low_r"]
BODY_ARM_SOCKETS = ["side_l", "side_r", "leg_front_l", "leg_front_r"]


def _arms(spec: CreatureSpec, body_id: str, humanoid: bool) -> list[PartSpec]:
    if spec.arms <= 0:
        return []
    sockets = HUMANOID_ARM_SOCKETS if humanoid else BODY_ARM_SOCKETS
    out: list[PartSpec] = []
    for index in range(spec.arms):
        if index < len(sockets):
            socket, parent = sockets[index], body_id
        else:
            socket, parent = "ring_%d" % (index - len(sockets)), body_id
        upper = "braccio_%d" % index
        out.append(PartSpec(id=upper, recipe="limb", tags=["arm", "limb"], blend=0.05,
                            params={"length": 0.26 * spec.scale, "radius": 0.068 * spec.scale,
                                    "taper": 0.30, "bend": 0.55,
                                    "muscle": 0.55, "joint": 0.45},
                            attach=AttachSpec(parent=parent, socket=socket)))
        out.append(PartSpec(id="avambraccio_%d" % index, recipe="limb",
                            tags=["arm", "limb"], blend=0.04,
                            params={"length": 0.24 * spec.scale, "radius": 0.055 * spec.scale,
                                    "taper": 0.38, "bend": 0.45,
                                    "muscle": 0.45, "joint": 0.35},
                            attach=AttachSpec(parent=upper, socket="tip")))
        out.append(PartSpec(id="mano_%d" % index, recipe="extremity",
                            tags=["arm", "hand"], blend=0.03,
                            params={"length": 0.10 * spec.scale, "width": 0.055 * spec.scale,
                                    "thickness": 0.028 * spec.scale},
                            attach=AttachSpec(parent="avambraccio_%d" % index, socket="tip")))
    return out


def _legs(spec: CreatureSpec, body_id: str, humanoid: bool) -> list[PartSpec]:
    if spec.legs <= 0:
        return []
    if humanoid:
        sockets = ["hip_l", "hip_r"]
    else:
        sockets = ["leg_front_l", "leg_front_r", "leg_rear_l", "leg_rear_r"]
    out: list[PartSpec] = []
    for index in range(min(spec.legs, len(sockets))):
        thigh = "coscia_%d" % index
        out.append(PartSpec(id=thigh, recipe="limb", tags=["leg", "limb"], blend=0.05,
                            params={"length": 0.26 * spec.scale, "radius": 0.082 * spec.scale,
                                    "taper": 0.42, "bend": -0.2,
                                    "muscle": 0.65, "joint": 0.50},
                            attach=AttachSpec(parent=body_id, socket=sockets[index])))
        shin = "stinco_%d" % index
        out.append(PartSpec(id=shin, recipe="limb", tags=["leg", "limb"], blend=0.04,
                            params={"length": 0.24 * spec.scale, "radius": 0.052 * spec.scale,
                                    "taper": 0.46, "bend": 0.3,
                                    "muscle": 0.50, "joint": 0.30},
                            attach=AttachSpec(parent=thigh, socket="tip")))
        out.append(PartSpec(id="piede_%d" % index, recipe="extremity",
                            tags=["leg", "foot"], blend=0.03,
                            params={"length": 0.14 * spec.scale, "width": 0.060 * spec.scale,
                                    "thickness": 0.032 * spec.scale,
                                    "pitch": 85.0, "heel": 0.28, "toe": 0.70},
                            attach=AttachSpec(parent=shin, socket="tip")))
    return out


def _wings(spec: CreatureSpec, body_id: str, humanoid: bool) -> list[PartSpec]:
    if spec.wings <= 0:
        return []
    sockets = ["back", "back"] if humanoid else ["wing_l", "wing_r"]
    out: list[PartSpec] = []
    for index in range(spec.wings):
        socket = sockets[index % len(sockets)]
        roll = 0.0 if not humanoid else (-35.0 if index % 2 == 0 else 35.0)
        out.append(PartSpec(id="ala_%d" % index, recipe="blade",
                            tags=["wing", "membrane"], blend=0.04, material="membrane",
                            params={"length": 0.62 * spec.scale, "width": 0.30 * spec.scale,
                                    "thickness": 0.022 * spec.scale, "bend": 0.55,
                                    "taper": 0.55, "fork": 0.35},
                            attach=AttachSpec(parent=body_id, socket=socket, roll=roll)))
    return out


def _tentacles(spec: CreatureSpec, body_id: str, humanoid: bool) -> list[PartSpec]:
    if spec.tentacles <= 0:
        return []
    out: list[PartSpec] = []
    for index in range(spec.tentacles):
        socket = "ring_%d" % index if not humanoid else "shoulder_l"
        out.append(PartSpec(id="tentacolo_%d" % index, recipe="limb",
                            tags=["tentacle", "limb"], blend=0.045,
                            params={"length": 0.95 * spec.scale, "radius": 0.082 * spec.scale,
                                    "taper": 0.86, "bend": 0.55 + 0.18 * (index % 3),
                                    "twist": 0.8, "muscle": 0.30, "joint": 0.0},
                            attach=AttachSpec(parent=body_id, socket=socket)))
    return out


# Raggio del cranio in frazione dell'ingombro del corpo. Su un quadrupede il
# riferimento e' l'altezza del tronco, su un umanoide quella del busto: in
# entrambi i casi una testa sta a poco meno di meta'.
HEAD_TO_BODY = {"humanoid": 0.42, "creature": 0.62}


def _head_size(spec: CreatureSpec, humanoid: bool, body_params: dict) -> float:
    """Quanto grande la testa, dato il corpo a cui va attaccata.

    Il preset della specie decide **la forma** — muso lungo, mascella, calotta —
    non la taglia. Prendere anche la taglia dal preset dava una testa di pesce
    da mezzo metro su un torso umano: era il difetto piu' visibile del banco
    "pesce con il corpo di una persona".

    In fondo si applica l'esagerazione dello stile: nel cartoon la testa e'
    grande, ed e' una scelta.
    """
    from app.core.style import current

    preset = HEAD_PRESETS.get(spec.head, HEAD_PRESETS["generic"])["size"]
    generico = HEAD_PRESETS["generic"]["size"]
    riferimento = float(body_params.get("height", 0.32))
    misurata = riferimento * HEAD_TO_BODY["humanoid" if humanoid else "creature"]
    # Il preset conta ancora, ma entro un fattore: una testa di cavallo resta
    # piu' grande di una di gatto sullo stesso corpo.
    forma = float(min(max(preset / generico, 0.75), 1.35))
    return misurata * forma * current().emphasis("head")


def _fins(spec: CreatureSpec, body_id: str, humanoid: bool) -> list[PartSpec]:
    if spec.fins <= 0 or humanoid:
        return []
    out = [PartSpec(id="pinna_dorsale", recipe="blade", tags=["fin"], blend=0.04,
                    params={"length": 0.30 * spec.scale, "width": 0.30 * spec.scale,
                            "thickness": 0.026 * spec.scale, "bend": -0.35, "sweep": 0.35,
                            "root": 0.95, "belly": 0.72, "tip": 0.14},
                    attach=AttachSpec(parent=body_id, socket="dorsal"))]
    if spec.fins >= 2:
        out.append(PartSpec(id="pinna_ventrale", recipe="blade", tags=["fin"], blend=0.04,
                            params={"length": 0.17 * spec.scale, "width": 0.17 * spec.scale,
                                    "thickness": 0.024 * spec.scale, "bend": 0.35, "sweep": 0.3,
                                    "root": 0.95, "belly": 0.70, "tip": 0.16},
                            attach=AttachSpec(parent=body_id, socket="ventral")))
    for index, side in enumerate(("l", "r")):
        if spec.fins >= 3 + index:
            out.append(PartSpec(id="pettorale_" + side, recipe="blade", tags=["fin"], blend=0.03,
                                params={"length": 0.20 * spec.scale, "width": 0.13 * spec.scale,
                                        "thickness": 0.022 * spec.scale, "bend": 0.35,
                                        "sweep": 0.4, "root": 0.85, "belly": 0.78, "tip": 0.20},
                                attach=AttachSpec(parent=body_id, socket="side_" + side)))
    return out


def _horns(spec: CreatureSpec) -> list[PartSpec]:
    out: list[PartSpec] = []
    for index, side in enumerate(("l", "r")):
        if spec.horns > index:
            out.append(PartSpec(id="corno_" + side, recipe="limb", tags=["horn"],
                                blend=0.03, material="horn",
                                params={"length": 0.20 * spec.scale, "radius": 0.030 * spec.scale,
                                        "taper": 0.85, "bend": -1.1},
                                attach=AttachSpec(parent="testa", socket="horn_" + side)))
    return out


def _armor(spec: CreatureSpec, body_id: str, humanoid: bool) -> list[PartSpec]:
    socket = "back" if humanoid else "dorsal"
    plates = [PartSpec(id="corazza_dorso", recipe="plate", tags=["armor"], hard=True,
                       material="armor",
                       params={"size": 0.30 * spec.scale, "thickness": 0.022,
                               "coverage": 0.70},
                       attach=AttachSpec(parent=body_id, socket=socket, insert=0.05))]
    plates.append(PartSpec(id="corazza_testa", recipe="plate", tags=["armor"], hard=True,
                           material="armor",
                           params={"size": 0.17 * spec.scale, "thickness": 0.018,
                                   "coverage": 0.55},
                           attach=AttachSpec(parent="testa", socket="crest", insert=0.05)))
    return plates


# --------------------------------------------------------------------------- #
# Dal linguaggio naturale alla descrizione
# --------------------------------------------------------------------------- #
SPECIES: dict[str, list[str]] = {
    "fish":    ["pesce", "pesci", "pesciolino", "fish", "trota", "salmone", "carpa",
                "tonno", "sardina", "orata"],
    "shark":   ["squalo", "shark", "pescecane"],
    "wolf":    ["lupo", "wolf", "cane", "dog", "volpe", "fox", "iena"],
    "feline":  ["gatto", "cat", "leone", "lion", "tigre", "tiger", "felino", "pantera"],
    "horse":   ["cavallo", "horse", "pony", "cervo", "alce", "toro", "mucca"],
    "bird":    ["uccello", "bird", "aquila", "eagle", "corvo", "gufo", "falco", "pappagallo"],
    "dragon":  ["drago", "dragon", "draco", "wyvern"],
    "serpent": ["serpente", "snake", "biscia", "anguilla", "verme"],
    "octopus": ["polpo", "piovra", "octopus", "calamaro", "seppia", "medusa"],
    "human":   ["persona", "umano", "umana", "uomo", "donna", "human", "person", "gente"],
    "bat":     ["pipistrello", "bat"],
}

# specie che non sono un corpo intero ma suggeriscono solo un dettaglio
DETAIL_ONLY = {"bat"}

GENERIC_CREATURE = ["creatura", "animale", "mostro", "bestia", "alieno",
                    "monster", "creature", "beast", "ibrido"]

ARCHETYPE_OF = {
    "fish": "fish", "shark": "fish", "serpent": "serpent",
    "wolf": "quadruped", "feline": "quadruped", "horse": "quadruped",
    "bird": "bird", "dragon": "quadruped", "octopus": "generic", "human": "humanoid",
}

# valori tipici dell'archetipo, prima di leggere le richieste esplicite
ARCHETYPE_DEFAULTS: dict[str, dict[str, Any]] = {
    "fish":      {"legs": 0, "arms": 0, "fins": 4, "tail": "fish", "eyes": 2},
    "serpent":   {"legs": 0, "arms": 0, "fins": 0, "tail": "long", "eyes": 2},
    "quadruped": {"legs": 4, "arms": 0, "fins": 0, "tail": "short", "eyes": 2},
    "bird":      {"legs": 2, "arms": 0, "wings": 2, "tail": "fan", "eyes": 2},
    "humanoid":  {"legs": 2, "arms": 2, "fins": 0, "tail": "", "eyes": 2},
    "generic":   {"legs": 0, "arms": 0, "fins": 0, "tail": "short", "eyes": 2},
}

ARM_WORDS = ["braccia", "braccio", "arms", "arm"]
LEG_WORDS = ["gambe", "gamba", "zampe", "zampa", "legs", "leg"]
TENTACLE_WORDS = ["tentacoli", "tentacolo", "tentacles", "tentacle"]
WING_WORDS = ["ali", "ala", "wings", "wing"]
HORN_WORDS = ["corna", "corno", "horns", "horn"]
FIN_WORDS = ["pinne", "pinna", "fins", "fin"]
ARMOR_WORDS = ["corazza", "corazzat", "armatura", "armor", "armour", "piastre", "blindat"]

# Le alternative vanno dalla piu' lunga alla piu' corta: con "un|uno|una"
# l'articolo "una" verrebbe consumato come "un", lasciando "a" come specie.
_ARTICLE = r"(?:(?:della|dello|delle|degli|dei|una|uno|un'|un|il|lo|la|le|gli|i)\s+)?"
_OF = r"\s+(?:della|dello|del|dei|delle|di|da|d')\s+"
BODY_OF = re.compile(r"corp[oi]" + _OF + _ARTICLE + r"(\w+)")
HEAD_OF = re.compile(r"test[ae]" + _OF + _ARTICLE + r"(\w+)")
TAIL_OF = re.compile(r"cod[ae]" + _OF + _ARTICLE + r"(\w+)")


def _species_of_word(word: str) -> str | None:
    for key, words in SPECIES.items():
        if any(word.startswith(w[:5]) and len(word) >= 4 for w in words):
            return key
    return None


# Parole che appartengono a un template specializzato: "robot umanoide" deve
# restare al generatore parametrico, che lo fa meglio. Perdono la precedenza
# solo se la richiesta contiene anche un innesto o un'appendice esotica, cioe'
# qualcosa che il template non sa rappresentare.
TEMPLATE_WORDS = ["robot", "umanoide", "androide", "droide", "mech", "cyborg"]
EXOTIC_WORDS = TENTACLE_WORDS + WING_WORDS + HORN_WORDS + FIN_WORDS


def has_graft(text: str) -> bool:
    """Vero se il testo innesta una parte di una specie su un'altra."""
    return bool(BODY_OF.search(text) or HEAD_OF.search(text) or TAIL_OF.search(text))


def looks_like_creature(text: str) -> bool:
    """Vero se la richiesta parla di un essere vivente, vero o inventato."""
    species = [s for s in all_matches(text, SPECIES) if s not in DETAIL_ONLY]
    exotic = has_word(text, EXOTIC_WORDS)
    hybrid = has_graft(text) or exotic or len(species) > 1

    if has_word(text, TEMPLATE_WORDS) and not hybrid:
        return False
    if has_word(text, GENERIC_CREATURE) or species:
        return True
    return hybrid


def parse_creature(prompt: str) -> CreatureSpec:
    """Legge una descrizione, anche impossibile, e ne ricava la struttura."""
    text = normalize(prompt)
    species = [s for s in all_matches(text, SPECIES) if s not in DETAIL_ONLY]

    # "con il corpo di X" e "testa di X" hanno la precedenza sull'ordine delle parole
    body = head = None
    match = BODY_OF.search(text)
    if match:
        body = _species_of_word(match.group(1))
    match = HEAD_OF.search(text)
    if match:
        head = _species_of_word(match.group(1))

    if body is None:
        body = species[0] if species else "generic"
    if head is None:
        # la testa segue il corpo, a meno che una seconda specie sia nominata
        others = [s for s in species if s != body]
        head = others[0] if (others and BODY_OF.search(text)) else (species[0] if species else "generic")

    archetype = ARCHETYPE_OF.get(body, "generic")
    spec = CreatureSpec(archetype=archetype, body=body if body != "octopus" else "generic",
                        head=head if head != "octopus" else "generic")

    defaults = ARCHETYPE_DEFAULTS.get(archetype, ARCHETYPE_DEFAULTS["generic"])
    for key, value in defaults.items():
        setattr(spec, key, value)

    if "octopus" in species:
        spec.tentacles = 8
        spec.legs = 0

    # --- richieste esplicite: hanno sempre la precedenza -------------------- #
    for words, attribute in ((ARM_WORDS, "arms"), (LEG_WORDS, "legs"),
                             (TENTACLE_WORDS, "tentacles"), (WING_WORDS, "wings"),
                             (HORN_WORDS, "horns"), (FIN_WORDS, "fins")):
        count = number_before(text, words)
        if count is not None:
            setattr(spec, attribute, int(max(0, min(count, 12))))
        elif has_word(text, words):
            setattr(spec, attribute, max(getattr(spec, attribute), 2))

    if has_any(text, ARMOR_WORDS):
        spec.armor = True
    if "bat" in all_matches(text, SPECIES) and spec.wings == 0:
        spec.wings = 2

    match = TAIL_OF.search(text)
    if match:
        tail_species = _species_of_word(match.group(1))
        spec.tail = "fish" if tail_species in ("fish", "shark") else spec.tail or "long"
    if has_any(text, ["senza coda", "no tail"]):
        spec.tail = ""

    height = measure(text, ["alt", "height", "altezza", "lung", "length"])
    if height:
        spec.scale = float(max(0.15, min(height / 1.7, 6.0)))
    elif has_any(text, BIG):
        spec.scale = 1.5
    elif has_any(text, SMALL):
        spec.scale = 0.6

    # un umanoide con coda di pesce resta un umanoide, ma prende le pinne
    if archetype == "humanoid" and spec.tail in ("fish", "shark"):
        spec.fins = max(spec.fins, 1)
    return spec
