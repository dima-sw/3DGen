"""La finestra di Teach: un cliente sottile, e lo si misura.

Il test che tiene insieme questo file e' l'ultimo:
`test_the_window_holds_no_teach_logic` legge `app/ui/teach_window.py` **per
token** e verifica che non contenga la logica del livello. E' lo stesso test
che V6 ha scritto per l'authoring, e serve alla stessa cosa: se un test della
finestra passasse e il test del servizio no, la finestra starebbe mentendo.

Tutto il resto verifica che ogni tabella **rispecchi il servizio** e che ogni
bottone chiami un metodo: una finestra che calcola qualcosa da sola e' una
seconda strada, e la seconda e' quella che nessuno puo' chiamare.
"""
from __future__ import annotations

import io
import pathlib
import tokenize

import pytest

from app.teach.model import (CANDIDATE, COVERAGE, LEARNED, MISSING, PROXY,
                             VALIDATED)
from tests.teach_fixtures import (data_component, dragon_decomposition,
                                  dragon_refinement, python_component,
                                  suitable_with_parameters, write_part_glb)

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def app():
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from app.ui.viewport import configure_opengl

    configure_opengl()
    existing = QApplication.instance()
    return existing if existing is not None else QApplication([])


@pytest.fixture
def window(app, teach_session, tmp_path):
    from app.ui.teach_window import TeachWindow

    widget = TeachWindow(session=teach_session)
    widget.service.close()
    widget.service._staging_root = tmp_path / "staging"
    widget.service._owned_staging = False
    widget.in_concept.setText("dragon")
    widget.in_description.setText("a large winged reptile")
    widget.in_style_target.setText("cartoon low-poly")
    widget.in_destination.setText(str(tmp_path / "library"))
    widget.on_new_project()
    try:
        yield widget
    finally:
        widget.service.close()
        widget.close()


@pytest.fixture
def analysed(window):
    window.on_decomposition_prompt()
    window.response_view.setPlainText(__import__("json").dumps(
        dragon_decomposition()))
    window.on_import_response()
    window.on_refinement_prompt()
    window.response_view.setPlainText(__import__("json").dumps(
        dragon_refinement()))
    window.on_import_response()
    window.on_analyze()
    return window


def _select_node(window, node_id: str) -> None:
    from PySide6.QtCore import Qt

    def walk(item):
        yield item
        for index in range(item.childCount()):
            yield from walk(item.child(index))

    for top in range(window.tree.topLevelItemCount()):
        for item in walk(window.tree.topLevelItem(top)):
            if item.data(0, Qt.ItemDataRole.UserRole) == node_id:
                window.tree.setCurrentItem(item)
                return
    raise AssertionError("nodo %r non nell'albero" % node_id)


def _select_row(table, value: str, column: int = 0) -> None:
    for row in range(table.rowCount()):
        item = table.item(row, column)
        if item is not None and item.text() == value:
            table.selectRow(row)
            return
    raise AssertionError("riga %r non nella tabella" % value)


# --------------------------------------------------------------------------- #
# Il flusso
# --------------------------------------------------------------------------- #
def test_the_declared_flow_is_five_pages(window):
    titles = [window.tabs.tabText(i) for i in range(window.tabs.count())]
    assert titles == ["1. Concept", "2. Hierarchy", "3. Candidates",
                      "4. Generate", "5. Complete"]


def test_a_new_project_reaches_the_service(window):
    assert window.service.project.concept == "dragon"
    assert window.service.project.style_target == "cartoon low-poly"
    assert window.service.project.detail_target == 2


def test_the_two_modes_are_offered_and_the_prompt_is_one_object(window):
    modes = [window.cmb_mode.itemText(i)
             for i in range(window.cmb_mode.count())]
    assert modes == ["External / Manual", "Provider configurato"]
    window.on_decomposition_prompt()
    assert window._bundle is not None
    assert window.prompt_view.toPlainText() == window._bundle.text
    assert "decomposition" in window.lbl_prompt.text()


def test_importing_a_response_without_a_prompt_is_a_status_line(window):
    window.response_view.setPlainText("{}")
    window.on_import_response()
    assert "genera prima un prompt" in window.status.text()


