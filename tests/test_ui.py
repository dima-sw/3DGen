"""L'interfaccia si apre, genera e mostra. Nient'altro.

Non e' un test di grafica: non guarda pixel e non prova bottoni uno per uno.
Verifica la cosa che si rompe davvero quando il core cambia — che la finestra
**parli ancora la stessa lingua della sessione**: chiedere un modello, leggere
il piano, elencare le parti, offrire i parametri del componente radice.

Era proprio questo a mancare: la UI non aveva un solo test, e dopo aver tolto
la pipeline storica si apriva su un errore che nessuno avrebbe visto fino al
primo avvio.

Gira senza schermo (`QT_QPA_PLATFORM=offscreen`) e senza rete.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="l'interfaccia e' facoltativa")

from PySide6.QtWidgets import QApplication            # noqa: E402

from app.ai.provider import OfflineProvider           # noqa: E402
from app.core.config import SETTINGS                 # noqa: E402
from app.core.planner.planner import MockPlanner      # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def finestra(app, tmp_path, monkeypatch):
    """Una finestra vera, con una sessione senza rete e senza autosalvataggio."""
    from app.core.session import Session

    monkeypatch.setattr(Session, "start_autosave", lambda self, interval=None: None)
    from app.ui.main_window import MainWindow

    w = MainWindow()
    w.session.provider = OfflineProvider()
    w.session.planner = MockPlanner()
    yield w
    w.close()


def test_the_window_opens(finestra):
    assert "3DGen" in finestra.windowTitle()


def test_generating_fills_the_window(finestra):
    finestra.session.generate("una casa con un pianeta enorme sopra")
    finestra.refresh_all()

    assert finestra.tree.topLevelItemCount() > 0, "l'albero delle parti"
    assert finestra.history_list.count() == 1, "la cronologia"
    assert "triangoli" in finestra.status.text()


def test_the_status_bar_speaks_the_language_of_the_plan(finestra):
    finestra.session.generate("una casa con un pianeta enorme sopra")
    finestra.refresh_all()
    stato = finestra.status.text()
    assert "architecture:house" in stato
    assert "dettaglio" in stato and "seme" in stato


def test_the_parameters_come_from_the_registry(finestra):
    """Il pannello si costruisce dal componente radice, non da un elenco fisso."""
    finestra.session.generate("una casa con un pianeta enorme sopra")
    finestra.refresh_all()
    assert set(finestra._param_widgets) == {"width", "height", "depth",
                                            "roof_pitch"}


def test_changing_a_parameter_rebuilds_the_model(finestra):
    """Si cambia il **piano**, e la geometria si rifa'. Non si tocca la mesh."""
    finestra.session.generate("una casa con un pianeta enorme sopra")
    finestra.refresh_all()
    casa = finestra.session.scene.by_id("house")
    prima = float(casa.mesh.extents[0])

    finestra._param_widgets["width"].setValue(20.0)
    finestra.on_apply_params()

    dopo = float(finestra.session.scene.by_id("house").mesh.extents[0])
    assert dopo > prima * 2
    assert finestra.session.current_plan.nodes["house"].overrides["width"] == 20.0


def test_regenerating_keeps_the_same_plan(finestra):
    finestra.session.generate("un albero con un nido")
    prima = finestra.session.current_plan.to_dict()
    finestra.on_regenerate()
    assert finestra.session.current_plan.to_dict() == prima


def test_the_window_survives_an_empty_session(finestra):
    """Appena aperta non c'e' niente: non e' un caso limite, e' il primo avvio."""
    finestra.refresh_all()
    assert finestra.tree.topLevelItemCount() == 0
    assert not finestra._param_widgets


def test_the_detail_selector_speaks_of_parts(finestra):
    scelte = [finestra.density_box.itemText(i)
              for i in range(finestra.density_box.count())]
    assert scelte == ["normale", "essenziale", "dettagliato"]
    assert finestra.dettaglio() == 2


def test_provider_selector_has_no_model_selector(finestra):
    cerebras = finestra.provider_box.findData("cerebras")
    nvidia = finestra.provider_box.findData("nvidia_nim")
    assert cerebras >= 0 and nvidia >= 0
    assert not hasattr(finestra, "model_box")


def test_selected_provider_and_failover_are_applied_to_the_session(finestra):
    index = finestra.provider_box.findData("cerebras")
    finestra.provider_box.setCurrentIndex(index)
    finestra.failover_box.setChecked(False)
    finestra._apply_ai_selection()

    assert finestra.session.provider.key == "cerebras"
    assert finestra.session.provider.model == SETTINGS.model("cerebras")
    assert not finestra.session.provider.allow_local_fallback
