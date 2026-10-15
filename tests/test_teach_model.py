"""Il modello di una sessione di apprendimento, e cio' che rifiuta.

Tre cose si misurano qui, e nessuna riguarda la copertura (che sta in
`test_teach_coverage.py`):

1. **l'identita' di un nodo non e' l'id di un Component**, e' un percorso
   derivato dai nomi che un modello non puo' scegliere;
2. **una risposta malformata viene rifiutata, non interpretata** - §6 elenca
   nove casi e ciascuno ha un test;
3. **tutto si salva e si riapre**, compresi i prompt, le risposte, i tentativi
   e gli artefatti (§44), e il formato non e' `.my3d`.
"""
from __future__ import annotations

import json

import pytest

from app.authoring.variant import VariantRecipe
from app.teach import errors as codes
from app.teach.errors import TeachError
from app.teach.knowledge import KnowledgeRecord, TeachKnowledge
from app.teach.model import (CANDIDATE, COVERAGE, FORMAT_VERSION, LEARNED,
                             LEARNING, MAX_COUNT, MAX_DEPTH, MAX_NODES, MISSING,
                             PROXY, VALIDATED, ArtifactRecord, Attempt,
                             Candidate, Evidence, Exchange, NodeState,
                             PROJECT_SUFFIX, Solution, SuitabilityRecord,
                             TeachNode, TeachProject, build_tree, slug)
from tests.teach_fixtures import (BAD_DECOMPOSITIONS, dragon_decomposition,
                                  dragon_refinement, too_deep, too_wide)


# --------------------------------------------------------------------------- #
# L'identita' dei nodi
# --------------------------------------------------------------------------- #
def test_node_ids_are_paths_derived_from_names_and_not_written_by_the_model():
    tree = build_tree(dragon_refinement()["root"], concept="dragon")
    ids = [n.id for n in tree.walk()]
    assert ids[0] == "dragon"
    assert "dragon.head" in ids
    assert "dragon.head.eye" in ids
    # Nessun id arriva dalla risposta: lo schema non ha nemmeno il campo.
    assert "id" not in dragon_refinement()["root"]


def test_two_siblings_with_the_same_name_get_distinct_ids():
    data = {"name": "thing", "mandatory": True,
            "children": [{"name": "part", "mandatory": True},
                         {"name": "part", "mandatory": True},
                         {"name": "Part", "mandatory": True}]}
    tree = build_tree(data, concept="thing")
    ids = [c.id for c in tree.children]
    assert ids == ["thing.part", "thing.part_2", "thing.part_3"]


def test_a_node_id_is_never_a_component_id():
    tree = build_tree(dragon_refinement()["root"], concept="dragon")
    for node in tree.walk():
        assert ":" not in node.id


def test_slug_normalises_what_a_model_wrote():
    assert slug("Upper Case") == "upper_case"
    assert slug("../escape") == "escape"
    assert slug("  dragon's head  ") == "dragon_s_head"
    assert slug("") == "part"


def test_depth_and_leaf_read_from_the_path():
    tree = build_tree(dragon_refinement()["root"], concept="dragon")
    assert tree.depth == 0
    eye = tree.find("dragon.head.eye")
    assert eye is not None and eye.depth == 2 and eye.leaf


def test_a_node_carries_the_information_the_milestone_asks_for():
    tree = build_tree(dragon_refinement()["root"], concept="dragon")
    eye = tree.find("dragon.head.eye")
    assert (eye.id, eye.name, eye.role) == ("dragon.head.eye", "eye", "eye")
    assert eye.mandatory is True and eye.count == 2
    assert 0.0 <= eye.importance <= 1.0 and eye.detail_level == 2
    assert eye.description and eye.children == ()


# --------------------------------------------------------------------------- #
# Cio' che l'import rifiuta (§6)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", sorted(BAD_DECOMPOSITIONS))
def test_a_malformed_decomposition_is_refused_with_a_code(name, teach):
    teach.create_project("dragon")
    teach.decomposition_prompt()
    with pytest.raises(TeachError) as exc:
        teach.import_decomposition(BAD_DECOMPOSITIONS[name])
    assert exc.value.code in (codes.RESPONSE_INVALID, codes.SCHEMA_INVALID)
    assert teach.project.root is None


def test_a_hierarchy_deeper_than_the_declared_limit_is_refused(teach):
    teach.create_project("deep")
    teach.decomposition_prompt()
    with pytest.raises(TeachError) as exc:
        teach.import_decomposition(too_deep(MAX_DEPTH + 3))
    assert exc.value.code == codes.HIERARCHY_TOO_DEEP


