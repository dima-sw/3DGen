"""Avvia la UI vera, esercita generazione, variante, modifica e libreria.

Salva due screenshot e chiude.

    python tests/_smoke_gui.py [prompt]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.ai.provider import OfflineProvider  # noqa: E402
from app.core.logging_setup import setup  # noqa: E402
from app.core.session import Session  # noqa: E402
from app.ui.viewport import configure_opengl  # noqa: E402

setup("INFO")
configure_opengl()
app = QApplication(sys.argv)

from app.ui.main_window import MainWindow  # noqa: E402

prompt = sys.argv[1] if len(sys.argv) > 1 else "Crea una Jeep militare 4x4 verde con ruote grandi"
window = MainWindow()
window.session = Session(provider=OfflineProvider())   # niente rete nello smoke test
window.show()

out_dir = Path("output")
state = {"step": 0}


def shot(name: str) -> None:
    window.repaint()
    out_dir.mkdir(exist_ok=True)
    target = out_dir / name
    window.grab().save(str(target))
    print("screenshot:", target.resolve())


def step() -> None:
    s = state["step"]
    if s == 0:
        window.prompt.setPlainText(prompt)
        window.on_run("generate")
    elif s == 1:
        window.on_run("variant")            # stesso oggetto, variante diversa
    elif s == 2:
        window.prompt.setPlainText("fai le ruote piu grandi e fallo nero")
        window.on_run("modify")
    elif s == 3:
        if window.viewport.gl_error:
            print("ERRORE OPENGL:", window.viewport.gl_error)
        shot("gui.png")
        # salvataggio senza passare dalla finestra modale, che bloccherebbe il test
        record = window.session.save_to_library("Jeep dallo smoke test")
        window.refresh_library()
        print("salvato:", record.id)
    elif s == 4:
        index = next(i for i in range(window.tabs.count())
                     if window.tabs.tabText(i) == "Libreria")
        window.tabs.setCurrentIndex(index)
        shot("gui_libreria.png")
        print("asset in libreria:", window.lib_list.count())
        print("stato:", window.status.text())
        print("versioni:", [v.label for v in window.session.history])
    elif s >= 5:
        app.quit()
    state["step"] = s + 1


timer = QTimer()
timer.timeout.connect(step)
timer.start(2000)
sys.exit(app.exec())
