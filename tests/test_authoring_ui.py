"""La finestra di authoring parla la lingua del servizio, e niente altro.

Non e' un test di grafica e non prova i bottoni uno per uno: verifica la cosa
che si rompe davvero, cioe' che la UI resti un **cliente** di
`AuthoringService`. Se un giorno un pannello cominciasse a decidere qualcosa da
solo, questi assert lo direbbero — perche' confrontano cio' che la finestra
mostra con cio' che il servizio risponde.

Gira senza schermo (`QT_QPA_PLATFORM=offscreen`) e senza rete.
"""
from __future__ import annotations

import io
import os
import tokenize
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="l'interfaccia e' facoltativa")

from PySide6.QtCore import Qt                        # noqa: E402
from PySide6.QtWidgets import QApplication           # noqa: E402

from app.ai.provider import OfflineProvider          # noqa: E402
from app.core.session import Session                 # noqa: E402
from tests.authoring_fixtures import write_knight_glb  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def window(app, tmp_path):
    from app.ui.authoring_window import AuthoringWindow

    session = Session(provider=OfflineProvider())
    w = AuthoringWindow(session=session)
    w.service.project.destination = str(tmp_path / "plugins")
    yield w
    w.close()


@pytest.fixture()
def loaded(window, tmp_path):
    """Una finestra con un GLB importato e i tre componenti del cavaliere."""
    from tests.test_authoring import knight_project

    window.service.import_model(write_knight_glb(tmp_path / "source"))
    keys = knight_project(window.service)
    window.refresh_all()
    return window, keys


# --------------------------------------------------------------------------- #
# Si apre, e il flusso e' quello dichiarato
# --------------------------------------------------------------------------- #
def test_the_window_opens_on_the_declared_flow(window):
    labels = [window.tabs.tabText(i) for i in range(window.tabs.count())]

    assert labels == ["1. Import", "2. Components", "3. Hierarchy",
                      "4. Sockets", "5. Variability", "6. Validate",
                      "7. Save / Install"]
    assert "Authoring" in window.windowTitle()


def test_the_context_bar_answers_the_four_questions(loaded):
    window, keys = loaded
    window.on_component_chosen(_item_for(window.components_list, keys["head"]))

    assert "head" in window.lbl_component.text()
    assert "3 oggetti" in window.lbl_geometry.text()
    assert "my_plugin" in window.lbl_destination.text()
    assert "validita'" in window.lbl_valid.text()

    window.on_component_chosen(_item_for(window.components_list, keys["root"]))
    assert "composite" in window.lbl_geometry.text()


def test_the_object_table_shows_what_the_service_imported(loaded):
    window, _keys = loaded
    objects = window.service.scene_objects()

    assert window.objects_table.rowCount() == len(objects) == 5
    names = [window.objects_table.item(r, 0).text()
             for r in range(window.objects_table.rowCount())]
    assert names == [o.name for o in objects]
    assert window.objects_table.item(0, 1).text() == "12"


def test_selecting_rows_in_the_table_selects_in_the_service(loaded):
    window, _keys = loaded
    window.objects_table.clearSelection()
    window.objects_table.selectRow(4)        # Sword, l'unico senza componente
    window.on_objects_selected()

    assert [o.name for o in window.service.selection()] == ["Sword"]


def test_creating_a_component_from_the_form_goes_through_the_service(loaded):
    window, _keys = loaded
    window.objects_table.clearSelection()
    window.objects_table.selectRow(4)
    window.on_objects_selected()
    window.in_name.setText("sword")
    window.in_role.setText("weapon")
    window.in_description.setText("A knight sword")
    window.in_provides.setText("limb_mount")
    window.on_create_component()

    draft = window.service.project.component_by_name("sword")
    assert draft is not None
    assert draft.role == "weapon"
    assert draft.provides == ("limb_mount",)
    assert draft.objects == ("knight/Sword",)
    assert window.service.project.current == draft.key


def test_a_refused_operation_becomes_a_status_line_not_a_traceback(window):
    window.in_name.setText("Not A Name")
    window.on_create_component()

    assert "AUTHORING_NAME_INVALID" in window.status.text()
    assert window.service.project.components == []


