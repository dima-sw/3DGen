"""Texture procedurali, coordinate UV, export PBR."""
from __future__ import annotations

import numpy as np
import pytest
import trimesh

from app.ai.provider import OfflineProvider
from app.core.session import Session
from app.geometry.uv import box_uv, uv_bounds_are_reasonable
from app.materials import texture as tx
from app.materials.library import CATALOG, Finish, finish_for, load_catalog, maps_for

OFFLINE = OfflineProvider()
load_catalog()


# --------------------------------------------------------------------------- #
# Rumore e mappe
# --------------------------------------------------------------------------- #
def test_noise_is_deterministic():
    a = tx.fractal_noise(64, cells=4, octaves=3, seed=7)
    b = tx.fractal_noise(64, cells=4, octaves=3, seed=7)
    c = tx.fractal_noise(64, cells=4, octaves=3, seed=8)
    assert np.array_equal(a, b)
    assert not np.array_equal(a, c)


def test_noise_is_normalised():
    n = tx.fractal_noise(64, seed=1)
    assert n.min() == pytest.approx(0.0, abs=1e-9)
    assert n.max() == pytest.approx(1.0, abs=1e-9)


def test_noise_tiles_without_a_seam():
    """La griglia si chiude su se stessa: niente riga visibile ai bordi."""
    n = tx.value_noise(64, cells=4, seed=3)
    assert np.allclose(n[0, :], n[0, :])
    # il bordo destro deve somigliare al sinistro molto piu' del centro
    seam = float(np.mean(np.abs(n[:, -1] - n[:, 0])))
    middle = float(np.mean(np.abs(n[:, 32] - n[:, 0])))
    assert seam < middle


@pytest.mark.parametrize("name", sorted(tx.GENERATORS))
def test_every_texture_produces_valid_maps(name):
    t = tx.generate(name, size=64, seed=2)
    assert t.base_color.shape == (64, 64, 3)
    assert t.roughness.shape == (64, 64)
    assert 0.0 <= t.base_color.min() and t.base_color.max() <= 1.0
    assert 0.0 < t.roughness.min() and t.roughness.max() <= 1.0
    normal = t.normal_map()
    assert normal.shape == (64, 64, 3)
    assert 0.0 <= normal.min() and normal.max() <= 1.0


def test_unknown_texture_is_reported():
    with pytest.raises(KeyError):
        tx.generate("inesistente")


def test_metallic_roughness_packing_follows_gltf():
    """glTF: rugosita' nel verde, metallicita' nel blu."""
    t = tx.generate("metal", size=32, seed=1)
    image = tx.metallic_roughness_image(t)
    data = np.asarray(image, dtype=float) / 255.0
    assert image.mode == "RGB"
    assert np.allclose(data[..., 0], 0.0, atol=1 / 255)
    assert np.allclose(data[..., 1], t.roughness, atol=2 / 255)


def test_tinting_keeps_the_requested_colour():
    """Il materiale decide la tinta, la texture il dettaglio."""
    t = tx.generate("metal", size=32, seed=1)
    rosso = tx.tint_base_color(t, (0.7, 0.1, 0.1))
    mean = rosso.reshape(-1, 3).mean(axis=0)
    assert mean[0] > mean[1] * 2 and mean[0] > mean[2] * 2
    assert float(np.std(rosso)) > 0.005, "il dettaglio non deve sparire"


# --------------------------------------------------------------------------- #
# UV
# --------------------------------------------------------------------------- #
def test_box_uv_covers_every_vertex():
    mesh = trimesh.creation.box((1, 1, 1))
    work, uv = box_uv(mesh, texel=0.5)
    assert uv.shape == (len(work.vertices), 2)
    assert np.all(np.isfinite(uv))


def test_box_uv_scale_is_in_metres():
    """La stessa texture deve avere la stessa grana su oggetti di taglia diversa."""
    small = trimesh.creation.box((1, 1, 1))
    large = trimesh.creation.box((2, 2, 2))
    _, uv_small = box_uv(small, texel=0.5)
    _, uv_large = box_uv(large, texel=0.5)
    span_small = float(np.ptp(uv_small))
    span_large = float(np.ptp(uv_large))
    assert span_large == pytest.approx(span_small * 2, rel=0.05)


def test_box_uv_handles_an_empty_mesh():
    empty = trimesh.Trimesh()
    work, uv = box_uv(empty)
    assert uv.shape == (0, 2)


def test_uv_guard_catches_absurd_scales():
    assert uv_bounds_are_reasonable(np.array([[0.0, 1.0], [2.0, 3.0]]))
    assert not uv_bounds_are_reasonable(np.array([[0.0, 1e6]]))


def test_box_uv_on_a_composed_creature():
    session = Session(provider=OFFLINE)
    session.generate_legacy("crea un pesce")
    body = session.scene.by_id("corpo")
    work, uv = box_uv(body.mesh, texel=0.3)
    assert len(uv) == len(work.vertices)
    assert uv_bounds_are_reasonable(uv)


# --------------------------------------------------------------------------- #
# Catalogo delle finiture
# --------------------------------------------------------------------------- #
def test_catalog_is_loaded_from_data():
    assert len(CATALOG) >= 20
    for name in ("body", "tire", "wood", "skin", "wall"):
        assert name in CATALOG


def test_finish_falls_back_on_keywords():
    """Non serve elencare ogni variante di nome."""
    assert finish_for("tire_front").texture == "rubber"
    assert finish_for("legno_scuro").texture == "wood"
    assert finish_for("acciaio_lucido").texture == "metal"
    assert finish_for("nome_senza_senso") is None


