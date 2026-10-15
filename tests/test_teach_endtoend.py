"""Il banco del drago, e il test piu' importante di V7 (§46-§50).

Tutto deterministico e senza rete: le risposte di un modello arrivano da
`tests/teach_fixtures.py`, che e' la **stessa** strada della modalita' esterna
di §5 — una risposta incollata a mano e una risposta di un fixture sono la
stessa cosa per il sistema.

La prova finale e' §38, e vale la pena dirla per esteso: dopo che il concetto
e' `LEARNED`, una `Session` **normale** — fuori da Teach, con il planner
locale — trova e costruisce quel concetto. Se quella riga non passasse, tutto
il resto sarebbe teatro.
"""
from __future__ import annotations

import pathlib

import pytest

from app.core.session import Options
from app.teach import errors as codes
from app.teach.errors import TeachError
from app.teach.knowledge import TeachKnowledge
from app.teach.model import (CANDIDATE, COMPOSITE, DATA_MESH, LEARNED, LEARNING,
                             MISSING, PROCEDURAL, PROXY, TeachProject,
                             VALIDATED)
from tests.teach_fixtures import (data_component, dragon_decomposition,
                                  dragon_refinement, python_component,
                                  suitable_with_parameters, visual_verdicts,
                                  write_part_glb)

PROXY_NODES = ("dragon.body", "dragon.wing", "dragon.leg", "dragon.tail")


# --------------------------------------------------------------------------- #
# Il banco del drago (§46)
# --------------------------------------------------------------------------- #
@pytest.fixture
def dragon(teach, tmp_path):
    teach.create_project("dragon", style_target="cartoon low-poly",
                         detail_target=2, destination=str(tmp_path / "library"))
    teach.decomposition_prompt()
    teach.import_decomposition(dragon_decomposition())
    teach.refinement_prompt()
    teach.import_refinement(dragon_refinement())
    teach.analyse()
    return teach


def test_the_dragon_benchmark_decomposes_into_the_parts_the_milestone_names(dragon):
    ids = [n.id for n in dragon.project.nodes()]
    for wanted in ("dragon", "dragon.body", "dragon.head", "dragon.head.eye",
                   "dragon.head.snout", "dragon.head.horn", "dragon.wing",
                   "dragon.leg", "dragon.tail"):
        assert wanted in ids


def test_the_refinement_turns_plurals_into_counts(dragon):
    project = dragon.project
    assert project.require_node("dragon.head.eye").count == 2
    assert project.require_node("dragon.wing").count == 2
    assert project.require_node("dragon.leg").count == 4
    assert project.require_node("dragon.head.horn").count == 2
    # e il nodo troppo granulare del pass 1 e' sparito
    assert project.node("dragon.leg.claw") is None


def test_mandatory_and_optional_are_as_the_milestone_describes(dragon):
    project = dragon.project
    for node_id in ("dragon.body", "dragon.head", "dragon.head.eye",
                    "dragon.head.snout", "dragon.wing", "dragon.leg",
                    "dragon.tail"):
        assert project.require_node(node_id).mandatory, node_id
    for node_id in ("dragon.head.horn", "dragon.head.tooth"):
        assert not project.require_node(node_id).mandatory, node_id


def test_the_initial_coverage_is_measured_and_not_arranged(dragon):
    """§46: «NON manipolare il ranking». Questo e' cio' che la libreria da'."""
    found = {row["id"]: row["coverage"] for row in dragon.tree()}
    assert found["dragon"] == MISSING            # nessun drago intero installato
    assert found["dragon.head"] == CANDIDATE     # creature:dragon_head
    assert found["dragon.head.eye"] == CANDIDATE
    assert found["dragon.head.horn"] == MISSING
    assert found["dragon.head.tooth"] == MISSING
    for node in PROXY_NODES:
        assert found[node] == PROXY
    assert all(v != VALIDATED for v in found.values())