def test_a_refused_response_becomes_a_status_line_and_not_a_traceback(window):
    window.on_decomposition_prompt()
    window.response_view.setPlainText("{not json")
    window.on_import_response()
    assert "TEACH_RESPONSE_INVALID" in window.status.text()
    assert window.service.project.root is None


def test_the_exchange_table_mirrors_the_service(analysed):
    rows = analysed.service.exchanges()
    assert analysed.exchanges_table.rowCount() == len(rows)
    kinds = [analysed.exchanges_table.item(i, 0).text()
             for i in range(analysed.exchanges_table.rowCount())]
    assert kinds == [row["kind"] for row in rows]
    assert analysed.exchanges_table.item(0, 3).text() == "importata"


# --------------------------------------------------------------------------- #
# L'albero e i colori (§40, §41)
# --------------------------------------------------------------------------- #
def test_the_tree_mirrors_the_service_with_the_four_states(analysed):
    rows = analysed.service.tree()
    found = []

    def walk(item):
        found.append(item)
        for index in range(item.childCount()):
            walk(item.child(index))

    for top in range(analysed.tree.topLevelItemCount()):
        walk(analysed.tree.topLevelItem(top))
    assert len(found) == len(rows)
    states = {item.text(1).split()[-1] for item in found}
    assert states <= set(COVERAGE)
    assert {MISSING, CANDIDATE, PROXY} <= states
    assert VALIDATED not in states


def test_the_counts_shown_and_the_bar_come_from_the_service(analysed):
    data = analysed.service.summary()
    assert analysed.bar.value() == int(data["mandatory_percent"])
    assert "mandatory" in analysed.lbl_progress.text()
    for state in COVERAGE:
        assert state in analysed.lbl_counts.text()
    assert analysed.lbl_completion.text() == data["completion"]


def test_green_never_appears_because_a_score_is_high(analysed):
    """§41: il verde e' una soluzione confermata, non un punteggio."""
    for row in analysed.service.tree():
        if row["coverage"] == VALIDATED:
            raise AssertionError("nulla dovrebbe essere verde dopo un'analisi")
    assert analysed.service.candidates("dragon.head")[0].score > 0.5


def test_choosing_a_node_fills_the_form_from_the_service(analysed):
    _select_node(analysed, "dragon.head.eye")
    detail = analysed.service.node_detail("dragon.head.eye")
    assert analysed.in_node_name.text() == detail["name"]
    assert analysed.in_node_role.text() == detail["role"]
    assert analysed.spin_count.value() == detail["count"]
    assert analysed.chk_mandatory.isChecked() is detail["mandatory"]


def test_editing_a_node_from_the_form_reaches_the_service(analysed):
    _select_node(analysed, "dragon.head.eye")
    analysed.spin_count.setValue(3)
    analysed.chk_mandatory.setChecked(False)
    analysed.on_apply_node()
    node = analysed.service.project.require_node("dragon.head.eye")
    assert node.count == 3 and node.mandatory is False


def test_forcing_a_state_from_the_combo_reaches_the_service(analysed):
    _select_node(analysed, "dragon.head")
    index = analysed.cmb_coverage.findText(PROXY)
    analysed.cmb_coverage.setCurrentIndex(index)
    analysed.on_force_coverage()
    assert analysed.service.project.coverage_of("dragon.head") == PROXY
    assert analysed.service.project.state("dragon.head").locked


def test_forcing_green_without_a_solution_is_refused_as_a_status_line(analysed):
    _select_node(analysed, "dragon.head")
    analysed.cmb_coverage.setCurrentIndex(analysed.cmb_coverage.findText(VALIDATED))
    analysed.on_force_coverage()
    assert "TEACH_NO_SOLUTION" in analysed.status.text()
    assert analysed.service.project.coverage_of("dragon.head") != VALIDATED


def test_adding_and_removing_a_node_reaches_the_service(analysed):
    _select_node(analysed, "dragon.head")
    analysed.in_node_name.setText("brow")
    analysed.on_add_node()
    assert analysed.service.project.node("dragon.head.brow") is not None
    _select_node(analysed, "dragon.head.brow")
    analysed.on_remove_node()
    assert analysed.service.project.node("dragon.head.brow") is None


