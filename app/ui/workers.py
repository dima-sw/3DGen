"""Lavoro pesante fuori dal thread della UI.

Rete (LLM) e geometria non devono mai bloccare la finestra: girano in un
QThread e comunicano solo tramite segnali.
"""
from __future__ import annotations

import traceback

from PySide6.QtCore import QObject, QThread, Signal

from app.core.logging_setup import get
from app.core.session import Session, Version

log = get("ui.worker")


class GenerationWorker(QObject):
    finished = Signal(object)   # Version
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, session: Session, prompt: str, mode: str,
                 detail: int = 0, seed: int = 0) -> None:
        super().__init__()
        self.session = session
        self.prompt = prompt
        self.mode = mode  # "generate" | "variant"
        self.detail = detail
        self.seed = seed

    def run(self) -> None:
        """Una generazione, oppure la stessa richiesta con un altro seme.

        Una "variante" non e' una perturbazione della mesh: e' lo stesso prompt
        con un seme diverso, cioe' un altro piano. Cambia quello che il sistema
        sceglie, non quanto rumore aggiunge alla geometria.
        """
        from app.core.session import Options

        try:
            versione = self.session.current
            if self.mode == "variant" and versione is not None:
                self.progress.emit("Genero un'altra variante...")
                seme = int(getattr(versione.plan, "seed", 0) or 0) + 1
                prompt = versione.prompt or self.prompt
            else:
                self.progress.emit("Interpreto la richiesta...")
                seme, prompt = self.seed, self.prompt
            self.session.generate(prompt, Options(detail_level=self.detail,
                                                  seed=seme))
            version = self.session.current
            self.finished.emit(version)
        except Exception as exc:  # pragma: no cover - protezione runtime
            log.error("worker fallito: %s\n%s", exc, traceback.format_exc())
            self.failed.emit(str(exc))


class ExportWorker(QObject):
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, session: Session, path: str) -> None:
        super().__init__()
        self.session = session
        self.path = path

    def run(self) -> None:
        try:
            out = self.session.export(self.path)
            self.finished.emit(str(out))
        except Exception as exc:
            log.error("export fallito: %s", exc)
            self.failed.emit(str(exc))


def run_in_thread(owner, worker: QObject) -> QThread:
    """Avvia il worker in un thread e ne gestisce la pulizia.

    Il thread viene tenuto vivo da `owner` per evitare che il garbage
    collector lo distrugga mentre e' in esecuzione.
    """
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    for sig in ("finished", "failed"):
        getattr(worker, sig).connect(thread.quit)
    thread.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    owner._threads = getattr(owner, "_threads", [])
    owner._threads.append((thread, worker))
    thread.finished.connect(lambda: owner._threads.remove((thread, worker))
                            if (thread, worker) in owner._threads else None)
    thread.start()
    return thread
