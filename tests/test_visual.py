"""Banchi di prova **visivi**: la correttezza strutturale non basta.

Un modello puo' avere corpo, testa, quattro zampe e una coda, essere chiuso,
passare ogni controllo semantico — ed essere una patata con degli
stuzzicadenti. Questi test misurano quello che i controlli strutturali non
guardano: se la sagoma e' articolata, se le appendici si vedono davvero, se il
conto dei triangoli e' quello di un low poly.

Nessun giudizio soggettivo e nessun modello di linguaggio: sono proiezioni e
rapporti, calcolati sempre allo stesso modo (`app/build/visual.py`).
"""
from __future__ import annotations

import numpy as np
import pytest
import trimesh

from app.ai.provider import OfflineProvider
from app.build.builder import build_scene
from app.build.visual import GRID, VisualCriteria, analyse, silhouette
from app.core.scene import Scene, SceneNode
from app.core.session import Session
from app.core.spec import GenerationPlan, MaterialSpec
from app.geometry.templates import load_all


def scena_da(mesh) -> Scene:
    scene = Scene(plan=GenerationPlan(template="freeform"))
    scene.add(SceneNode(id="c", name="c", mesh=mesh,
                        material=MaterialSpec(name="skin")))
    return scene


def creatura(prompt: str, seed: int = 7, densita: float = 1.0) -> Scene:
    session = Session(provider=OfflineProvider())
    session.generate_legacy(prompt, seed=seed)
    session.current_plan.density = densita
    session.rebuild()
    return session.scene


@pytest.fixture(scope="module")
def modelli():
    load_all()
    return {
        "pesce": creatura("un pesce"),
        "lupo": creatura("un lupo con quattro zampe e una coda"),
        "drago": creatura("un drago con quattro zampe, due ali e una lunga coda"),
        "ibrido": creatura("un pesce con il corpo di una persona e quattro braccia"),
        "umanoide": build_scene(GenerationPlan(template="humanoid",
                                               params={"height": 1.8})),
    }


# --------------------------------------------------------------------------- #
# La misura
# --------------------------------------------------------------------------- #
def test_a_convex_solid_fills_its_own_hull():
    """Taratura: una sfera *e'* il proprio inviluppo, quindi vale uno."""
    report = analyse(scena_da(trimesh.creation.icosphere(subdivisions=3, radius=0.5)))
    assert report.blobbiness > 0.95


def test_a_box_fills_its_own_hull():
    """E un cubo pure, anche se ha dodici facce sole: il campionamento e' per area."""
    assert analyse(scena_da(trimesh.creation.box((1, 1, 1)))).blobbiness > 0.95


def test_a_shape_with_limbs_does_not():
    """Una forma con appendici lascia vuoto il proprio inviluppo."""
    corpo = trimesh.creation.icosphere(subdivisions=3, radius=0.4)
    pezzi = [corpo]
    for direzione in ((1, 0, 0), (-1, 0, 0), (0, 0, 1), (0, 0, -1)):
        braccio = trimesh.creation.cylinder(radius=0.05, height=1.0)
        braccio.apply_transform(trimesh.geometry.align_vectors([0, 0, 1], direzione))
        braccio.apply_translation(np.array(direzione) * 0.6)
        pezzi.append(braccio)
    report = analyse(scena_da(trimesh.util.concatenate(pezzi)))
    assert report.blobbiness < 0.75


def test_the_silhouette_is_a_projection_not_a_render():
    """Deve funzionare senza contesto grafico: e' cio' che la rende testabile."""
    punti = np.array([[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]])
    mask = silhouette(punti, (0, 1))
    assert mask.shape == (GRID, GRID) and mask.sum() == 2


def test_an_empty_scene_is_reported_not_crashed():
    report = analyse(Scene(plan=GenerationPlan(template="freeform")))
    assert report.triangles == 0 and report.notes


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
# I cinque banchi visivi
# --------------------------------------------------------------------------- #
ATTESE = {
    # nome:      (riempimento massimo, parti visibili minime, triangoli)
    "pesce":    (0.86, 5, (800, 12_000)),
    "lupo":     (0.80, 8, (800, 12_000)),
    "drago":    (0.72, 10, (800, 12_000)),
    "ibrido":   (0.78, 10, (800, 12_000)),
    "umanoide": (0.84, 10, (800, 12_000)),
}


