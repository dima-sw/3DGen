"""Libreria di asset: salvataggio, ricerca, ricarica.

Il criterio di accettazione della voce 1 del TODO: un asset salvato deve
tornare identico dopo aver chiuso e riaperto l'applicazione.
"""
from __future__ import annotations

import json

import pytest

from app.ai.provider import OfflineProvider
from app.assets.library import AssetLibrary, AssetRecord, auto_tags, slugify
from app.build.builder import build_scene
from app.core.session import Session

OFFLINE = OfflineProvider()


@pytest.fixture()
def library(tmp_path):
    return AssetLibrary(tmp_path / "library")


@pytest.fixture()
def session(library):
    return Session(provider=OFFLINE, library=library)


# --------------------------------------------------------------------------- #
# Salvataggio
# --------------------------------------------------------------------------- #
def test_save_creates_the_three_files(session, library):
    session.generate_legacy("una jeep militare verde")
    record = session.save_to_library("Jeep di prova")

    folder = library.path(record.id)
    assert (folder / "asset.json").is_file()
    assert (folder / "model.glb").is_file()
    assert (folder / "preview.png").is_file()
    assert (folder / "model.glb").stat().st_size > 5000


def test_saved_metadata_describes_the_object(session):
    session.generate_legacy("una jeep militare verde a quattro porte")
    record = session.save_to_library()

    assert record.template == "vehicle"
    assert record.category == "veicoli"
    assert record.parts > 20 and record.triangles > 500
    assert all(d > 0 for d in record.dimensions)
    assert record.seed == session.current_plan.seed
    assert record.created.startswith("20")


def test_custom_tags_are_merged_with_automatic_ones(session):
    session.generate_legacy("una jeep militare")
    record = session.save_to_library("Jeep", tags=["preferito", "progetto-x"])
    assert "preferito" in record.tags and "progetto-x" in record.tags
    assert "vehicle" in record.tags and "veicoli" in record.tags


def test_saving_empty_session_is_refused(session):
    with pytest.raises(ValueError):
        session.save_to_library()


def test_ids_are_unique_and_filesystem_safe(session):
    session.generate_legacy("un'auto sportiva")
    ids = {session.save_to_library("Auto / prova: n°1").id for _ in range(5)}
    assert len(ids) == 5
    for asset_id in ids:
        assert all(c.isalnum() or c == "-" for c in asset_id)


# --------------------------------------------------------------------------- #
# Ricarica: il criterio di accettazione
# --------------------------------------------------------------------------- #
def test_asset_survives_a_restart(tmp_path):
    """Salvo, 'chiudo l'app', riapro con oggetti nuovi, ricarico: deve essere identico."""
    first = Session(provider=OFFLINE, library=AssetLibrary(tmp_path / "library"))
    first.generate_legacy("una jeep militare verde con ruote grandi")
    record = first.save_to_library("Jeep")
    original_params = dict(first.current_plan.params)
    original_triangles = first.scene.triangle_count
    original_colors = sorted((m.name, m.base_color) for m in first.current_plan.materials)

    # nuova sessione, nuova libreria che punta alla stessa cartella
    second = Session(provider=OFFLINE, library=AssetLibrary(tmp_path / "library"))
    version = second.load_from_library(record.id)

    assert version.plan.params == original_params
    assert version.plan.seed == record.seed
    assert sorted((m.name, m.base_color) for m in version.plan.materials) == original_colors
    assert version.scene.triangle_count == original_triangles


def test_loaded_asset_is_still_editable(session):
    """Non un blocco morto: si continua a modificarlo a voce."""
    session.generate_legacy("un suv")
    record = session.save_to_library()
    session.load_from_library(record.id)

    before = session.current_plan.params["wheel_radius"]
    session.modify("fai le ruote piu grandi")
    assert session.current_plan.params["wheel_radius"] > before


def test_loaded_asset_can_generate_new_variants(session):
    session.generate_legacy("un fuoristrada rosso")
    record = session.save_to_library()
    session.load_from_library(record.id)
    seed_before = session.current_plan.seed

    session.revariate()
    assert session.current_plan.seed != seed_before
    body = next(m for m in session.current_plan.materials if m.name == "body")
    assert body.base_color == "#b02a1f", "il rosso richiesto deve sopravvivere"


def test_load_appears_in_history(session):
    session.generate_legacy("una sedia")
    record = session.save_to_library("Sedia")
    session.generate_legacy("un tavolo")
    session.load_from_library(record.id)

    assert len(session.history) == 3
    assert session.history[-1].label == "Sedia"
    session.undo()
    assert session.current_plan.template == "table"


def test_loading_unknown_asset_fails_clearly(session):
    with pytest.raises(KeyError):
        session.load_from_library("non-esiste-123456")


def test_glb_is_readable_by_other_tools(session, library):
    import trimesh

    session.generate_legacy("una spada")
    record = session.save_to_library()
    loaded = trimesh.load(library.model_path(record.id))
    assert len(loaded.geometry) == len(session.scene.nodes)


