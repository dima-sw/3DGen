"""Banchi di prova **visivi**: la correttezza strutturale non basta.

Un modello puo' avere corpo, testa, quattro zampe e una coda, essere chiuso,
passare ogni controllo semantico — ed essere una patata con degli
stuzzicadenti. Questi test misurano quello che i controlli strutturali non
guardano: se la sagoma e' articolata, se le appendici si vedono davvero, se il
conto dei triangoli e' quello di un low poly.

Nessun giudizio soggettivo e nessun modello di linguaggio: sono proiezioni e
rapporti, calcolati sempre allo stesso modo (`app/build/visual.py`).

I modelli su cui si misura sono cambiati — vengono dalla composizione e non
piu' dal campo implicito — e con loro i numeri attesi, che sono stati
**rimisurati** e non adattati finche' passavano.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
import trimesh

from app.ai.provider import OfflineProvider
from app.build.visual import GRID, VisualCriteria, analyse, silhouette
from app.core.material import MaterialSpec
from app.core.planner.planner import MockPlanner
from app.core.scene import Scene, SceneNode
from app.core.session import Options, Session

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_scenari import COPIONI                        # noqa: E402


def scena_da(mesh) -> Scene:
    scene = Scene(plan=None)
    scene.add(SceneNode(id="c", name="c", mesh=mesh,
                        material=MaterialSpec(name="skin")))
    return scene


@pytest.fixture(scope="module")
def modelli():
    """I modelli veri, generati una volta sola dalla porta unica."""
    sessione = Session(provider=OfflineProvider(),
                       planner=MockPlanner(scripts=COPIONI))
    casi = {
        "figura": ("una persona con la testa di rana e le gambe di spada, "
                   "molto alta e magra", 2),
        "mostro": ("persona con testa di rana, corpo di pesce, gambe di spada, "
                   "capelli con casco, piercing al naso, molto alta e magra", 2),
        "albero": ("un albero con un nido e un uccello sopra", 2),
        "robot": ("un robot con testa di drago, corpo di pesce, ali e "
                  "cristalli luminosi", 2),
        "casa": ("una casa con un pianeta enorme sopra", 3),
    }
    fuori = {}
    for nome, (prompt, dettaglio) in casi.items():
        risultato = sessione.generate(prompt, Options(detail_level=dettaglio))
        fuori[nome] = risultato.scene(sessione.catalog())
    return fuori


# --------------------------------------------------------------------------- #
# La misura
# --------------------------------------------------------------------------- #
def test_a_convex_solid_fills_its_own_hull():
    """Taratura: una sfera *e'* il proprio inviluppo, quindi vale uno."""
    report = analyse(scena_da(trimesh.creation.icosphere(subdivisions=3,
                                                         radius=0.5)))
    assert report.blobbiness > 0.95


def test_a_box_fills_its_own_hull():
    report = analyse(scena_da(trimesh.creation.box(extents=(1, 1, 1))))
    assert report.blobbiness > 0.95


def test_a_shape_with_limbs_does_not():
    """Un corpo con quattro braccia lascia dei vuoti, e la misura li vede."""
    pezzi = [trimesh.creation.box(extents=(0.4, 0.6, 0.4))]
    for dx, dz in ((0.5, 0.5), (-0.5, 0.5), (0.5, -0.5), (-0.5, -0.5)):
        arto = trimesh.creation.box(extents=(0.08, 0.5, 0.08))
        arto.apply_translation([dx, -0.4, dz])
        pezzi.append(arto)
    report = analyse(scena_da(trimesh.util.concatenate(pezzi)))
    assert report.blobbiness < 0.6


def test_the_silhouette_is_a_projection_not_a_render():
    """La sagoma e' una griglia di celle piene: nessun renderer nel mezzo."""
    import numpy as np

    # `_dense_points` distribuisce i punti in proporzione all'area: e' cio' che
    # il modulo usa davvero, e con un campionamento uniforme la sagoma di un
    # cubo resterebbe bucherellata
    from app.build.visual import _dense_points

    cubo = trimesh.creation.box(extents=(1, 1, 1))
    maschera = silhouette(_dense_points(cubo), (0, 1))
    assert maschera.shape == (GRID, GRID)
    assert maschera.dtype == bool
    # quasi tutte: una nuvola campionata lascia qualche cella vuota per caso,
    # e pretendere il 100% misurerebbe il campionamento invece della sagoma
    assert maschera.mean() > 0.9, "un cubo visto di fronte riempie quasi tutto"


