"""Grammatica di forme: volumi, operazioni, combinatori, estrazione superficie."""
from __future__ import annotations

import numpy as np
import pytest

from app.geometry import sdf
from app.geometry.surface import PREVIEW, to_mesh, to_mesh_capped


def field_at(f: sdf.Field, *points) -> np.ndarray:
    return f.sample(np.asarray(points, dtype=float))


# --------------------------------------------------------------------------- #
# Volumi
# --------------------------------------------------------------------------- #
def test_sphere_distance_is_exact():
    s = sdf.Sphere(radius=1.0)
    d = field_at(s, (0, 0, 0), (1, 0, 0), (2, 0, 0), (0, 3, 0))
    assert d == pytest.approx([-1.0, 0.0, 1.0, 2.0], abs=1e-9)


def test_box_inside_and_outside():
    b = sdf.Box(size=(2, 2, 2))
    d = field_at(b, (0, 0, 0), (1, 0, 0), (2, 0, 0), (2, 2, 2))
    assert d[0] < 0 and d[1] == pytest.approx(0.0, abs=1e-9)
    assert d[2] == pytest.approx(1.0) and d[3] == pytest.approx(np.sqrt(3))


def test_capsule_with_variable_radius():
    c = sdf.Capsule(a=(0, 0, 0), b=(0, 1, 0), radius=0.3, radius_end=0.1)
    assert field_at(c, (0.29, 0, 0))[0] < 0        # dentro, estremo grosso
    assert field_at(c, (0.29, 1, 0))[0] > 0        # fuori, estremo sottile


@pytest.mark.parametrize("name,volume", sorted(sdf.VOLUMES.items()))
def test_every_volume_is_a_non_empty_solid(name, volume):
    """Il toro ha il centro nel buco: si verifica che esista materia, non dove."""
    f = volume()
    lo, hi = f.bounds()
    assert np.all(hi > lo) and np.all(np.isfinite(lo))
    rng = np.random.default_rng(1)
    pts = lo + rng.random((20000, 3)) * (hi - lo)
    assert np.any(f.sample(pts) < 0), "%s non contiene materia" % name


@pytest.mark.parametrize("name,volume", sorted(sdf.VOLUMES.items()))
def test_bounds_really_contain_the_solid(name, volume):
    """La scatola deve essere conservativa: nessun punto solido fuori."""
    f = volume()
    lo, hi = f.bounds()
    rng = np.random.default_rng(0)
    span = hi - lo
    pts = lo - span * 0.5 + rng.random((6000, 3)) * span * 2.0
    inside = f.sample(pts) < 0
    outside_box = np.any((pts < lo - 1e-6) | (pts > hi + 1e-6), axis=-1)
    assert not np.any(inside & outside_box), "%s: solido fuori dalla scatola" % name


# --------------------------------------------------------------------------- #
# Operazioni
# --------------------------------------------------------------------------- #
def test_translate_moves_the_solid():
    f = sdf.Translate(sdf.Sphere(0.5), (2, 0, 0))
    assert field_at(f, (2, 0, 0))[0] == pytest.approx(-0.5)
    assert field_at(f, (0, 0, 0))[0] == pytest.approx(1.5)


def test_rotate_is_reversible():
    base = sdf.Box(size=(2, 0.4, 0.4))
    turned = sdf.Rotate(base, (0, 0, 90))
    # la scatola lunga su X diventa lunga su Y
    assert field_at(turned, (0, 0.9, 0))[0] < 0
    assert field_at(turned, (0.9, 0, 0))[0] > 0


def test_elongate_turns_a_sphere_into_a_capsule():
    f = sdf.Elongate(sdf.Sphere(0.3), (0.7, 0, 0))
    assert field_at(f, (0.9, 0, 0))[0] < 0        # dentro il tratto stirato
    assert field_at(f, (0, 0.9, 0))[0] > 0        # non stirato in Y


def test_taper_narrows_along_the_axis():
    """La rastremazione e' cio' che distingue un corpo affusolato da un ovale."""
    f = sdf.Taper(sdf.Capsule(a=(0, -0.5, 0), b=(0, 0.5, 0), radius=0.3), amount=-0.8)
    largo = field_at(f, (0.25, -0.45, 0))[0]      # base
    stretto = field_at(f, (0.25, 0.45, 0))[0]     # punta
    assert largo < 0 < stretto


