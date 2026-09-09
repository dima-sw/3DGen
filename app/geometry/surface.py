"""Dal campo di distanza alla mesh.

Marching cubes sul campo, poi una lisciatura che toglie la scalettatura della
griglia senza gonfiare il volume. La risoluzione e' un parametro: bassa per
l'anteprima interattiva, alta per l'export.
"""
from __future__ import annotations

import time

import numpy as np
import trimesh

from app.core.logging_setup import get
from app.geometry.sdf import Field

log = get("geometry.surface")

# risoluzioni tipiche: quante celle sull'asse piu' lungo
PREVIEW = 64
NORMAL = 112
HIGH = 176


def grid_for(bounds: tuple[np.ndarray, np.ndarray], resolution: int,
             padding: float = 0.06) -> tuple[np.ndarray, float, tuple[int, int, int]]:
    lo, hi = bounds
    size = np.maximum(hi - lo, 1e-4)
    pad = size.max() * padding
    lo = lo - pad
    hi = hi + pad
    step = float(np.max(hi - lo)) / max(int(resolution), 8)
    shape = tuple(int(max(np.ceil(v / step), 4)) + 1 for v in (hi - lo))
    return lo, step, shape


def to_mesh(field: Field, resolution: int = NORMAL, padding: float = 0.06,
            smooth: int = 5, level: float = 0.0) -> trimesh.Trimesh:
    """Estrae la superficie del solido descritto dal campo."""
    from skimage import measure

    lo, hi = field.bounds()
    if not np.all(np.isfinite(lo)) or not np.all(np.isfinite(hi)):
        raise ValueError("il campo non ha limiti finiti: non e' estraibile")

    origin, step, shape = grid_for((lo, hi), resolution, padding)
    cells = int(np.prod(shape))

    t0 = time.perf_counter()
    values = field.eval_grid(origin, step, shape)
    t_field = time.perf_counter() - t0

    if values.min() > level or values.max() < level:
        raise ValueError("il campo non attraversa la superficie: solido vuoto o "
                         "risoluzione troppo bassa")

    t0 = time.perf_counter()
    verts, faces, _, _ = measure.marching_cubes(values, level=level,
                                                spacing=(step, step, step))
    t_mc = time.perf_counter() - t0
    verts = verts + origin

    mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
    mesh.merge_vertices()
    mesh.fix_normals()
    if smooth > 0 and len(mesh.faces):
        # Taubin non ritira il volume come farebbe il laplaciano puro
        trimesh.smoothing.filter_taubin(mesh, iterations=int(smooth))

    log.info("superficie: griglia %s (%d celle) campo %.2fs, marching cubes %.2fs, "
             "%d facce", "x".join(str(s) for s in shape), cells, t_field, t_mc, len(mesh.faces))
    return mesh


def to_mesh_capped(field: Field, resolution: int = NORMAL, max_cells: int = 6_000_000,
                   **kwargs) -> trimesh.Trimesh:
    """Come to_mesh, ma abbassa la risoluzione se la griglia sarebbe troppo grande.

    Serve a non far esplodere memoria e tempi su oggetti molto allungati, dove
    la scatola e' grande ma il solido e' sottile.
    """
    lo, hi = field.bounds()
    _, _, shape = grid_for((lo, hi), resolution, kwargs.get("padding", 0.06))
    cells = int(np.prod(shape))
    if cells > max_cells:
        scaled = int(resolution * (max_cells / cells) ** (1 / 3))
        log.warning("griglia da %d celle: riduco la risoluzione da %d a %d",
                    cells, resolution, scaled)
        resolution = max(scaled, 24)
    return to_mesh(field, resolution=resolution, **kwargs)