# --------------------------------------------------------------------------- #
# Elenco e ricerca
# --------------------------------------------------------------------------- #
def _populate(session) -> None:
    for prompt, name in [("una jeep militare verde", "Jeep militare"),
                         ("un'auto sportiva rossa", "Sportiva"),
                         ("una casa a due piani", "Casetta"),
                         ("un pino alto 9 metri", "Pino"),
                         ("una spada medievale", "Spada")]:
        session.generate_legacy(prompt)
        session.save_to_library(name)


def test_listing_is_newest_first(session, library):
    _populate(session)
    records = library.all()
    assert len(records) == 5
    assert [r.created for r in records] == sorted((r.created for r in records), reverse=True)


def test_search_by_name_and_tags(session, library):
    _populate(session)
    assert any(r.name == "Jeep militare" for r in library.search("jeep"))
    assert any(r.template == "vehicle" for r in library.search("militare"))
    assert library.search("sottomarino nucleare") == []


def test_search_finds_synonyms_from_the_template(session, library):
    """'albero' deve trovare un asset salvato come 'pino'."""
    _populate(session)
    assert any(r.name == "Pino" for r in library.search("albero"))
    assert any(r.name == "Spada" for r in library.search("arma"))
    assert any(r.template == "vehicle" for r in library.search("macchina"))


def test_user_words_rank_above_synonyms(session, library):
    """Chi ha davvero quella parola nel prompt viene prima."""
    session.generate_legacy("un pino alto 9 metri")
    session.save_to_library("Pino")
    session.generate_legacy("una palma")
    session.save_to_library("Palma")
    assert library.search("palma")[0].name == "Palma"
    assert library.search("pino")[0].name == "Pino"


def test_search_filters_by_category(session, library):
    _populate(session)
    veicoli = library.search(category="veicoli")
    assert len(veicoli) == 2
    assert all(r.category == "veicoli" for r in veicoli)
    assert set(library.categories()) == {"veicoli", "edifici", "natura", "armi"}


def test_search_respects_limit(session, library):
    _populate(session)
    assert len(library.search(limit=2)) == 2


# --------------------------------------------------------------------------- #
# Robustezza: il filesystem e' la fonte di verita'
# --------------------------------------------------------------------------- #
def test_deleted_folder_does_not_break_listing(session, library):
    _populate(session)
    victim = library.all()[0]
    import shutil

    shutil.rmtree(library.path(victim.id))
    assert len(library.all()) == 4
    assert library.get(victim.id) is None


def test_corrupted_metadata_is_skipped(session, library):
    _populate(session)
    victim = library.all()[0]
    (library.path(victim.id) / "asset.json").write_text("{ non e' json", encoding="utf-8")
    assert len(library.all()) == 4


def test_stray_directory_is_ignored(library, session):
    session.generate_legacy("una sedia")
    session.save_to_library()
    (library.root / "cartella-a-caso").mkdir()
    assert len(library.all()) == 1


def test_delete_and_rename(session, library):
    session.generate_legacy("una sedia")
    record = session.save_to_library("Prima")
    assert library.rename(record.id, "Dopo").name == "Dopo"
    assert library.get(record.id).name == "Dopo"
    assert library.delete(record.id) is True
    assert library.delete(record.id) is False
    assert library.all() == []


def test_cache_notices_external_edits(session, library):
    session.generate_legacy("una sedia")
    record = session.save_to_library("Prima")
    assert library.get(record.id).name == "Prima"

    meta = library.path(record.id) / "asset.json"
    data = json.loads(meta.read_text(encoding="utf-8"))
    data["name"] = "Modificata fuori"
    import os
    import time

    time.sleep(0.01)
    meta.write_text(json.dumps(data), encoding="utf-8")
    os.utime(meta, (time.time() + 1, time.time() + 1))
    assert library.get(record.id).name == "Modificata fuori"


# --------------------------------------------------------------------------- #
# Utilita'
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text,expected", [
    ("Jeep militare", "jeep-militare"),
    ("Auto / prova: n°1", "auto-prova-n-1"),
    ("   ", "asset"),
    ("Città", "citta"),
])
def test_slugify(text, expected):
    assert slugify(text) == expected


def test_auto_tags_describe_the_plan():
    from app.ai.planner import generate_plan

    plan, _ = generate_plan("una jeep militare con portapacchi", OFFLINE)
    plan.params["has_roof_rack"] = True
    tags = auto_tags(plan, build_scene(plan))
    assert "vehicle" in tags and "veicoli" in tags
    assert "roof_rack" in tags
    assert "offroad" in tags


def test_record_round_trips_through_json():
    from app.ai.planner import generate_plan

    plan, _ = generate_plan("una sedia", OFFLINE)
    record = AssetRecord(id="x-1", name="Sedia", plan=plan)
    again = AssetRecord.model_validate_json(record.model_dump_json())
    assert again.plan.params == plan.params
