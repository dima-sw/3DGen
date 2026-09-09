"""Vincoli semantici e riparazione deterministica."""
from __future__ import annotations

import copy

import numpy as np
import pytest

from app.ai.creature import build_assembly, parse_creature
from app.ai.provider import OfflineProvider
from app.core.session import Session
from app.core.spec import AssemblySpec, AttachSpec, PartSpec
from app.build.validation import (
    ERROR, WARNING, Issue, RULES, check_connections, check_degenerate_parts,
    check_required_parts,
    check_symmetry, check_tail_is_posterior, errors, repair, rule_for,
    validate, validate_and_repair,
)
from app.geometry.composition import compose

OFFLINE = OfflineProvider()


def creature(prompt: str) -> AssemblySpec:
    return build_assembly(parse_creature(prompt))[0]


# --------------------------------------------------------------------------- #
# Le creature costruite dal sistema devono passare i propri vincoli
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("prompt", [
    "crea un pesce", "un lupo", "un uccello", "una persona", "un polpo",
    "un serpente", "un cavallo",
    "un pesce con il corpo di una persona e quattro braccia",
    "un animale con corpo di lupo, sei tentacoli, ali da pipistrello e corazza",
    "una creatura con testa di drago, quattro zampe e due corna",
])
def test_generated_creatures_have_no_errors(prompt):
    issues = validate(creature(prompt))
    assert not errors(issues), [str(i) for i in errors(issues)]


def test_rules_exist_for_every_archetype():
    for name in ("fish", "quadruped", "bird", "humanoid", "serpent", "generic"):
        assert name in RULES
    assert rule_for("inesistente") is RULES["generic"]


# --------------------------------------------------------------------------- #
# I controlli devono accorgersi dei difetti veri
# --------------------------------------------------------------------------- #
def test_missing_part_is_detected():
    """Un pesce senza coda non e' un pesce."""
    assembly = creature("crea un pesce")
    assembly.parts = [p for p in assembly.parts if "tail" not in p.tags]
    issues = validate(assembly)
    codes = {i.code for i in issues}
    assert "MISSING_PART" in codes
    assert any(i.part == "tail" and i.severity == ERROR for i in issues)


def test_too_few_parts_is_a_warning():
    """La coda porta anch'essa il tag 'fin': e' una pinna caudale."""
    assembly = creature("crea un pesce")
    for part in [p for p in assembly.parts if "fin" in p.tags and "tail" not in p.tags]:
        assembly.parts.remove(part)
    issues = validate(assembly)
    assert any(i.code == "TOO_FEW_PARTS" and i.severity == WARNING for i in issues)


def test_disconnected_part_is_detected():
    """Il caso reale: fondere due volumi lontani non li unisce.

    Rimpicciolire una parte non la stacca, perche' il suo ancoraggio resta
    sulla superficie del padre: per provare il controllo si sposta la posa.
    """
    composition = compose(creature("crea un pesce"))
    coda = composition.by_id("coda")
    coda.placement.translation = coda.placement.translation + np.array([0.0, 1.5, 0.0])
    issues = check_connections(composition)
    assert any(i.code == "PART_NOT_CONNECTED" and i.part == "coda" for i in issues)


def test_connected_parts_are_not_flagged():
    assert not check_connections(compose(creature("crea un pesce")))


def test_connection_check_uses_the_socket_actually_used():
    """Regressione: la testa si attacca con 'neck', non con 'base'."""
    assembly = creature("una persona")
    assert not [i for i in check_connections(compose(assembly))
                if i.part == "testa"], "falso positivo sulla testa"


def test_tail_in_front_is_detected():
    assembly = creature("crea un pesce")
    assembly.by_id("coda").attach.socket = "head"      # coda sul muso
    issues = check_tail_is_posterior(compose(assembly), rule_for("fish"))
    assert any(i.code == "TAIL_NOT_POSTERIOR" for i in issues)


def test_broken_symmetry_is_detected():
    assembly = creature("una persona")
    assembly.by_id("braccio_0").attach.scale = 2.0     # un braccio spostato
    assembly.by_id("braccio_0").params["length"] = 0.6
    issues = check_symmetry(compose(assembly), rule_for("humanoid"))
    assert any(i.code == "SYMMETRY_BROKEN" for i in issues)


