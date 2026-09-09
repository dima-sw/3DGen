"""L'umanoide costruito come assemblaggio, non come pila di scatole.

Il template `humanoid` conserva i suoi parametri — sono la lingua con cui
l'utente e l'LLM lo descrivono — ma la geometria non viene piu' da cubi e
capsule messi uno sull'altro. Viene dallo stesso motore delle creature: parti
con profilo, socket, fusione. La differenza si vede: un torace, un addome e un
bacino invece di una scatola; un cranio con mascella invece di una sfera;
braccia con spalla, gomito e polso invece di tubi.

**Le proporzioni sono derivate, non inventate.** Tutto discende dall'altezza
attraverso una tabella sola (`RATIOS`), nella tradizione delle sette teste e
mezzo. Cambiare `height` non puo' produrre un torso gigante con braccine: le
misure si muovono insieme perche' sono la stessa misura moltiplicata.
"""
from __future__ import annotations

from app.core.spec import AssemblySpec, AttachSpec, MaterialSpec, PartSpec
from app.core.style import current as style

# Frazioni dell'altezza totale. Sono semi-dimensioni dove la ricetta vuole un
# semiasse (torso, testa) e lunghezze intere dove vuole una lunghezza (arti).
RATIOS: dict[str, float] = {
    "head":          0.0620,   # raggio del cranio
    "neck_length":   0.0450,
    "neck_radius":   0.0300,
    "torso_height":  0.1450,   # semialtezza
    "torso_width":   0.0980,   # semilarghezza al torace
    "torso_depth":   0.0560,
    "upper_arm":     0.1750,
    "forearm":       0.1550,
    "arm_radius":    0.0310,
    "hand_length":   0.1000,
    "hand_width":    0.0420,
    "thigh_radius":  0.0470,
    "shin_radius":   0.0370,
    "foot_length":   0.1500,
    "foot_width":    0.0520,
}

# Come la corporatura cambia gli spessori. Solo gli spessori: un tipo "heavy"
# e' piu' grosso, non piu' alto.
BUILDS: dict[str, dict[str, float]] = {
    "slim":   {"girth": 0.84, "muscle": 0.28, "belly": -0.10},
    "normal": {"girth": 1.00, "muscle": 0.45, "belly": 0.05},
    "heavy":  {"girth": 1.20, "muscle": 0.40, "belly": 0.45},
    "bulky":  {"girth": 1.34, "muscle": 0.85, "belly": 0.10},
}

MATERIALS = {
    "armor": MaterialSpec(name="armor", base_color="#8b929b", roughness=0.34, metallic=0.75),
    "skin": MaterialSpec(name="skin", base_color="#c98a5a", roughness=0.55, metallic=0.0),
    "eye": MaterialSpec(name="eye", base_color="#2ec4d6", roughness=0.10, metallic=0.0),
    "metal": MaterialSpec(name="metal", base_color="#6f757d", roughness=0.30, metallic=0.9),
}


# Quanto della somma nominale arriva davvero in altezza. Le parti si
# compenetrano negli attacchi, le articolazioni accorciano la catena, e
# l'esagerazione cartoon accorcia le gambe: il risultato e' costante a ogni
# scala, ma non e' uno. Si divide, cosi' "alto 1,80" vuol dire 1,80.
#
# **E' un valore misurato**, e cambia se cambia l'esagerazione dello stile.
# Per rimisurarlo: si mette 1.0 qui, si costruisce a un'altezza qualsiasi e si
# legge il rapporto fra l'altezza ottenuta e quella chiesta — quel rapporto e'
# il valore da scrivere. (Rimisurarlo *senza* azzerarlo prima da' un numero
# sbagliato, perche' la correzione precedente e' gia' dentro la misura.)
#
# A tenerlo onesto ci pensa `test_a_humanoid_is_as_tall_as_requested`, che
# confronta chiesto e ottenuto a tre scale: se qualcuno ritocca le proporzioni
# senza rimisurare, quel test cade subito. E' successo, e ha funzionato.
HEIGHT_YIELD = 0.833


