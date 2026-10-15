"""Il motore di copertura: le evidenze, i quattro stati, e il ricalcolo.

La cosa che questo file deve dimostrare e' una sola, ed e' §11: **la copertura
non e' una soglia su un punteggio**. Quindi si misura che:

* ogni candidato porta evidenze **nominate**, e lo stato si legge dai nomi;
* un punteggio altissimo senza identita' non fa un giallo;
* un'identita' senza contesto fa un blu e non un giallo;
* nessuna quantita' di evidenza fa un verde;
* la libreria reale, sul drago reale, da' i quattro stati che da' - e il banco
  registra quello, non una versione piu' bella (§46).
"""
from __future__ import annotations

import pathlib

import pytest

from app.teach import coverage as cov
from app.teach import errors as codes
from app.teach.errors import TeachError
from app.teach.knowledge import KnowledgeRecord, TeachKnowledge
from app.teach.model import (CANDIDATE, MISSING, PROXY, VALIDATED, Candidate,
                             Evidence, Solution, TeachProject, build_tree)
from tests.teach_fixtures import dragon_decomposition, dragon_refinement


@pytest.fixture
def dragon(teach):
    """Il drago raffinato, con la copertura calcolata sulla libreria vera."""
    teach.create_project("dragon", style_target="cartoon low-poly",
                         detail_target=2)
    teach.decomposition_prompt()
    teach.import_decomposition(dragon_decomposition())
    teach.refinement_prompt()
    teach.import_refinement(dragon_refinement())
    teach.analyse()
    return teach


# --------------------------------------------------------------------------- #
# Le evidenze
# --------------------------------------------------------------------------- #
def test_the_state_is_read_from_the_names_of_the_evidence_not_from_a_sum():
    identity = (Evidence(cov.ROLE, "", 4.0),)
    context = (Evidence(cov.CAPABILITY, "", 1.5),)
    similar = (Evidence(cov.RETRIEVAL, "", 0.9),)
    weak = (Evidence(cov.PARAMS, "", 0.4), Evidence(cov.STYLE, "", 0.2))

    assert cov.verdict_for(identity + context) == CANDIDATE
    assert cov.verdict_for(identity) == PROXY
    assert cov.verdict_for(context + similar) == PROXY
    assert cov.verdict_for(context) == MISSING
    assert cov.verdict_for(similar) == MISSING
    assert cov.verdict_for(weak + similar) == MISSING


def test_no_amount_of_evidence_produces_validated():
    """§14 e §41: il verde non si guadagna con le evidenze, si decide."""
    everything = tuple(Evidence(kind, "", weight)
                       for kind, weight in cov.WEIGHTS.items())
    everything += (Evidence(cov.RETRIEVAL, "", 1.0),)
    assert cov.verdict_for(everything) == CANDIDATE
    assert VALIDATED not in {cov.verdict_for(everything)}


def test_a_perfect_retrieval_score_alone_is_not_a_candidate():
    assert cov.verdict_for((Evidence(cov.RETRIEVAL, "1.000", 1.0),)) == MISSING


def test_identity_without_context_is_a_proxy_and_the_reason_says_why():
    candidate = Candidate(component_id="humanoid:leg", verdict=PROXY,
                          evidence=(Evidence(cov.ROLE, "role leg", 4.0),))
    candidate.reason = cov.reason_for(candidate)
    assert "niente la lega a questo oggetto" in candidate.reason


def test_identity_with_context_is_a_candidate_and_the_reason_says_why():
    candidate = Candidate(component_id="creature:dragon_head", verdict=CANDIDATE,
                          evidence=(Evidence(cov.ROLE, "role head", 4.0),
                                    Evidence(cov.FAMILY, "dragon", 1.5)))
    candidate.reason = cov.reason_for(candidate)
    assert "da verificare nel contesto" in candidate.reason


def test_family_words_are_the_concept_and_the_ancestors_not_the_node(dragon):
    project = dragon.project
    node = project.require_node("dragon.head.eye")
    words = cov.family_words(project, node)
    assert "dragon" in words                 # il concetto
    assert "head" in words                   # un antenato
    assert "eye" not in words                # non se stesso, o `family`
    assert "creature" in words               # il ruolo della radice


