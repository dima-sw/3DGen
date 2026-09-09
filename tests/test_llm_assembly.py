"""Piani compositivi prodotti dall'LLM: validazione, pulizia, correzione."""
from __future__ import annotations

import json

import pytest

from app.ai.planner import check_and_repair, generate_plan, sanitize_assembly
from app.ai.prompts import planner_system, repair_system
from app.ai.provider import LLMError, LLMProvider, OfflineProvider
from app.build.builder import build_scene
from app.build.validation import errors, validate
from app.core.spec import AssemblySpec, AttachSpec, GenerationPlan, PartSpec

OFFLINE = OfflineProvider()


def piano_pesce(**overrides) -> dict:
    """Un assemblaggio valido, come dovrebbe produrlo l'LLM."""
    data = {
        "strategy": "assembly",
        "object_type": "pesce",
        "assembly": {
            "root": "corpo",
            "semantic_class": "fish",
            "blend": 0.06,
            "parts": [
                {"id": "corpo", "recipe": "body", "tags": ["body"],
                 "params": {"length": 0.9, "height": 0.38, "width": 0.22}},
                {"id": "testa", "recipe": "head", "tags": ["head"], "blend": 0.12,
                 "params": {"size": 0.22}, "attach": {"parent": "corpo", "socket": "head"}},
                {"id": "coda", "recipe": "blade", "tags": ["tail", "fin"],
                 "params": {"length": 0.3, "fork": 0.7},
                 "attach": {"parent": "corpo", "socket": "tail"}},
                {"id": "dorsale", "recipe": "blade", "tags": ["fin"],
                 "params": {"length": 0.22}, "attach": {"parent": "corpo", "socket": "dorsal"}},
            ],
        },
        "materials": [{"name": "skin", "base_color": "#d2762a"}],
    }
    data.update(overrides)
    return data


class ScriptedProvider(LLMProvider):
    """Recita risposte prestabilite: si conta quante volte viene interpellato."""

    name = "scriptato"

    def __init__(self, *responses: dict) -> None:
        self.responses = list(responses)
        self.calls = 0

    def available(self) -> bool:
        return True

    def complete_json(self, system, user, temperature=0.2):
        self.calls += 1
        if not self.responses:
            raise LLMError("nessuna risposta programmata")
        return self.responses.pop(0)


# --------------------------------------------------------------------------- #
# Il prompt
# --------------------------------------------------------------------------- #
def test_prompt_offers_both_roads():
    text = planner_system()
    assert "STRADA A" in text and "STRADA B" in text
    assert "vehicle" in text, "il catalogo dei template"
    assert "body [organic]" in text, "il catalogo delle ricette"
    assert "shoulder" in text, "i nomi dei socket"


def test_prompt_stays_small_enough_to_be_cheap():
    """Un prompt di sistema enorme costerebbe a ogni generazione."""
    assert len(planner_system()) < 20_000


def test_repair_prompt_carries_structured_issues():
    from app.build.validation import ERROR, Issue

    text = repair_system("{}", [Issue("TAIL_NOT_POSTERIOR", ERROR, part="coda")])
    assert "TAIL_NOT_POSTERIOR" in text and "coda" in text


# --------------------------------------------------------------------------- #
# Validazione di cio' che arriva dall'LLM
# --------------------------------------------------------------------------- #
def test_a_valid_assembly_passes_through():
    plan = GenerationPlan.model_validate(piano_pesce())
    assert sanitize_assembly(plan) == []
    assert len(plan.assembly.parts) == 4


def test_invented_recipes_are_dropped():
    data = piano_pesce()
    data["assembly"]["parts"].append(
        {"id": "boh", "recipe": "ricetta_inventata",
         "attach": {"parent": "corpo", "socket": "dorsal"}})
    plan = GenerationPlan.model_validate(data)
    removed = sanitize_assembly(plan)
    assert any("ricetta" in r for r in removed)
    assert all(p.recipe != "ricetta_inventata" for p in plan.assembly.parts)


def test_invented_sockets_are_dropped():
    data = piano_pesce()
    data["assembly"]["parts"][1]["attach"]["socket"] = "socket_che_non_esiste"
    plan = GenerationPlan.model_validate(data)
    removed = sanitize_assembly(plan)
    assert any("socket" in r for r in removed)
    assert plan.assembly.by_id("testa") is None


def test_invented_parameters_are_dropped():
    data = piano_pesce()
    data["assembly"]["parts"][0]["params"]["parametro_inventato"] = 99
    plan = GenerationPlan.model_validate(data)
    sanitize_assembly(plan)
    assert "parametro_inventato" not in plan.assembly.by_id("corpo").params


def test_missing_parent_is_dropped():
    data = piano_pesce()
    data["assembly"]["parts"].append(
        {"id": "orfana", "recipe": "blade",
         "attach": {"parent": "padre_inesistente", "socket": "base"}})
    plan = GenerationPlan.model_validate(data)
    removed = sanitize_assembly(plan)
    assert any("padre" in r for r in removed)