def test_symmetry_does_not_confuse_unrelated_parts():
    """Regressione: pinna dorsale e ventrale venivano prese per una coppia."""
    issues = check_symmetry(compose(creature("crea un pesce")), rule_for("fish"))
    assert not issues


def test_round_body_is_flagged_for_a_fish():
    assembly = creature("crea un pesce")
    corpo = assembly.by_id("corpo")
    corpo.params.update({"length": 0.4, "height": 0.38, "width": 0.36})
    codes = {i.code for i in validate(assembly)}
    assert "SHAPE_TOO_ROUND" in codes


def test_recipe_limits_prevent_degenerate_parts():
    """Le ricette clampano i parametri: il caso degenere non nasce da li'."""
    assembly = creature("crea un pesce")
    assembly.by_id("pinna_dorsale").params.update(
        {"length": 0.0, "width": 0.0, "thickness": 0.0})
    composition = compose(assembly)
    lo, hi = composition.by_id("pinna_dorsale").field.bounds()
    assert float(np.min(hi - lo)) > 1e-3, "il minimo dichiarato protegge la parte"
    assert "DEGENERATE_PART" not in {i.code for i in validate(assembly)}


def test_degenerate_part_is_flagged_when_it_happens():
    """Protegge dalle ricette senza limiti, per esempio scritte dall'LLM."""
    composition = compose(creature("crea un pesce"))
    composition.by_id("pinna_dorsale").placement.scale = 1e-5
    codes = {i.code for i in check_degenerate_parts(composition)}
    assert "DEGENERATE_PART" in codes


# --------------------------------------------------------------------------- #
# Riparazione: deterministica, senza modelli
# --------------------------------------------------------------------------- #
def test_repair_pushes_a_floating_part_into_its_parent():
    """La correzione di un attacco lento: piu' innesto e piu' fusione."""
    assembly = creature("crea un pesce")
    assembly.by_id("coda").attach.insert = 0.0
    assembly.by_id("coda").blend = 0.0

    fixed, applied = repair(assembly, [Issue("PART_NOT_CONNECTED", ERROR, part="coda")])
    assert applied
    assert fixed.by_id("coda").attach.insert > 0.0
    assert fixed.by_id("coda").blend > 0.0
    # e non ha toccato nient'altro
    assert fixed.by_id("corpo").params == assembly.by_id("corpo").params


def test_repair_moves_a_misplaced_tail_back():
    assembly = creature("crea un pesce")
    assembly.by_id("coda").attach.socket = "head"
    fixed, _, issues, applied = validate_and_repair(assembly, attempts=3)
    assert fixed.by_id("coda").attach.socket == "tail"
    assert not [i for i in errors(issues) if i.code == "TAIL_NOT_POSTERIOR"]


def test_repair_removes_degenerate_parts():
    assembly = creature("crea un pesce")
    fixed, applied = repair(assembly, [Issue("DEGENERATE_PART", ERROR, part="pinna_ventrale")])
    assert fixed.by_id("pinna_ventrale") is None
    assert applied and "pinna_ventrale" in applied[0]


def test_repair_has_a_finite_budget():
    """Regola 10: nessun ciclo aperto, nemmeno quando non si riesce a riparare."""
    assembly = creature("crea un pesce")
    assembly.parts = [p for p in assembly.parts if "tail" not in p.tags]
    _, _, issues, applied = validate_and_repair(assembly, attempts=2)
    # una coda mancante non e' riparabile automaticamente: si segnala e basta
    assert any(i.code == "MISSING_PART" for i in issues)
    assert applied == []


def test_repair_never_touches_a_healthy_assembly():
    assembly = creature("crea un pesce")
    before = copy.deepcopy(assembly)
    fixed, _, issues, applied = validate_and_repair(assembly)
    assert applied == []
    assert fixed.model_dump() == before.model_dump()


# --------------------------------------------------------------------------- #
# Errori strutturati e integrazione
# --------------------------------------------------------------------------- #
def test_issues_are_machine_readable():
    issue = Issue("TAIL_NOT_POSTERIOR", ERROR, part="coda",
                  expected="posteriore", actual="laterale")
    data = issue.as_dict()
    assert data == {"code": "TAIL_NOT_POSTERIOR", "severity": "error", "part": "coda",
                    "expected": "posteriore", "actual": "laterale"}
    assert "TAIL_NOT_POSTERIOR" in str(issue)