def test_component_words_read_tags_and_plugin_not_the_description(dragon):
    registry = dragon.session.catalog()
    component = registry.component("creature:dragon_head")
    words = cov.component_words(registry, component)
    assert {"dragon", "head", "reptile", "creature"} <= words
    # la descrizione e' testo libero: non entra, o un plugin dichiarerebbe di
    # appartenere a qualunque cosa scrivendolo in prosa
    assert "sporgente" not in words


def test_a_singular_variant_is_queried_too_because_the_index_has_no_stemming():
    assert cov.variants("wings") == ("wings", "wing")
    assert cov.variants("bodies") == ("bodies", "body")
    assert cov.variants("eye") == ("eye",)
    assert cov.variants("") == ()


def test_the_part_queries_exclude_the_concept_word(dragon):
    project = dragon.project
    node = project.require_node("dragon.head.horn")
    everything = cov.node_queries(project, node)
    parts = cov.part_queries(project, node)
    assert "dragon horn" in everything
    assert "dragon horn" not in parts
    assert "horn" in parts


def test_a_concept_wide_query_never_counts_as_similarity(dragon):
    """Senza questa regola ogni parte di un drago avrebbe la testa come proxy."""
    state = dragon.project.state("dragon.head.horn")
    assert state.coverage == MISSING
    assert [c.component_id for c in state.candidates] == []


# --------------------------------------------------------------------------- #
# Il filtro della radice (e il debito 13 di PROJECT-INDEX)
# --------------------------------------------------------------------------- #
def test_the_root_only_accepts_whole_subjects(dragon):
    """Una testa di drago non e' un drago, e il filtro e' strutturale.

    Si riusa `subject_capabilities()` di V2 - una capability fornita da
    qualcuno e accettata da nessuno - che e' esattamente cio' che il debito 13
    di `PROJECT-INDEX` dice esistere e non essere usato dal retrieval.
    """
    from app.core.archetypes import subject_capabilities

    registry = dragon.session.catalog()
    subjects = subject_capabilities(registry)
    state = dragon.project.state("dragon")
    for candidate in state.candidates:
        component = registry.component(candidate.component_id)
        assert {c.name for c in component.provides} & subjects
    assert "creature:dragon_head" not in [c.component_id
                                          for c in state.candidates]


def test_a_part_must_be_mountable_or_it_is_not_offered(dragon):
    """`humanoid:body` non fornisce niente: nessun composite lo potrebbe montare."""
    registry = dragon.session.catalog()
    assert registry.component("humanoid:body").provides == ()
    for node in ("dragon.body", "dragon.leg", "dragon.tail"):
        offered = [c.component_id for c in dragon.project.state(node).candidates]
        assert "humanoid:body" not in offered
        for cid in offered:
            assert registry.component(cid).provides


# --------------------------------------------------------------------------- #
# Il banco del drago (§46)
# --------------------------------------------------------------------------- #
def test_the_dragon_benchmark_produces_all_four_states_on_the_real_library(dragon):
    counts = dragon.summary()["counts"]
    assert counts[MISSING] >= 1
    assert counts[PROXY] >= 1
    assert counts[CANDIDATE] >= 1
    assert counts[VALIDATED] == 0            # niente e' validato dall'analisi


def test_the_dragon_head_is_a_candidate_because_it_names_the_concept(dragon):
    state = dragon.project.state("dragon.head")
    assert state.coverage == CANDIDATE
    best = state.best
    assert best.component_id == "creature:dragon_head"
    assert cov.ROLE in best.kinds and cov.FAMILY in best.kinds


def test_the_dragon_eye_is_a_candidate_through_the_parent_socket(dragon):
    state = dragon.project.state("dragon.head.eye")
    assert state.coverage == CANDIDATE
    best = state.best
    assert cov.NAME in best.kinds
    assert cov.CAPABILITY in best.kinds
    detail = [e.detail for e in best.evidence if e.kind == cov.CAPABILITY][0]
    assert "face_mount" in detail


@pytest.mark.parametrize("node", ["dragon.body", "dragon.wing", "dragon.leg",
                                  "dragon.tail"])
def test_the_right_part_of_the_wrong_creature_is_a_proxy(node, dragon):
    state = dragon.project.state(node)
    assert state.coverage == PROXY
    best = state.best
    assert best.kinds & set(cov.IDENTITY)
    assert not (best.kinds & set(cov.CONTEXT))