def test_a_hierarchy_with_more_nodes_than_the_declared_limit_is_refused(teach):
    teach.create_project("wide")
    teach.decomposition_prompt()
    with pytest.raises(TeachError) as exc:
        teach.import_decomposition(too_wide(MAX_NODES + 10))
    assert exc.value.code == codes.HIERARCHY_TOO_LARGE


def test_count_must_be_a_positive_integer_inside_the_cap():
    for bad in (0, -1, MAX_COUNT + 1):
        with pytest.raises(TeachError):
            build_tree({"name": "x", "mandatory": True, "count": bad})
    good = build_tree({"name": "x", "mandatory": True, "count": MAX_COUNT})
    assert good.count == MAX_COUNT


def test_a_cycle_cannot_be_expressed_and_a_reference_is_refused():
    """§6 chiede di rifiutare un ciclo, e la risposta onesta e' che non esiste.

    Un figlio e' un **oggetto annidato**, non un riferimento a un nodo per
    nome: non c'e' un arco che possa tornare indietro. La forma in cui qualcuno
    proverebbe a scriverne uno e' un figlio che e' una stringa, e quella e'
    rifiutata. Lo stesso nome annidato resta legale e prende percorsi distinti,
    perche' «la testa della testa» non e' un errore: e' un percorso.
    """
    with pytest.raises(TeachError) as exc:
        build_tree({"name": "a", "mandatory": True, "children": ["a"]},
                   concept="a")
    assert exc.value.code == codes.SCHEMA_INVALID

    nested = build_tree({"name": "a", "mandatory": True,
                         "children": [{"name": "a", "mandatory": True,
                                       "children": [{"name": "a",
                                                     "mandatory": True}]}]},
                        concept="a")
    assert [n.id for n in nested.walk()] == ["a", "a.a", "a.a.a"]


def test_too_many_siblings_with_the_same_name_is_a_duplicate():
    data = {"name": "x", "mandatory": True,
            "children": [{"name": "p", "mandatory": True}
                         for _ in range(MAX_COUNT + 2)]}
    with pytest.raises(TeachError) as exc:
        build_tree(data, concept="x")
    assert exc.value.code == codes.DUPLICATE_NODE


def test_optional_is_accepted_as_the_mirror_of_mandatory():
    node = build_tree({"name": "x", "optional": True})
    assert node.mandatory is False


def test_import_does_not_execute_anything(teach, tmp_path):
    """§6: «Non eseguire nulla». Un campo che somiglia a un percorso resta testo."""
    marker = tmp_path / "boom.txt"
    data = dragon_decomposition()
    data["root"]["description"] = (
        "__import__('pathlib').Path(%r).write_text('x')" % str(marker))
    teach.create_project("dragon")
    teach.decomposition_prompt()
    teach.import_decomposition(data)
    assert not marker.exists()
    assert "__import__" in teach.project.root.description


# --------------------------------------------------------------------------- #
# I due passi, e cio' che sopravvive fra loro
# --------------------------------------------------------------------------- #
def test_the_refinement_replaces_the_hierarchy_and_records_what_changed(teach):
    teach.create_project("dragon")
    teach.decomposition_prompt()
    first = teach.import_decomposition(dragon_decomposition())
    assert first.detail["nodes"] == 11
    teach.refinement_prompt()
    second = teach.import_refinement(dragon_refinement())
    assert second.detail["nodes"] == 10
    assert any("count" in c for c in second.detail["changes"])
    assert teach.project.passes["refinement"]["nodes"] == 10


def test_a_decision_on_a_node_that_survives_the_refinement_survives_too(teach):
    teach.create_project("dragon")
    teach.decomposition_prompt()
    teach.import_decomposition(dragon_decomposition())
    teach.analyse()
    teach.set_coverage("dragon.body", PROXY)
    teach.refinement_prompt()
    report = teach.import_refinement(dragon_refinement())
    assert teach.project.coverage_of("dragon.body") == PROXY
    assert teach.project.state("dragon.body").locked
    assert report.detail["lost"] == []


def test_a_decision_on_a_node_the_refinement_removed_is_declared_lost(teach):
    teach.create_project("dragon")
    teach.decomposition_prompt()
    teach.import_decomposition(dragon_decomposition())
    teach.analyse()
    teach.set_coverage("dragon.head.eyes", PROXY)       # «eyes» diventa «eye»
    teach.refinement_prompt()
    report = teach.import_refinement(dragon_refinement())
    assert "dragon.head.eyes" in report.detail["lost"]
    assert "TEACH_DECISION_LOST" in report.report.codes()


