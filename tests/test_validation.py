"""Quello che la scena porta con se' delle diagnosi.

Questo file conteneva il validatore **semantico** della pipeline storica: le
regole per cui un pesce deve avere una coda, la coda deve stare dietro, e un
arto non puo' essere piu' lungo del corpo. Quelle regole sapevano che cosa
fosse un pesce, ed e' esattamente cio' che l'architettura nuova non vuole nel
core: un plugin che porta una creatura che non c'entra niente con un pesce non
puo' essere giudicato da una tabella scritta a Milano nel 2025.

Al loro posto c'e' `app/build/validate.py`, che misura **cio' che il componente
dichiara** — chiusura, connessione, giunti, compenetrazione, planarita' — ed e'
provato in `test_build_pipeline.py`. Qui resta la parte che sopravvive a quel
cambio: che le diagnosi arrivino fino alla scena, leggibili da un programma e
da una persona, senza fermare la costruzione.
"""
from __future__ import annotations

import pytest

from app.ai.provider import OfflineProvider
from app.core.capability import Requirement
from app.core.errors import ERROR
from app.core.graph import CompositionGraph
from app.core.planner.planner import MockPlanner
from app.core.session import Options, Session


@pytest.fixture(scope="module")
def sessione() -> Session:
    return Session(provider=OfflineProvider(), planner=MockPlanner())


def test_a_healthy_model_carries_no_errors(sessione):
    sessione.generate("un albero con un nido e un uccello sopra")
    scena = sessione.scene
    assert hasattr(scena, "issues")
    assert not [i for i in scena.issues if i.severity == ERROR], \
        [i.describe() for i in scena.issues]


def test_the_issues_are_machine_readable(sessione):
    """Una diagnosi ha dei campi, non una frase da interpretare."""
    risultato = sessione.generate("una casa con un pianeta enorme sopra")
    for diagnosi in risultato.diagnostics:
        assert diagnosi.code and diagnosi.code.isupper()
        assert diagnosi.severity in ("error", "warning", "info")
        assert isinstance(diagnosi.describe(), str)


def test_a_broken_plan_reaches_the_scene_warnings(sessione):
    """Un pezzo che non si attacca non ferma il modello: lo si dice e si va avanti."""
    g = CompositionGraph()
    g.set_root("casa", "architecture:house")
    g.add_child("testa", "creature:dragon_head", "casa",
                requirement=Requirement(capability="opening"))

    risultato = sessione.build(g, Options(repair=False))
    scena = risultato.scene(sessione.catalog())
    assert scena.nodes, "il modello si costruisce lo stesso"
    assert any("dragon_head" in w for w in scena.warnings), scena.warnings


def test_the_report_says_where_and_why(sessione):
    g = CompositionGraph()
    g.set_root("casa", "architecture:house")
    g.add_child("testa", "creature:dragon_head", "casa",
                requirement=Requirement(capability="opening"))

    risultato = sessione.build(g, Options(repair=False))
    gravi = [d for d in risultato.diagnostics if d.fatal]
    assert gravi
    assert gravi[0].where, "una diagnosi senza 'dove' non si corregge"
    assert gravi[0].why or gravi[0].alternatives


def test_geometry_requirements_are_the_plugin_s_own(sessione):
    """Solo cio' che un componente dichiara viene preteso.

    E' la regola che sostituisce le vecchie tabelle anatomiche: il pianeta
    dichiara `watertight` e `faceted`, e viene misurato su quelle due cose. Chi
    non dichiara niente non viene giudicato.
    """
    pianeta = sessione.catalog().component("space:planet")
    assert "watertight" in pianeta.requires
    assert "faceted" in pianeta.requires

    lamina = sessione.catalog().component("accessories:visor")
    assert not lamina.requires, "una lamina aperta e' aperta apposta"


def test_a_model_is_built_even_when_something_is_wrong(sessione):
    """Nessuna diagnosi solleva: si costruisce quel che si puo'."""
    g = CompositionGraph()
    g.set_root("corpo", "humanoid:body", height=1.8)
    g.add_child("torso", "humanoid:torso", "corpo",
                requirement=Requirement(capability="core_mount"))
    g.add_child("assurdo", "space:planet", "torso",
                requirement=Requirement(capability="head_mount"))

    risultato = sessione.build(g, Options(repair=False))
    assert risultato.build is not None and risultato.build.meshes()
    assert risultato.skipped() or not risultato.report.ok
