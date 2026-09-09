"""Distribuzione: profilo di qualita', recupero dopo crash, pacchetto Windows."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from app.ai.provider import OfflineProvider
from app.core import hardware, recovery
from app.core.hardware import PROFILES, Hardware, Quality
from app.core.session import Session


@pytest.fixture(autouse=True)
def profilo_pulito():
    """Il profilo e' globale: ogni test riparte da capo."""
    precedente = hardware._CURRENT
    yield
    hardware._CURRENT = precedente


@pytest.fixture
def sessione():
    sessione = Session(provider=OfflineProvider())
    sessione.generate_legacy("una sedia di legno", seed=5)
    return sessione


# --------------------------------------------------------------------------- #
# Rilevamento hardware
# --------------------------------------------------------------------------- #
def test_the_machine_is_detected():
    macchina = hardware.detect()
    assert macchina.cpu_cores >= 1
    assert macchina.ram_gb is None or macchina.ram_gb > 0.5
    assert macchina.describe()


def test_detection_is_cached():
    assert hardware.detect() is hardware.detect()


def test_unknown_values_stay_unknown():
    """`None` vuol dire 'non lo so'. Uno zero sarebbe una bugia."""
    ignota = Hardware(cpu_cores=4)
    assert ignota.ram_gb is None and ignota.vram_gb is None
    assert "RAM ignota" in ignota.describe() and "GPU ignota" in ignota.describe()


# --------------------------------------------------------------------------- #
# Scelta del profilo
# --------------------------------------------------------------------------- #
def test_a_weak_machine_gets_the_low_profile():
    scelto = hardware.choose(Hardware(cpu_cores=2, ram_gb=4.0))
    assert scelto.name == "basso" and scelto.reason


def test_a_strong_machine_gets_the_high_profile():
    assert hardware.choose(Hardware(cpu_cores=16, ram_gb=64.0)).name == "alto"


def test_an_ordinary_machine_gets_the_middle_profile():
    assert hardware.choose(Hardware(cpu_cores=6, ram_gb=16.0)).name == "medio"


def test_unknown_memory_is_treated_with_caution():
    """Senza un dato certo si sceglie il profilo prudente, non quello ottimista."""
    scelto = hardware.choose(Hardware(cpu_cores=32, ram_gb=None))
    assert scelto.name == "medio"
    assert "non rilevata" in scelto.reason


def test_every_profile_is_ordered():
    ordine = [PROFILES[n] for n in ("basso", "medio", "alto")]
    assert [p.resolution for p in ordine] == sorted(p.resolution for p in ordine)
    assert [p.texture_size for p in ordine] == sorted(p.texture_size for p in ordine)


def test_a_profile_can_be_forced():
    assert hardware.resolve("alto").name == "alto"
    assert "a mano" in hardware.resolve("alto").reason


def test_an_unknown_profile_falls_back_instead_of_failing():
    assert hardware.resolve("ultramegabello").name in PROFILES


# --------------------------------------------------------------------------- #
# Effetto sulla generazione
# --------------------------------------------------------------------------- #
def test_the_profile_scales_the_density_it_does_not_replace_it():
    """La densita' e' una scelta, il profilo dice quanto quella macchina regge.

    Le due cose si moltiplicano: chiedere meno dettaglio su una macchina veloce
    deve comunque dare meno dettaglio, e la stessa richiesta su una macchina
    lenta deve costare meno.
    """
    from app.build.builder import surface_settings

    hardware.use("basso")
    basso_normale, _ = surface_settings(1.0)
    basso_rado, _ = surface_settings(0.5)
    hardware.use("alto")
    alto_normale, _ = surface_settings(1.0)
    alto_rado, _ = surface_settings(0.5)

    assert basso_normale < alto_normale, "la macchina conta"
    assert basso_rado < basso_normale and alto_rado < alto_normale, "la densita' conta"


def test_the_smoothing_does_not_depend_on_the_machine():
    """Una macchina lenta fa lo stesso modello con meno triangoli, non piu'
    liscio: la lisciatura appartiene allo stile."""
    from app.build.builder import surface_settings

    hardware.use("basso")
    _, liscio_basso = surface_settings(1.0)
    hardware.use("alto")
    _, liscio_alto = surface_settings(1.0)
    assert liscio_basso == liscio_alto