def test_mirror_duplicates_across_the_axis():
    single = sdf.Translate(sdf.Sphere(0.2), (0.6, 0, 0))
    assert field_at(single, (-0.6, 0, 0))[0] > 0
    both = sdf.Mirror(single, axis=0)
    assert field_at(both, (0.6, 0, 0))[0] < 0
    assert field_at(both, (-0.6, 0, 0))[0] < 0


def test_repeat_creates_a_finite_centred_row():
    """Quattro copie a passo 0.5 stanno a -0.75, -0.25, +0.25, +0.75."""
    f = sdf.Repeat(sdf.Sphere(0.12), count=4, spacing=0.5, axis=0)
    for x in (-0.75, -0.25, 0.25, 0.75):
        assert field_at(f, (x, 0, 0))[0] < 0, "manca la copia in %.2f" % x
    assert field_at(f, (1.25, 0, 0))[0] > 0, "la ripetizione deve essere finita"
    assert field_at(f, (-1.25, 0, 0))[0] > 0
    lo, hi = f.bounds()
    assert hi[0] == pytest.approx(0.87) and lo[0] == pytest.approx(-0.87)


def test_repeat_with_odd_count_is_centred_on_zero():
    f = sdf.Repeat(sdf.Sphere(0.1), count=3, spacing=0.4, axis=0)
    for x in (-0.4, 0.0, 0.4):
        assert field_at(f, (x, 0, 0))[0] < 0


def test_twist_and_bend_preserve_the_solid():
    base = sdf.Capsule(a=(0, -0.6, 0), b=(0, 0.6, 0), radius=0.2)
    for op in (sdf.Twist(base, 1.5), sdf.Bend(base, 0.8)):
        assert op.sample(np.zeros((1, 3)))[0] < 0
        lo, hi = op.bounds()
        assert np.all(np.isfinite(lo)) and np.all(hi > lo)


def test_shell_hollows_the_solid():
    f = sdf.Shell(sdf.Sphere(0.5), thickness=0.06)
    assert field_at(f, (0, 0, 0))[0] > 0          # il centro ora e' vuoto
    assert field_at(f, (0.5, 0, 0))[0] < 0        # la parete e' solida


def test_round_grows_the_solid():
    assert field_at(sdf.Round(sdf.Box((1, 1, 1)), 0.2), (0.6, 0, 0))[0] < 0


@pytest.mark.parametrize("name,op", sorted(sdf.OPERATIONS.items()))
def test_every_operation_keeps_finite_bounds(name, op):
    base = sdf.Capsule(a=(0, -0.4, 0), b=(0, 0.4, 0), radius=0.2)
    f = op(base)
    lo, hi = f.bounds()
    assert np.all(np.isfinite(lo)) and np.all(np.isfinite(hi)), name
    assert np.all(hi >= lo), name


# --------------------------------------------------------------------------- #
# Combinatori
# --------------------------------------------------------------------------- #
def test_hard_union_is_the_minimum():
    a = sdf.Translate(sdf.Sphere(0.4), (-0.3, 0, 0))
    b = sdf.Translate(sdf.Sphere(0.4), (0.3, 0, 0))
    u = sdf.Union([a, b])
    p = np.array([[0.0, 0.0, 0.0]])
    assert u.sample(p)[0] == pytest.approx(min(a.sample(p)[0], b.sample(p)[0]))


def test_smooth_union_fills_the_joint():
    """La fusione morbida deve aggiungere materia nel punto di giunzione."""
    a = sdf.Translate(sdf.Sphere(0.35), (-0.45, 0, 0))
    b = sdf.Translate(sdf.Sphere(0.35), (0.45, 0, 0))
    probe = np.array([[0.0, 0.28, 0.0]])
    duro = sdf.Union([a, b], blend=0.0).sample(probe)[0]
    morbido = sdf.Union([a, b], blend=0.35).sample(probe)[0]
    assert morbido < duro