# --------------------------------------------------------------------------- #
# I candidati (§12, §13, §16)
# --------------------------------------------------------------------------- #
def test_the_candidate_table_mirrors_the_service(analysed):
    _select_node(analysed, "dragon.head.eye")
    candidates = analysed.service.candidates("dragon.head.eye")
    assert analysed.candidates_table.rowCount() == len(candidates)
    assert analysed.candidates_table.item(0, 0).text() == candidates[0].component_id
    assert analysed.candidates_table.item(0, 2).text() == candidates[0].verdict
    assert analysed.candidates_table.item(0, 3).text()


def test_choosing_a_candidate_shows_the_real_dossier(analysed):
    _select_node(analysed, "dragon.head.eye")
    component = analysed.service.candidates("dragon.head.eye")[0].component_id
    _select_row(analysed.candidates_table, component)
    text = analysed.dossier_view.toPlainText()
    assert text == analysed.service.dossier("dragon.head.eye", component)
    assert "WHY 3DGEN PROPOSED IT" in text


def test_validate_with_ai_generates_the_prompt_the_service_builds(analysed):
    _select_node(analysed, "dragon.head.eye")
    component = analysed.service.candidates("dragon.head.eye")[0].component_id
    _select_row(analysed.candidates_table, component)
    analysed.on_suitability_prompt()
    assert analysed._bundle.kind == "suitability"
    assert analysed._bundle.node == "dragon.head.eye"
    assert "SUITABLE_WITH_PARAMETERS" in analysed.prompt_view.toPlainText()


def test_the_yellow_to_green_flow_works_from_the_window(analysed):
    _select_node(analysed, "dragon.head.eye")
    component = analysed.service.candidates("dragon.head.eye")[0].component_id
    _select_row(analysed.candidates_table, component)
    analysed.on_suitability_prompt()
    analysed.response_view.setPlainText(__import__("json").dumps(
        suitable_with_parameters({"size": 0.12})))
    analysed.on_import_response()
    assert analysed.service.project.coverage_of("dragon.head.eye") == CANDIDATE

    _select_node(analysed, "dragon.head.eye")
    _select_row(analysed.candidates_table, component)
    analysed.on_apply_suggestion()
    assert "triangoli" in analysed.status.text()
    analysed.in_variant.setText("dragon_eye")
    analysed.on_save_variant()
    assert analysed.service.project.coverage_of("dragon.head.eye") == VALIDATED
    assert analysed.service.project.variant("dragon_eye") is not None


def test_this_works_and_reject_reach_the_service(analysed):
    _select_node(analysed, "dragon.tail")
    component = analysed.service.candidates("dragon.tail")[0].component_id
    _select_row(analysed.candidates_table, component)
    analysed.on_accept_candidate()
    assert analysed.service.project.coverage_of("dragon.tail") == VALIDATED

    _select_node(analysed, "dragon.wing")
    first = analysed.service.candidates("dragon.wing")[0].component_id
    _select_row(analysed.candidates_table, first)
    analysed.on_reject_candidate()
    assert first not in [c.component_id
                         for c in analysed.service.candidates("dragon.wing")]


def test_the_component_lab_opens_on_the_chosen_candidate(analysed):
    from app.ui.authoring_window import ComponentLabDialog

    _select_node(analysed, "dragon.head.eye")
    component = analysed.service.candidates("dragon.head.eye")[0].component_id
    _select_row(analysed.candidates_table, component)
    dialog = analysed.on_open_lab()
    assert isinstance(dialog, ComponentLabDialog)
    assert dialog.lab.component_id == component
    dialog.close()


# --------------------------------------------------------------------------- #
# La generazione (§21-§35)
# --------------------------------------------------------------------------- #
def test_the_queue_table_mirrors_the_service(analysed):
    nodes = analysed.service.queue()
    assert analysed.queue_table.rowCount() == len(nodes)
    assert analysed.queue_table.item(0, 0).text() == nodes[0].id
    assert analysed.queue_table.item(0, 3).text()


def test_the_spec_panel_shows_the_technical_specification(analysed):
    _select_node(analysed, "dragon.head.snout")
    for candidate in list(analysed.service.candidates("dragon.head.snout")):
        analysed.service.reject_candidate("dragon.head.snout",
                                          candidate.component_id)
    _select_node(analysed, "dragon.head")       # forza un cambio di selezione
    _select_node(analysed, "dragon.head.snout")
    text = analysed.spec_view.toPlainText()
    assert "dragon_snout:snout" in text
    assert "triangle_budget" in text
    assert "backend" in text