def test_scene_carries_the_issues():
    session = Session(provider=OFFLINE)
    session.generate_legacy("crea un pesce")
    assert hasattr(session.scene, "issues")
    assert not [i for i in session.scene.issues if i.severity == ERROR]


def test_errors_reach_the_scene_warnings():
    from app.build.builder import build_scene
    from app.core.spec import GenerationPlan

    assembly = creature("crea un pesce")
    assembly.parts = [p for p in assembly.parts if "tail" not in p.tags]
    scene = build_scene(GenerationPlan(prompt="x", strategy="assembly", assembly=assembly))
    assert any("MISSING_PART" in w for w in scene.warnings)
    assert scene.nodes, "il modello si costruisce lo stesso"


# --------------------------------------------------------------------------- #
# Proporzioni delle appendici
# --------------------------------------------------------------------------- #
def test_a_ridiculous_limb_is_detected():
    """Il caso reale: un drago di sette metri con zampe di cinque centimetri."""
    from app.build.validation import check_appendage_proportions

    assembly = creature("un lupo")
    assembly.by_id("corpo").params.update({"length": 3.5, "height": 1.4, "width": 1.2})
    issues = check_appendage_proportions(compose(assembly))
    assert any(i.code == "APPENDAGE_TOO_SMALL" and "coscia" in i.part for i in issues)


def test_an_oversized_appendage_is_only_a_warning():
    from app.build.validation import check_appendage_proportions

    assembly = creature("un lupo")
    assembly.by_id("coda").params["length"] = 3.5
    issues = check_appendage_proportions(compose(assembly))
    grandi = [i for i in issues if i.code == "APPENDAGE_TOO_LARGE"]
    assert grandi and all(i.severity == WARNING for i in grandi)


def test_repair_rescales_a_disproportionate_limb():
    assembly = creature("un lupo")
    assembly.by_id("corpo").params.update({"length": 3.5, "height": 1.4, "width": 1.2})
    fixed, _, issues, applied = validate_and_repair(assembly, attempts=3)
    assert applied, "deve intervenire"
    assert fixed.by_id("coscia_0").attach.scale > 1.0
    assert not [i for i in errors(issues) if i.code == "APPENDAGE_TOO_SMALL"]


def test_feet_are_allowed_to_be_small():
    """Un piede e' piccolo per definizione: non va confuso con una gamba."""
    from app.build.validation import check_appendage_proportions

    issues = check_appendage_proportions(compose(creature("un lupo")))
    assert not [i for i in issues if "piede" in i.part]


# --------------------------------------------------------------------------- #
# Fedelta' alla richiesta (regola 8)
# --------------------------------------------------------------------------- #
def test_missing_requested_wings_are_detected():
    """Un piano puo' essere valido e avere ignorato meta' della richiesta."""
    from app.build.validation import check_requested_features

    senza_ali = creature("un lupo")          # nessuna ala
    issues = check_requested_features("un drago con quattro zampe e due ali",
                                      compose(senza_ali))
    assert any(i.code == "MISSING_REQUESTED_FEATURE" and i.part == "wing" for i in issues)


def test_requested_features_that_are_present_pass():
    from app.build.validation import check_requested_features

    completo = creature("un animale con corpo di lupo, due ali e una coda")
    issues = check_requested_features("un animale con corpo di lupo, due ali e una coda",
                                      compose(completo))
    assert not [i for i in issues if i.code == "MISSING_REQUESTED_FEATURE"]


def test_too_few_of_a_requested_feature_is_a_warning():
    from app.build.validation import check_requested_features

    pochi = creature("una creatura con due tentacoli")
    issues = check_requested_features("una creatura con sei tentacoli", compose(pochi))
    assert any(i.code == "TOO_FEW_REQUESTED" and i.severity == WARNING for i in issues)


def test_non_creature_prompts_are_not_checked():
    from app.build.validation import check_requested_features

    assert check_requested_features("una jeep con sei ruote", compose(creature("un lupo"))) == []


def test_the_prompt_reaches_the_validator():
    fedele = creature("un animale con corpo di lupo e due ali")
    senza = creature("un lupo")
    assert not [i for i in validate(fedele, prompt="un animale con corpo di lupo e due ali")
                if i.code == "MISSING_REQUESTED_FEATURE"]
    assert [i for i in validate(senza, prompt="un lupo con due ali")
            if i.code == "MISSING_REQUESTED_FEATURE"]