def test_the_queue_goes_from_the_fine_parts_up_to_the_root(dragon):
    order = [n.id for n in dragon.queue()]
    assert order[-1] == "dragon"                      # la radice per ultima
    assert order.index("dragon.head.eye") < order.index("dragon.head")
    assert order.index("dragon.head.snout") < order.index("dragon.head")
    assert order.index("dragon.head") < order.index("dragon")
    assert "dragon.head.tooth" not in order           # gli optional non entrano


def test_the_next_node_is_the_first_one_that_can_really_be_faced(dragon):
    assert dragon.next_node().id == "dragon.head.eye"
    step = dragon.advance()
    assert step["action"] == "validate_candidate"
    assert step["node"] == "dragon.head.eye"


# --------------------------------------------------------------------------- #
# Giallo -> verde con una VariantRecipe (§47, §18)
# --------------------------------------------------------------------------- #
def test_a_yellow_candidate_becomes_green_through_a_variant(dragon):
    node = "dragon.head.eye"
    component = dragon.candidates(node)[0].component_id
    assert dragon.project.coverage_of(node) == CANDIDATE

    dragon.suitability_prompt(node, component)
    record = dragon.import_suitability(
        node, suitable_with_parameters({"size": 0.12}), component_id=component)
    assert record.status == "SUITABLE_WITH_PARAMETERS"
    # l'AI ha raccomandato, e il nodo e' ancora giallo
    assert dragon.project.coverage_of(node) == CANDIDATE

    lab = dragon.lab(node, component)
    before = lab.build().extents()
    built = dragon.apply_suggestion(node, component)
    assert built.ok
    assert built.extents() != before

    recipe = dragon.save_variant(node, "dragon_eye", component_id=component)
    assert dragon.project.coverage_of(node) == VALIDATED
    solution = dragon.project.state(node).solution
    assert solution.ref == component and solution.recipe == "dragon_eye"
    assert recipe.params == {"size": 0.12}
    assert recipe.coverage == VALIDATED


def test_the_variant_duplicates_no_geometry(dragon, tmp_path):
    node = "dragon.head.eye"
    component = dragon.candidates(node)[0].component_id
    dragon.suitability_prompt(node, component)
    dragon.import_suitability(node, suitable_with_parameters({"size": 0.12}),
                              component_id=component)
    dragon.apply_suggestion(node, component)
    recipe = dragon.save_variant(node, "dragon_eye", component_id=component)
    saved = recipe.save(tmp_path / "dragon_eye.json")
    assert saved.stat().st_size < 700
    raw = saved.read_text(encoding="utf-8")
    for word in ("mesh", "glb", "vertices", "faces"):
        assert word not in raw
    assert not list(tmp_path.glob("*.glb"))


def test_an_ai_recommendation_can_never_write_validated(dragon):
    """§14, sul caso piu' estremo: SUITABLE con confidenza 1.0."""
    node = "dragon.head.eye"
    component = dragon.candidates(node)[0].component_id
    dragon.suitability_prompt(node, component)
    dragon.import_suitability(node, {"status": "SUITABLE", "confidence": 1.0,
                                     "reason": "perfect"},
                              component_id=component)
    assert dragon.project.coverage_of(node) == CANDIDATE
    assert dragon.project.state(node).solution is None


def test_a_suggested_parameter_the_component_does_not_declare_is_dropped(dragon):
    node = "dragon.head.eye"
    component = dragon.candidates(node)[0].component_id
    dragon.suitability_prompt(node, component)
    record = dragon.import_suitability(
        node, suitable_with_parameters({"size": 0.12, "invented": 3.0,
                                        "callable": 1.0}),
        component_id=component)
    assert record.suggested_params == {"size": 0.12}


def test_a_visual_verdict_is_imported_and_stays_a_recommendation(dragon):
    node = "dragon.head.eye"
    component = dragon.candidates(node)[0].component_id
    dragon.visual_validation_prompt(node, component,
                                    variants=[{"label": "A", "params": {}},
                                              {"label": "B", "params": {}},
                                              {"label": "C", "params": {}}])
    out = dragon.import_visual(node, visual_verdicts())
    assert out["best"] == "B"
    assert len(out["verdicts"]) == 3
    assert dragon.project.coverage_of(node) == CANDIDATE


