"""Ricette di parti: espressioni sicure, socket, catalogo."""
from __future__ import annotations

import json

import numpy as np
import pytest

from app.geometry import sdf
from app.geometry.recipe import (
    CATALOG, Recipe, RecipeError, Socket, SocketSpec, build_shape,
    catalog_summary, evaluate, find_recipes, get_recipe, load_catalog,
)

load_catalog()


# --------------------------------------------------------------------------- #
# Espressioni: aritmetica, mai codice
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("expression,expected", [
    ("2 + 3", 5.0), ("length * 2", 1.8), ("-height", -0.4),
    ("max(length, height)", 0.9), ("min(length, height)", 0.4),
    ("sqrt(length * length)", 0.9), ("clamp(5, 0, 1)", 1.0),
    ("length / max(height, 0.05)", 2.25), (0.5, 0.5), (3, 3.0),
])
def test_expressions_are_arithmetic(expression, expected):
    assert evaluate(expression, {"length": 0.9, "height": 0.4}) == pytest.approx(expected)


@pytest.mark.parametrize("expression", [
    "__import__('os').system('echo')",
    "open('/etc/passwd')",
    "length.__class__",
    "[1, 2, 3]",
    "lambda: 1",
    "print(1)",
    "eval('1')",
    "length if length else 0; import os",
])
def test_expressions_reject_anything_but_numbers(expression):
    """Regola 1: nemmeno una ricetta scritta dall'LLM puo' eseguire codice."""
    with pytest.raises(RecipeError):
        evaluate(expression, {"length": 0.9})


def test_unknown_parameter_is_reported():
    with pytest.raises(RecipeError) as exc:
        evaluate("larghezza * 2", {"length": 1.0})
    assert "larghezza" in str(exc.value)


# --------------------------------------------------------------------------- #
# Socket
# --------------------------------------------------------------------------- #
def test_socket_normalises_direction_and_up():
    s = Socket("x", [0, 0, 0], [0, 3, 0], 0.1, up=[0, 5, 0])
    assert np.allclose(s.direction, [0, 1, 0])
    # up parallelo alla direzione e' degenere: ne viene scelto uno ortogonale
    assert abs(float(s.direction @ s.up)) < 1e-9
    assert np.isclose(np.linalg.norm(s.up), 1.0)


def test_socket_frame_is_orthonormal():
    s = Socket("x", [0, 0, 0], [1, 1, 0], 0.1, up=[0, 1, 1])
    f = s.frame()
    assert np.allclose(f.T @ f, np.eye(3), atol=1e-9)
    assert np.isclose(np.linalg.det(f), 1.0)


def test_pair_arrangement_is_mirrored():
    spec = SocketSpec(name="shoulder", arrangement="pair", axis=0,
                      position=["w", "h", 0], direction=[1, 0.2, 0], radius="r")
    sockets = {s.name: s for s in spec.build({"w": 0.3, "h": 0.5, "r": 0.08})}
    assert set(sockets) == {"shoulder_l", "shoulder_r"}
    assert sockets["shoulder_l"].position[0] == pytest.approx(-0.3)
    assert sockets["shoulder_r"].position[0] == pytest.approx(0.3)
    assert sockets["shoulder_l"].direction[0] == pytest.approx(-sockets["shoulder_r"].direction[0])


def test_radial_arrangement_spreads_around_the_axis():
    spec = SocketSpec(name="tentacle", arrangement="radial", axis=0, count="n",
                      ring="0.4", position=[0.5, 0, 0], direction=[1, 0, 0], radius="0.05")
    sockets = spec.build({"n": 6})
    assert len(sockets) == 6
    angles = sorted(np.arctan2(s.position[2], s.position[1]) for s in sockets)
    gaps = np.diff(angles)
    assert np.allclose(gaps, gaps[0], atol=1e-6), "i socket devono essere equidistanti"


def test_row_arrangement_is_centred():
    spec = SocketSpec(name="leg", arrangement="row", axis=0, count=4, spacing="0.5")
    xs = sorted(s.position[0] for s in spec.build({}))
    assert xs == pytest.approx([-0.75, -0.25, 0.25, 0.75])


def test_zero_count_produces_no_sockets():
    spec = SocketSpec(name="t", arrangement="radial", count=0)
    assert spec.build({}) == []


# --------------------------------------------------------------------------- #
# Costruzione della forma
# --------------------------------------------------------------------------- #
def test_build_shape_creates_the_grammar_tree():
    node = {"op": "taper", "amount": "-0.3", "axis": 0,
            "child": {"volume": "ellipsoid", "radii": ["l", "h", "w"]}}
    tree = build_shape(node, {"l": 0.9, "h": 0.4, "w": 0.2})
    assert isinstance(tree, sdf.Taper)
    assert isinstance(tree.child, sdf.Ellipsoid)
    assert tree.child.radii == pytest.approx((0.9, 0.4, 0.2))