def test_the_refinement_needs_a_hierarchy_first(teach):
    teach.create_project("dragon")
    with pytest.raises(TeachError) as exc:
        teach.refinement_prompt()
    assert exc.value.code == codes.NO_HIERARCHY


# --------------------------------------------------------------------------- #
# Lo stato di un nodo
# --------------------------------------------------------------------------- #
def test_an_unknown_coverage_value_falls_back_to_missing():
    assert NodeState(coverage="GREENISH").coverage == MISSING


@pytest.mark.parametrize("value", list(COVERAGE))
def test_the_four_states_round_trip_through_the_project(value, teach, tmp_path):
    teach.create_project("dragon")
    teach.decomposition_prompt()
    teach.import_decomposition(dragon_refinement())
    state = teach.project.state("dragon.body")
    if value == VALIDATED:
        state.solution = Solution(ref="humanoid:torso")
    state.coverage = value
    saved = teach.save_project(tmp_path / "p")
    assert saved.suffix == PROJECT_SUFFIX
    reopened = TeachProject.load(saved)
    assert reopened.coverage_of("dragon.body") == value


def test_a_solution_names_a_component_and_optionally_a_recipe():
    solution = Solution(ref="creature:eye", recipe="dragon_eye",
                        params={"size": 0.12})
    assert "creature:eye" in solution.describe()
    assert "dragon_eye" in solution.describe()
    assert Solution.from_dict(solution.to_dict()).params == {"size": 0.12}


def test_a_suitability_record_is_a_recommendation_and_knows_it():
    assert SuitabilityRecord(component_id="a", status="SUITABLE").recommends
    assert not SuitabilityRecord(component_id="a", status="NOT_SUITABLE").recommends
    assert SuitabilityRecord(component_id="a", status="nonsense").status \
        == "NEEDS_VISUAL_CHECK"


def test_an_attempt_keeps_its_codes_and_its_repair_lineage():
    attempt = Attempt(index=2, node="a.b", backend="procedural_python",
                      ok=False, codes=("X", "Y"), repaired_from=1)
    assert "riparazione di 1" in attempt.describe()
    assert Attempt.from_dict(attempt.to_dict()).codes == ("X", "Y")


def test_an_artifact_record_knows_whether_it_holds_python():
    assert ArtifactRecord(id="a", files=("plugin.json", "components/x.py")).code
    assert not ArtifactRecord(id="a", files=("plugin.json",
                                             "components/x.json")).code


def test_evidence_is_named_and_not_just_a_number():
    candidate = Candidate(component_id="x",
                          evidence=(Evidence("role", "role eye", 4.0),
                                    Evidence("retrieval", "0.5", 0.5)))
    assert candidate.kinds == frozenset({"role", "retrieval"})
    assert candidate.weight == pytest.approx(4.5)


# --------------------------------------------------------------------------- #
# Il progresso (§42)
# --------------------------------------------------------------------------- #
def test_progress_has_two_measures_and_the_formula_is_documented(teach):
    teach.create_project("dragon", detail_target=2)
    teach.decomposition_prompt()
    teach.import_decomposition(dragon_refinement())
    progress = teach.progress()
    # 8 mandatory rilevanti a livello 2: dragon, body, head, eye, snout, wing,
    # leg, tail. Il dente e' mandatory=False, il livello 3 non e' rilevante.
    assert progress.mandatory_total == 8
    assert progress.mandatory_percent == 0.0
    teach.project.state("dragon.tail").solution = Solution(ref="fish:tail")
    teach.project.state("dragon.tail").coverage = VALIDATED
    progress = teach.progress()
    assert progress.mandatory_validated == 1
    # il peso e' importance * count: la coda vale 0.75, il totale 8 nodi
    assert 0.0 < progress.mandatory_percent < progress.mandatory_node_percent * 2
    assert progress.mandatory_node_percent == pytest.approx(12.5)


def test_an_optional_node_never_blocks_the_mandatory_measure(teach):
    teach.create_project("dragon", detail_target=2)
    teach.decomposition_prompt()
    teach.import_decomposition(dragon_refinement())
    progress = teach.progress()
    assert progress.optional_total == 1           # horn; tooth e' a livello 3
    assert progress.optional_percent == 0.0
    assert not progress.complete


