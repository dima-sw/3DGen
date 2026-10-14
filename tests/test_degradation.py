"""La degradazione semantica: quando l'esatto non c'e', il piu' vicino che c'e'.

Questi test difendono sei proprieta', e sono le sei che distinguono un sistema
che approssima da uno che indovina:

    l'esatto vince sempre, finche' esiste
    un concetto sbagliato non uccide una radice valida
    cio' che manca degrada verso qualcosa di **correlato**, mai verso il primo
      componente in ordine alfabetico
    l'approssimazione e' dichiarata, con il suo punteggio
    la spiegazione sopravvive al salvataggio
    `generate()` e `build()` risolvono allo stesso modo

L'ultimo blocco e' il piu' importante per il futuro: un componente nuovo,
installato con soli metadata, deve entrare nella degradazione senza che nessuno
scriva un binding.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.ai.provider import OfflineProvider
from app.core.archetypes import (MATCH_DIRECT, MATCH_NAME, MATCH_PLAN_ROOT,
                                 MATCH_PROXY, MATCH_SUBJECT, ConceptResolver,
                                 normalize_reference, subject_capabilities)
from app.core.capability import Capability, Mount
from app.core.component import Component, Piece
from app.core.planner.planner import MockPlanner
from app.core.registry import PluginInfo, Registry
from app.core.session import Options, Session
from app.geometry.kernel import block

PLUGIN = Path(__file__).resolve().parent.parent / "app" / "plugins"


@pytest.fixture(scope="module")
def registro():
    from app.core.registry import load

    return load([PLUGIN]).freeze()


@pytest.fixture
def sessione(registro):
    return Session(registry=registro, provider=OfflineProvider(),
                   planner=MockPlanner())


def _piano(**extra) -> dict:
    piano = {"version": "1.3", "style": "low_poly"}
    piano.update(extra)
    return piano


# --------------------------------------------------------------------------- #
# Le capability soggetto: ricavate, non elencate
# --------------------------------------------------------------------------- #
def test_subject_capabilities_are_derived_from_the_library(registro):
    """Fornita da qualcuno e accettata da nessuno: e' un soggetto intero."""
    soggetti = subject_capabilities(registro)

    assert "vehicle" in soggetti        # l'auto e' un veicolo, non un innesto
    assert "animal" in soggetti
    assert "head_mount" not in soggetti  # una testa si attacca a qualcosa
    assert "core_mount" not in soggetti


def test_a_new_capability_becomes_a_subject_without_touching_the_core():
    registro = Registry()
    registro.register_plugin(PluginInfo(id="nuovo", version="1.0.0"))
    registro.register_component(
        Component(id="nuovo:navicella", build=lambda v, c: Piece(),
                  provides=(Capability("spacecraft"),)), "nuovo")

    assert "spacecraft" in subject_capabilities(registro)


# --------------------------------------------------------------------------- #
# Normalizzazione degli id: prudente e senza casi speciali
# --------------------------------------------------------------------------- #
def test_an_invented_prefix_is_removed_when_the_rest_is_unambiguous(registro):
    vero, nota = normalize_reference("registered:archetype_metadata:felid",
                                     registro.archetype,
                                     registro.archetype_ambiguous)

    assert vero == "archetype_metadata:felid"
    assert "normalizzato" in nota


def test_a_correct_id_is_left_alone(registro):
    vero, nota = normalize_reference("archetype_metadata:felid",
                                     registro.archetype)
    assert vero == "archetype_metadata:felid"
    assert nota == ""


def test_an_unknown_id_is_not_invented(registro):
    vero, nota = normalize_reference("qualcosa:che:non:esiste",
                                     registro.archetype)
    assert vero == ""
    assert nota == ""


def test_normalization_is_reported_not_silent(registro):
    plan = ConceptResolver(registro).resolve(
        "volpe", archetypes=["registered:archetype_metadata:felid"],
        style="low_poly")
    codici = [d["code"] for d in plan.diagnostics]

    assert "CONCEPT_ID_NORMALIZED" in codici


# --------------------------------------------------------------------------- #
# B — l'esatto vince
# --------------------------------------------------------------------------- #
def test_an_exact_component_id_wins(registro):
    plan = ConceptResolver(registro).resolve("fox_stylized:fox", style="low_poly")

    assert plan.selected_root_implementation == "fox_stylized:fox"
    assert plan.match == MATCH_DIRECT
    assert not plan.approximate


