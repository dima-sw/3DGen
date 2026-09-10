"""Libreria di asset: salvataggio, ricerca, ricarica.

Il criterio di accettazione e' rimasto quello di sempre: un asset salvato deve
tornare identico dopo aver chiuso e riaperto l'applicazione. A cambiare e' che
cosa viene salvato accanto alla mesh — un `CompositionGraph` invece di un piano
di template — e quindi che cosa si puo' fare dopo averlo ricaricato: cambiare
un parametro, alzare il dettaglio, aggiungere un pezzo.
"""
from __future__ import annotations

import json

import pytest

from app.ai.provider import OfflineProvider
from app.assets.library import AssetLibrary, AssetRecord, auto_tags, slugify
from app.core.planner.planner import MockPlanner
from app.core.session import Options, Session

OFFLINE = OfflineProvider()


@pytest.fixture()
def library(tmp_path):
    return AssetLibrary(tmp_path / "library")


@pytest.fixture()
def session(library):
    return Session(provider=OFFLINE, planner=MockPlanner(), library=library)


# --------------------------------------------------------------------------- #
# Salvataggio
# --------------------------------------------------------------------------- #
def test_save_creates_the_three_files(session, library):
    session.generate("un albero con un nido e un uccello")
    record = session.save_to_library("Albero di prova")

    folder = library.path(record.id)
    assert (folder / "asset.json").is_file()
    assert (folder / "model.glb").is_file()
    assert (folder / "model.glb").stat().st_size > 1000


def test_saved_metadata_describes_the_object(session):
    session.generate("una casa con un pianeta enorme sopra")
    record = session.save_to_library()

    assert record.root_ref == "architecture:house"
    assert record.category == "architecture"
    assert record.parts >= 2 and record.triangles > 100
    assert all(d > 0 for d in record.dimensions)
    assert record.created.startswith("20")
    assert record.plan, "il piano viaggia con l'asset"


def test_custom_tags_are_merged_with_automatic_ones(session):
    session.generate("una casa con un pianeta")
    record = session.save_to_library("Casa", tags=["preferito", "progetto-x"])
    assert "preferito" in record.tags and "progetto-x" in record.tags
    assert "house" in record.tags and "architecture" in record.tags


def test_saving_empty_session_is_refused(session):
    with pytest.raises(ValueError):
        session.save_to_library()


def test_ids_are_unique_and_filesystem_safe(session):
    session.generate("una casa")
    ids = {session.save_to_library("Casa / prova: n°1").id for _ in range(5)}
    assert len(ids) == 5
    for asset_id in ids:
        assert all(c.isalnum() or c == "-" for c in asset_id)


# --------------------------------------------------------------------------- #
# Ricarica: il criterio di accettazione
# --------------------------------------------------------------------------- #
def test_asset_survives_a_restart(tmp_path):
    """Salvo, 'chiudo l'app', riapro con oggetti nuovi, ricarico: identico."""
    prima = Session(provider=OFFLINE, planner=MockPlanner(),
                    library=AssetLibrary(tmp_path / "library"))
    prima.generate("un albero con un nido e un uccello")
    record = prima.save_to_library("Albero")
    piano_originale = prima.current_plan.to_dict()
    triangoli = prima.scene.triangle_count

    # nuova sessione, nuova libreria che punta alla stessa cartella
    dopo = Session(provider=OFFLINE, planner=MockPlanner(),
                   library=AssetLibrary(tmp_path / "library"))
    versione = dopo.load_from_library(record.id)

    assert versione.plan.to_dict() == piano_originale
    assert versione.scene.triangle_count == triangoli


def test_a_loaded_asset_is_still_a_plan_not_a_block(session):
    """Non un blocco morto: si cambia un parametro e si ricostruisce."""
    session.generate("una casa")
    record = session.save_to_library()
    session.load_from_library(record.id)

    piano = session.current_plan
    prima = session.scene.dimensions()[0]
    piano.nodes[piano.root_id].overrides["width"] = 18.0
    session.regenerate()
    assert session.scene.dimensions()[0] > prima * 2


def test_a_loaded_asset_can_be_rebuilt_at_another_detail(session):
    session.generate("una casa con un pianeta")
    record = session.save_to_library()
    session.load_from_library(record.id)

    fine = session.regenerate(Options(detail_level=3))
    assert fine is not None and fine.build.meshes()


def test_load_appears_in_history(session):
    session.generate("una casa")
    record = session.save_to_library("Casa")
    session.generate("un albero")
    session.load_from_library(record.id)

    assert len(session.history) == 3
    assert session.history[-1].label == "Casa"
    session.undo()
    assert "tree" in session.current_plan.resolved_ref(session.current_plan.root_id)