def test_the_rendered_variants_stay_inside_the_declared_ranges(dragon):
    node = "dragon.head.eye"
    component = dragon.candidates(node)[0].component_id
    shown = dragon.render_variants(node, component, count=2)
    assert [item["label"] for item in shown] == ["A", "C", "D"]
    lab = dragon.lab(node, component)
    for item in shown:
        for name, value in item["params"].items():
            spec = lab.component.params[name]
            if spec.min is not None:
                assert spec.min <= value <= spec.max


# --------------------------------------------------------------------------- #
# Proxy -> MISSING -> conoscenza nuova (§20, §48)
# --------------------------------------------------------------------------- #
def test_a_proxy_that_is_not_enough_becomes_missing(dragon):
    node = "dragon.head.snout"
    assert dragon.project.coverage_of(node) == PROXY
    for candidate in list(dragon.candidates(node)):
        dragon.reject_candidate(node, candidate.component_id)
    assert dragon.project.coverage_of(node) == MISSING
    assert dragon.project.state(node).locked


def test_a_missing_node_produces_a_technical_specification(dragon):
    node = "dragon.head.snout"
    for candidate in list(dragon.candidates(node)):
        dragon.reject_candidate(node, candidate.component_id)
    spec = dragon.spec(node)
    assert spec.node == node
    assert spec.component_id == "dragon_snout:snout"
    assert spec.plugin_id == "dragon_snout"
    assert spec.provides == ("face_mount",)
    assert spec.parent == "dragon.head"
    assert spec.parent_component == "creature:dragon_head"
    assert spec.backend == PROCEDURAL
    assert spec.triangle_budget >= 24
    assert spec.semantic_parameters
    assert spec.style_target == "cartoon low-poly"
    assert any("budget" in note for note in spec.notes)


def test_the_spec_recommends_a_backend_and_the_user_can_override(dragon):
    node = "dragon.head.snout"
    for candidate in list(dragon.candidates(node)):
        dragon.reject_candidate(node, candidate.component_id)
    assert dragon.spec(node).backend == PROCEDURAL
    dragon.set_backend(node, DATA_MESH)
    spec = dragon.spec(node)
    assert spec.backend == DATA_MESH
    assert "scelto dall'utente" in spec.backend_reason
    assert spec.backend_candidates[0] == DATA_MESH


def test_a_node_with_a_supplied_asset_is_recommended_as_data(dragon, tmp_path):
    glb = write_part_glb(tmp_path / "assets")
    dragon.supply_asset("dragon.head.horn", glb)
    spec = dragon.spec("dragon.head.horn")
    assert spec.backend == DATA_MESH
    assert spec.asset == str(glb)
    assert "asset" in spec.backend_reason


def test_a_node_whose_children_are_all_validated_is_recommended_as_composite(
        dragon, tmp_path):
    dragon.accept_candidate("dragon.head.eye",
                            dragon.candidates("dragon.head.eye")[0].component_id)
    dragon.accept_candidate("dragon.head.snout",
                            dragon.candidates("dragon.head.snout")[0].component_id)
    spec = dragon.spec("dragon.head")
    assert spec.backend == COMPOSITE
    assert "disposizione" in spec.backend_reason
    assert len(spec.children) == 2


def test_the_spec_declares_a_new_capability_when_the_parent_has_none(dragon):
    """Un composite scritto da noi non esiste ancora: la capability si dichiara."""
    for candidate in list(dragon.candidates("dragon.body")):
        dragon.reject_candidate("dragon.body", candidate.component_id)
    spec = dragon.spec("dragon.body")
    # il padre e' la radice, che non ha un componente: la capability e' nuova
    assert spec.provides == ("body_mount",)
    assert spec.declares_capability is True
    assert any("non e' installata" in note for note in spec.notes)


