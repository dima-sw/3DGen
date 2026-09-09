"""Riconoscimento per sagoma: confronto con il catalogo procedurale.

Non e' un classificatore addestrato e non pretende di esserlo: deve sapere
distinguere un'auto da un albero, e deve tacere quando non e' sicuro.
"""
from __future__ import annotations

import numpy as np
import pytest

from app.ai import shape_match
from app.ai.shape_match import BANDS, ShapeMatch, profile_from_mask


def maschera(righe: int, colonne: int, fasce) -> np.ndarray:
    """Costruisce una sagoma da larghezze relative, dal basso verso l'alto."""
    mask = np.zeros((righe, colonne), dtype=bool)
    for indice, larghezza in enumerate(fasce):
        y0 = righe - int(righe * (indice + 1) / len(fasce))
        y1 = righe - int(righe * indice / len(fasce))
        spessore = max(int(colonne * larghezza), 1)
        x0 = (colonne - spessore) // 2
        mask[y0:y1, x0:x0 + spessore] = True
    return mask


AUTO = [1.0, 1.0, 1.0, 0.55, 0.45, 0.4]        # larga sotto, cabina stretta
ALBERO = [0.15, 0.15, 0.8, 1.0, 0.95, 0.6]     # tronco sottile, chioma larga
TAVOLO = [0.12, 0.12, 0.12, 0.12, 1.0, 1.0]    # gambe sottili, piano largo


# --------------------------------------------------------------------------- #
# Profili
# --------------------------------------------------------------------------- #
def test_a_profile_has_a_fixed_length_and_is_normalised():
    profilo = profile_from_mask(maschera(120, 120, AUTO))
    assert len(profilo) == BANDS
    assert profilo.max() == pytest.approx(1.0, abs=0.02)
    assert profilo.min() >= 0.0


def test_a_profile_reads_from_the_bottom_up():
    profilo = profile_from_mask(maschera(120, 120, ALBERO))
    assert profilo[0] < 0.4, "il tronco e' in basso"
    assert profilo[len(profilo) // 2] > 0.7, "la chioma e' in mezzo"


def test_a_profile_ignores_the_scale():
    piccola = profile_from_mask(maschera(60, 60, AUTO))
    grande = profile_from_mask(maschera(240, 240, AUTO))
    assert np.abs(piccola - grande).mean() < 0.06


def test_an_empty_mask_gives_an_empty_profile():
    assert profile_from_mask(np.zeros((10, 10), dtype=bool)).sum() == 0


# --------------------------------------------------------------------------- #
# Rasterizzazione di una mesh
# --------------------------------------------------------------------------- #
def test_a_box_has_a_constant_profile():
    import trimesh

    profilo = profile_from_mask(shape_match.rasterize_side(trimesh.creation.box((2, 1, 1))))
    assert profilo.min() > 0.9, "un parallelepipedo e' largo uguale a ogni altezza"


def test_a_cone_narrows_towards_the_top():
    """La verticale e' Y, come in tutto il progetto: il cono va ruotato.

    trimesh costruisce i solidi di rivoluzione lungo Z; se il cono resta
    coricato la sagoma laterale e' un cerchio, non un triangolo, ed e' proprio
    questo che il confronto per sagoma deve vedere.
    """
    import trimesh

    coricato = trimesh.creation.cone(radius=1.0, height=2.0)
    in_piedi = coricato.copy()
    in_piedi.apply_transform(trimesh.transformations.rotation_matrix(
        -np.pi / 2, [1, 0, 0]))

    profilo = profile_from_mask(shape_match.rasterize_side(in_piedi))
    assert profilo[1] > 0.8, "largo alla base"
    assert profilo[-2] < 0.35, "stretto in punta"

    orizzontale = profile_from_mask(shape_match.rasterize_side(coricato))
    assert orizzontale[len(orizzontale) // 2] > profilo[len(profilo) // 2]


def test_an_empty_mesh_does_not_explode():
    import trimesh

    vuota = trimesh.Trimesh(vertices=np.zeros((0, 3)), faces=np.zeros((0, 3), dtype=int))
    assert shape_match.rasterize_side(vuota).sum() == 0


# --------------------------------------------------------------------------- #
# Il catalogo
# --------------------------------------------------------------------------- #
def test_the_catalog_covers_the_templates():
    voci = shape_match.catalog()
    assert {"vehicle", "tree", "house", "chair", "table"} <= set(voci)
    assert "primitive" not in voci, "un cubo somiglia a tutto"
    for nome, (profilo, aspetto) in voci.items():
        assert len(profilo) == BANDS, nome
        assert aspetto > 0.0, nome


def test_the_catalog_is_computed_once():
    prima = shape_match.catalog()
    assert shape_match.catalog() is prima


def test_the_catalog_is_not_slow():
    """Il riconoscimento non deve costare piu' della generazione stessa."""
    import time

    shape_match._CATALOG = None
    inizio = time.perf_counter()
    shape_match.catalog()
    assert time.perf_counter() - inizio < 8.0


# --------------------------------------------------------------------------- #
# Confronto
# --------------------------------------------------------------------------- #
def test_a_shape_matches_itself():
    profilo, aspetto = shape_match.catalog()["vehicle"]
    assert shape_match.distance(profilo, aspetto, profilo, aspetto) == pytest.approx(0.0)


def test_a_car_silhouette_finds_the_vehicle():
    esito = shape_match.match(maschera(100, 260, AUTO), 2.6)
    assert esito is not None and esito.template == "vehicle"
    assert esito.confident


def test_a_tree_silhouette_finds_the_tree():
    esito = shape_match.match(maschera(260, 140, ALBERO), 0.54)
    assert esito is not None and esito.template == "tree"


def test_a_table_silhouette_finds_the_table():
    esito = shape_match.match(maschera(120, 220, TAVOLO), 1.85)
    assert esito is not None and esito.template == "table"


def test_proportions_matter_not_only_the_profile():
    """Stesso profilo, proporzioni diverse: la distanza deve cambiare."""
    profilo = profile_from_mask(maschera(100, 260, AUTO))
    vicino = shape_match.distance(profilo, 2.6, profilo, 2.6)
    lontano = shape_match.distance(profilo, 2.6, profilo, 0.3)
    assert lontano > vicino


def test_an_ambiguous_shape_is_not_claimed():
    """Fra due candidati equivalenti non si sceglie: si dichiara l'incertezza."""
    ambigua = shape_match.ShapeMatch(template="chair", distance=0.2,
                                     confident=False, runner_up="table")
    assert "nessuna forma riconosciuta" in ambigua.describe()


def test_uncertainty_is_measured_against_the_runner_up(monkeypatch):
    finto = {"alfa": (np.ones(BANDS), 1.0),
             "beta": (np.ones(BANDS) * 0.999, 1.0)}
    monkeypatch.setattr(shape_match, "_CATALOG", finto)
    esito = shape_match.match(maschera(100, 100, [1.0] * 6), 1.0)
    assert esito is not None and not esito.confident, "i due candidati sono pari"
    assert esito.runner_up in finto


def test_no_catalog_means_no_guess(monkeypatch):
    monkeypatch.setattr(shape_match, "_CATALOG", {})
    assert shape_match.match(maschera(100, 100, AUTO), 2.6) is None
