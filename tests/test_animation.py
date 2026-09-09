"""Scheletro, animazioni di parti rigide, esportazione glTF animata."""
from __future__ import annotations

import json
import struct

import numpy as np
import pytest

from app.ai.creature import build_assembly, parse_creature
from app.anim import clip as clip_module
from app.anim import gltf, pose
from app.anim import skeleton as skeleton_module
from app.anim.clip import Clip, quaternion, swing
from app.anim.gltf import GltfError
from app.anim.skeleton import Joint, Skeleton
from app.build.builder import build_scene
from app.core.spec import GenerationPlan

DRAGO = "un drago con quattro zampe, due ali e una lunga coda"


def scena(prompt: str):
    assembly, materials = build_assembly(parse_creature(prompt))
    return build_scene(GenerationPlan(prompt=prompt, template="freeform",
                                      strategy="assembly", assembly=assembly,
                                      materials=materials))


@pytest.fixture(scope="module")
def drago():
    return scena(DRAGO)


@pytest.fixture(scope="module")
def ossa(drago):
    return skeleton_module.from_scene(drago)


# --------------------------------------------------------------------------- #
# Scheletro
# --------------------------------------------------------------------------- #
def test_the_skeleton_is_the_part_graph(drago, ossa):
    assert len(ossa) == len(drago.placements)
    assert ossa.root is not None and ossa.root.name == "corpo"
    assert sum(1 for j in ossa.joints if j.parent is None) == 1, "una sola radice"


def test_a_joint_sits_on_the_socket_it_hangs_from(drago, ossa):
    """Il pivot deve essere l'anca, non il centro della coscia.

    Le pose sono nel sistema della composizione; la scena e' stata alzata per
    appoggiarla a terra, e i giunti devono stare con le mesh, non con le pose.
    """
    coscia = drago.placements["coscia_0"]
    corpo = drago.placements[coscia.parent]
    atteso = corpo.placement.socket_world(
        corpo.part.socket(coscia.parent_socket)).position
    assert np.allclose(ossa.get("coscia_0").pivot, atteso + drago.ground_offset)


def test_a_joint_sits_inside_its_own_part(drago, ossa):
    """Verifica indipendente dell'appoggio: ogni giunto e' dentro la sua mesh."""
    per_id = {n.id: n for n in drago.nodes}
    for giunto in ossa.joints:
        nodo = per_id.get(giunto.name)
        if nodo is None:
            continue
        basso, alto = nodo.mesh.bounds
        fuori = float(np.max(np.maximum(basso - giunto.pivot, giunto.pivot - alto)))
        assert fuori < 0.15, "%s e' a %.2f m dalla propria parte" % (giunto.name, fuori)


def test_an_assembly_stands_on_the_ground(drago):
    """Come ogni altro modello: sotto lo zero non c'e' niente."""
    fuso = drago.to_trimesh_scene(textured=False).to_geometry()
    assert float(fuso.bounds[0][1]) == pytest.approx(0.0, abs=1e-6)


def test_a_limb_is_a_chain(ossa):
    figli = [j.name for j in ossa.descendants("coscia_0")]
    assert figli == ["stinco_0", "piede_0"] or set(figli) == {"stinco_0", "piede_0"}
    assert ossa.get("piede_0").parent == "stinco_0"


def test_the_frame_of_a_joint_is_orthonormal(ossa):
    for giunto in ossa.joints:
        for asse in ("forward", "up", "side"):
            assert np.linalg.norm(giunto.axis(asse)) == pytest.approx(1.0, abs=1e-6)
        assert abs(float(np.dot(giunto.forward, giunto.side))) < 1e-6


def test_the_long_axis_is_read_from_the_head(ossa):
    lungo, laterale = ossa.axes()
    assert lungo != laterale and 1 not in (lungo, laterale), "la verticale e' Y"
    testa, corpo = ossa.get("testa"), ossa.get("corpo")
    assert abs(testa.pivot[lungo] - corpo.pivot[lungo]) > \
           abs(testa.pivot[laterale] - corpo.pivot[laterale])


def test_diagonal_legs_move_together(ossa):
    fasi = ossa.gait_phases("leg")
    lungo, laterale = ossa.axes()
    cosce = [ossa.get(n) for n in fasi if n.startswith("coscia")]
    per_fase = {}
    for coscia in cosce:
        per_fase.setdefault(fasi[coscia.name], []).append(coscia)
    assert len(per_fase) == 2, "due gruppi: e' un'andatura alternata"
    for gruppo in per_fase.values():
        assert len(gruppo) == 2
        a, b = gruppo
        # In diagonale: le due zampe che si muovono insieme stanno una davanti
        # e una dietro, e su lati opposti. Quale delle due diagonali sia, non
        # importa: contano solo i due scambi di segno.
        assert a.pivot[lungo] != b.pivot[lungo], "una davanti e una dietro"
        assert a.pivot[laterale] != b.pivot[laterale], "su lati opposti"


