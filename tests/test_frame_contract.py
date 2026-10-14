"""V5: la convenzione d'asse e' una dichiarazione confrontabile, non una nota.

Tre livelli, in quest'ordine: il contratto da solo (`app/core/frame.py`), il
confronto durante la risoluzione, e il banco della chimera — un corpo di pesce,
una testa di drago e due ali di tre plugin diversi, che prima di V5 si
montavano senza che niente notasse che i tre asset non concordano su dove sia
il davanti.

Quello che questi test **non** pretendono: che il sistema raddrizzi la chimera.
V5 dichiara che non converte (vedi la docstring di `app/core/frame.py`), e un
test che pretendesse la rotazione applicata starebbe chiedendo un secondo
sistema di placement.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.ai.provider import OfflineProvider
from app.core.component import BuildContext, Component, Piece
from app.core.frame import (FRAME_AMBIGUOUS, FRAME_COMPATIBLE,
                            FRAME_CONVERTIBLE, FRAME_UNDECLARED, POLICY_DIAGNOSE,
                            POLICY_STRICT, FrameError, FrameSpec, compare,
                            frame_from_dict, frame_of)
from app.core.planner.planner import MockPlanner
from app.core.registry import load
from app.core.session import Options, Session

BUILTINS = Path(__file__).resolve().parents[1] / "app" / "plugins"
PROBE = Path(__file__).resolve().parent / "plugins" / "variabilita"


@pytest.fixture(scope="module")
def registry():
    return load([BUILTINS]).freeze()


def session_for(registry, **options):
    return Session(registry=registry, provider=OfflineProvider(),
                   planner=MockPlanner())


def chimera_plan():
    """Il caso storico: corpo di pesce, testa di drago, due ali."""
    return {"version": "1.3", "style": "low_poly", "detail_level": 2, "seed": 7,
            "root": {"id": "subject", "ref": "fish:fish_body", "children": [
                {"id": "head", "ref": "creature:dragon_head",
                 "at": {"capability": "head_mount"}},
                {"id": "wing_l", "ref": "fantasy:wing",
                 "at": {"capability": "limb_mount", "side": "l"}},
                {"id": "wing_r", "ref": "fantasy:wing",
                 "at": {"capability": "limb_mount", "side": "r"}}]}}


def codes(result, prefix="FRAME"):
    return sorted(d.code for d in result.diagnostics if d.code.startswith(prefix))


# --------------------------------------------------------------------------- #
# 1. Il contratto da solo
# --------------------------------------------------------------------------- #
def test_a_frame_declares_axes_by_name_and_refuses_anything_else():
    frame = FrameSpec(growth_axis="+Y", front="+Z", up="+Y")
    assert frame.declared == ("growth_axis", "front", "up")
    assert frame.complete
    assert not frame.empty
    assert np.allclose(frame.vector("front"), [0, 0, 1])
    assert frame.to_dict() == {"growth_axis": "+Y", "front": "+Z", "up": "+Y"}

    with pytest.raises(FrameError):
        FrameSpec(up="up")
    with pytest.raises(FrameError):
        FrameSpec(up="+W")
    with pytest.raises(FrameError):
        FrameSpec(front="+Z", up="+Z")          # non ortogonali
    with pytest.raises(FrameError):
        frame_from_dict({"davanti": "+Z"})
    with pytest.raises(FrameError):
        frame_from_dict({"up": 1})
    with pytest.raises(FrameError):
        frame_from_dict("+Y")


def test_an_undeclared_frame_is_empty_and_never_raises():
    assert FrameSpec().empty
    assert frame_from_dict(None).empty
    assert frame_from_dict({}).empty
    assert frame_of(object()).empty
    assert frame_of(Component(id="a:b", build=lambda v, c: Piece())).empty


def test_a_basis_exists_only_for_a_complete_frame():
    frame = FrameSpec(front="+Z", up="+Y")
    basis = frame.basis()
    assert np.allclose(basis.T @ basis, np.eye(3))
    assert np.isclose(np.linalg.det(basis), 1.0)        # destrorsa
    with pytest.raises(FrameError):
        FrameSpec(up="+Y").basis()
    with pytest.raises(FrameError):
        FrameSpec(growth_axis="+Y").basis()


@pytest.mark.parametrize("child, expected, axis, angle", [
    ({"front": "+Z", "up": "+Y"}, FRAME_COMPATIBLE, None, None),
    ({"front": "-Z", "up": "+Y"}, FRAME_CONVERTIBLE, "Y", 180.0),
    ({"front": "+X", "up": "+Y"}, FRAME_CONVERTIBLE, "Y", 90.0),
    ({"front": "+Z", "up": "+X"}, FRAME_CONVERTIBLE, "Z", 90.0),
    ({"up": "+Z"}, FRAME_AMBIGUOUS, None, None),
    ({"growth_axis": "+X"}, FRAME_UNDECLARED, None, None),
    ({}, FRAME_UNDECLARED, None, None),
])
def test_the_four_outcomes_of_a_comparison(child, expected, axis, angle):
    parent = FrameSpec(front="+Z", up="+Y")
    comparison = compare(parent, frame_from_dict(child))
    assert comparison.result == expected
    assert comparison.ok is (expected in (FRAME_COMPATIBLE, FRAME_UNDECLARED))
    assert comparison.detectable is (expected in (FRAME_CONVERTIBLE, FRAME_AMBIGUOUS))
    if expected != FRAME_CONVERTIBLE:
        assert comparison.rotation() is None
        assert comparison.move() is None
        return
    rotation = comparison.rotation()
    assert np.allclose(rotation.T @ rotation, np.eye(3))
    move = comparison.move(scope="subtree:head")
    assert move["type"] == "fx:rotate"
    assert move["scope"] == "subtree:head"
    assert move["params"]["axis"] == axis
    assert abs(move["params"]["angle"]) == pytest.approx(angle)


def test_the_declared_rotation_really_maps_one_frame_onto_the_other():
    """«Convertibile» significa che la rotazione esiste ed e' una sola."""
    a = FrameSpec(front="+Z", up="+Y")
    b = FrameSpec(front="+X", up="+Y")
    rotation = b.rotation_to(a)
    assert np.allclose(rotation @ b.vector("front"), a.vector("front"))
    assert np.allclose(rotation @ b.vector("up"), a.vector("up"))
    assert np.allclose(b.rotation_to(b), np.eye(3))
    assert b.axis_and_angle_to(b) == ("Y", 0.0)