@pytest.mark.parametrize("node", ["dragon.head.horn", "dragon.head.tooth"])
def test_a_part_the_library_has_nothing_for_is_missing(node, dragon):
    state = dragon.project.state(node)
    assert state.coverage == MISSING
    assert state.candidates == ()


def test_the_candidate_list_shows_what_the_milestone_asks_for(dragon):
    """§12: ogni candidato con descrizione, plugin, ruolo, tag, params, perche'."""
    candidates = dragon.candidates("dragon.head.eye")
    assert len(candidates) >= 3
    assert [c.component_id for c in candidates] == sorted(
        [c.component_id for c in candidates],
        key=lambda cid: -[c for c in candidates if c.component_id == cid][0].weight)
    for candidate in candidates:
        assert candidate.reason
        assert candidate.evidence
        assert 0.0 <= candidate.score <= 1.0
    text = dragon.dossier("dragon.head.eye", candidates[0].component_id)
    for heading in ("TARGET", "CANDIDATE", "role:", "tags:", "provides:",
                    "mounts:", "params:", "semantic roles:", "usable effects:",
                    "frame:", "WHY 3DGEN PROPOSED IT"):
        assert heading in text


def test_the_candidate_list_is_capped_so_it_stays_a_list(dragon):
    for node in dragon.project.nodes():
        assert len(dragon.project.state(node.id).candidates) <= cov.MAX_CANDIDATES


def test_the_report_says_what_changed_and_how_long_it_took(dragon):
    report = dragon.analyse()
    assert report.seconds >= 0.0
    assert not report.changed            # un secondo giro non cambia niente
    assert "copertura ricalcolata" in report.describe()


# --------------------------------------------------------------------------- #
# Il ricalcolo, e cio' che non tocca
# --------------------------------------------------------------------------- #
def test_a_confirmed_solution_stays_validated_across_a_recompute(dragon):
    dragon.accept_candidate("dragon.tail", "fish:tail")
    assert dragon.project.coverage_of("dragon.tail") == VALIDATED
    dragon.analyse()
    assert dragon.project.coverage_of("dragon.tail") == VALIDATED
    assert dragon.project.state("dragon.tail").candidates


def test_a_forced_state_survives_a_recompute(dragon):
    dragon.set_coverage("dragon.head", PROXY)
    dragon.analyse()
    assert dragon.project.coverage_of("dragon.head") == PROXY
    assert dragon.project.state("dragon.head").locked


def test_a_solution_whose_component_vanished_decays_and_is_reported(dragon):
    dragon.accept_candidate("dragon.tail", "fish:tail")
    dragon.project.state("dragon.tail").solution = Solution(ref="gone:forever")
    report = dragon.analyse()
    assert "gone:forever" in report.dropped
    assert dragon.project.coverage_of("dragon.tail") != VALIDATED
    assert "non piu' installata" in report.describe()


def test_validated_is_only_ever_written_by_a_decision(dragon):
    """Quattro metodi, e nessuno di essi importa una risposta di un modello."""
    import inspect

    from app.teach import service as module

    source = inspect.getsource(module)
    writers = [name for name in ("accept_candidate", "save_variant",
                                 "accept_artifact", "set_coverage",
                                 "emit_composite")
               if "def %s(" % name in source]
    assert len(writers) == 5
    # e i metodi che importano una risposta non lo scrivono
    for name in ("import_decomposition", "import_refinement",
                 "import_suitability", "import_visual",
                 "import_implementation"):
        body = source.split("def %s(" % name, 1)[1].split("\n    def ", 1)[0]
        assert "coverage = VALIDATED" not in body


# --------------------------------------------------------------------------- #
# La conoscenza come evidenza (§19, §39)
# --------------------------------------------------------------------------- #
def test_a_prior_validation_is_an_evidence_and_not_a_promotion(teach):
    store = TeachKnowledge()
    store.add(KnowledgeRecord(concept="dragon", path="dragon.head.eye",
                              component="creature:bulging_eye", role="eye",
                              name="eye", recipe="dragon_eye"))
    teach.knowledge = store
    teach.create_project("wyvern", description="a two-legged winged dragon")
    teach.decomposition_prompt()
    teach.import_decomposition({
        "concept": "wyvern",
        "root": {"name": "wyvern", "role": "creature", "mandatory": True,
                 "children": [{"name": "head", "role": "head",
                               "mandatory": True,
                               "children": [{"name": "eye", "role": "eye",
                                             "mandatory": True, "count": 2}]}]}})
    teach.analyse()
    state = teach.project.state("wyvern.head.eye")
    best = state.best
    assert best.component_id == "creature:bulging_eye"
    assert cov.PRIOR_VALIDATION in best.kinds
    # ma resta giallo: un giudizio dato su un drago non e' un giudizio su un
    # wyvern, e fingere il contrario sarebbe la bugia che §10 vieta
    assert state.coverage == CANDIDATE