def test_the_detail_target_decides_which_mandatory_nodes_count(teach):
    teach.create_project("dragon", detail_target=1)
    teach.decomposition_prompt()
    teach.import_decomposition(dragon_refinement())
    # a livello 1 l'occhio e il muso non servono
    assert teach.progress().mandatory_total == 6
    teach.project.detail_target = 3
    assert teach.progress().mandatory_total == 8


# --------------------------------------------------------------------------- #
# Persistenza (§44)
# --------------------------------------------------------------------------- #
def test_the_project_round_trips_with_prompts_responses_and_attempts(teach,
                                                                     tmp_path):
    teach.create_project("dragon", style_target="cartoon low-poly",
                         detail_target=2)
    teach.decomposition_prompt()
    teach.import_decomposition(dragon_decomposition())
    teach.refinement_prompt()
    teach.import_refinement(dragon_refinement())
    teach.analyse()
    project = teach.project
    project.state("dragon.tail").attempts = (
        Attempt(index=1, node="dragon.tail", backend="procedural_python"),)
    project.recipes["dragon_eye"] = VariantRecipe(base="creature:bulging_eye",
                                                  name="dragon_eye",
                                                  params={"size": 0.12})
    project.artifacts["a1"] = ArtifactRecord(id="a1", node="dragon.tail",
                                             files=("plugin.json",))
    saved = teach.save_project(tmp_path / "dragon")
    reopened = TeachProject.load(saved)

    assert reopened.concept == "dragon"
    assert reopened.style_target == "cartoon low-poly"
    assert [n.id for n in reopened.nodes()] == [n.id for n in project.nodes()]
    assert reopened.coverage_of("dragon.head") == project.coverage_of("dragon.head")
    assert reopened.state("dragon.head").candidates
    assert reopened.state("dragon.tail").attempts[0].index == 1
    assert reopened.variant("dragon_eye").params == {"size": 0.12}
    assert reopened.artifact("a1").files == ("plugin.json",)
    assert [e.kind for e in reopened.exchanges] == ["decomposition", "refinement"]
    assert reopened.exchanges[0].prompt and reopened.exchanges[0].response
    assert reopened.to_dict() == TeachProject.load(saved).to_dict()


def test_the_project_file_is_not_a_my3d_and_declares_its_format(teach, tmp_path):
    teach.create_project("dragon")
    teach.decomposition_prompt()
    teach.import_decomposition(dragon_refinement())
    saved = teach.save_project(tmp_path / "dragon")
    assert saved.suffix == ".teach3d"
    data = json.loads(saved.read_text(encoding="utf-8"))
    assert data["format"] == FORMAT_VERSION
    assert "plans" not in data and "plugins" not in data


def test_a_project_of_an_unknown_format_is_refused_instead_of_read(tmp_path):
    target = tmp_path / "x.teach3d"
    target.write_text(json.dumps({"format": 99, "concept": "dragon"}),
                      encoding="utf-8")
    with pytest.raises(TeachError) as exc:
        TeachProject.load(target)
    assert exc.value.code == codes.PROJECT_INVALID


def test_a_missing_project_file_says_so(tmp_path):
    with pytest.raises(TeachError) as exc:
        TeachProject.load(tmp_path / "nope.teach3d")
    assert exc.value.code == codes.FILE_MISSING


def test_a_project_without_a_concept_is_refused():
    with pytest.raises(TeachError):
        TeachProject(concept="   ")


def test_the_project_never_carries_geometry(teach, tmp_path):
    """Nessun campo di geometria, a nessuna profondita'. Come `.my3d`.

    Si guarda la **struttura** e non il testo: il progetto contiene i prompt, e
    un prompt di decomposizione dice al modello di non parlare di vertici, per
    cui la parola «vertices» compare legittimamente nel file. Cio' che non deve
    esserci e' un campo che porti geometria.
    """
    teach.create_project("dragon")
    teach.decomposition_prompt()
    teach.import_decomposition(dragon_refinement())
    saved = teach.save_project(tmp_path / "dragon")
    data = json.loads(saved.read_text(encoding="utf-8"))

    forbidden = {"mesh", "vertices", "faces", "normals", "uv", "geometry"}
    found = []

    def walk(value, where=""):
        if isinstance(value, dict):
            for key, inner in value.items():
                if key in forbidden:
                    found.append(where + "/" + key)
                walk(inner, where + "/" + key)
        elif isinstance(value, list):
            for item in value:
                walk(item, where)

    walk(data)
    assert found == []
    assert saved.stat().st_size < 120_000


