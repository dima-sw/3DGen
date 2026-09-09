"""Formato di progetto `.my3d`.

Un archivio zip che contiene tutto il lavoro: la cronologia completa, non solo
l'ultimo modello. Dentro ci sono i **piani**, non le mesh: la geometria si
ricostruisce da sola, e' deterministica a parita' di seme, e un piano pesa
qualche kilobyte contro i megabyte di un GLB.

    progetto.my3d
        project.json          nome, date, versione del formato, indice corrente
        history/0001.json     un piano per versione, con etichetta e messaggio
        preview.png           anteprima dell'ultima versione

Il numero di versione del formato serve a non rompere i progetti vecchi quando
il formato cambia: il caricatore sa migrare all'indietro.
"""
from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.logging_setup import get
from app.core.spec import GenerationPlan

log = get("core.project")

SUFFIX = ".my3d"
FORMAT_VERSION = 1
PROJECT_FILE = "project.json"
HISTORY_DIR = "history"
PREVIEW_FILE = "preview.png"


class ProjectError(ValueError):
    pass


@dataclass
class ProjectInfo:
    """Metadati di un progetto, leggibili senza aprire tutto."""

    name: str = "Senza titolo"
    created: str = ""
    modified: str = ""
    format_version: int = FORMAT_VERSION
    app_version: str = "0.2"
    cursor: int = 0
    versions: int = 0
    labels: list[str] = field(default_factory=list)

    @classmethod
    def now(cls, name: str) -> "ProjectInfo":
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return cls(name=name, created=stamp, modified=stamp)


def _entry_name(index: int) -> str:
    return "%s/%04d.json" % (HISTORY_DIR, index + 1)


# --------------------------------------------------------------------------- #
# Salvataggio
# --------------------------------------------------------------------------- #
def save(session, path: str | Path, name: str = "", preview: bytes | Path | None = None) -> Path:
    """Scrive l'intera sessione: ogni versione, non solo quella corrente."""
    out = Path(path)
    if out.suffix.lower() != SUFFIX:
        out = out.with_suffix(SUFFIX)
    out.parent.mkdir(parents=True, exist_ok=True)

    if not session.history:
        raise ProjectError("non c'e' niente da salvare: la sessione e' vuota")

    info = ProjectInfo.now(name or out.stem)
    info.cursor = max(0, min(session.cursor, len(session.history) - 1))
    info.versions = len(session.history)
    info.labels = [v.label for v in session.history]

    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(PROJECT_FILE, json.dumps(info.__dict__, indent=2, ensure_ascii=False))
        for index, version in enumerate(session.history):
            payload = {
                "label": version.label,
                "message": version.message,
                "seconds": version.seconds,
                "plan": version.plan.model_dump(),
            }
            archive.writestr(_entry_name(index),
                             json.dumps(payload, indent=2, ensure_ascii=False))
        data = _preview_bytes(preview)
        if data:
            archive.writestr(PREVIEW_FILE, data)

    log.info("progetto salvato: %s (%d versioni)", out, info.versions)
    return out


def _preview_bytes(preview: bytes | Path | None) -> bytes | None:
    if isinstance(preview, (bytes, bytearray)):
        return bytes(preview)
    if preview is not None:
        source = Path(preview)
        if source.is_file():
            return source.read_bytes()
    return None


# --------------------------------------------------------------------------- #
# Lettura
# --------------------------------------------------------------------------- #
def read_info(path: str | Path) -> ProjectInfo:
    """Metadati senza ricostruire nulla: serve a elencare i progetti."""
    with zipfile.ZipFile(Path(path)) as archive:
        try:
            raw = json.loads(archive.read(PROJECT_FILE).decode("utf-8"))
        except KeyError as exc:
            raise ProjectError("non e' un progetto 3DGen: manca %s" % PROJECT_FILE) from exc
    return migrate(raw)


def migrate(raw: dict[str, Any]) -> ProjectInfo:
    """Porta i metadati alla versione corrente del formato.

    Oggi c'e' una sola versione, ma il punto e' che il caricatore non si fidi
    mai di quello che trova: un progetto salvato da una versione futura non
    deve far esplodere l'applicazione.
    """
    version = int(raw.get("format_version", 0) or 0)
    if version > FORMAT_VERSION:
        log.warning("progetto in formato %d, piu' recente di quello noto (%d): "
                    "provo a leggerlo lo stesso", version, FORMAT_VERSION)
    known = {f for f in ProjectInfo.__dataclass_fields__}
    info = ProjectInfo(**{k: v for k, v in raw.items() if k in known})
    info.format_version = FORMAT_VERSION
    return info


def load(path: str | Path, session=None, provider=None, library=None):
    """Ricostruisce una sessione completa dal file di progetto."""
    from app.build.builder import build_scene
    from app.core.session import Session, Version

    source = Path(path)
    if not source.is_file():
        raise ProjectError("progetto inesistente: %s" % source)

    with zipfile.ZipFile(source) as archive:
        info = migrate(json.loads(archive.read(PROJECT_FILE).decode("utf-8")))
        entries = sorted(n for n in archive.namelist()
                         if n.startswith(HISTORY_DIR + "/") and n.endswith(".json"))
        payloads = [json.loads(archive.read(name).decode("utf-8")) for name in entries]

    target = session if session is not None else Session(provider=provider, library=library)
    target.history = []
    target.cursor = -1

    for payload in payloads:
        try:
            plan = GenerationPlan.model_validate(payload["plan"])
        except Exception as exc:
            log.warning("versione saltata, piano illeggibile: %s", exc)
            continue
        target.history.append(Version(
            label=payload.get("label", plan.object_type),
            plan=plan,
            scene=build_scene(plan),
            message=payload.get("message", ""),
            seconds=float(payload.get("seconds", 0.0)),
        ))

    if not target.history:
        raise ProjectError("il progetto non contiene versioni leggibili")
    target.cursor = max(0, min(int(info.cursor), len(target.history) - 1))
    log.info("progetto aperto: %s (%d versioni, corrente %d)",
             source.name, len(target.history), target.cursor + 1)
    return target


def preview_bytes(path: str | Path) -> bytes | None:
    try:
        with zipfile.ZipFile(Path(path)) as archive:
            return archive.read(PREVIEW_FILE)
    except (KeyError, zipfile.BadZipFile, FileNotFoundError):
        return None