def test_coverage_needs_a_hierarchy(teach):
    teach.create_project("dragon")
    with pytest.raises(TeachError) as exc:
        teach.analyse()
    assert exc.value.code == codes.NO_HIERARCHY


def test_an_empty_project_has_an_empty_report():
    project = TeachProject(concept="dragon")
    report = cov.analyse(project, None, None)
    assert not report.any_change and report.candidates == {}


def test_the_tree_text_shows_the_four_colours(dragon):
    text = cov.tree_text(dragon.project)
    assert "GREEN" not in text               # niente e' validato
    assert "YELLOW" in text and "BLUE" in text and "RED" in text
    assert "mandatory (peso)" in text


def test_the_summary_carries_both_progress_measures(dragon):
    data = dragon.summary()
    assert set(data) >= {"mandatory_percent", "mandatory_node_percent",
                         "optional_percent", "counts", "nodes",
                         "with_candidates", "completion"}


# --------------------------------------------------------------------------- #
# Nessuna conoscenza di dominio nel motore (§20 della Definition of Done)
# --------------------------------------------------------------------------- #
def code_only(path) -> str:
    """Il sorgente senza commenti e senza docstring. Solo cio' che esegue.

    La distinzione conta e non e' indulgenza: un commento che spiega **una
    misura** - «cercare `dragon horn` trova `creature:dragon_head`, misurato» -
    e' documentazione preziosa, e toglierla per far passare un grep
    renderebbe il codice peggiore. Una parola di dominio dentro una stringa che
    il programma usa, invece, e' conoscenza di dominio: un prompt che nomina un
    occhio, un `if role == ...`, un elenco di parti. Quella e' la regressione,
    e questo e' cio' che il test guarda.
    """
    import ast
    import io
    import tokenize

    source = pathlib.Path(path).read_text(encoding="utf-8")
    tree = ast.parse(source)
    skip: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)                 and isinstance(first.value.value, str):
            skip.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))
    comments: set[tuple[int, int]] = set()
    readline = io.StringIO(source).readline
    for token in tokenize.generate_tokens(readline):
        if token.type == tokenize.COMMENT:
            comments.add((token.start[0], token.start[1]))
    lines = source.splitlines()
    out = []
    for number, line in enumerate(lines, start=1):
        if number in skip:
            continue
        cuts = [column for row, column in comments if row == number]
        if cuts:
            line = line[:min(cuts)]
        out.append(line)
    return chr(10).join(out)


@pytest.mark.parametrize("name", ["coverage.py", "spec.py", "model.py",
                                   "schema.py", "prompts.py", "contracts.py",
                                   "staging.py", "service.py", "knowledge.py",
                                   "_runner.py"])
def test_the_teach_layer_names_no_subject_and_no_part_in_its_code(name):
    """Nessuna parola di dominio in cio' che esegue. §53, criterio 20."""
    import re

    code = code_only(pathlib.Path("app/teach", name)).lower()
    for word in ("dragon", "drago", "wyvern", "horn", "snout", "wing", "tail",
                  "claw", "fang", "eye", "leg", "tooth", "scale"):
        pattern = chr(92) + "b" + word + "s?" + chr(92) + "b"
        assert re.search(pattern, code) is None, (
            "%s nomina %r nel codice" % (name, word))


def test_the_core_does_not_know_that_teach_exists():
    import subprocess
    import sys

    done = subprocess.run(
        [sys.executable, "-c",
         "import pathlib, re;"
         "paths=[p for d in ('app/core','app/build','app/geometry','app/authoring')"
         " for p in pathlib.Path(d).rglob('*.py')];"
         "hits=[str(p) for p in paths if 'app.teach' in p.read_text(encoding='utf-8')];"
         "print('|'.join(hits))"],
        capture_output=True, text=True)
    assert done.stdout.strip() == ""