def test_resolutions_stay_inside_sane_limits():
    hardware.use("alto")
    assert hardware.scaled(400) <= 224
    hardware.use("basso")
    assert hardware.scaled(1) >= 24


def test_a_low_profile_really_builds_something_lighter():
    hardware.use("alto")
    pesante = Session(provider=OfflineProvider())
    pesante.generate_legacy("un pesce", seed=3)
    hardware.use("basso")
    leggero = Session(provider=OfflineProvider())
    leggero.generate_legacy("un pesce", seed=3)
    assert leggero.scene.triangle_count < pesante.scene.triangle_count


# --------------------------------------------------------------------------- #
# Salvataggio periodico
# --------------------------------------------------------------------------- #
def test_an_empty_session_saves_nothing(tmp_path):
    vuota = recovery.AutoSave(Session(provider=OfflineProvider()),
                              interval=0.0, root=tmp_path)
    assert vuota.due() is False
    assert vuota.save() is None


def test_a_save_is_small(sessione, tmp_path):
    """Un progetto contiene i piani, non le mesh: salvare spesso non costa."""
    salvato = recovery.AutoSave(sessione, interval=0.0, root=tmp_path).save()
    assert salvato.is_file()
    assert salvato.stat().st_size < 200_000


def test_saving_respects_the_interval(sessione, tmp_path):
    lento = recovery.AutoSave(sessione, interval=3600.0, root=tmp_path)
    assert lento.save() is not None
    assert lento.maybe_save() is None, "troppo presto"
    assert lento.maybe_save(force=True) is not None


def test_a_partial_file_is_never_left_behind(sessione, tmp_path):
    auto = recovery.AutoSave(sessione, interval=0.0, root=tmp_path)
    auto.save()
    assert not list(auto.slot.glob("*parziale*")), "si rinomina, non si accumula"


def test_a_broken_save_does_not_stop_the_work(sessione, tmp_path, monkeypatch):
    from app.core import project

    def esplodi(*args, **kwargs):
        raise OSError("disco pieno")

    monkeypatch.setattr(project, "save", esplodi)
    auto = recovery.AutoSave(sessione, interval=0.0, root=tmp_path)
    assert auto.save() is None, "fallisce in silenzio, non solleva"


# --------------------------------------------------------------------------- #
# Recupero
# --------------------------------------------------------------------------- #
def test_a_crashed_session_is_offered_back(sessione, tmp_path):
    auto = recovery.AutoSave(sessione, interval=0.0, root=tmp_path)
    auto.save()                                     # e poi il programma muore

    trovate = recovery.pending(tmp_path)
    assert len(trovate) == 1
    assert trovate[0].versions == 1
    assert "sedia" in trovate[0].describe()


def test_a_clean_exit_leaves_nothing_to_recover(sessione, tmp_path):
    auto = recovery.AutoSave(sessione, interval=0.0, root=tmp_path)
    auto.save()
    auto.close()
    assert recovery.pending(tmp_path) == []


def test_a_recovered_session_has_all_its_versions(tmp_path):
    originale = Session(provider=OfflineProvider())
    originale.generate_legacy("una sedia", seed=1)
    originale.revariate(seed=2)
    originale.generate_legacy("un tavolo", seed=3)
    recovery.AutoSave(originale, interval=0.0, root=tmp_path).save()

    ripresa = Session(provider=OfflineProvider())
    recovery.restore(recovery.pending(tmp_path)[0], ripresa)
    assert len(ripresa.history) == 3
    assert [v.label for v in ripresa.history] == [v.label for v in originale.history]
    assert ripresa.current_plan.template == originale.current_plan.template


def test_a_discarded_recovery_is_not_deleted_immediately(sessione, tmp_path):
    """Rifiutare per errore non deve distruggere il lavoro."""
    recovery.AutoSave(sessione, interval=0.0, root=tmp_path).save()
    trovato = recovery.pending(tmp_path)[0]
    recovery.discard(trovato)
    assert recovery.pending(tmp_path) == []
    assert trovato.path.is_file(), "il file c'e' ancora"