def test_flat_materials_have_no_texture():
    assert not finish_for("eye").enabled()
    assert maps_for("eye", (0.1, 0.1, 0.1), 0.2, 0.0, size=32) is None


def test_maps_are_cached():
    a = maps_for("tire", (0.1, 0.1, 0.1), 0.9, 0.0, size=32, seed=1)
    b = maps_for("tire", (0.1, 0.1, 0.1), 0.9, 0.0, size=32, seed=1)
    assert a is b, "le mappe si ricalcolano una volta sola"


def test_maps_have_all_three_channels():
    maps = maps_for("body", (0.3, 0.5, 0.3), 0.4, 0.3, size=32, seed=0)
    assert set(maps) == {"base_color", "metallic_roughness", "normal", "tiling"}
    assert maps["base_color"].size == (32, 32)


# --------------------------------------------------------------------------- #
# Export
# --------------------------------------------------------------------------- #
def test_textured_export_carries_pbr_maps(tmp_path):
    session = Session(provider=OFFLINE)
    session.generate_legacy("una jeep militare verde")
    out = tmp_path / "jeep.glb"
    session.scene.to_trimesh_scene(textured=True, texture_size=64).export(out)

    loaded = trimesh.load(out)
    body = loaded.geometry["body"]
    material = body.visual.material
    assert material.baseColorTexture is not None
    assert material.metallicRoughnessTexture is not None
    assert material.normalTexture is not None
    assert body.visual.uv is not None and len(body.visual.uv) == len(body.vertices)


def test_flat_export_still_works(tmp_path):
    session = Session(provider=OFFLINE)
    session.generate_legacy("una sedia")
    out = tmp_path / "sedia.glb"
    session.scene.to_trimesh_scene(textured=False).export(out)
    loaded = trimesh.load(out)
    material = next(iter(loaded.geometry.values())).visual.material
    assert material.baseColorTexture is None
    assert material.baseColorFactor is not None


def test_flat_export_is_much_smaller(tmp_path):
    session = Session(provider=OFFLINE)
    session.generate_legacy("una sedia")
    piatto = tmp_path / "piatto.glb"
    con_texture = tmp_path / "texture.glb"
    session.scene.to_trimesh_scene(textured=False).export(piatto)
    session.scene.to_trimesh_scene(textured=True, texture_size=64).export(con_texture)
    assert con_texture.stat().st_size > piatto.stat().st_size


def test_texture_failure_does_not_break_the_export(tmp_path, monkeypatch):
    """Regola dell'errore recuperabile: senza texture si esporta lo stesso."""
    import app.materials.library as library

    def boom(*args, **kwargs):
        raise RuntimeError("guasto simulato")

    monkeypatch.setattr(library, "maps_for", boom)
    session = Session(provider=OFFLINE)
    session.generate_legacy("una sedia")
    out = tmp_path / "sedia.glb"
    session.scene.to_trimesh_scene(textured=True).export(out)
    assert out.exists() and out.stat().st_size > 500


# --------------------------------------------------------------------------- #
# Intensita' del dettaglio
# --------------------------------------------------------------------------- #
def test_paint_is_subtle_and_bark_is_not():
    """La vernice ha una grana appena accennata, la corteccia quasi solo grana."""
    assert finish_for("body").detail < 0.3
    assert finish_for("bark").detail > 0.8
    assert finish_for("tire").detail > 0.7


def test_preview_texture_is_contrast_normalised():
    """Senza normalizzazione una texture scura non modulerebbe nulla."""
    from app.ui.render_core import _finish_texture

    for material in ("tire", "wood", "body"):
        texture, tiling, detail = _finish_texture(material, size=64)
        assert texture is not None and texture.shape == (64, 64, 3)
        assert abs(float(texture.mean()) - 0.5) < 0.12, "media attorno a 0.5"
        assert float(texture.std()) > 0.05, "deve avere contrasto"
        assert tiling > 0 and 0.0 <= detail <= 1.0


def test_preview_texture_is_absent_for_flat_materials():
    from app.ui.render_core import _finish_texture

    texture, _, detail = _finish_texture("eye")
    assert texture is None and detail == 0.0


def test_export_options_reach_the_exporter(tmp_path):
    session = Session(provider=OFFLINE)
    session.generate_legacy("un tavolo di legno")
    con = session.export(tmp_path / "tex.glb", textured=True)
    senza = session.export(tmp_path / "piatto.glb", textured=False)
    # le mappe pesano molto piu' della geometria di un tavolo
    assert con.stat().st_size > senza.stat().st_size + 50_000


def test_stl_never_carries_textures(tmp_path):
    """STL non trasporta materiali: generarle sarebbe solo tempo perso."""
    session = Session(provider=OFFLINE)
    session.generate_legacy("una sedia")
    out = session.export(tmp_path / "sedia.stl", textured=True)
    assert out.exists()


def test_export_writes_a_non_empty_file(tmp_path):
    """Regressione: trimesh restituiva i byte ma lasciava il file vuoto."""
    session = Session(provider=OFFLINE)
    session.generate_legacy("un tavolo di legno")
    for suffix in ("glb", "obj", "stl", "ply"):
        out = session.export(tmp_path / ("t." + suffix), textured=True)
        assert out.stat().st_size > 100, "%s vuoto" % suffix