# --------------------------------------------------------------------------- #
# §48: MISSING -> spec -> prompt -> staging -> validazione -> accept -> verde
# --------------------------------------------------------------------------- #
def test_a_data_only_response_is_validated_without_executing_anything(dragon,
                                                                       tmp_path):
    node = "dragon.head.horn"
    glb = write_part_glb(tmp_path / "assets")
    dragon.supply_asset(node, glb)
    spec = dragon.spec(node)
    bundle = dragon.implementation_prompt(node)
    assert "do not emit GLB bytes" in bundle.user

    artifact = dragon.import_implementation(
        node, data_component(spec.plugin_id, "horn",
                             capability=spec.provides[0], mesh=glb.name))
    assert artifact.kind == DATA_MESH
    assert not artifact.code
    assert not artifact.trusted                       # e non serve
    out = dragon.validate_artifact(artifact.id)
    assert out.ok and out.triangles == 12
    assert spec.component_id in out.installed

    installed = dragon.accept_artifact(artifact.id)
    assert installed.ok
    assert dragon.project.coverage_of(node) == VALIDATED
    assert dragon.session.catalog().component(spec.component_id) is not None
    assert not list((tmp_path / "library" / spec.plugin_id).rglob("*.py"))


def test_a_python_response_is_staged_but_not_run_until_trusted(dragon):
    """§49: il requisito di prodotto, misurato dal lato dell'effetto."""
    node = "dragon.head.snout"
    for candidate in list(dragon.candidates(node)):
        dragon.reject_candidate(node, candidate.component_id)
    spec = dragon.spec(node)
    dragon.implementation_prompt(node)
    artifact = dragon.import_implementation(
        node, python_component(spec.plugin_id, "snout",
                               capability=spec.provides[0], role="snout"))
    assert artifact.kind == PROCEDURAL and artifact.code
    assert artifact.trusted is False
    assert dragon.session.catalog().component(spec.component_id) is None

    with pytest.raises(TeachError) as exc:
        dragon.validate_artifact(artifact.id)
    assert exc.value.code == codes.TRUST_REQUIRED

    dragon.trust_artifact(artifact.id)
    out = dragon.validate_artifact(artifact.id)
    assert out.ok
    installed = dragon.accept_artifact(artifact.id)
    assert installed.ok
    assert dragon.project.coverage_of(node) == VALIDATED


def test_installing_a_component_recomputes_the_coverage(dragon, tmp_path):
    """§35: l'installazione puo' cambiare lo stato di **altri** nodi."""
    node = "dragon.head.horn"
    glb = write_part_glb(tmp_path / "assets")
    dragon.supply_asset(node, glb)
    spec = dragon.spec(node)
    dragon.implementation_prompt(node)
    artifact = dragon.import_implementation(
        node, data_component(spec.plugin_id, "horn",
                             capability=spec.provides[0], mesh=glb.name))
    before = {row["id"]: row["coverage"] for row in dragon.tree()}
    dragon.accept_artifact(artifact.id)
    after = {row["id"]: row["coverage"] for row in dragon.tree()}
    assert before[node] == MISSING and after[node] == VALIDATED
    # il dente aveva nessun candidato; adesso un corno installato esiste, e la
    # coda si e' ricalcolata da sola
    assert [n.id for n in dragon.queue()] != []
    assert dragon.project.state(node).solution.origin == "generated"