def test_an_unreadable_state_does_not_hide_the_others(sessione, tmp_path):
    recovery.AutoSave(sessione, interval=0.0, root=tmp_path).save()
    rotta = tmp_path / "sessione_0000000000000"
    rotta.mkdir()
    (rotta / "lavoro.my3d").write_bytes(b"non e' uno zip")
    (rotta / recovery.STATE).write_text("{ questo non e' json", encoding="utf-8")
    assert len(recovery.pending(tmp_path)) == 1


def test_old_closed_sessions_are_pruned(tmp_path):
    for indice in range(6):
        sessione = Session(provider=OfflineProvider())
        sessione.generate_legacy("oggetto %d" % indice, seed=indice)
        auto = recovery.AutoSave(sessione, interval=0.0, root=tmp_path)
        auto.slot = tmp_path / ("sessione_%d" % (1000 + indice))
        auto.save()
        auto._write_state(clean=True)
    recovery.prune(tmp_path, keep=3)
    assert len(list(tmp_path.glob("sessione_*"))) == 3


def test_an_open_session_is_never_pruned(sessione, tmp_path):
    auto = recovery.AutoSave(sessione, interval=0.0, root=tmp_path)
    auto.save()
    recovery.prune(tmp_path, keep=0)
    assert recovery.pending(tmp_path), "quella aperta e' l'unica che serve"


# --------------------------------------------------------------------------- #
# La sessione
# --------------------------------------------------------------------------- #
def test_autosave_is_off_by_default():
    """Chi genera un oggetto e esce non deve lasciare file di recupero."""
    assert Session(provider=OfflineProvider())._autosave is None


def test_autosave_follows_the_work(tmp_path, monkeypatch):
    monkeypatch.setattr(recovery, "recovery_dir", lambda: tmp_path)
    sessione = Session(provider=OfflineProvider())
    sessione.start_autosave(interval=0.0)
    sessione.generate_legacy("una sedia", seed=7)
    assert recovery.pending(tmp_path), "salvato subito dopo l'azione"
    sessione.stop_autosave()
    assert recovery.pending(tmp_path) == []


# --------------------------------------------------------------------------- #
# Percorsi scrivibili una volta installato
# --------------------------------------------------------------------------- #
def test_user_data_moves_out_of_the_program_folder(monkeypatch, tmp_path):
    """Installato in Programmi non si puo' scrivere: i dati vanno nel profilo."""
    import sys as sistema

    from app.core import config

    monkeypatch.setattr(sistema, "frozen", True, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    radice = config._user_root()
    assert radice == tmp_path / "3DGen" and radice.is_dir()


def test_from_source_everything_stays_in_the_project():
    from app.core import config

    assert config.USER_ROOT == config.ROOT


# --------------------------------------------------------------------------- #
# Pacchetto
# --------------------------------------------------------------------------- #
def test_the_build_script_declares_what_is_missing():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "build3dgen", Path(__file__).resolve().parents[1] / "packaging" / "build.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    assert isinstance(modulo.check(), list)
    assert modulo.DATA and modulo.HIDDEN, "dati e import nascosti dichiarati"


def test_the_recipes_are_shipped():
    """Le ricette sono file JSON: senza, l'eseguibile parte e poi non compone."""
    import importlib.util

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "build3dgen", root / "packaging" / "build.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    inclusi = {sorgente for sorgente, _ in modulo.DATA}
    assert "app/geometry/parts" in inclusi
    assert "app/materials/finishes.json" in inclusi


def test_every_template_module_is_imported_explicitly():
    """`load_all()` importa per nome: PyInstaller non puo' indovinarli."""
    import importlib.util

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "build3dgen", root / "packaging" / "build.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)

    moduli = {p.stem for p in (root / "app" / "geometry" / "templates").glob("*.py")
              if not p.stem.startswith("_") and p.stem != "variation_profile"}
    dichiarati = {n.rsplit(".", 1)[-1] for n in modulo.HIDDEN}
    assert moduli <= dichiarati, "manca %s" % (moduli - dichiarati)


def test_the_installer_script_exists_and_ships_the_folder():
    testo = (Path(__file__).resolve().parents[1] / "packaging" / "3dgen.iss") \
        .read_text(encoding="utf-8")
    assert "dist\\3DGen\\*" in testo, "l'installer prende cio' che build.py produce"
    assert "recursesubdirs" in testo
