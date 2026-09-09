"""Primitive geometriche. Wrapper su trimesh + costruzioni custom.

Convenzioni del progetto:
  - asse Y = alto (up)
  - asse X = larghezza (destra)
  - asse Z = profondita' (avanti = +Z)
  - unita' = metri
"""
from __future__ import annotations

import numpy as np
import trimesh
from trimesh import creation as tc

Vec3 = tuple[float, float, float]


# --------------------------------------------------------------------------- #
# helper interni
# --------------------------------------------------------------------------- #
def _earclip(poly: np.ndarray) -> np.ndarray:
    """Triangolazione ear-clipping di un poligono semplice 2D, senza dipendenze esterne."""
    n = len(poly)
    if n < 3:
        return np.zeros((0, 3), dtype=np.int64)
    idx = list(range(n))
    area = 0.0
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    if area < 0:
        idx.reverse()

    def cross(a, b, c) -> float:
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    def inside(p, a, b, c) -> bool:
        d1, d2, d3 = cross(a, b, p), cross(b, c, p), cross(c, a, p)
        neg = d1 < 0 or d2 < 0 or d3 < 0
        pos = d1 > 0 or d2 > 0 or d3 > 0
        return not (neg and pos)

    tris: list[tuple[int, int, int]] = []
    guard = 0
    while len(idx) > 3 and guard < 5000:
        guard += 1
        clipped = False
        for k in range(len(idx)):
            i0, i1, i2 = idx[k - 1], idx[k], idx[(k + 1) % len(idx)]
            a, b, c = poly[i0], poly[i1], poly[i2]
            if cross(a, b, c) <= 1e-12:
                continue
            if any(inside(poly[j], a, b, c) for j in idx if j not in (i0, i1, i2)):
                continue
            tris.append((i0, i1, i2))
            idx.pop(k)
            clipped = True
            break
        if not clipped:
            break
    if len(idx) >= 3:
        for k in range(1, len(idx) - 1):
            tris.append((idx[0], idx[k], idx[k + 1]))
    return np.asarray(tris, dtype=np.int64)