# --------------------------------------------------------------------------- #
# §50: il giro completo
# --------------------------------------------------------------------------- #
def learn_the_dragon(teach, tmp_path, *, with_asset: bool = True):
    """Il ciclo di §50, per intero e senza rete. Restituisce il referto finale."""
    node = "dragon.head.eye"
    eye = teach.candidates(node)[0].component_id
    teach.suitability_prompt(node, eye)
    teach.import_suitability(node, suitable_with_parameters({"size": 0.12}),
                             component_id=eye)
    teach.apply_suggestion(node, eye)
    teach.save_variant(node, "dragon_eye", component_id=eye)

    for proxy in PROXY_NODES:
        teach.accept_candidate(proxy, teach.candidates(proxy)[0].component_id)

    snout = "dragon.head.snout"
    for candidate in list(teach.candidates(snout)):
        teach.reject_candidate(snout, candidate.component_id)
    spec = teach.spec(snout)
    teach.implementation_prompt(snout)
    artifact = teach.import_implementation(
        snout, python_component(spec.plugin_id, "snout",
                                capability=spec.provides[0], role="snout"))
    teach.trust_artifact(artifact.id)
    assert teach.validate_artifact(artifact.id).ok
    assert teach.accept_artifact(artifact.id).ok

    if with_asset:
        horn = "dragon.head.horn"
        glb = write_part_glb(tmp_path / "assets")
        teach.supply_asset(horn, glb)
        hspec = teach.spec(horn)
        teach.implementation_prompt(horn)
        hart = teach.import_implementation(
            horn, data_component(hspec.plugin_id, "horn",
                                 capability=hspec.provides[0], mesh=glb.name))
        assert teach.validate_artifact(hart.id).ok
        teach.accept_artifact(hart.id)

    head = teach.emit_composite("dragon.head")
    assert head["ok"], head
    root = teach.emit_composite()
    assert root["ok"], root
    return teach.finish()


def test_the_whole_cycle_ends_with_a_learned_concept(dragon, tmp_path):
    report = learn_the_dragon(dragon, tmp_path)
    assert report.learned, report.describe()
    assert dragon.project.completion == LEARNED
    assert dragon.project.root_component == "dragon_pack:dragon"
    assert report.triangles > 0
    for _, ok in report.rows():
        assert ok


def test_every_mandatory_node_is_green_and_the_optional_ones_do_not_block(dragon,
                                                                          tmp_path):
    learn_the_dragon(dragon, tmp_path)
    progress = dragon.progress()
    assert progress.mandatory_validated == progress.mandatory_total
    assert progress.mandatory_percent == pytest.approx(100.0)
    # un optional rosso non blocca: il concetto e' LEARNED con un nodo MISSING
    assert dragon.project.coverage_of("dragon.head.tooth") == MISSING
    assert dragon.project.completion == LEARNED
    assert dragon.summary()["counts"][MISSING] == 1


def test_the_counts_are_satisfied_in_the_root_composite(dragon, tmp_path):
    learn_the_dragon(dragon, tmp_path)
    registry = dragon.session.catalog()
    from app.core.component import BuildContext

    component = registry.component("dragon_pack:dragon")
    values = {k: s.default for k, s in component.params.items() if not s.derived}
    children = component.children(values, BuildContext(detail_level=2))
    refs = [c.component for c in children]
    assert refs.count("fantasy:wing") == 2
    assert refs.count("humanoid:leg") == 4
    assert refs.count("fish:tail") == 1
    head = registry.component("dragon_head:head")
    head_children = head.children({}, BuildContext(detail_level=2))
    assert [c.component for c in head_children].count("creature:bulging_eye") == 2


def test_the_root_composite_carries_no_mesh_of_its_own(dragon, tmp_path):
    learn_the_dragon(dragon, tmp_path)
    folder = tmp_path / "library" / "dragon_pack"
    assert folder.is_dir()
    assert not list(folder.rglob("*.glb"))
    assert not list(folder.rglob("*.py"))
    definition = (folder / "components" / "dragon.json").read_text(
        encoding="utf-8")
    assert '"mesh"' not in definition
    assert '"children"' in definition


def test_a_normal_session_finds_and_builds_the_learned_concept(dragon, tmp_path):
    """§38, la prova finale: fuori da Teach, con il planner locale."""
    learn_the_dragon(dragon, tmp_path)
    session = dragon.session

    shortlist = session.shortlist("dragon")
    assert "dragon_pack:dragon" in shortlist.ids
    assert shortlist.ids[0] == "dragon_pack:dragon"

    result = session.generate("a cartoon dragon", Options(detail_level=2))
    assert result.ok
    assert result.plan_json["root"]["ref"] == "dragon_pack:dragon"
    assert result.triangles > 0

    concept = session.build({"version": "1.3", "style": "low_poly",
                             "detail_level": 2,
                             "concept": {"requested": "dragon"}},
                            Options(detail_level=2))
    assert concept.ok
    assert concept.triangles > 0


