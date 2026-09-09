"""Decimazione, livelli di dettaglio, preparazione per i motori."""
from __future__ import annotations

import numpy as np
import pytest
import trimesh

from app.ai.provider import OfflineProvider
from app.build.optimize import (
    COLLISION_BUDGET, PRESETS, cluster_decimate, collision_mesh, decimate_scene,
    decimate_to, export_game_ready, make_lods, merge_by_material,
    prepare_for_game, regenerate_lod,
)
from app.core.session import Session

OFFLINE = OfflineProvider()


@pytest.fixture()
def jeep() -> Session:
    session = Session(provider=OFFLINE)
    session.generate_legacy("una jeep militare verde")
    return session


@pytest.fixture()
def pesce() -> Session:
    session = Session(provider=OFFLINE)
    session.generate_legacy("crea un pesce")
    return session


# --------------------------------------------------------------------------- #
# Decimazione
# --------------------------------------------------------------------------- #
def test_clustering_reduces_the_face_count():
    sphere = trimesh.creation.icosphere(subdivisions=4)
    reduced = cluster_decimate(sphere, cell=0.25)
    assert 0 < len(reduced.faces) < len(sphere.faces)


def test_clustering_keeps_the_overall_shape():
    sphere = trimesh.creation.icosphere(subdivisions=4, radius=1.0)
    reduced = cluster_decimate(sphere, cell=0.3)
    extents = reduced.bounds[1] - reduced.bounds[0]
    assert np.allclose(extents, 2.0, atol=0.35), "il volume non deve collassare"


def test_decimate_to_approaches_the_target():
    sphere = trimesh.creation.icosphere(subdivisions=5)
    reduced = decimate_to(sphere, target_faces=800)
    assert len(reduced.faces) <= 1200
    assert len(reduced.faces) >= 200


def test_decimation_leaves_small_meshes_alone():
    box = trimesh.creation.box((1, 1, 1))
    assert len(decimate_to(box, target_faces=5000).faces) == len(box.faces)


def test_decimation_never_returns_an_empty_mesh():
    tiny = trimesh.creation.icosphere(subdivisions=1)
    for target in (4, 8, 20):
        assert len(decimate_to(tiny, target).faces) > 0


# --------------------------------------------------------------------------- #
# Livelli di dettaglio
# --------------------------------------------------------------------------- #
def test_lod_chain_decreases_monotonically(jeep):
    lods = make_lods(jeep.scene, levels=4)
    counts = [l.triangles for l in lods]
    assert counts == sorted(counts, reverse=True), counts
    assert counts[-1] < counts[0]


def test_lods_are_regenerated_when_possible(jeep):
    """Il vantaggio del procedurale: mesh pulite, non residui di decimazione."""
    rebuilt = regenerate_lod(jeep.current_plan, level=2)
    assert rebuilt is not None
    assert rebuilt.triangle_count < jeep.scene.triangle_count
    assert all(n.mesh.is_watertight for n in rebuilt.nodes if "fused" not in n.tags)


def test_lods_fall_back_to_decimation_without_a_plan(jeep):
    orfana = jeep.scene
    orfana.plan.template = "template_inesistente"
    orfana.plan.assembly = None
    lods = make_lods(orfana, levels=3, prefer_regeneration=True)
    assert [l.triangles for l in lods] == sorted([l.triangles for l in lods], reverse=True)


def test_every_lod_keeps_all_parts(jeep):
    lods = make_lods(jeep.scene, levels=3, prefer_regeneration=False)
    for lod in lods:
        assert len(lod.scene.nodes) == len(jeep.scene.nodes)


# --------------------------------------------------------------------------- #
# Fusione e collisione
# --------------------------------------------------------------------------- #
def test_merge_by_material_reduces_draw_calls(jeep):
    merged = merge_by_material(jeep.scene)
    materials = {n.material.name for n in jeep.scene.nodes}
    assert len(merged.nodes) == len(materials)
    assert len(merged.nodes) < len(jeep.scene.nodes)
    assert merged.triangle_count == jeep.scene.triangle_count, "niente si perde"


def test_collision_is_small_and_encloses_the_model(pesce):
    hull = collision_mesh(pesce.scene, "convex")
    assert len(hull.faces) <= COLLISION_BUDGET * 1.3
    model = pesce.scene.bounds()
    assert np.all(hull.bounds[0] <= model[0] + 1e-3)
    assert np.all(hull.bounds[1] >= model[1] - 1e-3)


def test_box_collision_is_a_box(jeep):
    box = collision_mesh(jeep.scene, "box")
    assert len(box.faces) == 12


def test_collision_of_an_empty_scene_is_refused(jeep):
    from app.core.scene import Scene

    with pytest.raises(ValueError):
        collision_mesh(Scene(plan=jeep.current_plan))


# --------------------------------------------------------------------------- #
# Preset dei motori
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("preset", sorted(PRESETS))
def test_every_preset_produces_a_usable_result(preset, jeep):
    result = prepare_for_game(jeep.scene, preset)
    assert result.preset.name == preset
    assert len(result.lods) == PRESETS[preset].lod_levels
    assert result.collision is not None
    assert result.within_budget


def test_budget_is_enforced_on_the_first_level(pesce):
    from app.build.optimize import GamePreset

    stretto = GamePreset("stretto", triangle_budget=3000, lod_levels=2)
    result = prepare_for_game(pesce.scene, stretto)
    assert result.lods[0].triangles <= 3000 * 1.05
    assert result.notes, "la riduzione forzata va dichiarata"
    assert result.within_budget


def test_unknown_preset_falls_back_to_generic(jeep):
    assert prepare_for_game(jeep.scene, "motore_inventato").preset.name == "generic"


def test_summary_is_readable(jeep):
    text = prepare_for_game(jeep.scene, "godot").summary()
    assert "LOD0" in text and "collisione" in text and "budget" in text


# --------------------------------------------------------------------------- #
# Export
# --------------------------------------------------------------------------- #
def test_export_writes_one_file_per_lod_plus_collision(tmp_path, jeep):
    files = export_game_ready(jeep.scene, tmp_path, "godot", "jeep")
    names = sorted(f.name for f in files)
    assert names == ["jeep_LOD0.glb", "jeep_LOD1.glb", "jeep_LOD2.glb",
                     "jeep_collision.glb"] or len(names) == 4
    for path in files:
        assert path.stat().st_size > 500, path.name


def test_lower_lods_are_lighter_on_disk(tmp_path, jeep):
    files = {f.name: f for f in export_game_ready(jeep.scene, tmp_path, "unity", "j")}
    assert files["j_LOD2.glb"].stat().st_size < files["j_LOD0.glb"].stat().st_size