def test_root_is_fixed_when_it_disappears():
    data = piano_pesce()
    data["assembly"]["root"] = "radice_inesistente"
    plan = GenerationPlan.model_validate(data)
    sanitize_assembly(plan)
    assert plan.assembly.root in {p.id for p in plan.assembly.parts}


def test_a_cleaned_assembly_still_builds():
    data = piano_pesce()
    data["assembly"]["parts"].append({"id": "x", "recipe": "inesistente"})
    plan = GenerationPlan.model_validate(data)
    sanitize_assembly(plan)
    scene = build_scene(plan)
    assert scene.nodes and scene.triangle_count > 0


# --------------------------------------------------------------------------- #
# Budget della correzione: regola 10
# --------------------------------------------------------------------------- #
def test_a_healthy_plan_costs_no_extra_call():
    provider = ScriptedProvider()
    plan = GenerationPlan.model_validate(piano_pesce())
    fixed, issues, notes = check_and_repair(plan, provider)
    assert provider.calls == 0, "niente da correggere, niente da chiedere"
    assert not errors(issues)


def test_deterministic_repair_comes_first():
    """Se la riparazione locale basta, l'LLM non viene disturbato."""
    data = piano_pesce()
    data["assembly"]["parts"][2]["attach"]["socket"] = "head"     # coda sul muso
    provider = ScriptedProvider()
    plan = GenerationPlan.model_validate(data)
    fixed, issues, notes = check_and_repair(plan, provider)
    assert provider.calls == 0
    assert fixed.assembly.by_id("coda").attach.socket == "tail"
    assert notes


def test_at_most_one_repair_call():
    """Anche quando la correzione non serve a niente, si chiede una volta sola."""
    data = piano_pesce()
    data["assembly"]["parts"] = [p for p in data["assembly"]["parts"]
                                 if "tail" not in p.get("tags", [])]
    provider = ScriptedProvider(piano_pesce())     # risposta valida
    plan = GenerationPlan.model_validate(data)
    fixed, issues, notes = check_and_repair(plan, provider)
    assert provider.calls == 1
    assert not errors(issues), "la correzione ha rimesso la coda"


def test_a_worse_correction_is_discarded():
    peggiore = piano_pesce()
    peggiore["assembly"]["parts"] = [peggiore["assembly"]["parts"][0]]   # solo il corpo
    data = piano_pesce()
    data["assembly"]["parts"] = [p for p in data["assembly"]["parts"]
                                 if "tail" not in p.get("tags", [])]

    provider = ScriptedProvider(peggiore)
    plan = GenerationPlan.model_validate(data)
    fixed, issues, notes = check_and_repair(plan, provider)
    assert provider.calls == 1
    assert any("scartata" in n for n in notes)
    assert fixed.assembly.by_id("dorsale") is not None, "si tiene il piano di partenza"


def test_a_failed_correction_keeps_the_repaired_plan():
    data = piano_pesce()
    data["assembly"]["parts"] = [p for p in data["assembly"]["parts"]
                                 if "tail" not in p.get("tags", [])]
    provider = ScriptedProvider()          # solleva: nessuna risposta
    plan = GenerationPlan.model_validate(data)
    fixed, issues, notes = check_and_repair(plan, provider)
    assert provider.calls == 1
    assert fixed.assembly.parts, "il piano resta utilizzabile"
    assert any("non riuscita" in n for n in notes)


def test_offline_never_asks_for_a_correction():
    data = piano_pesce()
    data["assembly"]["parts"] = [data["assembly"]["parts"][0]]
    plan = GenerationPlan.model_validate(data)
    fixed, issues, notes = check_and_repair(plan, OFFLINE)
    assert errors(issues), "i problemi restano segnalati"
    assert not any("LLM" in n for n in notes)


# --------------------------------------------------------------------------- #
# Percorso completo con un provider finto
# --------------------------------------------------------------------------- #
def test_generate_plan_accepts_an_assembly_from_the_llm():
    provider = ScriptedProvider(piano_pesce())
    plan, message = generate_plan("crea un pesce", provider)
    assert plan.strategy == "assembly"
    assert plan.assembly and len(plan.assembly.parts) >= 4
    scene = build_scene(plan)
    assert {"body", "head", "tail"} <= {t for n in scene.nodes for t in n.tags}


def test_an_assembly_without_valid_parts_falls_back_to_the_rules():
    rotto = piano_pesce()
    for part in rotto["assembly"]["parts"]:
        part["recipe"] = "inesistente"
    provider = ScriptedProvider(rotto)
    plan, message = generate_plan("crea un pesce", provider)
    assert plan.assembly is not None or plan.template
    assert build_scene(plan).nodes, "regola 9"
