"""Planner a regole: funziona senza rete, senza chiavi API e senza costi.

Serve a tre scopi:
  1. rendere l'app utilizzabile anche senza LLM (regola 13: mai un fallimento totale);
  2. fare da rete di sicurezza quando la risposta dell'LLM non e' valida;
  3. permettere i test automatici senza chiamate esterne.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from app.core.spec import EditOp, EditPlan, GenerationPlan, MaterialSpec
from app.geometry.templates import TEMPLATES, load_all

# Radici, non parole intere: l'italiano declina gli aggettivi (rosso/rossa/rossi).
# Il confine di parola iniziale evita falsi positivi come "grossa" -> "rossa".
COLORS: list[tuple[str, str]] = [
    (r"verde\s+militare|verde\s+oliva|mimetic|kaki|khaki", "#4a5533"),
    (r"ross|red\b", "#b02a1f"),
    (r"verd|green", "#2f7a3a"),
    (r"azzurr|celest", "#4a8fd4"),
    (r"blu\b|blue|blu[ae]", "#23478f"),
    (r"ner[oaie]|black", "#141518"),
    (r"bianc|white", "#e8e8e6"),
    (r"giall|yellow", "#d8b022"),
    (r"arancio|orange", "#d1741f"),
    (r"grigi|gray|grey", "#7b7f85"),
    (r"argent|silver|cromat", "#c2c7cd"),
    (r"marron|brown|legno", "#6b4526"),
    (r"rosa\b|pink", "#d78ba6"),
    (r"viola|purple|porpora", "#6f3f96"),
    (r"or[oi]\b|gold|dorat", "#c9a227"),
    (r"sabbia|sand|beige|desert", "#c4ad82"),
]

# Lo stile e' uno solo, ma "semplice" e "dettagliato" restano richieste
# legittime: diventano densita' della superficie, non stili diversi.
DENSITY_WORDS = {
    0.55: ["low poly", "lowpoly", "low-poly", "poligoni bassi", "semplice",
           "essenziale", "grezzo", "a blocchi", "squadrato", "voxel", "minecraft"],
    1.55: ["dettagliato", "dettagliata", "rifinito", "rifinita", "curato",
           "curata", "alta qualita", "definito", "definita"],
}

VEHICLE_SUBTYPES = {
    "offroad": ["jeep", "fuoristrada", "offroad", "off-road", "4x4", "suv militare", "campagnola"],
    "pickup": ["pickup", "pick-up", "cassone"],
    "van": ["van", "furgone", "furgoncino", "minivan"],
    "truck": ["camion", "truck", "autocarro", "tir"],
    "bus": ["bus", "autobus", "pullman", "corriera"],
    "sport": ["sportiva", "sport", "supercar", "da corsa", "racing", "coupe"],
    "sedan": ["berlina", "sedan", "utilitaria", "citycar"],
    "suv": ["suv", "crossover"],
}

WEAPON_SUBTYPES = {
    "dagger": ["pugnale", "dagger", "coltello", "stiletto"],
    "axe": ["ascia", "axe", "accetta", "bipenne"],
    "mace": ["mazza", "mace", "clava", "martello da guerra"],
    "spear": ["lancia", "spear", "giavellotto", "alabarda"],
    "sword": ["spada", "sword", "katana", "sciabola", "claymore"],
}

SHAPES = {
    "sphere": ["sfera", "sphere", "palla", "globo"],
    "cylinder": ["cilindro", "cylinder", "tubo"],
    "cone": ["cono", "cone", "piramide"],
    "torus": ["toro", "torus", "ciambella", "anello"],
    "capsule": ["capsula", "capsule", "pillola"],
    "rounded_box": ["arrotondato", "smussato", "rounded"],
    "box": ["cubo", "cube", "scatola", "box", "parallelepipedo", "blocco"],
}

BIG = ["grande", "grosso", "enorme", "gigante", "big", "large", "huge", "massiccio", "maggiorat"]
SMALL = ["piccolo", "mini", "small", "tiny", "compatto", "ridotto"]


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in t if not unicodedata.combining(c))


# Non sono colori, ma suggeriscono una tinta quando l'utente non ne indica una:
# "un veicolo militare" e' verde oliva, "un veicolo militare rosso" e' rosso.
CONTEXT_COLORS: list[tuple[str, str]] = [
    (r"militar|military|esercito|army", "#4a5533"),
    (r"pompier|fire\s*truck|antincendio", "#b02a1f"),
    (r"ambulanz|ambulance", "#e8e8e6"),
    (r"polizi|police", "#23478f"),
]


def _find_color(text: str, use_context: bool = True) -> str | None:
    """Colore esplicito se c'e'; altrimenti quello suggerito dal contesto.

    L'ordine della lista da' la precedenza alle espressioni piu' specifiche
    ('verde militare' prima di 'verde').
    """
    for pattern, hexcode in COLORS:
        if re.search(r"\b(?:" + pattern + ")", text):
            return hexcode
    if use_context:
        for pattern, hexcode in CONTEXT_COLORS:
            if re.search(r"\b(?:" + pattern + ")", text):
                return hexcode
    return None


def _number_before(text: str, words: list[str]) -> float | None:
    """Cerca 'N <parola>' oppure '<parola> N', con numeri anche a lettere."""
    spelled = {"una": 1, "uno": 1, "un": 1, "due": 2, "tre": 3, "quattro": 4, "cinque": 5,
               "sei": 6, "sette": 7, "otto": 8, "nove": 9, "dieci": 10,
               "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
    for w in words:
        m = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:\w+\s+)?" + w, text)
        if m:
            return float(m.group(1).replace(",", "."))
        m = re.search(r"\b(" + "|".join(spelled) + r")\s+(?:\w+\s+)?" + w, text)
        if m:
            return float(spelled[m.group(1)])
    return None


def _measure(text: str, words: list[str]) -> float | None:
    """Cerca 'lungo 5 metri', '5 m di altezza', ecc."""
    for w in words:
        for pat in (w + r"\D{0,12}?(\d+(?:[.,]\d+)?)\s*(?:m\b|metri|meters?)",
                    r"(\d+(?:[.,]\d+)?)\s*(?:m\b|metri|meters?)\D{0,12}?" + w):
            m = re.search(pat, text)
            if m:
                return float(m.group(1).replace(",", "."))
    return None


def _pick_template(text: str) -> str:
    load_all()
    scores: dict[str, int] = {}
    for name, t in TEMPLATES.items():
        score = 0
        for kw in t.keywords:
            if re.search(r"\b" + re.escape(kw), text):
                score += len(kw)
        if score:
            scores[name] = score
    if not scores:
        return "primitive"
    return max(scores.items(), key=lambda kv: kv[1])[0]


def _pick_density(text: str) -> float:
    """Quanto fitta vuole la superficie chi ha scritto questo.

    Non e' una scelta di stile — lo stile e' uno — ma di densita': "un albero
    semplice" e "un albero dettagliato" sono lo stesso albero con piu' o meno
    triangoli.
    """
    for valore, words in DENSITY_WORDS.items():
        if any(w in text for w in words):
            return valore
    return 1.0


def _subtype(text: str, table: dict[str, list[str]], default: str) -> str:
    best: tuple[int, str] | None = None
    for sub, words in table.items():
        for w in words:
            if w in text and (best is None or len(w) > best[0]):
                best = (len(w), sub)
    return best[1] if best else default


VEHICLE_BASE = {
    # sottotipo: lunghezza, larghezza, altezza, raggio ruota, larghezza ruota, altezza da terra
    "offroad": (4.3, 1.95, 1.95, 0.44, 0.32, 0.32),
    "pickup":  (5.3, 1.95, 1.85, 0.38, 0.28, 0.26),
    "van":     (5.0, 1.95, 2.35, 0.34, 0.24, 0.20),
    "truck":   (8.0, 2.45, 3.1, 0.5, 0.34, 0.34),
    "bus":     (11.0, 2.5, 3.2, 0.5, 0.3, 0.3),
    "sport":   (4.4, 1.9, 1.28, 0.34, 0.3, 0.1),
    "sedan":   (4.5, 1.8, 1.46, 0.33, 0.23, 0.15),
    "suv":     (4.6, 1.9, 1.78, 0.37, 0.26, 0.22),
}


def _vehicle_base(text: str) -> dict[str, Any]:
    """Valori tipici del sottotipo, prima di leggere le richieste dell'utente.

    Servono a distinguere cosa e' stato davvero chiesto da cosa e' solo un
    valore ragionevole di partenza: solo il primo va protetto dalle varianti.
    """
    sub = _subtype(text, VEHICLE_SUBTYPES, "suv")
    b = VEHICLE_BASE[sub]
    p: dict[str, Any] = {
        "body_style": sub,
        "length": b[0], "width": b[1], "height": b[2],
        "wheel_radius": b[3], "wheel_width": b[4], "ground_clearance": b[5],
    }
    if sub in ("offroad", "truck", "pickup"):
        p["fender_flare"] = 0.06
    if sub == "sport":
        p["has_spoiler"] = True
        p["windshield_tilt"] = 32.0
    if sub == "offroad":
        p["windshield_tilt"] = 10.0
    return p


def _vehicle_params(text: str) -> dict[str, Any]:
    p = _vehicle_base(text)

    if any(w in text for w in ["militare", "military", "esercito", "army", "mimetic"]):
        p["has_roll_bar"] = True
        p["has_spare_wheel"] = True
        p["has_bull_bar"] = True
        p["has_snorkel"] = True
        p["has_roof"] = False
    if any(w in text for w in ["armato", "mitragliatrice", "gun", "turret", "torretta", "armed"]):
        p["has_gun_mount"] = True
    if any(w in text for w in ["senza tetto", "aperto", "cabrio", "open top", "open-top",
                               "scoperta", "decappottabile", "no roof"]):
        p["has_roof"] = False
    if any(w in text for w in ["con tetto", "chiuso", "hard top", "hardtop", "coperto"]):
        p["has_roof"] = True
    if "portapacchi" in text or "roof rack" in text:
        p["has_roof_rack"] = True
    if "ruota di scorta" in text or "spare" in text:
        p["has_spare_wheel"] = True
    if "snorkel" in text:
        p["has_snorkel"] = True
    if "alettone" in text or "spoiler" in text:
        p["has_spoiler"] = True

    doors = _number_before(text, ["porte", "porta", "doors", "door"])
    if doors is not None:
        p["door_count"] = int(doors)

    # Numero di ruote: il veicolo e' parametrico negli assi, non serve un
    # generatore dedicato per il sei ruote.
    wheels = _number_before(text, ["ruote", "wheels", "gomme"])
    if wheels is not None and wheels >= 4:
        p["axle_count"] = int(max(2, min(round(wheels / 2), 4)))
    if any(w in text for w in ["cassone", "pianale", "cargo bed", "flatbed"]):
        p["has_bed"] = True
    if any(w in text for w in ["cabina aperta", "aperta", "scoperto"]):
        p["has_roof"] = False

    wheels_big = re.search(r"(ruote|gomme|pneumatici|wheels|tires)[^.]{0,25}(grand|gross|big|large|maggiorat)", text)
    wheels_big = wheels_big or re.search(r"(grand|gross|big|large)\w*\s+(ruote|gomme|pneumatici|wheels|tires)", text)
    if wheels_big:
        p["wheel_radius"] = min(p["wheel_radius"] * 1.32, 0.85)
        p["wheel_width"] = min(p["wheel_width"] * 1.25, 0.55)
        p["ground_clearance"] = min(p["ground_clearance"] * 1.3, 0.7)
        p["fender_flare"] = 0.08

    length = _measure(text, ["lung", "length", "lunghezza"])
    if length:
        scale = length / p["length"]
        p["length"] = length
        p["width"] *= min(max(scale, 0.75), 1.3)
        p["height"] *= min(max(scale, 0.75), 1.3)
    height = _measure(text, ["alt", "height", "altezza"])
    if height:
        p["height"] = height

    if any(w in text for w in BIG) and not wheels_big:
        for k in ("length", "width", "height"):
            p[k] *= 1.18
    if any(w in text for w in SMALL):
        for k in ("length", "width", "height"):
            p[k] *= 0.82
    return p


def _house_params(text: str) -> dict[str, Any]:
    p: dict[str, Any] = {}
    floors = _number_before(text, ["piani", "piano", "floors", "storey", "storeys"])
    if floors:
        p["floors"] = int(floors)
    if any(w in text for w in ["grattacielo", "palazzo", "skyscraper", "condominio"]):
        p["floors"] = max(int(p.get("floors", 6)), 6)
        p["roof_type"] = "flat"
        p["width"], p["depth"] = 14.0, 12.0
    if any(w in text for w in ["capanna", "baita", "cabin", "shed", "capanno", "casetta"]):
        p["width"], p["depth"] = 4.5, 4.0
        p["floors"] = 1
        p["roof_type"] = "gable"
    if "tetto piatto" in text or "flat roof" in text:
        p["roof_type"] = "flat"
    if "portico" in text or "porch" in text or "veranda" in text:
        p["has_porch"] = True
    if any(w in text for w in ["senza camino", "no chimney"]):
        p["has_chimney"] = False
    w = _measure(text, ["larg", "width"])
    if w:
        p["width"] = w
    if any(word in text for word in BIG):
        p["width"], p["depth"] = p.get("width", 8.0) * 1.4, p.get("depth", 6.0) * 1.4
    if any(word in text for word in SMALL):
        p["width"], p["depth"] = p.get("width", 8.0) * 0.7, p.get("depth", 6.0) * 0.7
    return p


def _humanoid_params(text: str) -> dict[str, Any]:
    p: dict[str, Any] = {}
    if any(w in text for w in ["robot", "mech", "androide", "droide", "meccanic", "cyborg"]):
        p["mechanical"] = True
    if any(w in text for w in ["umano", "persona", "uomo", "donna", "human", "cavaliere", "knight", "soldato"]):
        p["mechanical"] = False
        p["has_visor"] = False
    if any(w in text for w in ["armatura", "armor", "corazzat", "futuristic", "futuristica"]):
        p["mechanical"] = True
        p["has_shoulder_pads"] = True
    if "zaino" in text or "backpack" in text or "jetpack" in text or "reattore" in text:
        p["has_backpack"] = True
    if "antenna" in text:
        p["has_antenna"] = True
    h = _measure(text, ["alt", "height", "altezza"])
    if h:
        p["height"] = h
    if any(w in text for w in ["gigante", "colosso", "enorme", "giant"]):
        p["height"] = max(p.get("height", 1.8), 4.0)
        p["build"] = "bulky"
    if any(w in text for w in ["massiccio", "bulky", "corazzato", "pesante", "heavy"]):
        p["build"] = "heavy"
    if any(w in text for w in ["snello", "slim", "agile", "magro"]):
        p["build"] = "slim"
    return p


def _weapon_params(text: str) -> dict[str, Any]:
    p: dict[str, Any] = {"weapon_type": _subtype(text, WEAPON_SUBTYPES, "sword")}
    if p["weapon_type"] == "dagger":
        p["blade_length"], p["grip_length"], p["guard_width"] = 0.28, 0.13, 0.14
    if p["weapon_type"] in ("spear", "axe", "mace"):
        p["blade_length"] = 1.6 if p["weapon_type"] == "spear" else 0.9
    if "gemma" in text or "gem" in text or "magic" in text or "magica" in text:
        p["has_gem"] = True
    if any(w in text for w in ["due mani", "two handed", "grande", "claymore", "greatsword"]):
        p["blade_length"] = 1.25
        p["grip_length"] = 0.34
        p["blade_width"] = 0.11
    length = _measure(text, ["lung", "length", "lama", "blade"])
    if length:
        p["blade_length"] = length
    return p


def _tree_params(text: str) -> dict[str, Any]:
    p: dict[str, Any] = {}
    if any(w in text for w in ["pino", "abete", "conifera", "conifer", "spruce", "natale"]):
        p["canopy_style"] = "conifer"
    elif any(w in text for w in ["palma", "palm"]):
        p["canopy_style"] = "palm"
    elif any(w in text for w in ["secco", "morto", "spoglio", "bare", "dead"]):
        p["canopy_style"] = "bare"
    h = _measure(text, ["alt", "height", "altezza"])
    if h:
        p["height"] = h
    if any(w in text for w in BIG):
        p["height"] = p.get("height", 5.0) * 1.6
        p["trunk_radius"] = 0.35
    if any(w in text for w in SMALL):
        p["height"] = p.get("height", 5.0) * 0.5
    return p


def _furniture_params(text: str, template: str) -> dict[str, Any]:
    p: dict[str, Any] = {}
    if template == "chair":
        if any(w in text for w in ["sgabello", "stool"]):
            p["back_height"] = 0.0
            p["has_cushion"] = False
        if any(w in text for w in ["poltrona", "braccioli", "armrest", "armchair"]):
            p["has_armrests"] = True
            p["seat_width"], p["seat_depth"] = 0.58, 0.55
        if "ufficio" in text or "office" in text:
            p["round_legs"] = True
            p["has_armrests"] = True
    else:
        if any(w in text for w in ["rotondo", "round", "circolare", "tondo"]):
            p["round_top"] = True
        if any(w in text for w in ["scrivania", "desk"]):
            p["width"], p["depth"], p["height"] = 1.6, 0.75, 0.74
        if any(w in text for w in ["tavolino", "caffe", "coffee"]):
            p["width"], p["depth"], p["height"] = 1.0, 0.55, 0.42
        w = _measure(text, ["larg", "width", "lung", "length"])
        if w:
            p["width"] = w
        h = _measure(text, ["alt", "height"])
        if h:
            p["height"] = h
    if any(word in text for word in BIG):
        for k, v in list(p.items()):
            if isinstance(v, float):
                p[k] = v * 1.25
    return p


def _primitive_params(text: str) -> dict[str, Any]:
    p: dict[str, Any] = {}
    for shape, words in SHAPES.items():
        if any(w in text for w in words):
            p["shape"] = shape
            break
    n = _number_before(text, ["cubi", "sfere", "cilindri", "coni", "blocchi", "copie", "cubes", "spheres"])
    if n:
        p["count"] = int(n)
    size = _measure(text, ["lato", "raggio", "dimension", "size", "grande", "alt"])
    if size:
        p["width"] = p["height"] = p["depth"] = size
    if any(w in text for w in BIG):
        for k in ("width", "height", "depth"):
            p[k] = p.get(k, 1.0) * 2.0
    if any(w in text for w in SMALL):
        for k in ("width", "height", "depth"):
            p[k] = p.get(k, 1.0) * 0.5
    return p


PARAM_BUILDERS = {
    "vehicle": _vehicle_params,
    "house": _house_params,
    "humanoid": _humanoid_params,
    "weapon": _weapon_params,
    "tree": _tree_params,
    "primitive": _primitive_params,
}

# Per il veicolo i valori di partenza dipendono dal sottotipo, non dai default
# del template: senza questa base ogni dimensione risulterebbe "richiesta".
BASE_BUILDERS = {"vehicle": _vehicle_base}


def explicit_params(template: str, text: str, params: dict[str, Any]) -> list[str]:
    """Parametri che il testo ha davvero cambiato rispetto ai valori di partenza."""
    tmpl = TEMPLATES.get(template)
    if tmpl is None:
        return list(params)
    base = tmpl.defaults()
    if template in BASE_BUILDERS:
        base.update(BASE_BUILDERS[template](text))
    return [k for k, v in params.items() if base.get(k) != v]


# Template che la composizione puo' scavalcare: sono generici o coincidono con
# cio' che le parti sanno fare meglio. Veicoli, case e armi restano ai template.
COMPOSABLE_OVER = {"primitive", "humanoid"}


def plan(prompt: str) -> GenerationPlan:
    """Costruisce un GenerationPlan dal testo, senza chiamate esterne."""
    load_all()
    text = _norm(prompt)
    template = _pick_template(text)
    density = _pick_density(text)

    # Regola 9: se nessun template specializzato descrive la richiesta ma si
    # parla di un essere vivente, si passa alla composizione di parti invece
    # di ripiegare su un cubo.
    if template in COMPOSABLE_OVER:
        from app.ai import creature

        if creature.looks_like_creature(text):
            return _creature_plan(prompt, text, density)

    if template in PARAM_BUILDERS:
        params = PARAM_BUILDERS[template](text)
    elif template in ("chair", "table"):
        params = _furniture_params(text, template)
    else:
        params = {}

    locked = explicit_params(template, text, params)
    materials: list[MaterialSpec] = []
    color = _find_color(text)
    tmpl = TEMPLATES.get(template)
    if color and tmpl and tmpl.primary_material:
        base = tmpl.materials.get(tmpl.primary_material)
        materials.append(MaterialSpec(
            name=tmpl.primary_material, base_color=color,
            roughness=base.roughness if base else 0.6,
            metallic=base.metallic if base else 0.0,
        ))
        locked.append(tmpl.primary_material)

    return GenerationPlan(
        prompt=prompt,
        object_type=prompt.strip()[:60] or template,
        template=template,
        density=density,
        params=params,
        materials=materials,
        locked=locked,
        notes="Piano generato dalle regole locali (nessun LLM).",
    )


def _creature_plan(prompt: str, text: str, density: float) -> GenerationPlan:
    """Piano compositivo: parti, socket e attacchi invece di un template."""
    from app.ai import creature

    spec = creature.parse_creature(prompt)
    color = _find_color(text)
    if color:
        spec.color = color
    assembly, materials = creature.build_assembly(spec)

    locked = ["archetype", "body", "head"]
    for attribute in ("arms", "legs", "tentacles", "wings", "fins", "tail"):
        if getattr(spec, attribute):
            locked.append(attribute)
    if color:
        locked.append("skin")

    return GenerationPlan(
        prompt=prompt,
        object_type=prompt.strip()[:60] or spec.archetype,
        template="freeform",
        strategy="assembly",
        density=density,
        assembly=assembly,
        materials=materials,
        locked=locked,
        notes="Composizione di parti: %s con testa di %s" % (spec.body, spec.head),
    )


# --------------------------------------------------------------------------- #
# Editor a regole
# --------------------------------------------------------------------------- #
SIZE_TARGETS = {
    "wheel_radius": ["ruote", "ruota", "gomme", "pneumatici", "wheels", "tires", "tyres"],
    "height": ["alto", "alta", "altezza", "height", "taller", "basso", "bassa"],
    "length": ["lungo", "lunga", "lunghezza", "length", "longer", "corto", "corta"],
    "width": ["largo", "larga", "larghezza", "width", "wider", "stretto"],
}

GROW = ["piu grande", "piu grandi", "piu grosso", "piu grossi", "ingrandisci", "aumenta",
        "bigger", "larger", "increase", "enlarge", "maggiorat", "piu alto", "piu alta",
        "piu lungo", "piu lunga", "piu largo", "piu larga", "allarga", "allunga", "alza"]
SHRINK = ["piu piccolo", "piu piccoli", "riduci", "rimpicciolisci", "diminuisci", "smaller",
          "reduce", "shrink", "piu basso", "piu bassa", "piu corto", "piu corta",
          "piu stretto", "restringi", "abbassa", "accorcia"]


def edit(prompt: str, current: GenerationPlan) -> EditPlan:
    """Interpreta una richiesta di modifica senza LLM."""
    load_all()
    text = _norm(prompt)
    tmpl = TEMPLATES.get(current.template)
    ops: list[EditOp] = []
    notes: list[str] = []

    grow = any(w in text for w in GROW)
    shrink = any(w in text for w in SHRINK)

    if tmpl and (grow or shrink):
        factor = 1.3 if grow else 0.77
        hit = False
        for param, words in SIZE_TARGETS.items():
            if param in tmpl.params and any(w in text for w in words):
                ops.append(EditOp(op="scale_param", path=param, factor=factor,
                                  reason="dimensione richiesta"))
                if param == "wheel_radius" and "wheel_width" in tmpl.params:
                    ops.append(EditOp(op="scale_param", path="wheel_width", factor=1 + (factor - 1) * 0.7))
                    ops.append(EditOp(op="scale_param", path="ground_clearance", factor=factor))
                hit = True
        if not hit:  # nessun bersaglio: scala l'oggetto intero
            for param in ("length", "width", "height", "size", "seat_width", "seat_depth",
                          "seat_height", "depth", "blade_length"):
                if param in tmpl.params:
                    ops.append(EditOp(op="scale_param", path=param, factor=factor,
                                      reason="scala globale"))
        notes.append("dimensioni " + ("aumentate" if grow else "ridotte"))

    # in una modifica conta solo un colore detto esplicitamente
    color = _find_color(text, use_context=False)
    if color and tmpl and tmpl.primary_material:
        target = tmpl.primary_material
        for mat_name in tmpl.materials:
            if mat_name in text:
                target = mat_name
        ops.append(EditOp(op="set_material", target=target, value={"base_color": color},
                          reason="colore richiesto"))
        notes.append("colore aggiornato")

    for valore, words in DENSITY_WORDS.items():
        if any(w in text for w in words):
            ops.append(EditOp(op="set_density", value=valore,
                              reason="dettaglio richiesto"))
            notes.append("densita' %.2f" % valore)

    if tmpl:
        adding = any(w in text for w in ["aggiungi", "metti", "add", "con "])
        removing = any(w in text for w in ["togli", "rimuovi", "elimina", "remove", "senza", "no "])
        flags = {
            "has_roof": ["tetto", "roof", "capote"],
            "has_roll_bar": ["roll bar", "rollbar", "gabbia"],
            "has_bull_bar": ["bull bar", "bullbar", "paraurti tubolare"],
            "has_roof_rack": ["portapacchi", "roof rack"],
            "has_spare_wheel": ["scorta", "spare"],
            "has_spoiler": ["alettone", "spoiler"],
            "has_gun_mount": ["mitragliatrice", "arma", "gun", "torretta", "turret"],
            "has_snorkel": ["snorkel"],
            "has_windows": ["finestrini", "vetri", "windows"],
            "has_armrests": ["braccioli", "armrest"],
            "has_cushion": ["cuscino", "cushion"],
            "has_backpack": ["zaino", "backpack", "jetpack"],
            "has_antenna": ["antenna"],
            "has_porch": ["portico", "porch", "veranda"],
            "has_chimney": ["camino", "comignolo", "chimney"],
            "has_shelf": ["ripiano", "shelf"],
            "has_gem": ["gemma", "gem"],
        }
        for param, words in flags.items():
            if param in tmpl.params and any(w in text for w in words):
                value = not removing if (adding or removing) else True
                ops.append(EditOp(op="set_param", path=param, value=value,
                                  reason="accessorio richiesto"))
                notes.append(("aggiunto " if value else "rimosso ") + words[0])

        doors = _number_before(text, ["porte", "porta", "doors"])
        if doors is not None and "door_count" in tmpl.params:
            ops.append(EditOp(op="set_param", path="door_count", value=int(doors)))
            notes.append("%d porte" % int(doors))
        floors = _number_before(text, ["piani", "piano", "floors"])
        if floors is not None and "floors" in tmpl.params:
            ops.append(EditOp(op="set_param", path="floors", value=int(floors)))
            notes.append("%d piani" % int(floors))

    if not ops:
        new_template = _pick_template(text)
        if new_template != current.template and new_template != "primitive":
            return EditPlan(ops=[EditOp(op="set_template", value=new_template)],
                            summary="Cambio oggetto: " + new_template)
        return EditPlan(ops=[], summary="Non ho capito la modifica richiesta.")

    return EditPlan(ops=ops, summary=", ".join(notes).capitalize())
