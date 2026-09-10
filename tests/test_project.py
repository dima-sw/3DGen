"""Formato progetto .my3d: la cronologia sopravvive alla chiusura dell'app."""
from __future__ import annotations

import json
import zipfile

import pytest

from app.ai.provider import OfflineProvider
from app.core import project
from app.core.planner.planner import MockPlanner
from app.core.session import Session

OFFLINE = OfflineProvider()


def worked_session() -> Session:
    """Una sessione con piu' versioni e un undo, come dopo mezz'ora di lavoro."""
    session = Session(provider=OFFLINE, planner=MockPlanner())
    session.generate("una casa con un pianeta enorme sopra")

    # cambiare un parametro **nel piano** e ricostruire: e' cosi' che adesso si
    # modifica un modello, e una sessione salvata deve saperlo conservare
    piano = session.current_plan
    piano.nodes[piano.root_id].overrides["width"] = 12.0
    session.regenerate()

    session.generate("un albero con un nido e un uccello")
    session.generate("un pesce")
    session.undo()
    return session


# --------------------------------------------------------------------------- #
# Il criterio di accettazione
# --------------------------------------------------------------------------- #
def test_work_survives_closing_the_app(tmp_path):
    """Chiudo a meta' lavoro e riprendo esattamente da li', undo compreso."""
    original = worked_session()
    path = original.save_project(tmp_path / "lavoro", name="Prova")

    ripreso = Session(provider=OFFLINE, planner=MockPlanner())
    ripreso.open_project(path)

    assert len(ripreso.history) == len(original.history)
    assert ripreso.cursor == original.cursor
    assert [v.label for v in ripreso.history] == [v.label for v in original.history]
    assert ripreso.current_plan.to_dict() == original.current_plan.to_dict()
    assert ripreso.scene.triangle_count == original.scene.triangle_count


def test_undo_and_redo_work_after_reopening(tmp_path):
    original = worked_session()
    path = original.save_project(tmp_path / "lavoro")

    ripreso = Session(provider=OFFLINE, planner=MockPlanner())
    ripreso.open_project(path)
    assert ripreso.can_undo() and ripreso.can_redo()

    ripreso.redo()
    atteso = original.history[original.cursor + 1].plan.to_dict()
    assert ripreso.current_plan.to_dict() == atteso
    ripreso.undo()
    assert ripreso.current_plan.to_dict() == original.current_plan.to_dict()


def test_a_project_is_small(tmp_path):
    """Dentro ci sono i piani, non le mesh: la geometria si ricostruisce."""
    path = worked_session().save_project(tmp_path / "lavoro")
    assert path.stat().st_size < 60_000


# --------------------------------------------------------------------------- #
# Formato
# --------------------------------------------------------------------------- #
def test_suffix_is_added_when_missing(tmp_path):
    path = worked_session().save_project(tmp_path / "senza-estensione")
    assert path.suffix == ".my3d"


def test_archive_contains_one_entry_per_version(tmp_path):
    session = worked_session()
    path = session.save_project(tmp_path / "lavoro")
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
    versioni = [n for n in names if n.startswith("history/")]
    assert len(versioni) == len(session.history)
    assert "project.json" in names


def test_metadata_can_be_read_without_rebuilding(tmp_path):
    session = worked_session()
    path = session.save_project(tmp_path / "lavoro", name="Il mio lavoro")
    info = project.read_info(path)
    assert info.name == "Il mio lavoro"
    assert info.versions == len(session.history)
    assert info.cursor == session.cursor
    assert info.created and info.modified
    assert info.labels[0] == session.history[0].label


def test_preview_is_stored_when_provided(tmp_path):
    png = tmp_path / "anteprima.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 40)
    path = worked_session().save_project(tmp_path / "lavoro", preview=png)
    assert project.preview_bytes(path) is not None


def test_preview_is_optional(tmp_path):
    path = worked_session().save_project(tmp_path / "lavoro")
    assert project.preview_bytes(path) is None


# --------------------------------------------------------------------------- #
# Robustezza
# --------------------------------------------------------------------------- #
def test_empty_session_cannot_be_saved(tmp_path):
    with pytest.raises(project.ProjectError):
        Session(provider=OFFLINE, planner=MockPlanner()).save_project(tmp_path / "vuoto")


def test_opening_a_missing_file_is_reported(tmp_path):
    with pytest.raises(project.ProjectError):
        Session(provider=OFFLINE, planner=MockPlanner()).open_project(tmp_path / "inesistente.my3d")


def test_a_foreign_zip_is_rejected(tmp_path):
    path = tmp_path / "altro.my3d"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("qualcosa.txt", "non e' un progetto")
    with pytest.raises(project.ProjectError):
        project.read_info(path)


def test_a_broken_version_is_skipped_not_fatal(tmp_path):
    """Una versione illeggibile non deve far perdere tutto il resto."""
    session = worked_session()
    path = session.save_project(tmp_path / "lavoro")

    rotto = tmp_path / "rotto.my3d"
    with zipfile.ZipFile(path) as source, zipfile.ZipFile(rotto, "w") as target:
        for name in source.namelist():
            data = source.read(name)
            if name.endswith("0002.json"):
                data = b'{"label": "rotta", "plan": {"template": 12345, "params": "no"}}'
            target.writestr(name, data)

    ripreso = Session(provider=OFFLINE, planner=MockPlanner())
    ripreso.open_project(rotto)
    assert len(ripreso.history) >= len(session.history) - 1
    assert ripreso.scene.nodes


def test_a_project_without_versions_is_refused(tmp_path):
    path = tmp_path / "vuoto.my3d"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("project.json", json.dumps({"name": "x", "format_version": 1}))
    with pytest.raises(project.ProjectError):
        Session(provider=OFFLINE, planner=MockPlanner()).open_project(path)


def test_a_newer_format_is_read_anyway(tmp_path, caplog):
    """Un progetto di una versione futura non deve far esplodere l'app."""
    session = worked_session()
    path = session.save_project(tmp_path / "lavoro")
    futuro = tmp_path / "futuro.my3d"
    with zipfile.ZipFile(path) as source, zipfile.ZipFile(futuro, "w") as target:
        for name in source.namelist():
            data = source.read(name)
            if name == "project.json":
                payload = json.loads(data)
                payload["format_version"] = 99
                payload["campo_del_futuro"] = "boh"
                data = json.dumps(payload).encode("utf-8")
            target.writestr(name, data)

    info = project.read_info(futuro)
    assert info.format_version == project.FORMAT_VERSION
    ripreso = Session(provider=OFFLINE, planner=MockPlanner())
    ripreso.open_project(futuro)
    assert ripreso.history


def test_reopening_replaces_the_current_session(tmp_path):
    path = worked_session().save_project(tmp_path / "lavoro")
    altra = Session(provider=OFFLINE, planner=MockPlanner())
    altra.generate("una sedia")
    altra.open_project(path)
    radice = altra.current_plan.resolved_ref(altra.current_plan.root_id)
    assert radice.startswith("nature:") or radice.startswith("architecture:")
    assert all("sedia" not in v.label for v in altra.history)
