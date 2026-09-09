"""Motore di composizione: attacchi geometrici veri, non scatole sovrapposte."""
from __future__ import annotations

import numpy as np
import pytest

from app.build.builder import build_scene
from app.core.spec import AssemblySpec, AttachSpec, GenerationPlan, PartSpec
from app.geometry.composition import (
    CompositionError, Placement, attachment_placement, compose, fused_mesh, to_meshes,
)
from app.geometry.recipe import Socket, get_recipe, load_catalog

load_catalog()


def assembly(*parts: PartSpec, root: str = "", blend: float = 0.06) -> AssemblySpec:
    return AssemblySpec(root=root or parts[0].id, parts=list(parts), blend=blend)


# --------------------------------------------------------------------------- #
# Allineamento dei socket
# --------------------------------------------------------------------------- #
def test_attachment_puts_the_part_at_the_socket():
    parent_socket = Socket("s", [1.0, 0.0, 0.0], [1, 0, 0], 0.2, up=[0, 1, 0])
    child_socket = Socket("base", [0.0, 0.0, 0.0], [-1, 0, 0], 0.2, up=[0, 1, 0])
    place = attachment_placement(Placement(), parent_socket, child_socket, insert=0.0)
    # l'origine del figlio finisce esattamente sul socket del padre
    assert place.apply_point(np.zeros(3)) == pytest.approx([1.0, 0.0, 0.0])


def test_attachment_rotates_the_part_to_face_the_socket():
    """Una parte attaccata a un socket rivolto in su deve crescere verso l'alto."""
    parent_socket = Socket("s", [0, 1.0, 0], [0, 1, 0], 0.2, up=[-1, 0, 0])
    child_socket = Socket("base", [0, 0, 0], [-1, 0, 0], 0.2, up=[0, 1, 0])
    place = attachment_placement(Placement(), parent_socket, child_socket, insert=0.0)
    tip_local = np.array([1.0, 0.0, 0.0])                # la parte cresce lungo +X
    tip_world = place.apply_point(tip_local)
    assert tip_world[1] > 0.9, "deve puntare verso l'alto"
    assert abs(tip_world[0]) < 1e-6 and abs(tip_world[2]) < 1e-6


def test_attachment_preserves_roll_through_up():
    """Senza 'up' l'orientamento attorno all'asse sarebbe indeterminato."""
    parent_socket = Socket("s", [0, 0, 0], [0, 1, 0], 0.2, up=[0, 0, 1])
    child_socket = Socket("base", [0, 0, 0], [-1, 0, 0], 0.2, up=[0, 1, 0])
    place = attachment_placement(Placement(), parent_socket, child_socket, insert=0.0)
    # il dorso del figlio (+Y locale) deve finire sul dorso indicato dal padre (+Z)
    assert place.apply_direction(np.array([0.0, 1.0, 0.0])) == pytest.approx([0, 0, 1], abs=1e-9)


def test_attachment_scale_matches_socket_radii():
    parent_socket = Socket("s", [0, 0, 0], [1, 0, 0], 0.4, up=[0, 1, 0])
    child_socket = Socket("base", [0, 0, 0], [-1, 0, 0], 0.1, up=[0, 1, 0])
    place = attachment_placement(Placement(), parent_socket, child_socket,
                                 scale_mode="socket", insert=0.0)
    assert place.scale == pytest.approx(4.0)


def test_attachment_inserts_the_part_into_the_parent():
    """Senza compenetrazione la fusione morbida non unisce niente."""
    parent_socket = Socket("s", [1.0, 0, 0], [1, 0, 0], 0.2, up=[0, 1, 0])
    child_socket = Socket("base", [0, 0, 0], [-1, 0, 0], 0.2, up=[0, 1, 0])
    inserted = attachment_placement(Placement(), parent_socket, child_socket, insert=0.5)
    assert inserted.apply_point(np.zeros(3))[0] == pytest.approx(1.0 - 0.1)