def test_blend_can_differ_per_child():
    parts = [sdf.Sphere(0.4),
             sdf.Translate(sdf.Sphere(0.2), (0.5, 0, 0)),
             sdf.Translate(sdf.Sphere(0.2), (0, 0.5, 0))]
    u = sdf.Union(parts, blend=[0.0, 0.3, 0.02])
    assert u._k(1) == pytest.approx(0.3)
    assert u._k(2) == pytest.approx(0.02)


def test_difference_carves():
    f = sdf.Difference(sdf.Box((1, 1, 1)), sdf.Sphere(0.6))
    assert field_at(f, (0, 0, 0))[0] > 0          # scavato al centro
    assert field_at(f, (0.48, 0.48, 0.48))[0] < 0  # angoli intatti


def test_operators_are_wired():
    a, b = sdf.Sphere(0.4), sdf.Translate(sdf.Sphere(0.4), (0.5, 0, 0))
    assert isinstance(a | b, sdf.Union)
    assert isinstance(a & b, sdf.Intersection)
    assert isinstance(a - b, sdf.Difference)


# --------------------------------------------------------------------------- #
# Banda stretta: stessa forma, meno lavoro
# --------------------------------------------------------------------------- #
def test_narrow_band_matches_the_naive_evaluation():
    parts = [sdf.Translate(sdf.Sphere(0.3), (-0.8, 0, 0)),
             sdf.Translate(sdf.Ellipsoid((0.4, 0.2, 0.2)), (0.2, 0, 0)),
             sdf.Translate(sdf.Sphere(0.15), (0.9, 0.3, 0))]
    u = sdf.Union(parts, blend=[0.0, 0.12, 0.05])

    origin = np.array([-1.6, -0.9, -0.9])
    step, shape = 0.05, (64, 36, 36)
    veloce = u.eval_grid(origin, step, shape)
    lento = sdf.Field.eval_grid(u, origin, step, shape)

    # vicino alla superficie i due percorsi devono coincidere esattamente:
    # e' l'unica zona che marching cubes legge
    banda = np.abs(lento) < 0.08
    assert banda.sum() > 500
    assert np.allclose(veloce[banda], lento[banda], atol=1e-9)

    # lontano il percorso veloce puo' sovrastimare: non cambia la superficie
    assert np.all(veloce >= lento - 1e-9), "la banda stretta non deve mai sottostimare"

    # stesso solido, a meno dello zero con segno
    diverso = (veloce < 0) != (lento < 0)
    assert np.all(np.abs(lento[diverso]) < 1e-9)


# --------------------------------------------------------------------------- #
# Estrazione superficie
# --------------------------------------------------------------------------- #
def test_sphere_mesh_has_the_right_volume():
    mesh = to_mesh(sdf.Sphere(0.5), resolution=96, smooth=0)
    assert mesh.is_watertight
    assert mesh.volume == pytest.approx(4 / 3 * np.pi * 0.5 ** 3, rel=0.03)


def test_mesh_is_watertight_for_a_composed_body():
    corpo = sdf.Taper(sdf.Ellipsoid((0.8, 0.35, 0.22)), amount=-0.2)
    coda = sdf.Translate(sdf.Capsule((0, 0, 0), (-0.6, 0, 0), 0.13, 0.04), (-0.6, 0, 0))
    creatura = sdf.Union([corpo, coda], blend=0.14)
    mesh = to_mesh(creatura, resolution=PREVIEW)
    assert mesh.is_watertight and mesh.volume > 0
    assert len(mesh.faces) > 500


def test_empty_field_is_reported_clearly():
    with pytest.raises(ValueError):
        to_mesh(sdf.Union([]), resolution=32)


def test_resolution_cap_protects_memory():
    lungo = sdf.Capsule(a=(-40, 0, 0), b=(40, 0, 0), radius=0.05)
    mesh = to_mesh_capped(lungo, resolution=400, max_cells=400_000)
    assert len(mesh.faces) > 0


def test_grammar_summary_lists_the_vocabulary():
    text = sdf.grammar_summary()
    for word in ("ellipsoid", "capsule", "taper", "mirror", "repeat", "union"):
        assert word in text
