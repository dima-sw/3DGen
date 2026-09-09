"""Texture procedurali.

Nessun file di immagine da distribuire: le mappe si calcolano da un seme, quindi
occupano zero spazio nel repository e sono riproducibili. Rumore, striature e
motivi geometrici bastano a coprire i materiali che servono a questo software:
metallo, gomma, legno, squame, pelo, intonaco, pelle.

Ogni generatore restituisce le mappe PBR pronte per il GLB: colore base,
rugosita'/metallicita' impacchettate come vuole glTF, e normali derivate da una
mappa di altezza.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

import numpy as np

DEFAULT_SIZE = 256


# --------------------------------------------------------------------------- #
# Rumore
# --------------------------------------------------------------------------- #
def value_noise(size: int, cells: int, seed: int) -> np.ndarray:
    """Rumore di valore interpolato, ripetibile e senza cuciture.

    La griglia casuale viene chiusa su se stessa prima dell'interpolazione:
    cosi' la texture si puo' ripetere senza righe visibili ai bordi.
    """
    rng = np.random.default_rng(seed)
    cells = max(int(cells), 1)
    grid = rng.random((cells + 1, cells + 1))
    grid[-1, :] = grid[0, :]
    grid[:, -1] = grid[:, 0]

    coords = np.linspace(0.0, cells, size, endpoint=False)
    i0 = np.floor(coords).astype(int)
    frac = coords - i0
    smooth = frac * frac * (3.0 - 2.0 * frac)          # interpolazione morbida

    top = grid[i0][:, i0]
    bottom = grid[i0 + 1][:, i0]
    left = grid[i0][:, i0 + 1]
    right = grid[i0 + 1][:, i0 + 1]

    sx = smooth[None, :]
    sy = smooth[:, None]
    a = top * (1 - sx) + left * sx
    b = bottom * (1 - sx) + right * sx
    return a * (1 - sy) + b * sy


def fractal_noise(size: int, cells: int = 4, octaves: int = 4, seed: int = 0,
                  persistence: float = 0.5) -> np.ndarray:
    total = np.zeros((size, size))
    amplitude = 1.0
    weight = 0.0
    for octave in range(max(octaves, 1)):
        total += value_noise(size, cells * 2 ** octave, seed + octave * 977) * amplitude
        weight += amplitude
        amplitude *= persistence
    out = total / max(weight, 1e-9)
    return (out - out.min()) / max(float(np.ptp(out)), 1e-9)


def _grid(size: int) -> tuple[np.ndarray, np.ndarray]:
    axis = np.linspace(0.0, 1.0, size, endpoint=False)
    return np.meshgrid(axis, axis, indexing="ij")


# --------------------------------------------------------------------------- #
# Mappe
# --------------------------------------------------------------------------- #
@dataclass
class TextureSet:
    """Le mappe di un materiale, in valori 0..1."""

    base_color: np.ndarray          # (n, n, 3)
    roughness: np.ndarray           # (n, n)
    height: np.ndarray              # (n, n)
    metallic: np.ndarray | None = None

    def normal_map(self, strength: float = 1.0) -> np.ndarray:
        """Normali dalla mappa di altezza, per differenze centrali."""
        h = self.height * float(strength)
        dx = np.roll(h, -1, axis=1) - np.roll(h, 1, axis=1)
        dy = np.roll(h, -1, axis=0) - np.roll(h, 1, axis=0)
        normals = np.stack([-dx, -dy, np.full_like(h, 2.0 / max(h.shape[0], 1) * 8.0)], axis=-1)
        length = np.linalg.norm(normals, axis=-1, keepdims=True)
        normals = normals / np.maximum(length, 1e-9)
        return normals * 0.5 + 0.5


def _tint(pattern: np.ndarray, dark: tuple[float, float, float],
          light: tuple[float, float, float]) -> np.ndarray:
    a = np.asarray(dark, dtype=float)
    b = np.asarray(light, dtype=float)
    return a[None, None, :] + (b - a)[None, None, :] * pattern[..., None]


def metal(size: int = DEFAULT_SIZE, seed: int = 0) -> TextureSet:
    """Metallo graffiato: striature direzionali sottili."""
    x, y = _grid(size)
    streaks = fractal_noise(size, cells=2, octaves=3, seed=seed)
    fine = value_noise(size, size // 4, seed + 31)
    scratches = np.clip(np.sin((y * 90.0 + streaks * 22.0)) ** 8, 0, 1)
    pattern = 0.72 + 0.16 * streaks + 0.12 * fine
    height = scratches * 0.35 + fine * 0.15
    roughness = np.clip(0.22 + 0.30 * scratches + 0.12 * fine, 0.05, 0.95)
    return TextureSet(_tint(pattern, (0.42, 0.44, 0.47), (0.86, 0.88, 0.92)),
                      roughness, height, metallic=np.full((size, size), 0.95))


def rubber(size: int = DEFAULT_SIZE, seed: int = 0) -> TextureSet:
    """Gomma: opaca, granulosa, con tasselli regolari."""
    x, y = _grid(size)
    grain = fractal_noise(size, cells=16, octaves=3, seed=seed)
    tread = ((np.sin(x * math.tau * 9.0) > 0.25) ^ (np.sin(y * math.tau * 5.0) > 0.4)).astype(float)
    pattern = 0.20 + 0.10 * grain + 0.06 * tread
    height = tread * 0.6 + grain * 0.25
    return TextureSet(_tint(pattern, (0.05, 0.05, 0.06), (0.30, 0.30, 0.33)),
                      np.clip(0.88 + 0.08 * grain, 0.4, 1.0), height)


def wood(size: int = DEFAULT_SIZE, seed: int = 0) -> TextureSet:
    """Legno: anelli disturbati dal rumore."""
    x, y = _grid(size)
    warp = fractal_noise(size, cells=3, octaves=4, seed=seed)
    rings = np.sin((x * 14.0 + warp * 4.5) * math.pi) * 0.5 + 0.5
    fibre = value_noise(size, size // 3, seed + 7)
    pattern = 0.35 + 0.45 * rings ** 1.6 + 0.12 * fibre
    height = rings * 0.4 + fibre * 0.2
    return TextureSet(_tint(pattern, (0.24, 0.13, 0.06), (0.72, 0.50, 0.28)),
                      np.clip(0.62 + 0.18 * rings, 0.2, 1.0), height)


def scales(size: int = DEFAULT_SIZE, seed: int = 0) -> TextureSet:
    """Squame: file sfalsate di losanghe."""
    x, y = _grid(size)
    rows = 14.0
    offset = np.floor(y * rows) % 2 * 0.5
    u = (x * rows + offset) % 1.0 - 0.5
    v = (y * rows) % 1.0 - 0.5
    d = np.sqrt(u * u + (v * 1.35) ** 2)
    scale_mask = np.clip(1.0 - d * 2.4, 0.0, 1.0)
    mottle = fractal_noise(size, cells=5, octaves=3, seed=seed)
    pattern = 0.45 + 0.40 * scale_mask + 0.18 * mottle
    return TextureSet(_tint(pattern, (0.18, 0.22, 0.28), (0.80, 0.72, 0.45)),
                      np.clip(0.55 - 0.25 * scale_mask + 0.15 * mottle, 0.08, 0.95),
                      scale_mask * 0.7 + mottle * 0.2)


def fur(size: int = DEFAULT_SIZE, seed: int = 0) -> TextureSet:
    """Pelo: rumore direzionale fitto."""
    x, y = _grid(size)
    strands = value_noise(size, size // 2, seed)
    drift = fractal_noise(size, cells=3, octaves=3, seed=seed + 5)
    pattern = 0.35 + 0.40 * strands ** 1.5 + 0.22 * drift
    return TextureSet(_tint(pattern, (0.16, 0.12, 0.09), (0.66, 0.53, 0.38)),
                      np.clip(0.80 + 0.15 * strands, 0.4, 1.0),
                      strands * 0.5 + drift * 0.25)


def plaster(size: int = DEFAULT_SIZE, seed: int = 0) -> TextureSet:
    """Intonaco: grana grossa, quasi senza riflessi."""
    coarse = fractal_noise(size, cells=6, octaves=4, seed=seed)
    speckle = value_noise(size, size // 3, seed + 3)
    pattern = 0.68 + 0.22 * coarse + 0.10 * speckle
    return TextureSet(_tint(pattern, (0.55, 0.52, 0.47), (0.95, 0.93, 0.88)),
                      np.clip(0.86 + 0.10 * coarse, 0.5, 1.0), coarse * 0.5)


def skin(size: int = DEFAULT_SIZE, seed: int = 0) -> TextureSet:
    """Pelle: variazioni ampie e pori appena accennati."""
    broad = fractal_noise(size, cells=3, octaves=3, seed=seed)
    pores = value_noise(size, size // 2, seed + 11)
    pattern = 0.55 + 0.30 * broad + 0.12 * pores
    return TextureSet(_tint(pattern, (0.52, 0.33, 0.24), (0.92, 0.72, 0.58)),
                      np.clip(0.62 + 0.16 * pores, 0.3, 0.95), pores * 0.25 + broad * 0.2)


def glass(size: int = DEFAULT_SIZE, seed: int = 0) -> TextureSet:
    smear = fractal_noise(size, cells=2, octaves=2, seed=seed)
    pattern = 0.80 + 0.12 * smear
    return TextureSet(_tint(pattern, (0.62, 0.72, 0.80), (0.92, 0.96, 1.0)),
                      np.clip(0.05 + 0.10 * smear, 0.01, 0.4), smear * 0.05)


def concrete(size: int = DEFAULT_SIZE, seed: int = 0) -> TextureSet:
    coarse = fractal_noise(size, cells=8, octaves=4, seed=seed)
    stains = fractal_noise(size, cells=2, octaves=2, seed=seed + 17)
    pattern = 0.52 + 0.26 * coarse - 0.14 * stains
    return TextureSet(_tint(np.clip(pattern, 0, 1), (0.38, 0.38, 0.36), (0.80, 0.80, 0.78)),
                      np.clip(0.90 - 0.10 * stains, 0.5, 1.0), coarse * 0.45)


GENERATORS: dict[str, Callable[..., TextureSet]] = {
    "metal": metal, "rubber": rubber, "wood": wood, "scales": scales,
    "fur": fur, "plaster": plaster, "skin": skin, "glass": glass,
    "concrete": concrete,
}


def generate(name: str, size: int = DEFAULT_SIZE, seed: int = 0) -> TextureSet:
    generator = GENERATORS.get(name)
    if generator is None:
        raise KeyError("texture procedurale sconosciuta: %s" % name)
    return generator(size=size, seed=seed)


# --------------------------------------------------------------------------- #
# Verso glTF
# --------------------------------------------------------------------------- #
def to_image(array: np.ndarray):
    """Da array 0..1 a immagine Pillow."""
    from PIL import Image

    data = np.clip(np.asarray(array, dtype=float), 0.0, 1.0)
    if data.ndim == 2:
        return Image.fromarray((data * 255).astype(np.uint8), mode="L")
    return Image.fromarray((data * 255).astype(np.uint8), mode="RGB")


def metallic_roughness_image(textures: TextureSet):
    """glTF vuole rugosita' in verde e metallicita' in blu, nella stessa mappa."""
    size = textures.roughness.shape[0]
    metal_channel = (textures.metallic if textures.metallic is not None
                     else np.zeros((size, size)))
    packed = np.stack([np.zeros((size, size)), textures.roughness, metal_channel], axis=-1)
    return to_image(packed)


def tint_base_color(textures: TextureSet, color: tuple[float, float, float]) -> np.ndarray:
    """Riporta la texture sulla tinta chiesta, conservandone il contrasto.

    Senza questo passaggio una jeep rossa uscirebbe con il colore della texture
    invece del suo: il materiale decide la tinta, la texture il dettaglio.
    """
    luminance = textures.base_color @ np.array([0.299, 0.587, 0.114])
    mean = float(np.mean(luminance)) or 1.0
    factor = np.clip(luminance / mean, 0.55, 1.6)[..., None]
    return np.clip(np.asarray(color, dtype=float)[None, None, :] * factor, 0.0, 1.0)