def test_the_learned_concept_exports_like_any_other_model(dragon, tmp_path):
    learn_the_dragon(dragon, tmp_path)
    session = dragon.session
    result = session.generate("a cartoon dragon", Options(detail_level=2))
    assert result.ok
    target = session.export(tmp_path / "dragon.glb")
    assert target.is_file() and target.read_bytes()[:4] == b"glTF"


def test_finishing_early_stays_learning_and_says_what_is_missing(dragon):
    report = dragon.finish()
    assert not report.learned
    assert dragon.project.completion == LEARNING
    assert report.missing
    assert "TEACH_ROOT_NOT_INSTALLED" in report.report.codes()
    assert "-> LEARNING" in report.describe()


def test_a_composite_cannot_be_emitted_while_a_child_is_not_validated(dragon):
    with pytest.raises(TeachError) as exc:
        dragon.emit_composite()
    assert exc.value.code == codes.NO_SOLUTION
    assert "non validati" in exc.value.message


# --------------------------------------------------------------------------- #
# Persistenza a metà (§44) e riproducibilita' (§45)
# --------------------------------------------------------------------------- #
def test_closing_halfway_and_reopening_keeps_everything(dragon, tmp_path):
    node = "dragon.head.eye"
    eye = dragon.candidates(node)[0].component_id
    dragon.suitability_prompt(node, eye)
    dragon.import_suitability(node, suitable_with_parameters({"size": 0.12}),
                              component_id=eye)
    dragon.apply_suggestion(node, eye)
    dragon.save_variant(node, "dragon_eye", component_id=eye)
    for proxy in PROXY_NODES:
        dragon.accept_candidate(proxy, dragon.candidates(proxy)[0].component_id)
    snout = "dragon.head.snout"
    for candidate in list(dragon.candidates(snout)):
        dragon.reject_candidate(snout, candidate.component_id)
    spec = dragon.spec(snout)
    dragon.implementation_prompt(snout)
    artifact = dragon.import_implementation(
        snout, python_component(spec.plugin_id, "snout",
                                capability=spec.provides[0]))
    before = dragon.progress()
    assert 0.0 < before.mandatory_percent < 100.0

    saved = dragon.save_project(tmp_path / "halfway")

    from app.teach import TeachService

    again = TeachService(session=dragon.session,
                         knowledge=TeachKnowledge(),
                         staging_root=tmp_path / "teach-staging")
    try:
        project = again.load_project(saved)
        assert project.concept == "dragon"
        assert again.progress().mandatory_percent == pytest.approx(
            before.mandatory_percent)
        assert project.coverage_of(node) == VALIDATED
        assert project.state(node).solution.recipe == "dragon_eye"
        assert project.variant("dragon_eye").params == {"size": 0.12}
        assert project.coverage_of(snout) == MISSING
        assert project.state(snout).attempts
        assert [e.kind for e in project.exchanges].count("implementation") == 1
        assert project.exchanges[-1].response
        # l'artefatto generato si ritrova dal disco, con la sua fiducia a falso
        recovered = again.artifact(artifact.id)
        assert recovered.trusted is False
        assert recovered.component_id == spec.component_id
        assert [f.path for f in recovered.files] == [f.path
                                                     for f in artifact.files]
    finally:
        again.close()


def test_an_artifact_whose_folder_vanished_stays_a_record(dragon, tmp_path):
    snout = "dragon.head.snout"
    for candidate in list(dragon.candidates(snout)):
        dragon.reject_candidate(snout, candidate.component_id)
    spec = dragon.spec(snout)
    dragon.implementation_prompt(snout)
    artifact = dragon.import_implementation(
        snout, python_component(spec.plugin_id, "snout",
                                capability=spec.provides[0]))
    saved = dragon.save_project(tmp_path / "p")
    import shutil

    shutil.rmtree(artifact.container)
    project = TeachProject.load(saved)
    record = project.artifact(artifact.id)
    assert record is not None and not record.available


