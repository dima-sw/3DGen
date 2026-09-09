"""Test del livello AI. Nessuna chiamata di rete: si usa il planner a regole."""
from __future__ import annotations

import pytest

from app.ai import offline
from app.ai.planner import apply_edit, edit_plan, generate_plan
from app.ai.provider import OfflineProvider
from app.core.spec import EditOp, EditPlan, GenerationPlan, MaterialSpec
from app.geometry.templates import TEMPLATES, load_all

load_all()
OFFLINE = OfflineProvider()


@pytest.mark.parametrize("prompt,template", [
    ("crea una jeep militare 4x4", "vehicle"),
    ("un'auto sportiva rossa", "vehicle"),
    ("una casa a due piani", "house"),
    ("un robot umanoide con armatura", "humanoid"),
    ("una spada medievale", "weapon"),
    ("una sedia da ufficio", "chair"),
    ("un tavolo rotondo", "table"),
    ("un pino alto 8 metri", "tree"),
    ("un masso", "rock"),
    ("un cubo", "primitive"),
    ("qualcosa di indefinito", "primitive"),
])
def test_template_selection(prompt, template):
    plan, _ = generate_plan(prompt, OFFLINE)
    assert plan.template == template


@pytest.mark.parametrize("prompt,atteso", [
    ("una sedia low poly", "meno"),
    ("una casa semplice", "meno"),
    ("un albero dettagliato", "piu"),
    ("una spada", "normale"),
])
def test_density_detection(prompt, atteso):
    """Lo stile non si sceglie piu'. "Semplice" e "dettagliato" restano
    richieste legittime, e diventano densita' della superficie."""
    plan, _ = generate_plan(prompt, OFFLINE)
    if atteso == "meno":
        assert plan.density < 1.0
    elif atteso == "piu":
        assert plan.density > 1.0
    else:
        assert plan.density == 1.0


def test_there_is_only_one_style():
    """Il piano non ha piu' un campo stile: non c'e' niente da scegliere."""
    plan, _ = generate_plan("una sedia", OFFLINE)
    assert not hasattr(plan, "style")
    assert "style" not in plan.model_dump()


def test_density_only_changes_the_triangle_count():
    """Cambiare densita' non cambia l'oggetto, solo quanto e' fitto."""
    from app.build.builder import build_scene

    plan, _ = generate_plan("una sedia di legno", OFFLINE)
    rado = plan.model_copy(deep=True)
    rado.density = 0.5
    fitto = plan.model_copy(deep=True)
    fitto.density = 1.8

    a, b = build_scene(rado), build_scene(fitto)
    assert a.triangle_count < b.triangle_count
    assert {n.id for n in a.nodes} == {n.id for n in b.nodes}, "stesse parti"


def test_color_is_applied_to_primary_material():
    plan, _ = generate_plan("una jeep rossa", OFFLINE)
    body = next(m for m in plan.materials if m.name == "body")
    assert body.base_color == "#b02a1f"


def test_military_prompt_sets_offroad_kit():
    plan, _ = generate_plan("un veicolo militare", OFFLINE)
    assert plan.params["body_style"] in ("offroad", "suv", "truck")
    assert plan.params["has_roll_bar"] is True
    assert plan.params["has_roof"] is False


def test_measures_are_parsed():
    plan, _ = generate_plan("un albero alto 12 metri", OFFLINE)
    assert plan.params["height"] == pytest.approx(12.0)
    plan, _ = generate_plan("una casa a tre piani", OFFLINE)
    assert plan.params["floors"] == 3
    plan, _ = generate_plan("un'auto a due porte", OFFLINE)
    assert plan.params["door_count"] == 2


# --------------------------------------------------------------------------- #
# Validazione: l'LLM non puo' sfondare i limiti
# --------------------------------------------------------------------------- #
def test_params_are_clamped_to_schema():
    tmpl = TEMPLATES["vehicle"]
    params = tmpl.sanitize({"length": 9999, "wheel_radius": -5,
                            "body_style": "astronave", "door_count": "4",
                            "parametro_inventato": 1})
    assert params["length"] == tmpl.params["length"].max
    assert params["wheel_radius"] == tmpl.params["wheel_radius"].min
    assert params["body_style"] == tmpl.params["body_style"].default
    assert params["door_count"] == 4
    assert "parametro_inventato" not in params


def test_unknown_template_falls_back():
    from app.ai.planner import _sanitize_plan
    plan = _sanitize_plan(GenerationPlan(template="astronave_aliena"))
    assert plan.template == "primitive"


def test_invalid_color_is_rejected():
    assert MaterialSpec(name="x", base_color="non-un-colore").base_color == "#9aa0a6"
    assert MaterialSpec(name="x", base_color="ff0000").base_color == "#ff0000"


# --------------------------------------------------------------------------- #
# Editing incrementale
# --------------------------------------------------------------------------- #
def test_edit_only_touches_requested_parameter():
    plan, _ = generate_plan("un fuoristrada", OFFLINE)
    before = dict(plan.params)
    after, _ = edit_plan("fai le ruote piu grandi", plan, OFFLINE)
    assert after.params["wheel_radius"] > before["wheel_radius"]
    assert after.params["length"] == before["length"]
    assert after.params["door_count"] == before["door_count"]


def test_edit_can_add_and_remove_features():
    plan, _ = generate_plan("un suv", OFFLINE)
    opened, _ = edit_plan("togli il tetto", plan, OFFLINE)
    assert opened.params["has_roof"] is False
    closed, _ = edit_plan("aggiungi il tetto", opened, OFFLINE)
    assert closed.params["has_roof"] is True


def test_edit_changes_color_only():
    plan, _ = generate_plan("un suv", OFFLINE)
    after, _ = edit_plan("fallo nero", plan, OFFLINE)
    body = next(m for m in after.materials if m.name == "body")
    assert body.base_color == "#141518"
    assert after.params == plan.params


def test_edit_scale_param_respects_limits():
    plan, _ = generate_plan("un suv", OFFLINE)
    for _ in range(20):
        plan = apply_edit(plan, EditPlan(ops=[EditOp(op="scale_param",
                                                     path="wheel_radius", factor=1.5)]))
    assert plan.params["wheel_radius"] <= TEMPLATES["vehicle"].params["wheel_radius"].max


def test_edit_ignores_unknown_operations():
    plan, _ = generate_plan("un suv", OFFLINE)
    before = dict(plan.params)
    after = apply_edit(plan, EditPlan(ops=[
        EditOp(op="set_param", path="campo_inesistente", value=42),
        EditOp(op="noop"),
    ]))
    assert after.params == before


def test_offline_edit_reports_when_not_understood():
    plan, _ = generate_plan("un suv", OFFLINE)
    edits = offline.edit("zxcvbnm qwerty", plan)
    assert edits.ops == []
