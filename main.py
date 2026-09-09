"""Punto di ingresso dell'applicazione desktop.

    python main.py            avvia la UI
    python cli.py "prompt"    genera da riga di comando, senza interfaccia
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.core.config import SETTINGS  # noqa: E402
from app.core.logging_setup import get, setup  # noqa: E402


def main() -> int:
    setup(SETTINGS.log_level)
    log = get("main")

    from PySide6.QtWidgets import QApplication  # noqa: E402

    from app.ui.viewport import configure_opengl  # noqa: E402

    configure_opengl()          # deve precedere QApplication
    app = QApplication(sys.argv)
    app.setApplicationName("3DGen")

    from app.ui.main_window import MainWindow  # noqa: E402

    window = MainWindow()
    window.show()

    if window.viewport.gl_error:
        log.error("viewport non disponibile: %s", window.viewport.gl_error)
    log.info("avvio interfaccia | provider: %s",
             ", ".join(SETTINGS.available_chain()) or "solo regole locali")
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