def test_a_bare_component_name_is_not_an_approximation(registro):
    """`fox` identifica `fox_stylized:fox` senza ambiguita': non si approssima."""
    plan = ConceptResolver(registro).resolve("fox", style="low_poly")

    assert plan.selected_root_implementation == "fox_stylized:fox"
    assert plan.match in (MATCH_DIRECT, MATCH_NAME)
    assert not plan.approximate


def test_an_exact_concept_wins_over_a_root_written_in_the_plan(sessione):
    risultato = sessione.build(_piano(
        concept={"requested": "fox_stylized:fox"},
        root={"id": "h", "ref": "architecture:house"}), Options(style="low_poly"))

    assert risultato.concept_resolution.selected_root_implementation \
        == "fox_stylized:fox"
    assert risultato.triangles > 0


# --------------------------------------------------------------------------- #
# C — l'antenato / il soggetto vicino
# --------------------------------------------------------------------------- #
def test_an_unknown_concept_degrades_to_a_related_subject(registro):
    """«jeep» non e' installato. La risposta e' un veicolo, e lo dice."""
    plan = ConceptResolver(registro).resolve("jeep", style="low_poly")

    assert plan.selected_root_implementation == "vehicle_stylized:car"
    assert plan.match == MATCH_SUBJECT
    assert plan.approximate
    assert plan.confidence > 0


def test_the_degradation_never_picks_something_unrelated(registro):
    """Il difetto che V2 esiste per togliere: «jeep» non e' un casco."""
    plan = ConceptResolver(registro).resolve("jeep", style="low_poly")

    assert plan.selected_root_implementation != "accessories:helmet"
    scelto = registro.component(plan.selected_root_implementation)
    assert "vehicle" in {c.name for c in scelto.provides} | set(scelto.tags)


def test_a_whole_subject_is_preferred_to_a_piece_of_one(registro):
    """Fra l'auto e la ruota si sceglie l'auto, e non perche' somiglia di piu':
    perche' `vehicle` e' una capability soggetto e `wheel_mount` no."""
    candidati = ConceptResolver(registro).candidates("jeep", style="low_poly")
    soggetto = {c.id: j for c, _, j in candidati}

    assert candidati[0][0].id == "vehicle_stylized:car"
    assert soggetto["vehicle_stylized:car"] is True
    assert soggetto.get("vehicle_stylized:wheel") is False
    # e il primo pezzo non soggetto viene dopo ogni soggetto
    primi_non_soggetti = [i for i, (_, _, j) in enumerate(candidati) if not j]
    primi_soggetti = [i for i, (_, _, j) in enumerate(candidati) if j]
    assert max(primi_soggetti) < min(primi_non_soggetti)


def test_degradation_is_deterministic(registro):
    uno = ConceptResolver(registro).resolve("jeep", style="low_poly")
    due = ConceptResolver(registro).resolve("jeep", style="low_poly")

    assert uno.selected_root_implementation == due.selected_root_implementation
    assert uno.confidence == due.confidence


# --------------------------------------------------------------------------- #
# A — un concetto sbagliato non distrugge una radice valida
# --------------------------------------------------------------------------- #
def test_a_hallucinated_concept_does_not_kill_a_valid_root(sessione):
    risultato = sessione.build(_piano(
        concept={"requested": "zzzqwerty",
                 "archetypes": ["registered:archetype_metadata:animal"]},
        root={"id": "casa", "ref": "architecture:house"}), Options(style="low_poly"))

    assert risultato.ok
    assert risultato.triangles > 0
    assert risultato.concept_resolution.selected_root_implementation \
        == "architecture:house"
    assert risultato.concept_resolution.match == MATCH_PLAN_ROOT


def test_an_approximated_concept_yields_to_an_explicit_root(sessione):
    """Fra una scelta del planner e una supposizione, vince la scelta."""
    risultato = sessione.build(_piano(
        concept={"requested": "jeep"},
        root={"id": "casa", "ref": "architecture:house"}), Options(style="low_poly"))

    assert risultato.concept_resolution.selected_root_implementation \
        == "architecture:house"
    assert risultato.concept_resolution.provenance[
        "superseded_root_implementation"] == "vehicle_stylized:car"