def test_a_whole_limb_shares_one_phase(ossa):
    fasi = ossa.gait_phases("leg")
    assert fasi["coscia_0"] == fasi["stinco_0"] == fasi["piede_0"]


def test_two_legs_alternate(ossa):
    bipede = Skeleton(joints=[
        Joint("corpo", None, np.zeros(3), np.array([0., 0., 1.]),
              np.array([0., 1., 0.]), np.array([1., 0., 0.]), ["body"]),
        Joint("testa", "corpo", np.array([0., 1., 0.3]), np.array([0., 0., 1.]),
              np.array([0., 1., 0.]), np.array([1., 0., 0.]), ["head"]),
        Joint("gamba_l", "corpo", np.array([-0.2, 0., 0.]), np.array([0., -1., 0.]),
              np.array([0., 0., 1.]), np.array([1., 0., 0.]), ["leg"]),
        Joint("gamba_r", "corpo", np.array([0.2, 0., 0.]), np.array([0., -1., 0.]),
              np.array([0., 0., 1.]), np.array([1., 0., 0.]), ["leg"]),
    ])
    fasi = bipede.gait_phases("leg")
    assert set(fasi.values()) == {0.0, 0.5}


def test_the_two_wings_are_on_opposite_sides(ossa):
    ali = ossa.find("wing")
    assert len(ali) == 2
    assert ossa.lateral_sign(ali[0]) == -ossa.lateral_sign(ali[1])


def test_an_orphan_joint_is_reattached():
    posti = {
        "corpo": _finto(None, ""),
        "perso": _finto("padre_svanito", "hip"),
    }
    ossa = skeleton_module.from_placements(posti)
    assert ossa.get("perso").parent == "corpo", "meglio riattaccato che immobile"


def _finto(parent, parent_socket):
    class FintaParte:
        def socket(self, name):
            return None

    class FintaPosa:
        translation = np.zeros(3)

        def socket_world(self, socket):
            return socket

    class Finto:
        pass

    finto = Finto()
    finto.parent = parent
    finto.parent_socket = parent_socket
    finto.part = FintaParte()
    finto.placement = FintaPosa()
    finto.tags = []
    return finto


def test_a_template_model_has_no_skeleton():
    """Una scena da template non e' un grafo di parti, e non deve fingere di esserlo."""
    scene = build_scene(GenerationPlan(template="chair"))
    assert len(skeleton_module.from_scene(scene)) == 0


# --------------------------------------------------------------------------- #
# Animazioni
# --------------------------------------------------------------------------- #
def test_a_zero_rotation_is_the_identity_quaternion():
    assert np.allclose(quaternion([0, 1, 0], 0.0), [0, 0, 0, 1])


def test_a_half_turn_is_a_pure_vector_quaternion():
    q = quaternion([0, 1, 0], 180.0)
    assert np.allclose(q, [0, 1, 0, 0], atol=1e-9)


def test_a_degenerate_axis_gives_no_rotation():
    assert np.allclose(quaternion([0, 0, 0], 45.0), [0, 0, 0, 1])


def test_a_cycle_closes_on_itself(ossa):
    for nome in clip_module.BUILDERS:
        animazione = clip_module.make(nome, ossa)
        assert animazione.is_closed(), "%s scatta a ogni giro" % nome


def test_only_the_animations_the_model_can_do(ossa):
    nomi = [c.name for c in clip_module.default_clips(ossa)]
    assert nomi == ["idle", "walk", "wing_beat"]


def test_a_finned_creature_does_not_walk():
    pesce = skeleton_module.from_scene(scena("un pesce con quattro pinne"))
    nomi = [c.name for c in clip_module.default_clips(pesce)]
    assert "walk" not in nomi, "un pesce non cammina"
    assert "idle" in nomi, "ma respira"


def test_an_unknown_animation_is_an_error(ossa):
    with pytest.raises(KeyError, match="sconosciuta"):
        clip_module.make("moonwalk", ossa)


def test_the_amplitude_decreases_along_the_limb(ossa):
    passo = clip_module.walk(ossa)
    ampiezze = [max(abs(_angle(q)) for q in passo.channel(n).rotations)
                for n in ("coscia_0", "stinco_0", "piede_0")]
    assert ampiezze[0] > ampiezze[1] > ampiezze[2], "l'anca fa il passo"