def test_the_hierarchy_tree_mirrors_the_service(loaded):
    window, _keys = loaded
    rows = window.service.hierarchy()
    tree = window.hierarchy_tree

    assert tree.topLevelItemCount() == 1
    root = tree.topLevelItem(0)
    assert root.text(0) == "knight"
    assert root.childCount() == 1
    assert root.child(0).text(0) == "body"
    assert root.child(0).child(0).text(0) == "head"
    assert len(rows) == 3


def test_attaching_from_the_form_uses_set_parent(loaded):
    window, keys = loaded
    window.objects_table.clearSelection()
    window.objects_table.selectRow(4)
    window.on_objects_selected()
    window.in_name.setText("sword")
    window.in_description.setText("A knight sword")
    window.in_provides.setText("head_mount")
    window.on_create_component()
    sword = window.service.project.component_by_name("sword")
    window.service.add_socket(sword.key, "base", direction=(0, -1, 0), radius=0.05)

    window.cmb_parent.setCurrentIndex(
        [window.cmb_parent.itemData(i) for i in
         range(window.cmb_parent.count())].index(keys["body"]))
    window.cmb_child.setCurrentIndex(
        [window.cmb_child.itemData(i) for i in
         range(window.cmb_child.count())].index(sword.key))
    window.in_child_id.setText("blade")
    window.in_requirement.setText("head_mount")
    window.on_set_parent()

    body = window.service._draft(keys["body"])
    assert [c.id for c in body.children] == ["head", "blade"]
    assert body.child("blade").requirement == {"capability": "head_mount"}


def test_the_socket_table_and_the_snap_buttons_edit_the_draft(loaded):
    window, keys = loaded
    window.on_component_chosen(_item_for(window.components_list, keys["body"]))

    assert [window.sockets_table.item(r, 0).text()
            for r in range(window.sockets_table.rowCount())] == ["base", "neck"]
    window.sockets_table.selectRow(1)
    window.on_socket_chosen()
    assert window.in_socket_name.text() == "neck"

    window.on_snap_face("-Y")
    socket = window.service._draft(keys["body"]).socket("neck")
    assert socket.position[1] == pytest.approx(0.0, abs=1e-6)

    window.sockets_table.selectRow(1)
    window.on_align_direction("+X")
    socket = window.service._draft(keys["body"]).socket("neck")
    assert socket.direction == pytest.approx((1.0, 0.0, 0.0))


def test_the_variability_page_offers_only_installed_strategies(loaded):
    window, keys = loaded
    window.on_component_chosen(_item_for(window.components_list, keys["body"]))
    strategies = window.service.param_strategies()

    assert [window.cmb_transform.itemText(i)
            for i in range(window.cmb_transform.count())] == strategies["transforms"]
    offered = {window.cmb_effect.itemText(i)
               for i in range(window.cmb_effect.count())}
    assert offered == {e["type"] for e in strategies["effects"]}

    window.cmb_effect.setCurrentText("fx:bend")
    window.refresh_effect_knobs()
    knobs = {window.cmb_effect_knob.itemText(i)
             for i in range(window.cmb_effect_knob.count())}
    bend = next(e for e in strategies["effects"] if e["type"] == "fx:bend")
    assert knobs == set(bend["knobs"])
    assert "axis" not in knobs, "un parametro dati pilota solo numeri"


def test_adding_an_effect_backed_param_from_the_form(loaded):
    window, keys = loaded
    window.on_component_chosen(_item_for(window.components_list, keys["body"]))
    window.in_param_name.setText("curvature")
    window.cmb_strategy.setCurrentText("effect")
    window.cmb_effect.setCurrentText("fx:bend")
    window.refresh_effect_knobs()
    window.cmb_effect_knob.setCurrentText("amount")
    window.cmb_effect_scope.setCurrentText("part")
    window.spin_param_min.setValue(-1.0)
    window.spin_param_max.setValue(1.0)
    window.spin_param_default.setValue(0.0)
    window.spin_neutral.setValue(0.0)
    window.on_add_param()

    param = window.service._draft(keys["body"]).param("curvature")
    assert param is not None
    assert param.transform == ""
    assert param.effect == {"type": "fx:bend", "parameter": "amount",
                            "scope": "part", "neutral": 0.0}