def test_rotation_matrices_stay_orthonormal():
    parent_socket = Socket("s", [0.3, 0.2, -0.1], [1, 2, -0.5], 0.2, up=[0.1, 1, 0.3])
    child_socket = Socket("base", [0, 0, 0], [-1, 0.2, 0.1], 0.15, up=[0.2, 1, 0])
    place = attachment_placement(Placement(), parent_socket, child_socket, roll=37.0)
    assert np.allclose(place.rotation.T @ place.rotation, np.eye(3), atol=1e-9)
    assert np.isclose(np.linalg.det(place.rotation), 1.0)


# --------------------------------------------------------------------------- #
# Composizione
# --------------------------------------------------------------------------- #
def test_compose_places_children_after_parents():
    spec = assembly(
        PartSpec(id="corpo", recipe="body"),
        PartSpec(id="testa", recipe="head", attach=AttachSpec(parent="corpo", socket="head")),
        PartSpec(id="occhio", recipe="eye", hard=True,
                 attach=AttachSpec(parent="testa", socket="eye_l")),
    )
    result = compose(spec)
    assert [p.id for p in result.parts] == ["corpo", "testa", "occhio"]
    assert not result.warnings


def test_head_sits_in_front_of_the_body():
    result = compose(assembly(
        PartSpec(id="corpo", recipe="body", params={"length": 0.9}),
        PartSpec(id="testa", recipe="head", attach=AttachSpec(parent="corpo", socket="head")),
    ))
    corpo = result.by_id("corpo").centre()
    testa = result.by_id("testa").centre()
    assert testa[0] > corpo[0] + 0.5, "la testa deve stare davanti"
    assert abs(testa[1]) < 0.3 and abs(testa[2]) < 0.1


def test_tail_sits_behind_the_body():
    result = compose(assembly(
        PartSpec(id="corpo", recipe="body", params={"length": 0.9}),
        PartSpec(id="coda", recipe="blade", attach=AttachSpec(parent="corpo", socket="tail")),
    ))
    assert result.by_id("coda").centre()[0] < result.by_id("corpo").centre()[0] - 0.5


def test_paired_sockets_produce_mirrored_parts():
    parts = [PartSpec(id="torso", recipe="torso")]
    for side in ("l", "r"):
        parts.append(PartSpec(id="braccio_" + side, recipe="limb",
                              attach=AttachSpec(parent="torso", socket="shoulder_" + side)))
    result = compose(assembly(*parts))
    left = result.by_id("braccio_l").centre()
    right = result.by_id("braccio_r").centre()
    assert left[0] < 0 < right[0]
    assert left[0] == pytest.approx(-right[0], abs=1e-6), "simmetria bilaterale"
    assert left[1] == pytest.approx(right[1], abs=1e-6)


def test_missing_socket_is_reported_not_fatal():
    result = compose(assembly(
        PartSpec(id="corpo", recipe="body"),
        PartSpec(id="testa", recipe="head",
                 attach=AttachSpec(parent="corpo", socket="socket_inesistente")),
    ))
    assert result.by_id("corpo") is not None
    assert any("socket" in w for w in result.warnings)
    assert result.by_id("testa") is None


def test_unknown_recipe_is_reported_not_fatal():
    result = compose(assembly(
        PartSpec(id="corpo", recipe="body"),
        PartSpec(id="boh", recipe="ricetta_inventata",
                 attach=AttachSpec(parent="corpo", socket="head")),
    ))
    assert result.by_id("corpo") is not None
    assert any("ricetta" in w for w in result.warnings)


def test_root_ignores_its_own_incoming_attachment():
    """La radice non e' attaccata a niente: un attacco su di lei si ignora."""
    result = compose(AssemblySpec(root="a", parts=[
        PartSpec(id="a", recipe="body", attach=AttachSpec(parent="b", socket="head")),
        PartSpec(id="b", recipe="body", attach=AttachSpec(parent="a", socket="head")),
    ]))
    assert [p.id for p in result.parts] == ["a", "b"]
    assert result.by_id("a").parent is None


def test_real_cycle_is_broken_with_a_warning():
    result = compose(AssemblySpec(root="c", parts=[
        PartSpec(id="c", recipe="torso"),
        PartSpec(id="a", recipe="limb", attach=AttachSpec(parent="b", socket="tip")),
        PartSpec(id="b", recipe="limb", attach=AttachSpec(parent="a", socket="tip")),
    ]))
    assert result.by_id("c") is not None, "il resto della scena si genera lo stesso"
    assert any("ciclo" in w for w in result.warnings)