@pytest.mark.parametrize("nome", sorted(ATTESE))
def test_the_model_is_not_a_blob(modelli, nome):
    """Il banco visivo: sagoma articolata, appendici visibili, low poly."""
    riempimento, parti, triangoli = ATTESE[nome]
    report = analyse(modelli[nome])
    criteri = VisualCriteria(max_blobbiness=riempimento, min_visible_parts=parti,
                             triangle_range=triangoli, max_largest_share=0.92)
    difetti = criteri.check(report)
    assert not difetti, "%s: %s  (%s)" % (nome, "; ".join(difetti), report.describe())


def test_a_creature_is_more_articulated_than_an_ellipsoid(modelli):
    """Il confronto che conta: meglio della forma da cui siamo partiti.

    Il pesce di prima era un ellissoide con una testa incollata. Qualunque
    modifica futura che lo riportasse li' fa cadere questo test.
    """
    ellissoide = trimesh.creation.icosphere(subdivisions=4, radius=0.5)
    ellissoide.apply_scale([2.2, 0.9, 0.5])
    riferimento = analyse(scena_da(ellissoide)).blobbiness
    for nome in ("pesce", "lupo", "drago"):
        assert analyse(modelli[nome]).blobbiness < riferimento - 0.10, nome


def test_no_part_dominates_the_whole_model(modelli):
    """Se una parte vale quasi tutta la superficie, le altre sono decorazioni."""
    for nome, scene in modelli.items():
        assert analyse(scene).largest_share < 0.92, nome


def test_every_creature_stays_in_the_low_poly_band(modelli):
    """Low poly e' un requisito del prodotto, non un caso fortunato."""
    for nome, scene in modelli.items():
        assert 800 <= scene.triangle_count <= 12_000, "%s: %d" % (nome, scene.triangle_count)


def test_density_moves_the_triangle_count(modelli):
    """La densita' deve poter chiedere piu' o meno dettaglio, a stile invariato."""
    leggero = creatura("un pesce", densita=0.5).triangle_count
    pesante = creatura("un pesce", densita=1.8).triangle_count
    assert leggero < modelli["pesce"].triangle_count < pesante


# --------------------------------------------------------------------------- #
# Proporzioni
# --------------------------------------------------------------------------- #
def test_a_humanoid_is_as_tall_as_requested():
    """Chiedere 1,80 e ottenere 1,63 non e' una proporzione, e' un errore."""
    load_all()
    for altezza in (1.2, 1.8, 2.6):
        scene = build_scene(GenerationPlan(template="humanoid",
                                           params={"height": altezza}))
        alto = float(scene.to_trimesh_scene(textured=False).to_geometry().extents[1])
        assert alto == pytest.approx(altezza, rel=0.04), "%.1f -> %.3f" % (altezza, alto)


def test_a_humanoid_keeps_its_proportions_at_any_size():
    """Raddoppiare l'altezza non deve dare un torso gigante con braccine."""
    load_all()
    misure = []
    for altezza in (1.2, 2.4):
        scene = build_scene(GenerationPlan(template="humanoid",
                                           params={"height": altezza}))
        per_id = {n.id: n for n in scene.nodes}
        torso = float(per_id["torso"].mesh.extents[1])
        braccio = float(per_id["braccio_l"].mesh.extents.max())
        testa = float(per_id["testa"].mesh.extents.max())
        misure.append((torso / altezza, braccio / altezza, testa / altezza))
    for piccolo, grande in zip(*misure):
        assert piccolo == pytest.approx(grande, rel=0.15)


def test_a_humanoid_is_not_wider_than_it_is_tall():
    load_all()
    scene = build_scene(GenerationPlan(template="humanoid",
                                       params={"height": 1.8}))
    estensione = scene.to_trimesh_scene(textured=False).to_geometry().extents
    assert estensione[0] < estensione[1] * 0.62


def test_the_humanoid_has_the_parts_a_humanoid_has(modelli):
    """Torace, testa, due braccia con gomito, due gambe con ginocchio, mani, piedi."""
    presenti = {n.id for n in modelli["umanoide"].nodes}
    for atteso in ("torso", "testa", "braccio_l", "avambraccio_l", "mano_l",
                   "coscia_r", "stinco_r", "piede_r"):
        assert atteso in presenti, atteso