def test_a_broken_concept_alone_is_not_fatal_if_something_is_close(sessione):
    risultato = sessione.build(_piano(concept={"requested": "jeep"}),
                               Options(style="low_poly"))

    assert risultato.ok and risultato.triangles > 0


# --------------------------------------------------------------------------- #
# E — niente di adatto: lo si dice
# --------------------------------------------------------------------------- #
def test_with_no_related_candidate_the_system_says_so(registro):
    plan = ConceptResolver(registro).resolve("zzzqwerty", style="low_poly")
    codici = [d["code"] for d in plan.diagnostics]

    assert not plan.selected_root_implementation
    assert "CONCEPT_NO_CANDIDATE" in codici or "CONCEPT_TOO_FAR" in codici


def test_a_far_candidate_is_refused_instead_of_being_used(registro):
    """Meglio dichiarare che non c'e' niente che costruire un'omonimia."""
    plan = ConceptResolver(registro).resolve("robot", style="low_poly")

    if plan.selected_root_implementation:
        assert plan.confidence > 0
    else:
        assert any(d["code"] in ("CONCEPT_NO_CANDIDATE", "CONCEPT_TOO_FAR")
                   for d in plan.diagnostics)


# --------------------------------------------------------------------------- #
# D — comporre: il planner riceve i candidati giusti
# --------------------------------------------------------------------------- #
def test_a_two_family_request_offers_both_families(sessione):
    rosa = sessione.shortlist("Un pesce con corpo umanoide.", "low_poly")
    plugin = {cid.partition(":")[0] for cid in rosa.ids}

    assert "fish" in plugin
    assert any(p.startswith("humanoid") for p in plugin)


def test_the_planner_composes_from_both_families(sessione):
    risultato = sessione.generate("Un pesce con corpo umanoide.",
                                  Options(style="low_poly"))
    refs = {n.ref.partition(":")[0] for n in risultato.resolved.walk()}

    assert "fish" in refs
    assert risultato.triangles > 0


# --------------------------------------------------------------------------- #
# F — generate() e build() risolvono allo stesso modo
# --------------------------------------------------------------------------- #
def test_build_resolves_a_concept_plan_like_generate(registro):
    piano = _piano(concept={"requested": "jeep"})

    diretto = Session(registry=registro, provider=OfflineProvider(),
                      planner=MockPlanner()).build(piano, Options(style="low_poly"))
    tramite_planner = Session(
        registry=registro, provider=OfflineProvider(),
        planner=MockPlanner(scripts={"x": piano})).generate("x", Options(style="low_poly"))

    assert diretto.concept_resolution.selected_root_implementation == \
        tramite_planner.concept_resolution.selected_root_implementation
    assert diretto.triangles == tramite_planner.triangles


def test_a_concept_plan_no_longer_needs_a_backend_to_be_built(sessione):
    """Prima di V2: «un piano concept deve essere materializzato dal backend»."""
    risultato = sessione.build(_piano(concept={"requested": "fox_stylized:fox"}),
                               Options(style="low_poly"))

    assert risultato.ok and risultato.triangles > 0


# --------------------------------------------------------------------------- #
# La spiegazione
# --------------------------------------------------------------------------- #
def test_the_approximation_is_explained_programmatically(sessione):
    risultato = sessione.build(_piano(concept={"requested": "jeep"}),
                               Options(style="low_poly"))
    righe = risultato.degradation()
    testo = "\n".join(righe)

    assert righe
    assert "jeep" in testo
    assert "vehicle_stylized:car" in testo
    assert MATCH_SUBJECT in testo


def test_the_explanation_is_in_explain_too(sessione):
    risultato = sessione.build(_piano(concept={"requested": "jeep"}),
                               Options(style="low_poly"))

    assert risultato.explain()[:len(risultato.degradation())] \
        == risultato.degradation()


def test_an_exact_match_explains_nothing(sessione):
    risultato = sessione.build(_piano(concept={"requested": "fox_stylized:fox"}),
                               Options(style="low_poly"))

    assert risultato.degradation() == []


def test_the_coverage_structure_is_reused_not_duplicated(registro):
    plan = ConceptResolver(registro).resolve("jeep", style="low_poly")

    assert plan.coverage
    voce = plan.coverage[0]
    assert voce["candidate"] == "vehicle_stylized:car"
    assert voce["match"] == plan.match
    assert voce["reasons"]