def test_the_planner_preview_shows_the_rendered_text(loaded):
    window, keys = loaded
    window.on_component_chosen(_item_for(window.components_list, keys["head"]))

    text = window.planner_view.toPlainText()
    assert text == window.service.planner_preview(keys["head"])
    assert "my_plugin:head" in text


def test_the_test_search_uses_the_real_index(loaded):
    window, _keys = loaded
    window.in_test_search.setText("knight head")
    window.on_test_search()

    rows = [window.search_results.item(i).text()
            for i in range(window.search_results.count())]
    assert rows, "qualcosa e' stato trovato"
    assert "my_plugin:head" in " ".join(rows)
    assert rows[0].startswith("1. ")


def test_the_detail_preview_lists_the_nodes_that_really_expand(loaded):
    window, keys = loaded
    window.on_component_chosen(_item_for(window.components_list, keys["root"]))
    window.on_detail_preview(1)
    low = [window.detail_list.item(i).text()
           for i in range(window.detail_list.count())]
    window.on_detail_preview(2)
    high = [window.detail_list.item(i).text()
            for i in range(window.detail_list.count())]

    assert low[0] == "detail 1: 2 nodi"
    assert high[0] == "detail 2: 3 nodi"


def test_the_frame_table_shows_the_outcome_and_the_move(loaded):
    window, keys = loaded
    window.service.set_frame(keys["head"], growth_axis="+Y", front="-Z", up="+Y")
    window.refresh_frame()

    rows = [[window.frame_table.item(r, c).text() for c in range(4)]
            for r in range(window.frame_table.rowCount())]
    head = next(r for r in rows if r[0].endswith("/head"))
    assert head[2] == "convertible"
    assert head[3] == "fx:rotate Y 180.0"


def test_the_validation_table_shows_the_real_report(loaded):
    window, _keys = loaded
    window.on_validate()
    report = window.service.validate()

    assert window.validation_table.rowCount() == len(report.rows())
    severities = {window.validation_table.item(r, 0).text()
                  for r in range(window.validation_table.rowCount())}
    assert severities <= {"error", "warning", "info"}
    assert "ok" in window.lbl_valid.text()


def test_building_from_the_window_goes_through_the_real_pipeline(loaded):
    window, keys = loaded
    window.on_component_chosen(_item_for(window.components_list, keys["root"]))
    window.spin_detail.setValue(3)
    window.on_build()

    text = window.build_view.toHtml()
    assert "48 triangoli" in text
    assert "subject/body/head" in text


def test_the_preview_adds_gizmo_nodes_without_touching_the_model(loaded):
    from app.authoring.gizmo import GIZMO_TAG

    window, keys = loaded
    window.on_component_chosen(_item_for(window.components_list, keys["body"]))
    window.chk_sockets.setChecked(True)
    window.spin_detail.setValue(1)
    window.refresh_preview()
    scene = window.service.preview_scene(keys["body"], detail_level=1,
                                         sockets=True)
    model = [n for n in scene.nodes if GIZMO_TAG not in n.tags]

    assert sum(n.triangles for n in model) == 12
    assert len(scene.nodes) == len(model) + 6, "due socket per tre nodi di gizmo"


def test_save_and_install_from_the_window(loaded, tmp_path):
    window, _keys = loaded
    window.in_destination.setText(str(tmp_path / "out"))
    window.on_apply_plugin_meta()
    window.on_save_plugin()
    assert (tmp_path / "out" / "my_plugin" / "plugin.json").is_file()

    window.on_install_plugin()
    text = window.install_view.toHtml()
    assert "componenti installati" in text
    assert window.service.session.catalog().component("my_plugin:knight") is not None


def test_the_component_lab_dialog_reflects_the_lab(app, loaded):
    from app.ui.authoring_window import ComponentLabDialog

    window, keys = loaded
    lab = window.service.draft_lab(keys["body"])
    dialog = ComponentLabDialog(lab, service=window.service)
    try:
        assert "my_plugin:body" in dialog.windowTitle()
        assert set(dialog.sliders) == {k.name for k in lab.params() if k.bounded}
        assert "triangoli" in dialog.summary.text()

        slider = dialog.sliders["width"]
        slider.setValue(slider.maximum())
        dialog.on_slider()
        assert dialog.labels["width"].text() == "2.500"
        # Il corpo a detail 2 porta anche la testa: 12 + 36.
        assert "48 triangoli" in dialog.summary.text()
        assert dialog.summary.text().endswith("ok")

        dialog.on_reset()
        assert dialog.labels["width"].text() == "1.000"
    finally:
        dialog.close()