def test_an_empty_scene_is_reported_not_crashed():
    report = analyse(Scene(plan=None))
    assert report.triangles == 0
    assert any("vuot" in n.lower() for n in report.notes)


# --------------------------------------------------------------------------- #
# I criteri
# --------------------------------------------------------------------------- #
def test_criteria_catch_a_blob():
    difetti = VisualCriteria().check(
        analyse(scena_da(trimesh.creation.icosphere(subdivisions=4, radius=0.5))))
    assert any("blob" in d for d in difetti)


def test_criteria_catch_too_many_triangles():
    denso = trimesh.creation.icosphere(subdivisions=6, radius=0.5)
    difetti = VisualCriteria(triangle_range=(200, 5000)).check(analyse(scena_da(denso)))
    assert any("triangoli" in d for d in difetti)


# --------------------------------------------------------------------------- #
# I banchi visivi, sui modelli veri
# --------------------------------------------------------------------------- #
# nome: (riempimento massimo, parti visibili minime, intervallo di triangoli)
# Numeri **misurati** sui modelli di adesso, con un po' di margine. Alzarli
# perche' un test passi vorrebbe dire spegnere il test.
ATTESE = {
    "figura": (0.80, 5, (200, 3200)),
    "mostro": (0.62, 8, (300, 3200)),
    "albero": (0.80, 3, (150, 3200)),
    "robot": (0.68, 5, (200, 3200)),
}


@pytest.mark.parametrize("nome", sorted(ATTESE))
def test_the_model_is_not_a_blob(modelli, nome):
    """Il banco visivo: sagoma articolata, appendici visibili, low poly."""
    riempimento, parti, triangoli = ATTESE[nome]
    report = analyse(modelli[nome])
    criteri = VisualCriteria(max_blobbiness=riempimento, min_visible_parts=parti,
                             triangle_range=triangoli, max_largest_share=0.92)
    difetti = criteri.check(report)
    assert not difetti, "%s: %s  (%s)" % (nome, "; ".join(difetti),
                                          report.describe())


def test_a_figure_is_more_articulated_than_a_planet(modelli):
    """La misura distingue una figura da una massa, ed e' tutto cio' che deve fare.

    Una casa con un pianeta enorme sopra riempie la propria sagoma: e' una
    palla, e non e' un difetto — e' un pianeta. Per questo il criterio del
    riempimento **non** si applica a tutto: si applica a cio' che dovrebbe
    avere delle appendici.
    """
    assert analyse(modelli["mostro"]).blobbiness < 0.7
    assert analyse(modelli["casa"]).blobbiness > 0.9


def test_no_part_dominates_the_whole_model(modelli):
    for nome in ATTESE:
        quota = analyse(modelli[nome]).largest_share
        assert quota < 0.92, "%s: una parte sola e' il %.0f%%" % (nome, quota * 100)


def test_every_model_stays_in_the_low_poly_band(modelli):
    for nome, scena in modelli.items():
        assert 100 < scena.triangle_count < 3500, \
            "%s: %d triangoli" % (nome, scena.triangle_count)


def test_detail_moves_the_number_of_parts():
    """Il dettaglio cambia **quante parti** ci sono, non quanto sono dense.

    Non e' un dettaglio di lessico: al livello alto un pezzo unico puo'
    diventare due pezzi piu' piccoli, e i triangoli possono perfino calare.
    Quello che cresce e' il numero di parti.
    """
    sessione = Session(provider=OfflineProvider(), planner=MockPlanner())
    parti = [len(sessione.generate("un albero con un nido e un uccello",
                                   Options(detail_level=n)).build.geometry())
             for n in (1, 3)]
    assert parti[1] > parti[0]


def test_the_measure_is_deterministic(modelli):
    misure = {round(analyse(modelli["mostro"]).blobbiness, 6) for _ in range(3)}
    assert len(misure) == 1


def test_the_parts_of_a_model_are_named_and_coloured(modelli):
    """Ogni pezzo ha un nome leggibile e un materiale vero, non un grigio."""
    scena = modelli["albero"]
    assert all(n.name and n.name[0].isupper() for n in scena.nodes)
    colori = {n.material.base_color for n in scena.nodes}
    assert len(colori) > 1, "un albero non e' tutto dello stesso colore"
    assert all(np.isfinite(n.mesh.bounds).all() for n in scena.nodes)