def test_build_shape_handles_union_and_difference():
    tree = build_shape({"union": [{"volume": "sphere", "radius": "1"},
                                  {"volume": "box", "size": [1, 1, 1]}],
                        "blend": "0.2"}, {})
    assert isinstance(tree, sdf.Union) and tree.blend == pytest.approx(0.2)
    carved = build_shape({"difference": {"volume": "sphere", "radius": "1"},
                          "tool": {"volume": "sphere", "radius": "0.5"}}, {})
    assert isinstance(carved, sdf.Difference)


def test_integer_fields_stay_integers():
    tree = build_shape({"op": "repeat", "count": "3", "spacing": "0.4", "axis": "0",
                        "child": {"volume": "sphere", "radius": "0.1"}}, {})
    assert isinstance(tree.count, int) and isinstance(tree.axis, int)


@pytest.mark.parametrize("node", [
    {}, {"volume": "inesistente"}, {"op": "inesistente", "child": {}},
    {"sconosciuto": 1},
])
def test_bad_shape_nodes_are_rejected(node):
    with pytest.raises(RecipeError):
        build_shape(node, {})


# --------------------------------------------------------------------------- #
# Catalogo
# --------------------------------------------------------------------------- #
def test_catalog_is_loaded():
    assert len(CATALOG) >= 8
    for name in ("body", "torso", "head", "limb", "blade", "eye"):
        assert name in CATALOG


@pytest.mark.parametrize("name", sorted(CATALOG))
def test_every_recipe_builds_with_defaults(name):
    part = CATALOG[name].build()
    assert part.sockets, "%s non espone socket" % name
    lo, hi = part.field.bounds()
    assert np.all(np.isfinite(lo)) and np.all(hi > lo)
    # deve contenere materia
    rng = np.random.default_rng(2)
    pts = lo + rng.random((20000, 3)) * (hi - lo)
    assert np.any(part.field.sample(pts) < 0), "%s e' vuota" % name


@pytest.mark.parametrize("name", sorted(CATALOG))
def test_every_recipe_has_a_base_socket(name):
    """Serve per poter essere attaccata a qualcosa."""
    part = CATALOG[name].build()
    assert part.socket("base") is not None, "%s non ha socket 'base'" % name


@pytest.mark.parametrize("name", sorted(CATALOG))
def test_every_recipe_survives_extreme_params(name):
    recipe = CATALOG[name]
    for pick in ("min", "max"):
        params = {}
        for key, spec in recipe.params.items():
            if spec.min is not None and spec.max is not None:
                params[key] = spec.min if pick == "min" else spec.max
        part = recipe.build(params)
        lo, hi = part.field.bounds()
        assert np.all(np.isfinite(lo)), "%s (%s) senza limiti" % (name, pick)


def test_parameters_are_clamped():
    recipe = get_recipe("limb")
    values = recipe.resolve({"length": 999, "radius": -5, "inesistente": 3})
    assert values["length"] == recipe.params["length"].max
    assert values["radius"] == recipe.params["radius"].min
    assert "inesistente" not in values


def test_recipes_are_searchable_by_keyword():
    assert any(r.name == "limb" for r in find_recipes("tentacolo"))
    assert any(r.name == "blade" for r in find_recipes("pinna"))
    assert any(r.name == "plate" for r in find_recipes("corazza"))


def test_catalog_summary_is_usable_in_a_prompt():
    text = catalog_summary()
    for name in ("body", "limb", "blade"):
        assert name in text
    assert "socket:" in text


def test_a_recipe_can_be_written_at_runtime():
    """L'LLM deve poter aggiungere una parte senza toccare il motore."""
    data = {
        "name": "prova_pinnone",
        "description": "parte inventata al volo",
        "params": {"size": {"default": 0.3, "min": 0.05, "max": 2.0}},
        "shape": {"op": "twist", "amount": "2.0", "axis": 0,
                  "child": {"volume": "capsule", "a": [0, 0, 0], "b": ["size", 0, 0],
                            "radius": "size*0.2"}},
        "sockets": [{"name": "base", "position": [0, 0, 0], "direction": [-1, 0, 0],
                     "radius": "size*0.2"}],
    }
    recipe = Recipe.model_validate(json.loads(json.dumps(data)))
    part = recipe.build({"size": 0.5})
    assert part.socket("base") is not None
    assert part.field.sample(np.array([[0.25, 0.0, 0.0]]))[0] < 0


def test_socket_lookup_tolerates_generated_names():
    part = get_recipe("torso").build()
    assert part.socket("shoulder") is not None       # trova shoulder_l
    assert part.socket("shoulder_r") is not None
    assert part.socket("inesistente") is None