def test_loading_unknown_asset_fails_clearly(session):
    with pytest.raises(KeyError):
        session.load_from_library("non-esiste-123456")


def test_glb_is_readable_by_other_tools(session, library):
    import trimesh

    session.generate("un albero con un nido")
    record = session.save_to_library()
    loaded = trimesh.load(library.model_path(record.id))
    assert len(loaded.geometry) == len(session.scene.nodes)


# --------------------------------------------------------------------------- #
# Elenco e ricerca
# --------------------------------------------------------------------------- #
def _popola(session) -> None:
    for prompt, nome in [("una casa con un pianeta enorme sopra", "Casa spaziale"),
                         ("un albero con un nido e un uccello", "Albero"),
                         ("un pesce con una spada", "Pesce armato"),
                         ("una persona", "Figura"),
                         ("un cristallo luminoso", "Cristallo")]:
        session.generate(prompt)
        session.save_to_library(nome)


def test_listing_is_newest_first(session, library):
    _popola(session)
    records = library.all()
    assert len(records) == 5
    assert [r.created for r in records] == sorted((r.created for r in records),
                                                  reverse=True)


def test_search_by_name_and_tags(session, library):
    _popola(session)
    assert any(r.name == "Albero" for r in library.search("albero"))
    assert any(r.category == "architecture" for r in library.search("casa"))
    assert library.search("sottomarino nucleare") == []


def test_search_finds_the_words_of_the_plugins(session, library):
    """I tag vengono dai riferimenti usati: `nature:tree` da' `nature` e `tree`."""
    _popola(session)
    assert any(r.name == "Albero" for r in library.search("tree"))
    assert any(r.name == "Casa spaziale" for r in library.search("planet"))


def test_user_words_rank_above_synonyms(session, library):
    """Chi ha davvero quella parola nel prompt viene prima."""
    session.generate("un albero con un nido")
    session.save_to_library("Albero")
    session.generate("una casa con un pianeta")
    session.save_to_library("Casa")
    assert library.search("casa")[0].name == "Casa"
    assert library.search("albero")[0].name == "Albero"


def test_search_filters_by_category(session, library):
    _popola(session)
    alberi = library.search(category="nature")
    assert alberi and all(r.category == "nature" for r in alberi)
    assert "architecture" in set(library.categories())


def test_search_respects_limit(session, library):
    _popola(session)
    assert len(library.search(limit=2)) == 2


# --------------------------------------------------------------------------- #
# Robustezza: il filesystem e' la fonte di verita'
# --------------------------------------------------------------------------- #
def test_deleted_folder_does_not_break_listing(session, library):
    _popola(session)
    vittima = library.all()[0]
    import shutil

    shutil.rmtree(library.path(vittima.id))
    assert len(library.all()) == 4
    assert library.get(vittima.id) is None


def test_corrupted_metadata_is_skipped(session, library):
    _popola(session)
    vittima = library.all()[0]
    (library.path(vittima.id) / "asset.json").write_text("{ non e' json",
                                                         encoding="utf-8")
    assert len(library.all()) == 4


def test_stray_directory_is_ignored(library, session):
    session.generate("una casa")
    session.save_to_library()
    (library.root / "cartella-a-caso").mkdir()
    assert len(library.all()) == 1


def test_delete_and_rename(session, library):
    session.generate("una casa")
    record = session.save_to_library("Prima")
    assert library.rename(record.id, "Dopo").name == "Dopo"
    assert library.get(record.id).name == "Dopo"
    assert library.delete(record.id) is True
    assert library.delete(record.id) is False
    assert library.all() == []


def test_cache_notices_external_edits(session, library):
    session.generate("una casa")
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


def test_auto_tags_come_from_the_plan_and_the_prompt(session):
    """Nessuna tabella di categorie: i tag sono i riferimenti e le parole."""
    risultato = session.generate("un albero con un nido e un uccello")
    tags = auto_tags(risultato.plan, risultato.scene(session.catalog()),
                     risultato.prompt)
    assert {"nature", "tree", "nest", "bird"} <= set(tags)
    assert "uccello" in tags, "anche le parole della richiesta"


def test_a_record_round_trips_through_json(session):
    risultato = session.generate("una casa")
    record = AssetRecord(id="x-1", name="Casa",
                         plan=risultato.plan.to_dict())
    ancora = AssetRecord.model_validate_json(record.model_dump_json())
    assert ancora.plan == record.plan
    assert ancora.payload()["graph"] == record.plan
