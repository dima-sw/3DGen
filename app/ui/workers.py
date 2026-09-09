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
                 image: str = "", front: str = "") -> None:
        super().__init__()
        self.session = session
        self.prompt = prompt
        self.mode = mode  # "generate" | "modify" | "variant" | "image"
        self.image = image
        self.front = front

    def run(self) -> None:
        try:
            if self.mode == "image":
                self.progress.emit("Analizzo l'immagine di riferimento...")
                version = self.session.generate_from_image(
                    self.image, self.prompt, front=self.front or None)
            elif self.mode == "variant" and self.session.current_plan is not None:
                self.progress.emit("Genero un'altra variante...")
                version = self.session.revariate()
            elif self.mode == "modify" and self.session.current_plan is not None:
                self.progress.emit("Interpreto la modifica...")
                version = self.session.modify(self.prompt)
            else:
                self.progress.emit("Interpreto la richiesta...")
                version = self.session.generate_legacy(self.prompt)
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
