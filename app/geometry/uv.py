"""Coordinate UV per mesh che non hanno una parametrizzazione naturale.

Le mesh estratte da un campo di distanza non arrivano con delle UV: marching
cubes produce triangoli, non una superficie parametrizzata. Srotolarle davvero
richiederebbe un algoritmo di unwrap; qui basta molto meno.

La proiezione a scatola assegna a ogni triangolo il piano piu' vicino alla sua
normale e ci proietta sopra. Le cuciture cadono dove la superficie gira, cioe'
dove si notano poco, e la scala resta uniforme in metri: una texture di gomma
ha la stessa grana su una ruota grande e su una piccola.
"""
from __future__ import annotations

import numpy as np
import trimesh


def box_uv(mesh: trimesh.Trimesh, texel: float = 0.5,
           origin: np.ndarray | None = None) -> tuple[trimesh.Trimesh, np.ndarray]:
    """Proiezione triplanare per faccia.

    `texel` e' quanti metri di superficie coprono una ripetizione della texture.
    Restituisce una copia della mesh con i vertici sdoppiati per faccia (serve
    perche' facce adiacenti possono usare piani diversi) e le sue UV.
    """
    if len(mesh.faces) == 0:
        return mesh, np.zeros((0, 2))

    work = mesh.copy()
    work.unmerge_vertices()          # ogni faccia ha i propri vertici
    scale = 1.0 / max(float(texel), 1e-4)
    shift = np.zeros(3) if origin is None else np.asarray(origin, dtype=float)

    normals = np.asarray(work.face_normals, dtype=float)
    axis = np.argmax(np.abs(normals), axis=1)          # piano dominante
    vertices = (np.asarray(work.vertices, dtype=float) - shift) * scale

    # per ogni asse dominante, le due coordinate che restano
    plane = {0: (1, 2), 1: (0, 2), 2: (0, 1)}
    uv = np.zeros((len(work.vertices), 2))
    faces = np.asarray(work.faces)
    for dominant in (0, 1, 2):
        picked = np.flatnonzero(axis == dominant)
        if picked.size == 0:
            continue
        u_axis, v_axis = plane[dominant]
        indices = faces[picked].reshape(-1)
        uv[indices, 0] = vertices[indices, u_axis]
        uv[indices, 1] = vertices[indices, v_axis]

    # il verso della normale evita che la texture appaia specchiata sul retro
    flip = np.flatnonzero(normals[np.arange(len(normals)), axis] < 0)
    if flip.size:
        indices = faces[flip].reshape(-1)
        uv[indices, 0] = -uv[indices, 0]

    return work, uv


def uv_bounds_are_reasonable(uv: np.ndarray, limit: float = 5000.0) -> bool:
    """Guardia contro texel troppo piccoli su oggetti grandi."""
    return bool(uv.size == 0 or np.max(np.abs(uv)) < limit)