def assembly(params: dict) -> tuple[AssemblySpec, list[MaterialSpec]]:
    """Da parametri del template a grafo di parti."""
    altezza = float(params.get("height", 1.8)) / HEIGHT_YIELD
    corporatura = BUILDS.get(str(params.get("build", "normal")), BUILDS["normal"])
    girth = corporatura["girth"]
    muscle = corporatura["muscle"]

    testa = float(params.get("head_scale", 1.0))
    spalle = float(params.get("shoulder_width", 1.0))
    braccia = float(params.get("arm_thickness", 1.0))
    gambe = float(params.get("leg_ratio", 0.48))
    meccanico = bool(params.get("mechanical", True))
    pelle = "armor" if meccanico else "skin"

    def m(chiave: str) -> float:
        return RATIOS[chiave] * altezza

    # L'esagerazione e' dello stile, non del generatore: testa e mani crescono,
    # gli arti si accorciano. E' la firma del cartoon, e sta scritta in un posto
    # solo (app/core/style.py) perche' valga per tutto cio' che si genera.
    enfasi = style().emphasis

    def curva(giro: float, lunghezza: float) -> float:
        """Curvatura da giro totale a radianti per metro.

        La ricetta vuole radianti **al metro**: passandole lo stesso numero a
        ogni scala, un arto lungo il triplo curva il triplo, e a sei metri di
        altezza la gamba si arrotola fino a staccarsi dal ginocchio. Quello che
        deve restare costante e' il giro complessivo del segmento.
        """
        return giro / max(lunghezza, 1e-6)

    def fusione(frazione: float) -> float:
        """Anche il raggio di fusione e' una proporzione, non un numero.

        Scritto in metri, a sei metri di altezza diventa invisibile e le
        giunture si staccano: il controllo di connessione lo trovava, ed
        aveva ragione.
        """
        return frazione * altezza

    lunghezza_gamba = gambe * altezza * style().emphasis("limb_length")
    parti: list[PartSpec] = []

    # ------------------------------------------------------------- busto #
    parti.append(PartSpec(
        id="torso", recipe="torso", tags=["body", "torso"], material=pelle,
        params={"height": m("torso_height"),
                "width": m("torso_width") * spalle * girth * enfasi("torso_width"),
                "depth": m("torso_depth") * girth * enfasi("torso_width"),
                "shoulder": 1.0 + (spalle - 1.0) * 0.5,
                "flare": 0.35, "waist": 0.30 if girth < 1.15 else 0.12,
                "belly": corporatura["belly"]}))

    # -------------------------------------------------------- collo e testa #
    parti.append(PartSpec(
        id="collo", recipe="limb", tags=["neck"], material=pelle, blend=fusione(0.020),
        params={"length": m("neck_length"), "radius": m("neck_radius") * girth,
                "taper": 0.10, "muscle": 0.25, "joint": 0.0},
        attach=AttachSpec(parent="torso", socket="neck")))
    parti.append(PartSpec(
        id="testa", recipe="head", tags=["head"], material=pelle, blend=fusione(0.017),
        params={"size": m("head") * testa * enfasi("head"),
                "snout": 0.22, "snout_size": 0.44,
                "flat": 1.0, "jaw": 0.85, "brow": 0.75, "cranium": 1.18},
        attach=AttachSpec(parent="collo", socket="tip", own_socket="neck")))
    for lato, segno in (("l", -1.0), ("r", 1.0)):
        parti.append(PartSpec(
            id="occhio_" + lato, recipe="eye", tags=["eye", "detail"],
            material="eye", hard=True,
            params={"size": m("head") * testa * 0.20 * enfasi("eye")},
            attach=AttachSpec(parent="testa", socket="eye_" + lato, insert=0.35)))

    # ------------------------------------------------------------ braccia #
    for lato in ("l", "r"):
        superiore = "braccio_" + lato
        parti.append(PartSpec(
            id=superiore, recipe="limb", tags=["arm", "limb"], material=pelle, blend=fusione(0.017),
            params={"length": m("upper_arm") * enfasi("limb_length"),
                    "radius": m("arm_radius") * braccia * girth,
                    "taper": 0.30,
                    "bend": curva(0.045, m("upper_arm") * enfasi("limb_length")),
                    "muscle": muscle + 0.2, "joint": 0.45},
            attach=AttachSpec(parent="torso", socket="shoulder_" + lato)))
        avambraccio = "avambraccio_" + lato
        parti.append(PartSpec(
            id=avambraccio, recipe="limb", tags=["arm", "limb"], material=pelle, blend=fusione(0.014),
            params={"length": m("forearm") * enfasi("limb_length"),
                    "radius": m("arm_radius") * braccia * girth * 0.82,
                    "taper": 0.36,
                    "bend": curva(0.048, m("forearm") * enfasi("limb_length")),
                    "muscle": muscle, "joint": 0.30},
            attach=AttachSpec(parent=superiore, socket="tip")))
        parti.append(PartSpec(
            id="mano_" + lato, recipe="extremity", tags=["arm", "hand"], material=pelle,
            blend=fusione(0.012),
            params={"length": m("hand_length") * enfasi("hand"),
                    "width": m("hand_width") * girth * enfasi("hand"),
                    "thickness": m("hand_width") * 0.42 * girth * enfasi("hand"),
                    "pitch": 8.0, "heel": 0.10, "toe": 0.80},
            attach=AttachSpec(parent=avambraccio, socket="tip")))

    # ------------------------------------------------------------- gambe #
    for lato in ("l", "r"):
        coscia = "coscia_" + lato
        parti.append(PartSpec(
            id=coscia, recipe="limb", tags=["leg", "limb"], material=pelle, blend=fusione(0.020),
            params={"length": lunghezza_gamba * 0.52, "radius": m("thigh_radius") * girth,
                    "taper": 0.34, "bend": curva(-0.055, lunghezza_gamba * 0.52),
                    "muscle": muscle + 0.3, "joint": 0.50},
            attach=AttachSpec(parent="torso", socket="hip_" + lato)))
        stinco = "stinco_" + lato
        parti.append(PartSpec(
            id=stinco, recipe="limb", tags=["leg", "limb"], material=pelle, blend=fusione(0.017),
            params={"length": lunghezza_gamba * 0.48, "radius": m("shin_radius") * girth,
                    "taper": 0.40, "bend": curva(0.055, lunghezza_gamba * 0.48),
                    "muscle": muscle + 0.15, "joint": 0.25},
            attach=AttachSpec(parent=coscia, socket="tip")))
        parti.append(PartSpec(
            id="piede_" + lato, recipe="extremity", tags=["leg", "foot"], material=pelle,
            blend=fusione(0.012),
            params={"length": m("foot_length") * enfasi("foot"),
                    "width": m("foot_width") * girth * enfasi("foot"),
                    "thickness": m("foot_width") * 0.55 * enfasi("foot"),
                    "pitch": 88.0, "heel": 0.30, "toe": 0.72},
            attach=AttachSpec(parent=stinco, socket="tip")))

    parti += _accessories(params, altezza, spalle, girth, m)

    spec = AssemblySpec(root="torso", parts=parti, blend=fusione(0.025),
                        symmetry="bilateral", semantic_class="humanoid")
    return spec, list(MATERIALS.values())