def test_growth_axis_alone_is_never_a_disagreement():
    """Un arto cresce +X su un torso che cresce +Y: e' la convenzione, non un bug.

    E' la decisione centrale del modulo: il socket del padre porta `direction` e
    `up`, quindi la rotazione del figlio e' gia' decisa dal placement. Se
    `compare` guardasse `growth_axis`, ogni arto di ogni umanoide produrrebbe
    una diagnostica — e una diagnostica che compare sempre non si legge piu'.
    """
    torso = FrameSpec(growth_axis="+Y", front="+Z", up="+Y")
    limb = FrameSpec(growth_axis="+X", front="+Z", up="+Y")
    assert compare(torso, limb).result == FRAME_COMPATIBLE
    assert compare(torso, limb).compared == ("up", "front")


# --------------------------------------------------------------------------- #
# 2. Dichiararlo: componente, plugin, dati
# --------------------------------------------------------------------------- #
def test_a_plugin_manifest_declares_the_convention_for_its_components(registry):
    """La convenzione appartiene all'autore del plugin, non a ogni pezzo.

    Prima di V5 `humanoid_anatomical` scriveva la stessa cosa in `metadata`
    come prosa italiana: vera, e non confrontabile da nessuno.
    """
    info = registry.plugin("humanoid_anatomical")
    assert info.frame == FrameSpec(up="+Y", front="+Z")
    assert "+Y" in str(info.metadata)                     # la prosa resta
    for cid in ("humanoid_anatomical:body", "humanoid_anatomical:head",
                "humanoid_anatomical:hand"):
        assert frame_of(registry.component(cid)) == FrameSpec(up="+Y", front="+Z")


def test_a_component_frame_wins_over_the_plugin_default():
    component = Component(id="unit:piece", build=lambda v, c: Piece(),
                          frame={"up": "+Z", "front": "+X"})
    registry = load([]).register_plugin  # noqa: F841 - documenta l'ordine
    from app.core.registry import PluginInfo, Registry

    reg = Registry()
    reg.register_plugin(PluginInfo(id="unit", version="1.0.0",
                                   frame=FrameSpec(up="+Y", front="+Z")))
    assert reg.register_component(component, "unit")
    assert component.frame == FrameSpec(up="+Z", front="+X")


def test_a_component_without_a_frame_inherits_the_plugin_one():
    from app.core.registry import PluginInfo, Registry

    component = Component(id="unit:piece", build=lambda v, c: Piece())
    reg = Registry()
    reg.register_plugin(PluginInfo(id="unit", version="1.0.0",
                                   frame=FrameSpec(up="+Y", front="+Z")))
    assert reg.register_component(component, "unit")
    assert component.frame == FrameSpec(up="+Y", front="+Z")