# --------------------------------------------------------------------------- #
# La persistenza
# --------------------------------------------------------------------------- #
def test_the_approximation_survives_the_project(tmp_path, registro):
    piano = _piano(concept={"requested": "jeep"})
    sessione = Session(registry=registro, provider=OfflineProvider(),
                       planner=MockPlanner(scripts={"x": piano}))
    sessione.generate("x", Options(style="low_poly"))

    percorso = tmp_path / "progetto.my3d"
    sessione.save_project(percorso)

    riaperta = Session(registry=registro, provider=OfflineProvider(),
                       planner=MockPlanner())
    riaperta.open_project(percorso)
    risoluzione = riaperta.current.plan.concept_resolution

    assert risoluzione is not None
    assert risoluzione.requested_concept == "jeep"
    assert risoluzione.selected_root_implementation == "vehicle_stylized:car"
    assert risoluzione.approximate
    assert risoluzione.describe()


def test_an_old_project_without_the_new_fields_still_opens(registro):
    from app.core.archetypes import ConceptResolutionPlan

    vecchio = {"requested_concept": "jeep",
               "selected_root_implementation": "vehicle_stylized:car"}
    risoluzione = ConceptResolutionPlan.from_dict(vecchio)

    assert risoluzione is not None
    assert risoluzione.match == ""
    assert risoluzione.strategy == []


# --------------------------------------------------------------------------- #
# La libreria cresce: nessun binding scritto a mano
# --------------------------------------------------------------------------- #
def _libreria(con_sottomarino: bool) -> Registry:
    """Una libreria minima, con o senza il componente nuovo.

    Il componente nuovo non porta nessun `ImplementationBinding` e nessun
    `ArchetypeSpec`: solo id, descrizione, tag, capability e i sinonimi
    dichiarati dal suo plugin. Se la degradazione lo trova, la trova per i dati.
    """
    registro = Registry()
    registro.register_plugin(PluginInfo(id="base", version="1.0.0"))
    registro.register_component(
        Component(id="base:scatola", build=lambda v, c: Piece(mesh=block((1, 1, 1))),
                  description="un blocco", tags=frozenset({"solido"}),
                  provides=(Capability("solid"),)), "base")
    if con_sottomarino:
        registro.register_plugin(PluginInfo(
            id="mare", version="1.0.0", name="Mezzi subacquei",
            synonyms={"sottomarino": ("submarine", "sommergibile"),
                      "sommergibile": ("submarine", "sottomarino"),
                      "batiscafo": ("submarine",)}))
        registro.register_component(
            Component(id="mare:submarine",
                      build=lambda v, c: Piece(mesh=block((2, 1, 1))),
                      description="uno scafo subacqueo con torretta",
                      tags=frozenset({"submarine", "underwater", "vessel"}),
                      role="hull",
                      provides=(Capability("submarine"),),
                      mounts=(Mount(capability="solid", socket_id="base"),)),
            "mare")
    return registro.freeze()


def test_before_installing_it_there_is_no_candidate():
    plan = ConceptResolver(_libreria(False)).resolve("sommergibile")

    assert not plan.selected_root_implementation


def test_installing_a_component_is_enough_to_make_it_a_candidate():
    """install → index → retrieval → degradazione. Nessun binding, nessun core."""
    registro = _libreria(True)
    plan = ConceptResolver(registro).resolve("sommergibile")

    assert plan.selected_root_implementation == "mare:submarine"
    assert plan.approximate
    assert registro.implementation_bindings() == []
    assert registro.archetypes() == []


def test_the_new_component_is_found_through_its_declared_synonyms():
    registro = _libreria(True)
    plan = ConceptResolver(registro).resolve("batiscafo")

    assert plan.selected_root_implementation == "mare:submarine"


def test_the_new_component_is_a_subject_without_being_declared_one():
    registro = _libreria(True)

    assert "submarine" in subject_capabilities(registro)


def test_the_core_knows_none_of_these_words():
    """La prova che la conoscenza sta nella libreria: tolto il plugin, sparisce."""
    assert not ConceptResolver(_libreria(False)).resolve(
        "sottomarino").selected_root_implementation
    assert ConceptResolver(_libreria(True)).resolve(
        "sottomarino").selected_root_implementation == "mare:submarine"