def test_a_plugin_that_changed_after_the_teach_is_detected(dragon):
    """§45: non si duplicano i plugin, si registra la loro identita'."""
    dragon.accept_candidate("dragon.tail", "fish:tail")
    assert dragon.changed_components() == []
    dragon.project.fingerprints["fish"] = "0.0.1#deadbeef"
    changed = dragon.changed_components()
    assert len(changed) == 1
    assert changed[0]["ref"] == "fish:tail"
    assert changed[0]["change"] == "PLUGIN_VERSION_CHANGED"


def test_the_project_records_fingerprints_and_not_copies(dragon):
    project = dragon.project
    assert project.fingerprints
    for value in project.fingerprints.values():
        assert "#" in value
    assert len(project.to_dict()["fingerprints"]) == len(project.fingerprints)


# --------------------------------------------------------------------------- #
# §39: riuso della conoscenza
# --------------------------------------------------------------------------- #
WYVERN = {
    "concept": "wyvern",
    "description": "a two-legged winged dragon",
    "root": {"name": "wyvern", "role": "creature", "mandatory": True,
             "count": 1, "importance": 1.0, "detail_level": 1,
             "children": [
                 {"name": "body", "role": "body", "mandatory": True,
                  "count": 1, "importance": 1.0, "detail_level": 1},
                 {"name": "head", "role": "head", "mandatory": True,
                  "count": 1, "importance": 0.9, "detail_level": 1,
                  "children": [{"name": "eye", "role": "eye",
                                "mandatory": True, "count": 2,
                                "importance": 0.6, "detail_level": 2}]},
                 {"name": "wing", "role": "wing", "mandatory": True,
                  "count": 2, "importance": 0.9, "detail_level": 1},
                 {"name": "leg", "role": "leg", "mandatory": True, "count": 2,
                  "importance": 0.8, "detail_level": 1},
                 {"name": "tail", "role": "tail", "mandatory": True,
                  "count": 1, "importance": 0.7, "detail_level": 1}]}}


def test_a_second_concept_reuses_what_the_first_one_taught(dragon, tmp_path):
    learn_the_dragon(dragon, tmp_path)
    store_path = dragon.export_knowledge(tmp_path / "knowledge.json")
    assert store_path.is_file()

    from app.teach import TeachService

    second = TeachService(session=dragon.session,
                          knowledge=TeachKnowledge.load(store_path),
                          staging_root=tmp_path / "teach-staging-2")
    try:
        second.create_project("wyvern", description="a two-legged winged dragon",
                              detail_target=2,
                              destination=str(tmp_path / "library2"))
        second.decomposition_prompt()
        second.import_decomposition(WYVERN)
        second.analyse()

        found = {row["id"]: row["coverage"] for row in second.tree()}
        # ogni parte parte da un candidato, non da zero
        for node in ("wyvern.body", "wyvern.head", "wyvern.head.eye",
                     "wyvern.wing", "wyvern.leg", "wyvern.tail"):
            assert found[node] == CANDIDATE, (node, found[node])
        # e la radice trova il composite del drago, perche' e' un soggetto
        assert "dragon_pack:dragon" in [
            c.component_id for c in second.candidates("wyvern")]

        from app.teach import coverage as cov

        for node in ("wyvern.head.eye", "wyvern.wing", "wyvern.tail"):
            best = second.project.state(node).best
            assert cov.PRIOR_VALIDATION in best.kinds, node
        # ma nessuna parte e' verde: un giudizio su un drago non e' un
        # giudizio su un wyvern
        assert all(v != VALIDATED for v in found.values())
    finally:
        second.close()


