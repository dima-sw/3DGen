"""Quanto costa, e come cresce.

Due domande diverse, e nessuna delle due e' "e' abbastanza veloce?".

    baseline   quanto costa oggi una generazione, passo per passo
    scala      che cosa succede con 100, 500, 1000 componenti installati

I tetti sono **larghi**: dieci volte le misure prese su una macchina normale.
Non servono a difendere una prestazione, servono ad accorgersi di un
peggioramento di un ordine di grandezza — un `O(n^2)` nascosto, un file riletto
a ogni chiamata, una cache che ha smesso di funzionare. Un test di prestazione
stretto su una macchina qualunque e' un test che fallisce a caso.

Nessuna ottimizzazione parte da qui. Parte da una misura che peggiora.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from app.ai.provider import OfflineProvider
from app.core.capability import Capability, Requirement, mount
from app.core.component import Component, Piece
from app.core.graph import CompositionGraph
from app.core.params import DISTANCE, ParamSpec
from app.core.planner.planner import MockPlanner
from app.core.planner.vocabulary import build_vocabulary
from app.core.registry import Registry, load
from app.core.resolver import resolve
from app.core.session import Session
from app.core.socket import socket
from app.core.authoring import base_socket
from app.geometry.kernel import block

PLUGIN = Path(__file__).resolve().parent.parent / "app" / "plugins"

# Millisecondi. Misurati il 10 settembre 2026 su una macchina normale e
# moltiplicati per dieci: vedi il modulo per il perche'.
TETTI = {
    "caricamento": 400.0,      # misurato 16
    "vocabolario": 60.0,       # misurato 2,7
    "generazione": 300.0,      # misurato 6-13
}


def millisecondi(fai) -> float:
    inizio = time.perf_counter()
    fai()
    return (time.perf_counter() - inizio) * 1000.0


def mediana(fai, quante: int = 5) -> float:
    """La mediana di piu' misure: una sola su una macchina condivisa non dice niente."""
    import statistics

    return statistics.median(millisecondi(fai) for _ in range(quante))


@pytest.fixture(scope="module")
def catalogo():
    return load([PLUGIN]).freeze()


# --------------------------------------------------------------------------- #
# La linea di partenza
# --------------------------------------------------------------------------- #
def test_loading_the_plugins_is_fast_enough():
    assert mediana(lambda: load([PLUGIN]).freeze(), 3) < TETTI["caricamento"]


def test_building_the_vocabulary_is_fast_enough(catalogo):
    assert mediana(lambda: build_vocabulary(catalogo)) < TETTI["vocabolario"]


def test_a_whole_generation_is_fast_enough(catalogo):
    sessione = Session(provider=OfflineProvider(), planner=MockPlanner(),
                       registry=catalogo)
    sessione.generate("una casa con un pianeta enorme sopra", remember=False)
    assert mediana(lambda: sessione.generate(
        "una casa con un pianeta enorme sopra", remember=False), 3) \
        < TETTI["generazione"]


def test_the_vocabulary_is_cached_between_calls(catalogo):
    """Due generazioni non ricostruiscono due volte lo stesso vocabolario."""
    sessione = Session(provider=OfflineProvider(), planner=MockPlanner(),
                       registry=catalogo)
    assert sessione.vocabulary() is sessione.vocabulary()