def test_only_the_installed_backends_are_offered(analysed):
    offered = [analysed.cmb_backend.itemText(i)
               for i in range(analysed.cmb_backend.count())]
    assert offered == ["procedural_python", "data_mesh", "composite"]


def test_setting_a_backend_from_the_combo_reaches_the_service(analysed):
    _select_node(analysed, "dragon.head.snout")
    analysed.cmb_backend.setCurrentIndex(
        analysed.cmb_backend.findText("data_mesh"))
    analysed.on_set_backend()
    assert analysed.service.project.state("dragon.head.snout").backend \
        == "data_mesh"


def test_the_whole_generation_flow_works_from_the_window(analysed):
    node = "dragon.head.snout"
    for candidate in list(analysed.service.candidates(node)):
        analysed.service.reject_candidate(node, candidate.component_id)
    analysed.refresh_all()
    _select_node(analysed, node)
    analysed.on_implementation_prompt()
    assert analysed._bundle.kind == "implementation"

    spec = analysed.service.spec(node)
    analysed.response_view.setPlainText(__import__("json").dumps(
        python_component(spec.plugin_id, "snout",
                         capability=spec.provides[0], role="snout")))
    analysed.on_import_response()
    assert analysed.artifacts_table.rowCount() == 1
    artifact_id = analysed.artifacts_table.item(0, 0).text()
    assert analysed.artifacts_table.item(0, 4).text() == "non fidato"

    _select_row(analysed.artifacts_table, artifact_id)
    inspection = analysed.inspection_view.toPlainText()
    assert "contiene Python: si" in inspection
    assert "fidato: no" in inspection
    assert "SICUREZZA" in inspection
    assert "components/snout.py" in inspection
    assert "def build_snout" in inspection       # il sorgente, prima della fiducia

    analysed.on_validate_artifact()
    assert "TEACH_TRUST_REQUIRED" in analysed.status.text()

    analysed.service.trust_artifact(artifact_id)
    analysed.on_validate_artifact()
    assert "ok" in analysed.status.text()
    assert analysed.validation_table.rowCount() >= 0

    analysed.on_accept_artifact()
    assert analysed.service.project.coverage_of(node) == VALIDATED


def test_trusting_from_the_window_asks_first(analysed, monkeypatch):
    """Un'azione esplicita, e la finestra spiega che cosa concede."""
    from PySide6.QtWidgets import QMessageBox

    node = "dragon.head.snout"
    for candidate in list(analysed.service.candidates(node)):
        analysed.service.reject_candidate(node, candidate.component_id)
    analysed.refresh_all()
    _select_node(analysed, node)
    analysed.on_implementation_prompt()
    spec = analysed.service.spec(node)
    analysed.response_view.setPlainText(__import__("json").dumps(
        python_component(spec.plugin_id, "snout", capability=spec.provides[0])))
    analysed.on_import_response()
    artifact_id = analysed.artifacts_table.item(0, 0).text()
    _select_row(analysed.artifacts_table, artifact_id)

    asked = {}

    def refuse(_parent, _title, text):
        asked["text"] = text
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", staticmethod(refuse))
    analysed.on_trust()
    assert "non sono una sandbox" in asked["text"]
    assert analysed.service.artifact(artifact_id).trusted is False


def test_the_repair_prompt_can_be_generated_from_the_window(analysed):
    node = "dragon.head.snout"
    for candidate in list(analysed.service.candidates(node)):
        analysed.service.reject_candidate(node, candidate.component_id)
    analysed.refresh_all()
    _select_node(analysed, node)
    analysed.on_implementation_prompt()
    spec = analysed.service.spec(node)
    analysed.response_view.setPlainText(__import__("json").dumps(
        python_component(spec.plugin_id, "snout", capability=spec.provides[0],
                         broken=True)))
    analysed.on_import_response()
    artifact_id = analysed.artifacts_table.item(0, 0).text()
    _select_row(analysed.artifacts_table, artifact_id)
    analysed.service.trust_artifact(artifact_id)
    analysed.on_validate_artifact()
    analysed.on_repair_prompt()
    assert analysed._bundle.kind == "repair"
    assert "WHAT THE VALIDATORS SAID" in analysed.prompt_view.toPlainText()