def _accessories(params: dict, altezza: float, spalle: float, girth: float, m) -> list[PartSpec]:
    """Spallacci, zaino, antenna: cio' che rende un umanoide *quel* personaggio.

    Sono parti dure: non devono sciogliersi nel corpo, si devono vedere come
    pezzi applicati, perche' e' quello che sono.
    """
    parti: list[PartSpec] = []
    if params.get("has_shoulder_pads", True):
        for lato in ("l", "r"):
            parti.append(PartSpec(
                id="spallaccio_" + lato, recipe="plate", tags=["armor", "plate"],
                material="armor", hard=True,
                params={"size": m("torso_width") * spalle * 0.62,
                        "thickness": m("torso_width") * 0.16, "coverage": 0.75},
                attach=AttachSpec(parent="torso", socket="shoulder_" + lato, insert=0.15)))
    if params.get("has_backpack", False):
        parti.append(PartSpec(
            id="zaino", recipe="segment", tags=["armor", "gear"], material="metal", hard=True,
            params={"length": m("torso_depth") * 1.5, "height": m("torso_height") * 0.85,
                    "width": m("torso_width") * 0.80, "rounding": 0.35, "taper": 0.15},
            attach=AttachSpec(parent="torso", socket="back", insert=0.25)))
    if params.get("has_antenna", False):
        parti.append(PartSpec(
            id="antenna", recipe="limb", tags=["gear"], material="metal", hard=True,
            params={"length": m("head") * 2.4, "radius": m("head") * 0.07,
                    "taper": 0.55, "muscle": 0.0, "joint": 0.0},
            attach=AttachSpec(parent="testa", socket="crest", insert=0.2)))
    if params.get("has_visor", True):
        parti.append(PartSpec(
            id="visiera", recipe="plate", tags=["gear", "face"], material="eye", hard=True,
            params={"size": m("head") * 0.72, "thickness": m("head") * 0.16, "coverage": 0.55},
            attach=AttachSpec(parent="testa", socket="face", insert=0.55)))
    return parti
