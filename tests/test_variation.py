"""Le varianti devono cambiare l'oggetto senza tradire la richiesta."""
from __future__ import annotations

import pytest

from app.ai.planner import edit_plan, generate_plan, revariate
from app.ai.provider import OfflineProvider
from app.ai.variation import jitter_color, vary
from app.build.builder import build_scene
from app.geometry.templates import TEMPLATES, load_all
from app.geometry.templates.variation_profile import PALETTES, PROFILES

load_all()
OFFLINE = OfflineProvider()


# --------------------------------------------------------------------------- #
# Coerenza delle tabelle
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("template", sorted(PROFILES))
def test_profile_refers_to_existing_params(template):
    """Impedisce che il profilo resti indietro se un template cambia parametri."""
    assert template in TEMPLATES
    unknown = set(PROFILES[template]) - set(TEMPLATES[template].params)
    assert not unknown, "parametri inesistenti in %s: %s" % (template, unknown)


@pytest.mark.parametrize("template", sorted(PALETTES))
def test_palettes_are_valid_hex(template):
    assert template in TEMPLATES
    for color in PALETTES[template]:
        assert len(color) == 7 and color.startswith("#")
        int(color[1:], 16)


def test_semantic_params_never_vary():
    """Cio' che definisce *cosa* e' l'oggetto non deve cambiare da solo."""
    sacred = {"vehicle": ["body_style", "door_count", "has_roof", "has_windows", "has_gun_mount"],
              "weapon": ["weapon_type"],
              "house": ["floors", "roof_type"],
              "humanoid": ["mechanical", "build", "has_visor"],
              "tree": ["canopy_style"]}
    for template, names in sacred.items():
        for name in names:
            assert TEMPLATES[template].params[name].vary == 0.0, "%s.%s varia" % (template, name)


# --------------------------------------------------------------------------- #
# Comportamento
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("prompt", ["crea un suv", "una casa", "una sedia",
                                    "un albero", "una spada", "un robot"])
def test_repeated_generation_differs(prompt):
    plans = [generate_plan(prompt, OFFLINE)[0] for _ in range(5)]
    signatures = {tuple(sorted((k, str(v)) for k, v in p.params.items())) for p in plans}
    assert len(signatures) >= 4, "%r produce quasi sempre lo stesso oggetto" % prompt


def test_explicit_request_is_never_varied():
    for _ in range(12):
        plan, _ = generate_plan("un fuoristrada rosso a due porte alto 2 metri", OFFLINE)
        assert plan.params["body_style"] == "offroad"
        assert plan.params["door_count"] == 2
        assert plan.params["height"] == pytest.approx(2.0)
        body = next(m for m in plan.materials if m.name == "body")
        assert body.base_color == "#b02a1f"


def test_variation_respects_parameter_limits():
    tmpl = TEMPLATES["vehicle"]
    for seed in range(40):
        plan, _ = generate_plan("un camion", OFFLINE, seed=seed)
        for name, value in plan.params.items():
            spec = tmpl.params[name]
            if spec.min is not None and not isinstance(spec.default, bool):
                assert spec.min <= value <= spec.max, "%s fuori scala: %s" % (name, value)


def test_every_variant_still_builds():
    for seed in range(25):
        plan, _ = generate_plan("un fuoristrada", OFFLINE, seed=seed)
        scene = build_scene(plan)
        assert scene.nodes and not scene.warnings
        assert scene.by_id("body").mesh.is_watertight


def test_revariate_keeps_requests_and_changes_the_rest():
    plan, _ = generate_plan("un fuoristrada verde a quattro porte", OFFLINE, seed=1)
    other, message = revariate(plan)
    assert other.seed != plan.seed
    assert other.params["door_count"] == 4
    assert other.params["body_style"] == "offroad"
    assert next(m for m in other.materials if m.name == "body").base_color == "#2f7a3a"
    assert other.params != plan.params
    assert "variante" in message.lower()


def test_edits_are_protected_from_later_variations():
    """Una modifica esplicita diventa un vincolo: le varianti successive la rispettano."""
    plan, _ = generate_plan("un suv", OFFLINE, seed=7)
    edited, _ = edit_plan("fai le ruote piu grandi", plan, OFFLINE)
    radius = edited.params["wheel_radius"]
    assert "wheel_radius" in edited.locked
    for seed in range(10):
        again = vary(edited.model_copy(deep=True), seed)
        assert again.params["wheel_radius"] == radius


def test_modify_does_not_reroll_the_object():
    """Una modifica non deve rigenerare l'oggetto: cambia solo cio' che serve."""
    from app.core.session import Session

    session = Session(provider=OFFLINE)
    session.generate_legacy("un suv")
    before = dict(session.current_plan.params)
    session.modify("fallo nero")
    after = session.current_plan.params
    assert after == before                 # nessun parametro geometrico toccato
    assert session.current_plan.seed == session.history[0].plan.seed


def test_jitter_color_stays_in_range():
    import random

    rng = random.Random(0)
    for _ in range(200):
        c = jitter_color("#3d6b4a", rng)
        assert len(c) == 7 and c.startswith("#")
        assert 0 <= int(c[1:], 16) <= 0xFFFFFF