def test_the_knowledge_store_points_at_components_and_carries_its_recipes(dragon,
                                                                          tmp_path):
    learn_the_dragon(dragon, tmp_path)
    store_path = dragon.export_knowledge(tmp_path / "knowledge.json")
    store = TeachKnowledge.load(store_path)
    assert store.variant("dragon_eye") is not None
    components = store.components()
    assert "fish:tail" in components
    # i componenti generati da **questo** Teach non diventano validazioni
    # riusabili: li trova il retrieval come qualunque altro componente
    assert not any(c.startswith("dragon_") for c in components)


def test_the_cycle_never_runs_in_the_background():
    """§36: ogni passo e' una chiamata che ritorna."""
    source = pathlib.Path("app/teach/service.py").read_text(encoding="utf-8")
    for word in ("threading", "asyncio", "Thread(", "QThread", "Timer(",
                 "multiprocessing", "schedule"):
        assert word not in source


def test_the_teach_layer_imports_no_qt():
    for path in pathlib.Path("app/teach").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "PySide6" not in source
        assert "QtWidgets" not in source


def test_a_whole_concept_can_be_taught_without_any_user_interface(teach,
                                                                  tmp_path):
    """§40 dal lato opposto: la finestra non e' la via, e questo lo prova."""
    teach.create_project("dragon", style_target="cartoon low-poly",
                         detail_target=2, destination=str(tmp_path / "library"))
    teach.decomposition_prompt()
    teach.import_decomposition(dragon_decomposition())
    teach.refinement_prompt()
    teach.import_refinement(dragon_refinement())
    teach.analyse()
    report = learn_the_dragon(teach, tmp_path)
    assert report.learned
    assert teach.session.shortlist("dragon").ids[0] == "dragon_pack:dragon"


# --------------------------------------------------------------------------- #
# §43: l'utente puo' sovrascrivere ogni decisione
# --------------------------------------------------------------------------- #
def test_a_validated_node_can_be_pushed_back_to_candidate(dragon):
    node = "dragon.tail"
    dragon.accept_candidate(node, "fish:tail")
    assert dragon.project.coverage_of(node) == VALIDATED
    dragon.set_coverage(node, CANDIDATE)
    assert dragon.project.coverage_of(node) == CANDIDATE
    assert dragon.project.state(node).solution is None
    dragon.analyse()
    assert dragon.project.coverage_of(node) == CANDIDATE   # la decisione resta


def test_every_state_can_be_forced_by_hand(dragon):
    node = "dragon.wing"
    for value in (CANDIDATE, PROXY, MISSING):
        dragon.set_coverage(node, value)
        assert dragon.project.coverage_of(node) == value
    dragon.accept_candidate(node, dragon.candidates(node)[0].component_id)
    assert dragon.project.coverage_of(node) == VALIDATED


def test_a_component_nobody_proposed_can_still_be_chosen(dragon):
    """§43: «choose another component», non «uno fra quelli offerti»."""
    node = "dragon.tail"
    offered = [c.component_id for c in dragon.candidates(node)]
    assert "weapon:sword" not in offered
    dragon.choose_candidate(node, "weapon:sword")
    assert dragon.candidates(node)[0].component_id == "weapon:sword"
    dragon.accept_candidate(node)
    assert dragon.project.state(node).solution.ref == "weapon:sword"


def test_choosing_a_component_that_is_not_installed_is_refused(dragon):
    with pytest.raises(TeachError) as exc:
        dragon.choose_candidate("dragon.tail", "nope:nope")
    assert exc.value.code == codes.UNKNOWN_COMPONENT


def test_the_lab_never_modifies_the_library(dragon):
    """Il laboratorio di V6, invariato: costruisce piani, non tocca il registry."""
    node = "dragon.head.eye"
    component = dragon.candidates(node)[0].component_id
    lab = dragon.lab(node, component)
    defaults = dict(lab.defaults())
    before = lab.build().extents()
    lab.randomize(seed=3)
    lab.reset()
    assert lab.build().extents() == before
    assert lab.defaults() == defaults
    registry = dragon.session.catalog()
    assert registry.frozen
