"""Un GLB vero, con oggetti separati, come un artista lo esporterebbe.

Non e' codice di plugin ed e' solo strumento di test: produce file su disco che
si importano senza questo modulo. I nomi dei nodi sono quelli del caso ideale
descritto dalla milestone — `Body`, `Head`, `Eye_L`, `Eye_R`, `Sword` — perche'
un GLB che arriva gia' diviso in parti e' esattamente la situazione in cui
l'authoring deve essere comodo.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import trimesh


def box(extents, translate=(0.0, 0.0, 0.0), color=None) -> trimesh.Trimesh:
    mesh = trimesh.creation.box(extents=extents)
    mesh.apply_translation(translate)
    if color is not None:
        mesh.visual.face_colors = np.tile(np.array(color, dtype=np.uint8),
                                          (len(mesh.faces), 1))
    return mesh


def knight_scene() -> trimesh.Scene:
    """Un cavaliere in cinque pezzi distinti, che crescono lungo +Y."""
    scene = trimesh.Scene()
    scene.add_geometry(box((0.5, 1.0, 0.3), (0.0, 0.5, 0.0), (120, 130, 150, 255)),
                       node_name="Body", geom_name="Body")
    scene.add_geometry(box((0.34, 0.34, 0.34), (0.0, 1.2, 0.0), (210, 180, 140, 255)),
                       node_name="Head", geom_name="Head")
    scene.add_geometry(box((0.08, 0.08, 0.06), (-0.1, 1.26, 0.17), (30, 30, 40, 255)),
                       node_name="Eye_L", geom_name="Eye_L")
    scene.add_geometry(box((0.08, 0.08, 0.06), (0.1, 1.26, 0.17), (30, 30, 40, 255)),
                       node_name="Eye_R", geom_name="Eye_R")
    scene.add_geometry(box((0.07, 0.9, 0.02), (0.45, 0.8, 0.0), (200, 200, 210, 255)),
                       node_name="Sword", geom_name="Sword")
    return scene


def write_knight_glb(root: Path, name: str = "knight.glb") -> Path:
    """Scrive il GLB e restituisce il percorso. Byte veri, non un mock."""
    target = Path(root) / name
    target.parent.mkdir(parents=True, exist_ok=True)
    raw = knight_scene().export(file_type="glb")
    target.write_bytes(raw if isinstance(raw, bytes) else bytes(raw))
    return target


def write_single_glb(root: Path, name: str = "pebble.glb", *,
                     extents=(0.4, 0.4, 0.4)) -> Path:
    """Un GLB con un solo oggetto: il caso minimo."""
    target = Path(root) / name
    target.parent.mkdir(parents=True, exist_ok=True)
    scene = trimesh.Scene()
    scene.add_geometry(box(extents, (0.0, extents[1] / 2.0, 0.0)),
                       node_name="Pebble", geom_name="Pebble")
    raw = scene.export(file_type="glb")
    target.write_bytes(raw if isinstance(raw, bytes) else bytes(raw))
    return target