def test_saving_a_variant_from_the_lab_dialog_reaches_the_project(app, loaded):
    from app.ui.authoring_window import ComponentLabDialog

    window, keys = loaded
    lab = window.service.draft_lab(keys["body"])
    dialog = ComponentLabDialog(lab, service=window.service)
    try:
        slider = dialog.sliders["width"]
        slider.setValue(slider.maximum())
        dialog.on_slider()
        recipe = lab.save_variant("wide_body")
        window.service.save_variant(recipe)
        window.refresh_variants()
    finally:
        dialog.close()

    assert [v.name for v in window.service.variants()] == ["wide_body"]
    assert window.variants_list.count() == 1
    assert "wide_body" in window.variants_list.item(0).text()


def test_save_as_defaults_writes_on_the_draft_and_not_on_the_library(app, loaded):
    from app.ui.authoring_window import ComponentLabDialog

    window, keys = loaded
    lab = window.service.draft_lab(keys["body"])
    dialog = ComponentLabDialog(lab, service=window.service)
    try:
        slider = dialog.sliders["width"]
        slider.setValue(slider.maximum())
        dialog.on_slider()
        dialog.on_save_defaults()
    finally:
        dialog.close()

    assert window.service._draft(keys["body"]).param("width").default == \
        pytest.approx(2.5)
    # Il componente installato non e' stato toccato: era congelato.
    assert lab.component.params["width"].default == pytest.approx(1.0)


def test_the_lab_on_an_installed_component_refuses_to_write_defaults(app, window):
    from app.authoring import ComponentLab
    from app.ui.authoring_window import ComponentLabDialog

    lab = ComponentLab(window.service.session, "creature:bulging_eye")
    dialog = ComponentLabDialog(lab, service=None)
    try:
        dialog.on_save_defaults()
        assert "Save Variant" in dialog.summary.text()
    finally:
        dialog.close()


# --------------------------------------------------------------------------- #
# La finestra non contiene logica di authoring
# --------------------------------------------------------------------------- #
def test_the_window_holds_no_authoring_logic():
    """Nessun emettitore, nessun loader, nessun trimesh dentro la finestra.

    La UI puo' leggere il servizio e disegnare. Se cominciasse a scrivere JSON
    o a toccare geometria, esisterebbero due modi di costruire un plugin — che
    e' esattamente cio' che il punto 25 della milestone chiede di evitare.
    """
    source = Path("app/ui/authoring_window.py").read_text(encoding="utf-8")
    # Si confrontano **token**, non sottostringhe: `np` sta dentro
    # `QInputDialog`, e un test che lo contasse direbbe una cosa falsa.
    names = {token.string for token
             in tokenize.generate_tokens(io.StringIO(source).readline)
             if token.type == tokenize.NAME}

    for forbidden in ("trimesh", "emit_plugin", "load_component", "json",
                      "Registry", "safe_path", "np", "numpy", "load_model",
                      "export_glb"):
        assert forbidden not in names, forbidden


def test_the_main_window_opens_authoring_on_the_same_session(app, monkeypatch):
    monkeypatch.setattr(Session, "start_autosave", lambda self, interval=None: None)
    from app.ui.main_window import MainWindow

    main = MainWindow()
    main.session.provider = OfflineProvider()
    try:
        authoring = main.on_open_authoring()
        assert authoring.service.session is main.session
        # Due aperture non creano due finestre.
        assert main.on_open_authoring() is authoring
        lab = main.on_open_component_lab("creature:bulging_eye")
        assert lab is not None
        lab.close()
        authoring.close()
    finally:
        main.close()


def _item_for(widget, key: str):
    for index in range(widget.count()):
        item = widget.item(index)
        if item.data(Qt.ItemDataRole.UserRole) == key:
            return item
    raise AssertionError("nessuna voce per %r" % key)
