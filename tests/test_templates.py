"""Ogni generatore deve reggere anche i parametri estremi.

E' il test che ha intercettato il caso reale delle ruote enormi che sfondavano
la carrozzeria producendo una mesh aperta.
"""
from __future__ import annotations

import itertools

import pytest

from app.build.builder import build_scene
from app.core.spec import GenerationPlan
from app.geometry.templates import TEMPLATES, load_all

load_all()
TEMPLATE_NAMES = sorted(TEMPLATES)
# Lo stile e' uno solo: quello che varia e' la densita' della superficie.
DENSITIES = [0.35, 0.7, 1.0, 1.6, 2.4]


def _scene(template: str, params: dict | None = None, density: float = 1.0):
    return build_scene(GenerationPlan(template=template, density=density,
                                      params=params or {}))


@pytest.mark.parametrize("name", TEMPLATE_NAMES)
def test_defaults_build(name):
    scene = _scene(name)
    assert scene.nodes, "%s non ha prodotto geometria" % name
    assert not scene.warnings, scene.warnings
    assert scene.triangle_count > 0


@pytest.mark.parametrize("name,density", itertools.product(TEMPLATE_NAMES, DENSITIES))
def test_every_density_builds(name, density):
    """Da estremo a estremo della densita', ogni template deve reggere."""
    scene = _scene(name, density=density)
    assert scene.nodes and not scene.warnings


@pytest.mark.parametrize("name", TEMPLATE_NAMES)
def test_extremes_build(name):
    """Tutti i parametri al minimo, poi tutti al massimo."""
    tmpl = TEMPLATES[name]
    for pick in ("min", "max"):
        params = {}
        for key, spec in tmpl.params.items():
            if isinstance(spec.default, bool):
                params[key] = pick == "max"
            elif spec.choices is not None:
                continue
            elif spec.min is not None and spec.max is not None:
                params[key] = spec.min if pick == "min" else spec.max
        scene = _scene(name, params)
        assert scene.nodes, "%s (%s) vuoto" % (name, pick)
        assert not scene.warnings, "%s (%s): %s" % (name, pick, scene.warnings)


@pytest.mark.parametrize("choice", TEMPLATES["vehicle"].params["body_style"].choices)
def test_vehicle_every_body_style_is_watertight(choice):
    scene = _scene("vehicle", {"body_style": choice})
    body = scene.by_id("body")
    assert body is not None
    assert body.mesh.is_watertight, "carrozzeria aperta per %s" % choice


@pytest.mark.parametrize("radius", [0.2, 0.35, 0.5, 0.7, 0.85])
def test_huge_wheels_keep_body_closed(radius):
    """Ruote fuori scala non devono spaccare il profilo laterale."""
    scene = _scene("vehicle", {"wheel_radius": radius, "wheel_width": radius * 0.9,
                               "length": 2.6, "height": 1.0, "ground_clearance": 0.75})
    body = scene.by_id("body")
    assert body is not None and body.mesh.is_watertight
    assert body.mesh.volume > 1e-4


def test_open_top_has_no_solid_cabin():
    closed = _scene("vehicle", {"has_roof": True})
    opened = _scene("vehicle", {"has_roof": False})
    assert closed.by_id("cabin") is not None
    assert opened.by_id("cabin") is None
    assert opened.by_id("tub_l") is not None      # fiancate al posto della cabina
    assert opened.by_id("rollbar_h_f") is not None


def test_scene_sits_on_ground():
    for name in TEMPLATE_NAMES:
        scene = _scene(name)
        y_min = float(scene.bounds()[0][1])
        assert -0.3 < y_min < 0.15, "%s parte da y=%.3f" % (name, y_min)