# --------------------------------------------------------------------------- #
# Il completamento
# --------------------------------------------------------------------------- #
def test_the_completion_table_mirrors_the_report(analysed):
    report = analysed.service.completion_report()
    assert analysed.completion_table.rowCount() == len(report.rows()) + 1
    assert analysed.completion_table.item(0, 1).text() == "no"
    assert analysed.completion_table.item(len(report.rows()), 0).text() == "mancano"


def test_the_next_step_button_reads_the_service(analysed):
    analysed.on_advance()
    step = analysed.service.advance()
    assert step["action"] in analysed.status.text()


def test_marking_as_learned_early_says_what_is_missing(analysed):
    analysed.on_finish()
    assert "LEARNING" in analysed.status.text()
    assert analysed.service.project.completion != LEARNED


def test_the_window_can_save_and_reopen_a_project(analysed, tmp_path,
                                                   monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    target = tmp_path / "dragon.teach3d"
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(target), "")))
    analysed.on_save_project()
    assert target.is_file()
    assert "salvato" in analysed.status.text()

    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (str(target), "")))
    analysed.on_load_project()
    assert analysed.service.project.concept == "dragon"
    assert analysed.tree.topLevelItemCount() == 1


def test_asking_a_provider_that_is_not_there_is_a_status_line(analysed):
    analysed.on_decomposition_prompt()
    analysed.on_ask_provider()
    assert "TEACH_PROVIDER_FAILED" in analysed.status.text()
    assert "modalita' esterna" in analysed.status.text()


# --------------------------------------------------------------------------- #
# La finestra non contiene logica
# --------------------------------------------------------------------------- #
def test_the_window_holds_no_teach_logic():
    """Letto per token: la finestra chiama, non decide.

    Gli stessi nomi che V6 cerca in `authoring_window.py`, piu' quelli del
    livello Teach. Un `candidates_for` o un `build_spec` qui vorrebbero dire
    due strade per decidere una copertura, e la seconda e' quella che un tool a
    riga di comando non puo' chiamare.
    """
    source = pathlib.Path("app/ui/teach_window.py").read_text(encoding="utf-8")
    names = {token.string for token in
             tokenize.generate_tokens(io.StringIO(source).readline)
             if token.type == tokenize.NAME}
    # `analyse` non e' nell'elenco: e' il **nome del metodo del servizio**
    # che la finestra chiama, non la funzione del motore. Che la finestra
    # importi solo la faccia pubblica del livello lo fissa il test successivo.
    forbidden = {"TeachProject", "TeachNode", "build_tree",
                 "candidates_for", "evidence_for", "verdict_for", "build_spec",
                 "recommend_backend", "build_queue", "next_buildable",
                 "parse_envelope", "inspect_python", "validate_artifact_files",
                 "emit_plugin", "load_component", "Registry", "Session_",
                 "AuthoringService", "VariantRecipe", "TeachKnowledge",
                 "KnowledgeRecord", "json", "trimesh", "np", "numpy",
                 "ComponentLab", "prompts", "staging", "coverage_module"}
    assert not (names & forbidden), sorted(names & forbidden)


def test_the_window_only_imports_the_public_face_of_the_layer():
    source = pathlib.Path("app/ui/teach_window.py").read_text(encoding="utf-8")
    imported = [line for line in source.splitlines()
                if line.startswith("from app.teach")]
    assert imported == ["from app.teach import BACKENDS, COVERAGE, TeachError, "
                        "TeachService"]


def test_the_main_window_opens_teach_on_the_same_session(app, teach_session):
    from app.ui.main_window import MainWindow
    from app.ui.teach_window import TeachWindow

    main = MainWindow()
    try:
        actions = [a.text() for a in main.findChildren(type(main.act_undo))]
        assert "Teach" in actions
        teach = main.on_open_teach()
        assert isinstance(teach, TeachWindow)
        # la **stessa** sessione: un componente imparato e' subito generabile
        assert teach.service.session is main.session
        assert main.on_open_teach() is teach
        teach.service.close()
    finally:
        main.close()
