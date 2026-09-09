"""Gestore delle strategie: chi costruisce cosa, e cosa succede se fallisce."""
from __future__ import annotations

import pytest

from app.ai.creature import build_assembly, parse_creature
from app.ai.provider import OfflineProvider
from app.assets.library import AssetLibrary
from app.build.builder import build_scene
from app.build.strategy import (
    AI_MESH, ASSEMBLY, FALLBACK, LIBRARY, ORDER, TEMPLATE, GeneratorManager,
)
from app.core.session import Session
from app.core.spec import AssemblySpec, GenerationPlan, PartSpec

OFFLINE = OfflineProvider()


def creature_plan(prompt: str) -> GenerationPlan:
    assembly, materials = build_assembly(parse_creature(prompt))
    return GenerationPlan(prompt=prompt, template="freeform", strategy="assembly",
                          assembly=assembly, materials=materials)


# --------------------------------------------------------------------------- #
# Scelta
# --------------------------------------------------------------------------- #
def test_known_object_uses_the_template():
    outcome = GeneratorManager().build(GenerationPlan(template="vehicle"))
    assert outcome.strategy == TEMPLATE
    assert outcome.scene.nodes


def test_creature_uses_the_composition():
    outcome = GeneratorManager().build(creature_plan("un pesce"))
    assert outcome.strategy == ASSEMBLY
    assert outcome.scene.nodes


def test_order_is_the_one_declared_in_the_roadmap():
    assert ORDER == [TEMPLATE, ASSEMBLY, LIBRARY, AI_MESH]


def test_assembly_is_skipped_when_the_plan_has_no_parts():
    manager = GeneratorManager()
    plan = GenerationPlan(template="chair", strategy="assembly")
    assert ASSEMBLY not in manager._applicable(plan)
    assert manager.build(plan).strategy == TEMPLATE


def test_ai_mesh_is_not_attempted_yet():
    """Resta l'ultima risorsa: finche' non c'e' un provider, non si prova."""
    manager = GeneratorManager()
    assert AI_MESH not in manager._applicable(GenerationPlan(strategy="ai_mesh"))


def test_library_is_only_available_with_a_library(tmp_path):
    plan = GenerationPlan(template="chair", strategy="library")
    assert LIBRARY not in GeneratorManager()._applicable(plan)
    assert LIBRARY in GeneratorManager(library=AssetLibrary(tmp_path))._applicable(plan)


# --------------------------------------------------------------------------- #
# Ripieghi: regola 9
# --------------------------------------------------------------------------- #
def test_broken_assembly_falls_back_to_the_template():
    plan = GenerationPlan(template="chair", strategy="assembly",
                          assembly=AssemblySpec(root="a", parts=[
                              PartSpec(id="a", recipe="inesistente")]))
    outcome = GeneratorManager().build(plan)
    assert outcome.strategy == TEMPLATE
    assert [a.strategy for a in outcome.attempts] == [ASSEMBLY, TEMPLATE]
    assert not outcome.attempts[0].ok


def test_everything_broken_still_answers():
    plan = GenerationPlan(template="inesistente", strategy="template")
    outcome = GeneratorManager().build(plan)
    assert outcome.strategy == FALLBACK
    assert outcome.scene.triangle_count > 0
    assert any("solido di base" in w for w in outcome.scene.warnings)


def test_attempts_are_readable():
    plan = GenerationPlan(template="chair", strategy="assembly",
                          assembly=AssemblySpec(root="a", parts=[
                              PartSpec(id="a", recipe="inesistente")]))
    outcome = GeneratorManager().build(plan)
    assert "assembly: fallita" in outcome.summary()
    assert "template: ok" in outcome.summary()


def test_scene_records_the_strategy_that_made_it():
    scene = build_scene(creature_plan("un lupo"))
    assert scene.strategy == ASSEMBLY
    assert scene.attempts and scene.attempts[-1].ok


# --------------------------------------------------------------------------- #
# Libreria come strategia
# --------------------------------------------------------------------------- #
def test_library_strategy_reuses_a_saved_asset(tmp_path):
    library = AssetLibrary(tmp_path / "lib")
    session = Session(provider=OFFLINE, library=library)
    session.generate_legacy("una sedia")
    record = session.save_to_library("Sedia")

    plan = GenerationPlan(template="freeform", strategy="library",
                          params={"asset_id": record.id})
    outcome = GeneratorManager(library=library).build(plan)
    assert outcome.strategy == LIBRARY
    assert outcome.scene.nodes


def test_library_strategy_falls_through_when_the_asset_is_missing(tmp_path):
    plan = GenerationPlan(template="chair", strategy="library",
                          params={"asset_id": "non-esiste"})
    outcome = GeneratorManager(library=AssetLibrary(tmp_path / "lib")).build(plan)
    assert outcome.strategy == TEMPLATE, "si passa alla strategia successiva"


# --------------------------------------------------------------------------- #
# Nessuna richiesta senza risposta, qualunque sia il percorso
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("prompt", [
    "crea una jeep", "crea un pesce", "una creatura impossibile con dodici ali",
    "asdfgh", "", "una sedia di legno", "un drago con corazza",
])
def test_every_prompt_produces_geometry(prompt):
    session = Session(provider=OFFLINE)
    session.generate_legacy(prompt or "x")
    assert session.scene.nodes and session.scene.triangle_count > 0
    assert session.scene.strategy in (TEMPLATE, ASSEMBLY, LIBRARY, FALLBACK)
