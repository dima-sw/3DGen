"""Test della geometria di base."""
from __future__ import annotations

import numpy as np
import pytest

from app.core.spec import ComponentSpec
from app.build.builder import build_component
from app.geometry import primitives as P

PRIMITIVE_NAMES = sorted(P.PRIMITIVES)


@pytest.mark.parametrize("name", PRIMITIVE_NAMES)
def test_primitive_is_valid_solid(name):
    mesh = P.PRIMITIVES[name]()
    assert len(mesh.faces) > 0
    assert mesh.is_watertight, "%s non e' chiusa" % name
    assert mesh.volume > 1e-6, "%s ha volume nullo" % name


def test_prism_from_concave_profile():
    """Profilo con una tacca: l'ear clipping deve gestire i vertici riflessi."""
    profile = [(-2, 0), (-0.5, 0), (-0.5, 0.6), (0.5, 0.6), (0.5, 0), (2, 0), (2, 1.4), (-2, 1.4)]
    mesh = P.prism(profile, 1.5)
    assert mesh.is_watertight
    assert mesh.volume > 0


def test_prism_orientation():
    """Il profilo giace nel piano ZY ed e' estruso lungo X."""
    mesh = P.prism([(-1, 0), (1, 0), (1, 2)], 0.5)
    extents = mesh.bounds[1] - mesh.bounds[0]
    assert extents[0] == pytest.approx(0.5, abs=1e-6)   # larghezza = depth
    assert extents[1] == pytest.approx(2.0, abs=1e-6)   # altezza
    assert extents[2] == pytest.approx(2.0, abs=1e-6)   # profondita


def test_hexahedron_is_truncated_pyramid():
    mesh = P.hexahedron((2.0, 2.0), (1.0, 1.0), 2.0)
    assert mesh.is_watertight
    # volume di un tronco di piramide: h/3 * (A1 + A2 + sqrt(A1*A2))
    expected = 2.0 / 3.0 * (4.0 + 1.0 + np.sqrt(4.0))
    assert mesh.volume == pytest.approx(expected, rel=1e-6)


def test_component_transform_order():
    """Scala, poi rotazione, poi traslazione."""
    comp = ComponentSpec(id="t", primitive="box", params={"size": (1, 1, 1)},
                         scale=(2.0, 1.0, 1.0), rotation=(0, 90, 0), position=(5, 0, 0))
    mesh = build_component(comp)
    extents = mesh.bounds[1] - mesh.bounds[0]
    assert extents[0] == pytest.approx(1.0, abs=1e-6)   # la X scalata ruota su Z
    assert extents[2] == pytest.approx(2.0, abs=1e-6)
    assert mesh.centroid[0] == pytest.approx(5.0, abs=1e-6)


def test_unknown_primitive_raises():
    comp = ComponentSpec(id="t", primitive="box", params={"size": (1, 1, 1)})
    comp.primitive = "inesistente"  # forzato dopo la validazione
    with pytest.raises(ValueError):
        build_component(comp)