# --------------------------------------------------------------------------- #
# La conoscenza riusabile (§19)
# --------------------------------------------------------------------------- #
def test_knowledge_is_not_a_field_on_component():
    """§19: la decisione e' non toccare `Component`, e questo la fissa."""
    import dataclasses

    from app.core.component import Component

    names = {f.name for f in dataclasses.fields(Component)}
    assert "validated_for" not in names
    assert not any("valid" in n for n in names)


def test_a_knowledge_record_is_keyed_on_role_and_name_not_on_the_path():
    store = TeachKnowledge()
    store.add(KnowledgeRecord(concept="dragon", path="dragon.head.eye",
                              component="creature:bulging_eye", role="eye",
                              name="eye", recipe="dragon_eye"))
    # un occhio di wyvern e' lo stesso ruolo, e trova il record
    found = store.records_for(role="eye", name="eye")
    assert [r.component for r in found] == ["creature:bulging_eye"]
    assert store.records_for(role="wing", name="wing") == []


def test_knowledge_round_trips_with_its_recipes(tmp_path):
    store = TeachKnowledge()
    recipe = VariantRecipe(base="creature:bulging_eye", name="dragon_eye",
                           params={"size": 0.12})
    store.add(KnowledgeRecord(concept="dragon", path="dragon.head.eye",
                              component="creature:bulging_eye", role="eye",
                              name="eye", recipe="dragon_eye"), recipe)
    path = store.save(tmp_path / "k.json")
    again = TeachKnowledge.load(path)
    assert again.describe() == "1 validazioni, 1 ricette"
    assert again.variant("dragon_eye").params == {"size": 0.12}


def test_a_missing_knowledge_file_is_an_empty_store_not_an_error(tmp_path):
    store = TeachKnowledge.load(tmp_path / "nope.json")
    assert store.records == ()


def test_merge_takes_the_validated_nodes_and_skips_what_this_teach_generated(teach):
    teach.create_project("dragon")
    teach.decomposition_prompt()
    teach.import_decomposition(dragon_refinement())
    project = teach.project
    project.state("dragon.tail").solution = Solution(ref="fish:tail")
    project.state("dragon.tail").coverage = VALIDATED
    project.state("dragon.body").solution = Solution(ref="dragon_body:body")
    project.state("dragon.body").coverage = VALIDATED
    store = TeachKnowledge()
    added = store.merge(project)
    assert [r.component for r in added] == ["fish:tail"]
    assert "dragon_body:body" not in store.components()


def test_the_concept_owns_the_plugins_it_generates():
    project = TeachProject(concept="dragon")
    assert project.plugin_id == "dragon"
    assert project.pack_plugin == "dragon_pack"
    assert project.plugin_named("snout") == "dragon_snout"
    assert project.owns("dragon_pack:dragon")
    assert project.owns("dragon_snout:snout")
    assert not project.owns("creature:dragon_head")


# --------------------------------------------------------------------------- #
# Le viste
# --------------------------------------------------------------------------- #
def test_the_tree_view_merges_ontology_and_state(teach):
    teach.create_project("dragon")
    teach.decomposition_prompt()
    teach.import_decomposition(dragon_refinement())
    rows = teach.tree()
    assert len(rows) == 10
    head = [r for r in rows if r["id"] == "dragon.head"][0]
    assert set(head) >= {"id", "name", "role", "depth", "mandatory", "count",
                         "importance", "detail_level", "coverage", "solution",
                         "candidates", "locked", "backend"}
    assert head["coverage"] in COVERAGE


def test_completion_starts_at_learning_and_is_not_a_switch(teach):
    teach.create_project("dragon")
    assert teach.project.completion == LEARNING
    assert not teach.project.learned
    teach.project.completion = LEARNED
    assert teach.project.learned


def test_concept_words_exclude_the_style_because_a_style_is_not_a_subject():
    project = TeachProject(concept="dragon", description="a winged reptile",
                           style_target="cartoon low-poly")
    words = project.concept_words()
    assert "dragon" in words and "reptile" in words
    assert "cartoon" not in words and "poly" not in words


def test_an_exchange_keeps_both_sides():
    exchange = Exchange(kind="decomposition", prompt="ask", response="answer",
                        accepted=True)
    again = Exchange.from_dict(exchange.to_dict())
    assert (again.prompt, again.response, again.accepted) == ("ask", "answer",
                                                              True)
