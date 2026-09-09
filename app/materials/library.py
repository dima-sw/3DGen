"""Finiture: quale texture procedurale spetta a quale materiale.

Il materiale (`MaterialSpec`) dice *di che colore* e' una superficie; la finitura
dice *com'e' fatta*. Sono separati apposta: una jeep rossa e una nera usano la
stessa finitura "vernice", con tinte diverse.

Le finiture sono dati, come le ricette delle parti: un file JSON, nessun codice.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from app.core.logging_setup import get
from app.core.spec import MaterialSpec
from app.materials import texture as tx

log = get("materials.library")

DEFINITIONS = Path(__file__).resolve().parent / "finishes.json"


@dataclass(frozen=True)
class Finish:
    """Come si veste un materiale."""

    texture: str = ""                 # generatore procedurale, "" = tinta piatta
    tiling: float = 0.4               # metri per ripetizione
    normal_strength: float = 1.0
    roughness_mix: float = 0.7        # quanto la texture domina sulla rugosita'
    # Quanto il dettaglio modula il colore. Una vernice ha una grana appena
    # accennata; la corteccia o la roccia quasi solo grana.
    detail: float = 0.8

    def enabled(self) -> bool:
        return bool(self.texture) and self.texture in tx.GENERATORS


CATALOG: dict[str, Finish] = {}

# Ripiego per nome quando il materiale non e' in catalogo: evita di dover
# elencare ogni variante ("body", "corpo", "carrozzeria", ...).
KEYWORD_FALLBACK = (
    ("tire", "rubber"), ("rubber", "rubber"), ("gomma", "rubber"),
    ("wood", "wood"), ("legno", "wood"),
    ("metal", "metal"), ("chrome", "metal"), ("rim", "metal"), ("armor", "metal"),
    ("steel", "metal"), ("blade", "metal"), ("acciaio", "metal"),
    ("skin", "skin"), ("pelle", "skin"), ("flesh", "skin"),
    ("scale", "scales"), ("squam", "scales"),
    ("fur", "fur"), ("pelo", "fur"), ("membrane", "fur"),
    ("wall", "plaster"), ("muro", "plaster"), ("stone", "concrete"),
    ("concrete", "concrete"), ("foundation", "concrete"),
    ("glass", "glass"), ("vetro", "glass"),
)


def load_catalog(path: Path | None = None, reload: bool = False) -> dict[str, Finish]:
    if CATALOG and not reload:
        return CATALOG
    if reload:
        CATALOG.clear()
    source = Path(path) if path is not None else DEFINITIONS
    if not source.is_file():
        log.warning("catalogo finiture assente: %s", source)
        return CATALOG
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except Exception as exc:
        log.error("catalogo finiture illeggibile: %s", exc)
        return CATALOG
    for name, values in data.items():
        try:
            CATALOG[name] = Finish(**values)
        except TypeError as exc:
            log.warning("finitura '%s' scartata: %s", name, exc)
    log.info("catalogo finiture: %d voci", len(CATALOG))
    return CATALOG


def finish_for(material: str) -> Finish | None:
    """Finitura di un materiale, per nome o per parola chiave."""
    load_catalog()
    if material in CATALOG:
        return CATALOG[material]
    lowered = (material or "").lower()
    for keyword, generator in KEYWORD_FALLBACK:
        if keyword in lowered:
            return Finish(texture=generator)
    return None


# --------------------------------------------------------------------------- #
# Generazione delle mappe, con cache
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=64)
def _textures(name: str, size: int, seed: int) -> tx.TextureSet:
    return tx.generate(name, size=size, seed=seed)


@lru_cache(maxsize=128)
def maps_for(material_name: str, base_color: tuple[float, float, float],
             roughness: float, metallic: float, size: int = 256, seed: int = 0):
    """Immagini PBR pronte per il GLB, oppure None se il materiale e' piatto.

    Il risultato e' in cache: gli stessi materiali ricorrono su molte parti e
    rigenerare le mappe a ogni nodo sarebbe uno spreco.
    """
    finish = finish_for(material_name)
    if finish is None or not finish.enabled():
        return None

    textures = _textures(finish.texture, size, seed)
    colour = tx.tint_base_color(textures, base_color)

    # la rugosita' del materiale resta il riferimento, la texture la modula
    mix = float(np.clip(finish.roughness_mix, 0.0, 1.0))
    rough = np.clip(roughness * (1.0 - mix) + textures.roughness * mix, 0.02, 1.0)
    metal_map = textures.metallic
    if metal_map is None:
        metal_map = np.full(rough.shape, float(np.clip(metallic, 0.0, 1.0)))
    else:
        metal_map = np.clip(metal_map * max(metallic, 0.25), 0.0, 1.0)

    packed = tx.TextureSet(colour, rough, textures.height, metal_map)
    return {
        "base_color": tx.to_image(colour),
        "metallic_roughness": tx.metallic_roughness_image(packed),
        "normal": tx.to_image(textures.normal_map(finish.normal_strength)),
        "tiling": finish.tiling,
    }


def describe(material: MaterialSpec) -> str:
    finish = finish_for(material.name)
    return "%s (%s)" % (material.name, finish.texture if finish else "tinta piatta")