def test_a_malformed_manifest_frame_refuses_the_plugin(tmp_path):
    import json

    folder = tmp_path / "storto"
    folder.mkdir()
    (folder / "plugin.json").write_text(json.dumps({
        "id": "storto", "version": "1.0.0", "frame": {"up": "+W"}}),
        encoding="utf-8")
    registry = load([tmp_path])
    assert not registry.report.ok
    assert "INVALID_MANIFEST" in [d.code for d in registry.report.entries]
    assert registry.plugin("storto") is None


def test_a_data_component_frame_goes_through_the_same_contract(tmp_path):
    from tests.data_plugin_fixtures import write_variable_plugin

    folder = write_variable_plugin(tmp_path)
    registry = load([BUILTINS, folder]).freeze()
    tail = registry.component("mesh_variable:tail")
    assert tail.frame == FrameSpec(growth_axis="+X", front="+Z", up="+Y")
    piece = tail.build({"length": 1.0, "curvature": 0.0}, BuildContext())
    # V4 metteva la terna nei metadata del pezzo e la verificava: resta vero
    assert piece.metadata["frame"]["growth_axis"] == "+X"


# --------------------------------------------------------------------------- #
# 3. Il confronto durante la risoluzione
# --------------------------------------------------------------------------- #
def test_a_coherent_composition_says_nothing(registry):
    session = session_for(registry)
    result = session.build({"version": "1.3", "detail_level": 2, "seed": 7,
                            "root": {"id": "subject",
                                     "ref": "humanoid_anatomical:body"}})
    assert result.ok
    assert codes(result) == []
    links = [n.link.frame for n in result.resolved.walk() if n.link is not None]
    assert links and set(links) == {FRAME_COMPATIBLE}


def test_an_undeclared_frame_produces_no_diagnostic(registry):
    """17 plugin su 22 non dichiarano niente, e il contratto non li inventa."""
    session = session_for(registry)
    result = session.build({"version": "1.3", "detail_level": 2, "seed": 7,
                            "root": {"id": "subject", "ref": "architecture:house"}})
    assert result.ok
    assert codes(result) == []
    assert frame_of(registry.component("architecture:house")).empty
    links = [n.link.frame for n in result.resolved.walk() if n.link is not None]
    assert set(links) == {FRAME_UNDECLARED}


def test_the_link_records_the_comparison_on_every_edge(registry):
    session = session_for(registry)
    result = session.build(chimera_plan())
    per_nodo = {n.id: n.link.frame for n in result.resolved.walk() if n.link}
    assert per_nodo["head"] == FRAME_CONVERTIBLE
    assert per_nodo["wing_l"] == FRAME_CONVERTIBLE
    assert per_nodo["wing_r"] == FRAME_CONVERTIBLE
    # la coda e' un figlio dichiarato dal corpo, dello stesso plugin: concorda
    assert per_nodo["subject/coda"] == FRAME_COMPATIBLE


# --------------------------------------------------------------------------- #
# 4. Il banco della chimera
# --------------------------------------------------------------------------- #
def test_the_dragon_chimera_no_longer_passes_in_silence(registry):
    """Il caso di VISION-GAP: tre plugin, tre convenzioni, nessun referto.

    Dopo V5 la composizione si costruisce ancora — non e' rotta, e' orientata
    in modo discutibile — ma ogni innesto discordante ha il suo avviso, con la
    convenzione di entrambi i componenti e la mossa che la riconcilierebbe.
    """
    session = session_for(registry)
    result = session.build(chimera_plan())
    assert result.ok                                  # `diagnose` costruisce
    assert result.triangles > 0
    avvisi = [d for d in result.diagnostics if d.code == "FRAME_CONVERTIBLE"]
    assert len(avvisi) == 3                           # testa + due ali
    assert {d.where for d in avvisi} == {"subject/head", "subject/wing_l",
                                          "subject/wing_r"}
    for d in avvisi:
        assert not d.fatal
        assert "front -Z" in d.why and "front +Z" in d.why
        assert d.alternatives
        assert d.alternatives[0].startswith("fx:rotate axis=Y angle=180")


def test_the_suggested_move_is_a_real_installed_effect(registry):
    """La mossa suggerita non e' prosa: e' un effetto che il piano accetta."""
    session = session_for(registry)
    plain = session.build(chimera_plan())
    assert registry.effect("fx:rotate") is not None

    raddrizzata = chimera_plan()
    raddrizzata["root"]["children"][0]["effects"] = [
        {"type": "fx:rotate", "scope": "subtree:head",
         "params": {"axis": "Y", "angle": 180.0}, "amount": 1.0}]
    fixed = session.build(raddrizzata)
    assert fixed.ok
    assert fixed.triangles == plain.triangles          # una posa, non geometria
    testa_prima = plain.build.nodes["head"].mesh
    testa_dopo = fixed.build.nodes["head"].mesh
    assert not np.allclose(testa_prima.vertices, testa_dopo.vertices)