def test_empty_assembly_is_refused():
    with pytest.raises(CompositionError):
        compose(AssemblySpec(root="x", parts=[]))


# --------------------------------------------------------------------------- #
# Fusione e ripartizione
# --------------------------------------------------------------------------- #
def test_fused_body_is_a_single_watertight_piece():
    """Il criterio che distingue un corpo composto da tre pezzi appoggiati."""
    result = compose(assembly(
        PartSpec(id="corpo", recipe="body", params={"length": 0.8, "height": 0.35}),
        PartSpec(id="testa", recipe="head", blend=0.12,
                 attach=AttachSpec(parent="corpo", socket="head")),
        PartSpec(id="coda", recipe="blade", blend=0.07,
                 attach=AttachSpec(parent="corpo", socket="tail")),
    ))
    mesh = fused_mesh(result, resolution=72)
    assert mesh.is_watertight
    assert len(mesh.split(only_watertight=False)) == 1, "deve essere un pezzo solo"


def test_pieces_keep_their_identity_after_fusion():
    result = compose(assembly(
        PartSpec(id="corpo", recipe="body", tags=["body"]),
        PartSpec(id="testa", recipe="head", tags=["head"], blend=0.12,
                 attach=AttachSpec(parent="corpo", socket="head")),
    ))
    pieces = dict((p.id, m) for p, m in to_meshes(result, resolution=64))
    assert set(pieces) == {"corpo", "testa"}
    assert all(len(m.faces) > 50 for m in pieces.values())
    # la testa sta davanti anche dopo la ripartizione
    assert pieces["testa"].centroid[0] > pieces["corpo"].centroid[0]


def test_hard_parts_are_not_fused():
    result = compose(assembly(
        PartSpec(id="testa", recipe="head"),
        PartSpec(id="occhio", recipe="eye", hard=True,
                 attach=AttachSpec(parent="testa", socket="eye_l")),
    ))
    assert [p.id for p in result.hard] == ["occhio"]
    assert [p.id for p in result.soft] == ["testa"]
    meshes = dict((p.id, m) for p, m in to_meshes(result, resolution=56))
    assert meshes["occhio"].is_watertight, "una parte dura resta un solido chiuso"


# --------------------------------------------------------------------------- #
# Integrazione con la pipeline esistente
# --------------------------------------------------------------------------- #
def test_builder_produces_a_scene_from_an_assembly():
    plan = GenerationPlan(prompt="creatura", strategy="assembly",
                          assembly=assembly(
                              PartSpec(id="corpo", recipe="body", tags=["body"]),
                              PartSpec(id="testa", recipe="head", tags=["head"],
                                       attach=AttachSpec(parent="corpo", socket="head"))))
    scene = build_scene(plan)
    assert {n.id for n in scene.nodes} == {"corpo", "testa"}
    assert not scene.warnings
    assert scene.triangle_count > 100
    assert "fused" in scene.by_id("corpo").tags
    assert scene.placements and "corpo" in scene.placements


def test_builder_falls_back_when_the_assembly_is_broken():
    """Regola 9: nemmeno un assemblaggio rotto puo' lasciare l'utente a mani vuote."""
    plan = GenerationPlan(prompt="x", template="chair", strategy="assembly",
                          assembly=AssemblySpec(root="a", parts=[
                              PartSpec(id="a", recipe="ricetta_che_non_esiste")]))
    scene = build_scene(plan)
    assert scene.nodes, "deve ripiegare sul template"
    assert scene.strategy == "template"
    # il ripiego deve restare visibile, non nascosto
    assert any(a.strategy == "assembly" and not a.ok for a in scene.attempts)


def test_last_resort_answers_even_without_any_strategy():
    """Se nemmeno il template esiste, resta il solido di base."""
    plan = GenerationPlan(prompt="x", template="template_inesistente", strategy="template")
    scene = build_scene(plan)
    assert scene.nodes and scene.triangle_count > 0
    assert scene.strategy == "fallback"
    assert any("solido di base" in w for w in scene.warnings)