def test_idle_stays_small(ossa):
    """Un idle che si nota e' un idle sbagliato, e apre le cuciture."""
    for canale in clip_module.idle(ossa).channels:
        assert max(abs(_angle(q)) for q in canale.rotations) < 8.0


def _angle(q) -> float:
    return float(np.degrees(2.0 * np.arccos(np.clip(abs(float(q[3])), -1.0, 1.0))))


def test_a_swing_starts_and_ends_together():
    giunto = Joint("x", None, np.zeros(3), np.array([1., 0., 0.]),
                   np.array([0., 1., 0.]), np.array([0., 0., 1.]))
    canale = swing(giunto, [0, 1, 0], 20.0, duration=1.0)
    assert np.allclose(canale.rotations[0], canale.rotations[-1], atol=1e-9)
    assert canale.times[0] == 0.0 and canale.times[-1] == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# Cinematica
# --------------------------------------------------------------------------- #
def test_the_rest_pose_puts_everything_back(ossa):
    matrici = pose.pose(ossa, None)
    for giunto in ossa.joints:
        assert np.allclose(matrici[giunto.name][:3, 3], giunto.pivot, atol=1e-9)


def test_a_rotating_joint_stays_where_it_is(ossa):
    passo = clip_module.walk(ossa)
    anca = ossa.get("coscia_0").pivot
    for t in (0.0, 0.2, 0.45, 0.9):
        assert np.allclose(pose.pose(ossa, passo, t)["coscia_0"][:3, 3], anca, atol=1e-9)


def test_the_end_of_a_limb_moves_more_than_its_root(ossa):
    passo = clip_module.walk(ossa)
    riposo = pose.pose(ossa, passo, 0.0)
    mosso = pose.pose(ossa, passo, 0.25)
    anca = np.linalg.norm(mosso["coscia_0"][:3, 3] - riposo["coscia_0"][:3, 3])
    piede = np.linalg.norm(mosso["piede_0"][:3, 3] - riposo["piede_0"][:3, 3])
    assert piede > anca + 0.01


def test_diagonal_legs_swing_in_opposite_directions(ossa):
    passo = clip_module.walk(ossa)
    lungo, _ = ossa.axes()
    riposo, mosso = pose.pose(ossa, passo, 0.0), pose.pose(ossa, passo, 0.25)
    davanti = mosso["piede_0"][lungo, 3] - riposo["piede_0"][lungo, 3]
    dietro = mosso["piede_2"][lungo, 3] - riposo["piede_2"][lungo, 3]
    assert davanti * dietro < 0, "una gamba avanza mentre l'altra arretra"


def test_the_animation_loops(ossa):
    passo = clip_module.walk(ossa)
    assert np.allclose(pose.sample(passo, "coscia_0", 0.0),
                       pose.sample(passo, "coscia_0", 1.0), atol=1e-6)


def test_sampling_interpolates_between_keys(ossa):
    passo = clip_module.walk(ossa)
    canale = passo.channel("coscia_0")
    meta = (canale.times[0] + canale.times[1]) / 2.0
    interpolato = pose.sample(passo, "coscia_0", meta)
    assert not np.allclose(interpolato, canale.rotations[0], atol=1e-6)
    assert np.linalg.norm(interpolato) == pytest.approx(1.0, abs=1e-6)


def test_a_missing_channel_means_no_rotation(ossa):
    vuota = Clip(name="vuota", duration=1.0, channels=[])
    assert np.allclose(pose.sample(vuota, "corpo", 0.3), [0, 0, 0, 1])


def test_a_posed_scene_keeps_every_part(drago, ossa):
    posata = pose.posed_scene(drago, ossa, clip_module.walk(ossa), 0.25)
    assert len(posata.nodes) == len(drago.nodes)
    assert posata.triangle_count == drago.triangle_count
    originali = {n.id: n.mesh.bounds.tolist() for n in drago.nodes}
    assert any(n.mesh.bounds.tolist() != originali[n.id] for n in posata.nodes)
    assert drago.nodes[0].mesh.bounds.tolist() == originali[drago.nodes[0].id], \
        "la scena di partenza non viene toccata"


# --------------------------------------------------------------------------- #
# Esportazione glTF
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def glb(tmp_path_factory, drago):
    path = tmp_path_factory.mktemp("anim") / "drago.glb"
    return gltf.export_animated(drago, path)


def documento(path) -> dict:
    raw = path.read_bytes()
    lunghezza = struct.unpack("<I", raw[12:16])[0]
    return json.loads(raw[20:20 + lunghezza])