# --------------------------------------------------------------------------- #
# Come cresce
# --------------------------------------------------------------------------- #
def _finto(indice: int) -> Component:
    """Un componente leggero ma vero: geometria, parametri, innesti.

    Non un segnaposto: se lo fosse, il test misurerebbe un dizionario invece
    del registry. Ogni pezzo fornisce una capability comune e una propria, cosi'
    le ricerche hanno davvero qualcosa da filtrare.
    """
    def costruisci(v, ctx) -> Piece:
        mesh = block((v["size"], v["size"], v["size"]), sides=4, axis=1)
        return Piece(mesh=mesh, material="metal", tags=("finto",), sockets={
            "base": base_socket(v["size"] * 0.5, axis="+Y"),
            "cima": socket("cima", (0, v["size"], 0), (0, 1, 0), up=(0, 0, 1),
                           radius=v["size"] * 0.4, provides="end_mount")})

    return Component(
        id="scala:pezzo_%04d" % indice, build=costruisci,
        description="pezzo numero %d di un catalogo grande" % indice,
        params={"size": ParamSpec(0.2, DISTANCE, min=0.01, max=2.0,
                                  semantic_role="girth")},
        provides=(Capability("end_mount"), Capability("gruppo_%d" % (indice % 17))),
        mounts=(mount("end_mount", socket_id="cima"),),
        tags=frozenset({"finto", "gruppo_%d" % (indice % 17)}))


def registro_grande(quanti: int) -> Registry:
    registro = Registry()
    for indice in range(quanti):
        registro.register_component(_finto(indice))
    return registro.freeze()


@pytest.mark.parametrize("quanti", [100, 500, 1000])
def test_a_big_catalogue_stays_usable(quanti):
    """Mille componenti installati: scoperta, vocabolario, ricerche, risoluzione.

    Non e' un obiettivo di prodotto — nessuno ha mille plugin oggi. Serve a
    sapere **dove** cominciano i problemi prima di trovarli addosso.
    """
    registro = registro_grande(quanti)
    assert len(registro.components()) == quanti

    vocabolario = build_vocabulary(registro)
    assert len(vocabolario.components) == quanti

    # le ricerche che il resolver e il planner fanno davvero
    assert registro.component("scala:pezzo_0007") is not None
    assert len(registro.providers(capability="end_mount")) == quanti
    assert len(registro.providers(capability="gruppo_3")) >= 1
    assert registro.search("pezzo")

    grafo = CompositionGraph()
    grafo.set_root("radice", "scala:pezzo_0000")
    for indice in range(1, 6):
        grafo.add_child("p%d" % indice, "scala:pezzo_%04d" % indice,
                        "p%d" % (indice - 1) if indice > 1 else "radice",
                        requirement=Requirement(capability="end_mount"))
    risolto = resolve(grafo, registro)
    assert risolto.ok, risolto.report.describe()
    assert len(risolto) == 6


def test_the_cost_grows_with_the_catalogue_but_not_explosively():
    """Da 100 a 1000 componenti il costo cresce, e resta lineare abbastanza.

    Il fattore dieci sui componenti non deve diventare un fattore cento sul
    tempo: quello sarebbe una ricerca dentro una ricerca, ed e' esattamente il
    genere di cosa che questo test esiste per trovare.
    """
    piccolo = registro_grande(100)
    grande = registro_grande(1000)

    def cerca(registro):
        registro.component("scala:pezzo_0050")
        registro.providers(capability="end_mount")
        registro.search("pezzo")

    corto = mediana(lambda: cerca(piccolo))
    lungo = mediana(lambda: cerca(grande))
    assert lungo < max(corto, 0.05) * 60, (corto, lungo)


def test_a_lookup_by_id_does_not_scan_the_catalogue():
    """Cercare per id deve costare uguale con cento pezzi e con mille."""
    piccolo = registro_grande(100)
    grande = registro_grande(1000)
    corto = mediana(lambda: [piccolo.component("scala:pezzo_0050")
                             for _ in range(200)])
    lungo = mediana(lambda: [grande.component("scala:pezzo_0050")
                             for _ in range(200)])
    assert lungo < max(corto, 0.05) * 6, (corto, lungo)


def test_a_big_catalogue_is_still_deterministic():
    """Con mille componenti l'ordine delle risposte resta lo stesso."""
    registro = registro_grande(300)
    risposte = {tuple(c.id for c in registro.providers(capability="end_mount"))
                for _ in range(3)}
    assert len(risposte) == 1