def _finish(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    mesh.merge_vertices()
    try:  # API cambiata fra trimesh 3.x e 5.x
        mesh.update_faces(mesh.nondegenerate_faces())
    except AttributeError:
        mesh.remove_degenerate_faces()
    mesh.remove_unreferenced_vertices()
    mesh.fix_normals()
    return mesh


def _rot(angle_rad: float, axis: list[float]) -> np.ndarray:
    return trimesh.transformations.rotation_matrix(angle_rad, axis)


# --------------------------------------------------------------------------- #
# primitive
# --------------------------------------------------------------------------- #
def box(size: Vec3 = (1, 1, 1)) -> trimesh.Trimesh:
    return tc.box(extents=np.asarray(size, dtype=float))


def rounded_box(size: Vec3 = (1, 1, 1), radius: float = 0.08, subdiv: int = 2) -> trimesh.Trimesh:
    """Box con spigoli arrotondati: convex hull di 8 sfere. Ideale per carrozzerie."""
    sx, sy, sz = (max(float(s), 1e-4) for s in size)
    r = float(np.clip(radius, 1e-3, 0.49 * min(sx, sy, sz)))
    hx, hy, hz = sx / 2 - r, sy / 2 - r, sz / 2 - r
    unit = tc.icosphere(subdivisions=int(np.clip(subdiv, 1, 3)), radius=r).vertices
    pts = [unit + np.array([x, y, z])
           for x in (-hx, hx) for y in (-hy, hy) for z in (-hz, hz)]
    return _finish(trimesh.Trimesh(vertices=np.vstack(pts)).convex_hull)


def sphere(radius: float = 0.5, subdiv: int = 3) -> trimesh.Trimesh:
    return tc.icosphere(subdivisions=int(np.clip(subdiv, 0, 4)), radius=float(radius))


def cylinder(radius: float = 0.5, height: float = 1.0, sections: int = 32) -> trimesh.Trimesh:
    """Cilindro con asse Y."""
    m = tc.cylinder(radius=float(radius), height=float(height), sections=int(sections))
    m.apply_transform(_rot(np.pi / 2, [1, 0, 0]))
    return m


def cone(radius: float = 0.5, height: float = 1.0, sections: int = 32) -> trimesh.Trimesh:
    """Cono con base in basso e apice verso +Y, centrato sull'origine."""
    m = tc.cone(radius=float(radius), height=float(height), sections=int(sections))
    m.apply_transform(trimesh.transformations.translation_matrix([0, 0, -float(height) / 2]))
    m.apply_transform(_rot(-np.pi / 2, [1, 0, 0]))
    return m


def capsule(radius: float = 0.25, height: float = 1.0, count: int = 16) -> trimesh.Trimesh:
    """Capsula con asse Y, centrata. Lunghezza totale = height + 2 * radius."""
    m = tc.capsule(radius=float(radius), height=float(height), count=(int(count), int(count)))
    m.apply_transform(_rot(np.pi / 2, [1, 0, 0]))
    return m


def torus(radius: float = 0.5, tube: float = 0.12, sections: int = 32) -> trimesh.Trimesh:
    m = tc.torus(major_radius=float(radius), minor_radius=float(tube),
                 major_sections=int(sections), minor_sections=max(8, int(sections) // 2))
    m.apply_transform(_rot(np.pi / 2, [1, 0, 0]))
    return m


def tube(radius: float = 0.5, inner: float = 0.3, height: float = 0.3, sections: int = 32) -> trimesh.Trimesh:
    """Anello estruso, asse Y. Pneumatici, cerchioni, tubi."""
    inner = float(min(inner, radius * 0.95))
    m = tc.annulus(r_min=inner, r_max=float(radius), height=float(height), sections=int(sections))
    m.apply_transform(_rot(np.pi / 2, [1, 0, 0]))
    return m


def plane(width: float = 1.0, depth: float = 1.0, thickness: float = 0.01) -> trimesh.Trimesh:
    return box((float(width), float(thickness), float(depth)))


def prism(profile: list[tuple[float, float]] | None = None, depth: float = 1.0) -> trimesh.Trimesh:
    """Estrude un profilo 2D lungo X. Il profilo giace nel piano (Z=avanti, Y=alto).

    profile: lista di punti (z, y). depth = larghezza lungo X.
    """
    if not profile:
        profile = [(-0.5, 0.0), (0.5, 0.0), (0.5, 1.0), (-0.5, 1.0)]
    poly = np.asarray(profile, dtype=float)
    tris = _earclip(poly)
    n = len(poly)
    h = float(depth) / 2.0
    lo = np.column_stack([np.full(n, -h), poly[:, 1], poly[:, 0]])
    hi = np.column_stack([np.full(n, h), poly[:, 1], poly[:, 0]])
    verts = np.vstack([lo, hi])
    faces: list[tuple[int, int, int]] = []
    for a, b, c in tris:
        faces.append((int(a), int(c), int(b)))
        faces.append((int(a) + n, int(b) + n, int(c) + n))
    for i in range(n):
        j = (i + 1) % n
        faces.append((i, j, j + n))
        faces.append((i, j + n, i + n))
    return _finish(trimesh.Trimesh(vertices=verts, faces=np.asarray(faces, dtype=np.int64)))


def wedge(size: Vec3 = (1, 1, 1)) -> trimesh.Trimesh:
    """Cuneo: sale da Z- verso Z+."""
    sx, sy, sz = (float(s) for s in size)
    return prism([(-sz / 2, -sy / 2), (sz / 2, -sy / 2), (sz / 2, sy / 2)], sx)


def hexahedron(bottom: tuple[float, float], top: tuple[float, float],
               height: float, top_offset: tuple[float, float] = (0.0, 0.0)) -> trimesh.Trimesh:
    """Tronco di piramide a base rettangolare: base (x,z) verso cima (x,z). Cabine, torsi."""
    bx, bz = float(bottom[0]) / 2, float(bottom[1]) / 2
    tx, tz = float(top[0]) / 2, float(top[1]) / 2
    ox, oz = top_offset
    hy = float(height) / 2
    v = np.array([
        [-bx, -hy, -bz], [bx, -hy, -bz], [bx, -hy, bz], [-bx, -hy, bz],
        [-tx + ox, hy, -tz + oz], [tx + ox, hy, -tz + oz], [tx + ox, hy, tz + oz], [-tx + ox, hy, tz + oz],
    ], dtype=float)
    f = np.array([
        [0, 2, 1], [0, 3, 2],
        [4, 5, 6], [4, 6, 7],
        [0, 1, 5], [0, 5, 4],
        [1, 2, 6], [1, 6, 5],
        [2, 3, 7], [2, 7, 6],
        [3, 0, 4], [3, 4, 7],
    ], dtype=np.int64)
    return _finish(trimesh.Trimesh(vertices=v, faces=f))


PRIMITIVES = {
    "box": box, "rounded_box": rounded_box, "sphere": sphere, "cylinder": cylinder,
    "cone": cone, "capsule": capsule, "torus": torus, "tube": tube,
    "plane": plane, "prism": prism, "wedge": wedge,
}