def test_the_file_is_a_glb(glb):
    raw = glb.read_bytes()
    assert raw[:4] == b"glTF"
    magia, versione, totale = struct.unpack("<III", raw[:12])
    assert versione == 2 and totale == len(raw)


def test_chunks_are_aligned(glb):
    """Un blocco non allineato a 4 byte viene rifiutato dai lettori severi."""
    raw = glb.read_bytes()
    lunghezza_json = struct.unpack("<I", raw[12:16])[0]
    assert lunghezza_json % 4 == 0
    inizio_bin = 20 + lunghezza_json
    lunghezza_bin = struct.unpack("<I", raw[inizio_bin:inizio_bin + 4])[0]
    assert lunghezza_bin % 4 == 0
    for vista in documento(glb)["bufferViews"]:
        assert vista["byteOffset"] % 4 == 0


def test_the_hierarchy_is_exported(glb, ossa):
    doc = documento(glb)
    assert len(doc["nodes"]) == len(ossa)
    per_nome = {n["name"]: i for i, n in enumerate(doc["nodes"])}
    coscia = doc["nodes"][per_nome["coscia_0"]]
    assert per_nome["stinco_0"] in coscia.get("children", [])
    radice = doc["nodes"][per_nome["corpo"]]
    assert per_nome["coscia_0"] in radice.get("children", [])


def test_a_node_sits_at_its_own_joint(glb, ossa):
    """La catena delle traslazioni deve ridare i pivot originali."""
    doc = documento(glb)
    per_nome = {n["name"]: n for n in doc["nodes"]}
    somma = np.zeros(3)
    for nome in ("corpo", "coscia_0", "stinco_0", "piede_0"):
        somma = somma + np.array(per_nome[nome]["translation"])
    assert np.allclose(somma, ossa.get("piede_0").pivot, atol=1e-5)


def test_the_animations_are_rotations_only(glb):
    doc = documento(glb)
    assert {a["name"] for a in doc["animations"]} == {"idle", "walk", "wing_beat"}
    for animazione in doc["animations"]:
        assert animazione["channels"]
        for canale in animazione["channels"]:
            assert canale["target"]["path"] == "rotation", "parti rigide, non skinning"
        for campionatore in animazione["samplers"]:
            assert campionatore["interpolation"] == "LINEAR"


def test_no_skinning_data_is_written(glb):
    doc = documento(glb)
    assert "skins" not in doc
    for mesh in doc["meshes"]:
        for primitiva in mesh["primitives"]:
            assert "JOINTS_0" not in primitiva["attributes"]
            assert "WEIGHTS_0" not in primitiva["attributes"]


def test_the_rest_pose_is_identical_to_the_source(glb, drago):
    """Aprire il file animato e non animarlo deve dare il modello di partenza."""
    import trimesh

    riletto = trimesh.load(str(glb)).to_geometry()
    originale = drago.to_trimesh_scene(textured=False).to_geometry()
    assert np.abs(riletto.bounds - originale.bounds).max() < 1e-5
    assert len(riletto.faces) == len(originale.faces)


def test_materials_are_reused_not_duplicated(glb, drago):
    doc = documento(glb)
    tinte = {tuple(m["pbrMetallicRoughness"]["baseColorFactor"]) for m in doc["materials"]}
    assert len(doc["materials"]) == len(tinte), "un materiale per colore, non per parte"


def test_a_model_without_a_skeleton_cannot_be_animated(tmp_path):
    scene = build_scene(GenerationPlan(template="chair"))
    with pytest.raises(GltfError, match="scheletro|grafo"):
        gltf.export_animated(scene, tmp_path / "sedia.glb")


def test_only_the_requested_animations_are_written(tmp_path, drago):
    path = gltf.export_animated(drago, tmp_path / "solo_idle.glb", clips=["idle"])
    assert {a["name"] for a in documento(path)["animations"]} == {"idle"}


# --------------------------------------------------------------------------- #
# Dalla sessione
# --------------------------------------------------------------------------- #
def test_the_session_exposes_what_can_be_animated(drago):
    from app.ai.provider import OfflineProvider
    from app.core.session import Session, Version

    session = Session(provider=OfflineProvider())
    session._push(Version(label="drago", plan=drago.plan, scene=drago,
                          message="", seconds=0.0))
    assert session.animations() == ["idle", "walk", "wing_beat"]
    assert len(session.skeleton()) == len(drago.placements)


def test_a_template_session_offers_no_animation():
    from app.ai.provider import OfflineProvider
    from app.core.session import Session

    session = Session(provider=OfflineProvider())
    session.generate_legacy("una sedia di legno", seed=4)
    assert session.animations() == []