def test_strict_policy_refuses_what_diagnose_only_reports(registry):
    """La politica e' del progetto, non del piano: stesso piano, due esiti."""
    session = session_for(registry)
    permissivo = session.build(chimera_plan(),
                               Options(frame_policy=POLICY_DIAGNOSE))
    assert permissivo.ok

    assert permissivo.report.ok
    severo = session.build(chimera_plan(), Options(frame_policy=POLICY_STRICT))
    # `ok` dice che la geometria e' uscita, non che la richiesta e' stata
    # soddisfatta (regola 23): la differenza fra le due politiche sta nel
    # referto, che e' cio' su cui la riparazione e il punteggio decidono.
    assert not severo.report.ok
    fatali = [d for d in severo.diagnostics if d.fatal]
    assert fatali and all(d.code == "FRAME_CONVERTIBLE" for d in fatali)
    assert len(fatali) == 3

    from app.core.planner.repair import repair_brief

    brief = repair_brief(severo.report)
    assert brief.worth_retrying
    assert len(brief) == 3
    assert {e["code"] for e in brief.to_dict()} == {"FRAME_CONVERTIBLE"}
    assert "fx:rotate" in brief.to_text()
    # con `diagnose` non c'e' niente da rimandare indietro: un avviso e' una
    # cosa che il sistema ha gia' deciso di tollerare
    assert not repair_brief(permissivo.report).worth_retrying


def test_strict_policy_lets_a_coherent_composition_through(registry):
    session = session_for(registry)
    result = session.build({"version": "1.3", "detail_level": 2, "seed": 7,
                            "root": {"id": "subject",
                                     "ref": "humanoid_anatomical:body"}},
                           Options(frame_policy=POLICY_STRICT))
    assert result.ok
    assert codes(result) == []


def test_an_unknown_policy_falls_back_to_diagnose(registry):
    session = session_for(registry)
    result = session.build(chimera_plan(), Options(frame_policy="severissimo"))
    assert result.ok
    assert result.report.ok
    assert result.resolved.frame_policy == POLICY_DIAGNOSE


def test_the_policy_survives_a_project_round_trip(tmp_path, registry):
    assert Options(frame_policy=POLICY_STRICT).to_dict()["frame_policy"] == "strict"
    assert "frame_policy" not in Options().to_dict()
    assert Options.from_dict({"frame_policy": "strict"}).frame_policy == "strict"
    assert Options.from_dict({}).frame_policy == POLICY_DIAGNOSE
    assert Options.from_dict({"frame_policy": "boh"}).frame_policy == POLICY_DIAGNOSE


# --------------------------------------------------------------------------- #
# 5. Un frame ambiguo e' diverso da uno convertibile
# --------------------------------------------------------------------------- #
def test_an_incomplete_frame_is_ambiguous_and_names_what_is_missing(tmp_path):
    from app.core.registry import PluginInfo, Registry
    from app.core.capability import Capability, mount
    from app.geometry.kernel import block
    from app.core.authoring import base_socket
    from app.core.socket import socket

    def costruisci(v, ctx):
        return Piece(mesh=block(0.2, 0.3, 0.2), sockets={
            "base": base_socket(0.1, axis="+Y"),
            "top": socket("top", (0, 0.3, 0), (0, 1, 0), up=(0, 0, 1),
                          radius=0.1, provides="unit_mount")})

    registry = Registry()
    registry.register_plugin(PluginInfo(id="unit", version="1.0.0"))
    padre = Component(id="unit:host", build=costruisci,
                      mounts=(mount("unit_mount", socket_id="top"),),
                      frame={"up": "+Y", "front": "+Z"})
    figlio = Component(id="unit:guest", build=costruisci,
                       provides=(Capability("unit_mount"),),
                       frame={"up": "+Z"})                 # solo un asse
    registry.register_component(padre, "unit")
    registry.register_component(figlio, "unit")
    registry.register_plugin(PluginInfo(id="fx_stub", version="1.0.0"))
    registry = registry.freeze()

    session = Session(registry=registry, provider=OfflineProvider(),
                      planner=MockPlanner())
    result = session.build({"version": "1.3", "detail_level": 2, "seed": 1,
                            "root": {"id": "subject", "ref": "unit:host",
                                     "children": [{"id": "g", "ref": "unit:guest",
                                                   "at": {"capability": "unit_mount"}}]}})
    assert codes(result) == ["FRAME_AMBIGUOUS"]
    ambiguo = [d for d in result.diagnostics if d.code == "FRAME_AMBIGUOUS"][0]
    assert "indeterminata" in ambiguo.why
    assert ambiguo.alternatives == ("dichiarare up e front su entrambi i componenti",)
