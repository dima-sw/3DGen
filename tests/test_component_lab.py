"""Component Lab: lo stesso laboratorio su procedurale e su mesh-backed.

E' il punto 27 della milestone, ed e' anche il banco che prepara il giallo di
V7: un componente che esiste ma non si sa se va bene si apre, si muove, si
misura, e se la configurazione serve si salva come variant senza duplicare la
geometria.

La cosa che questi test misurano davvero non e' che il laboratorio funzioni, e'
che **non sappia** da dove viene la geometria: gli stessi assert girano su un
componente del kernel poligonale e su uno caricato da un GLB.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from app.authoring import (CANDIDATE, VALIDATED, AuthoringError, AuthoringService,
                           ComponentLab, VariantRecipe)
from app.core.session import Session
from tests.authoring_fixtures import write_knight_glb

PROCEDURAL = "creature:bulging_eye"


@pytest.fixture(scope="module")
def session():
    return Session()


@pytest.fixture()
def mesh_service(tmp_path):
    """Un componente mesh-backed installato, aperto nel laboratorio."""
    glb = write_knight_glb(tmp_path / "source")
    with AuthoringService() as svc:
        svc.create_authoring_project("lab_plugin",
                                     destination=str(tmp_path / "plugins"))
        svc.import_model(glb)
        svc.select("knight/Sword")
        draft = svc.create_component("blade", role="weapon",
                                     description="A thin imported knight blade",
                                     provides=["limb_mount"], tags=["sword"])
        svc.add_socket(draft.key, "base", direction=(0, -1, 0), radius=0.05)
        svc.snap_socket_to_face(draft.key, "base", "-Y")
        svc.add_param(draft.key, "length", default=1.0, min=0.4, max=2.0,
                      transform="scale_y", semantic_role="length")
        svc.add_param(draft.key, "curvature", default=0.0, min=-1.0, max=1.0,
                      semantic_role="curvature",
                      effect={"type": "fx:bend", "parameter": "amount",
                              "scope": "part", "neutral": 0.0})
        yield svc, draft.key


def labs(session, mesh_service):
    """I due laboratori, per gli assert che devono girare su entrambi."""
    service, key = mesh_service
    return {"procedural": ComponentLab(session, PROCEDURAL),
            "mesh": service.draft_lab(key)}


# --------------------------------------------------------------------------- #
# 23-24. Lo stesso laboratorio sui due backend
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("backend", ["procedural", "mesh"])
def test_the_lab_opens_on_both_backends_and_offers_the_same_things(
        session, mesh_service, backend):
    lab = labs(session, mesh_service)[backend]

    assert lab.params(), "i parametri dichiarati"
    assert all(k.name and k.type for k in lab.params())
    assert lab.effects(), "gli effetti compatibili"
    assert lab.defaults() == {k.name: k.default for k in lab.params()
                              if k.adjustable}
    built = lab.build()
    assert built.ok and built.triangles > 0
    assert built.extents() is not None
    assert isinstance(built.diagnostics(), list)


@pytest.mark.parametrize("backend", ["procedural", "mesh"])
def test_moving_a_parameter_changes_the_geometry_on_both_backends(
        session, mesh_service, backend):
    lab = labs(session, mesh_service)[backend]
    knob = next(k for k in lab.params() if k.bounded and k.type != "enum"
                and float(k.min) > 0)
    low = lab.build({knob.name: float(knob.min)}, remember=False)
    high = lab.build({knob.name: float(knob.max)}, remember=False)

    assert low.ok and high.ok
    assert low.extents() != high.extents(), knob.name


@pytest.mark.parametrize("backend", ["procedural", "mesh"])
def test_the_lab_never_modifies_the_component_it_opened(session, mesh_service,
                                                        backend):
    lab = labs(session, mesh_service)[backend]
    component = lab.component
    before_params = {n: s.default for n, s in component.params.items()}
    baseline = lab.build().extents()

    lab.randomize(11)
    lab.build({}, traits=[{"trait": "std:part_scale", "value": 2.0}])

    assert {n: s.default for n, s in component.params.items()} == before_params
    assert lab.reset().extents() == baseline, "si torna esattamente dove si era"
    # Il registry non e' stato toccato: e' congelato e lo resta.
    assert lab.session.catalog().frozen


@pytest.mark.parametrize("backend", ["procedural", "mesh"])
def test_reset_and_randomize_stay_inside_the_declared_ranges(session,
                                                              mesh_service,
                                                              backend):
    lab = labs(session, mesh_service)[backend]
    built = lab.randomize(3)

    for knob in lab.params():
        if not knob.bounded or knob.name not in built.values:
            continue
        value = float(built.values[knob.name])
        assert float(knob.min) - 1e-9 <= value <= float(knob.max) + 1e-9
    assert built.ok
    # Deterministico: lo stesso seme da' gli stessi valori.
    assert lab.randomize(3).values == built.values


@pytest.mark.parametrize("backend", ["procedural", "mesh"])
def test_the_lab_reports_the_real_diagnostics(session, mesh_service, backend):
    lab = labs(session, mesh_service)[backend]
    built = lab.build(check=True)

    assert built.result.report is not None
    rows = built.diagnostics()
    assert all(set(r) >= {"code", "message", "severity"} for r in rows)
    assert all(r["severity"] in ("error", "warning", "info") for r in rows)


def code_of(path: str) -> str:
    """Il codice di un file, senza commenti e senza stringhe.

    Serve perche' questi test cercano **identificatori**: una prosa che spiega
    perche' un certo ramo non c'e' non e' quel ramo, e un grep ingenuo la
    troverebbe. Si usa `tokenize`, cosi' non c'e' una seconda idea di «che cosa
    e' un commento».
    """
    import io
    import tokenize

    source = Path(path).read_text(encoding="utf-8")
    kept = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        kept.append(token.string)
    return " ".join(kept)


def test_the_lab_has_no_branch_for_mesh_backed_components():
    """Il laboratorio non sa da dove viene la geometria, e si legge dal file.

    Non e' un test di stile: un `if mesh_backed:` qui farebbe passare tutti i
    numeri e fallire il punto 27 della milestone, che chiede **un**
    laboratorio per due backend e non due laboratori con la stessa facciata.
    """
    body = code_of("app/authoring/lab.py")
    for forbidden in ("mesh_backed", "is_mesh", "glb", "gltf", "trimesh",
                      "data_plugin"):
        assert forbidden not in body, forbidden


# --------------------------------------------------------------------------- #
# Trait ed effetti compatibili
# --------------------------------------------------------------------------- #
def test_compatible_traits_follow_the_declared_composition(session):
    """Un trait che colpisce una **parte** e' compatibile con il tutto.

    E' il motivo per cui `subtree()` risolve invece di leggere gli attachment:
    la testa di un umanoide non e' la radice, e `std:head_scale` filtra per
    ruolo. Misurato contro il banco di V5, che su questo stesso componente fa
    ×1.74 sulla testa.
    """
    lab = ComponentLab(session, "humanoid_anatomical:body")
    traits = {t.id for t in lab.traits()}

    assert {"std:head_scale", "std:hand_scale", "std:limb_length"} <= traits
    assert "std:body_mass" in traits
    parts = {c.id for c in lab.subtree()}
    assert len(parts) > 10, "il sottoalbero e' risolto, non solo la radice"
    assert "humanoid_anatomical:head" in parts


def test_compatible_structural_traits_use_the_rule_selector(session):
    lab = ComponentLab(session, "humanoid_anatomical:body")
    assert {t.id for t in lab.structural_traits()} == {"character:arm_count"}

    wheels = ComponentLab(session, "vehicle_stylized:car")
    assert "vehicle:wheel_count" in {t.id for t in wheels.structural_traits()}


def test_an_offered_trait_really_applies(session):
    lab = ComponentLab(session, "humanoid_anatomical:body")
    plain = lab.build()
    for spec in lab.traits():
        built = lab.build({}, traits=[{"trait": spec.id, "value": 1.6
                                       if spec.value.max and spec.value.max >= 1.6
                                       else spec.value.default}],
                          remember=False)
        assert built.ok, spec.id
        assert built.result.traits is not None
    assert plain.ok


def test_compatible_effects_are_the_installed_ones_that_declare_they_fit(session):
    lab = ComponentLab(session, PROCEDURAL)
    offered = {e.id for e in lab.effects()}
    registry = session.catalog()

    assert offered <= {e.id for e in registry.effects()}
    assert {"fx:bend", "fx:squash", "fx:elongate", "fx:taper", "fx:twist"} <= offered
    for effect in lab.effects():
        caps = [c.name for c in lab.component.provides] or [""]
        assert any(effect.fits(cap) for cap in caps), effect.id


def test_an_offered_effect_can_be_applied_from_the_lab(session):
    lab = ComponentLab(session, PROCEDURAL)
    plain = lab.build()
    bent = lab.build({}, effects=[{"type": "fx:squash", "scope": "part",
                                   "amount": 0.9, "params": {"axis": "Y"}}],
                     remember=False)

    assert bent.ok
    assert bent.triangles == plain.triangles
    assert bent.extents() != plain.extents()


# --------------------------------------------------------------------------- #
# 16. Detail level nel laboratorio
# --------------------------------------------------------------------------- #
def test_detail_levels_are_measured_with_real_builds(session):
    lab = ComponentLab(session, "humanoid_anatomical:body")
    levels = lab.detail_levels(range(1, 4))

    assert len(levels[1]) < len(levels[2]) <= len(levels[3])
    assert levels[1] == [n for n in levels[1]]
    assert all(path.startswith("subject") for path in levels[2])


def test_detail_level_and_parameters_stay_separate(session):
    lab = ComponentLab(session, "humanoid_anatomical:body")
    small_detailed = lab.build({}, detail_level=3, remember=False)
    big_simple = lab.build({}, traits=[{"trait": "std:part_scale", "value": 2.5}],
                           detail_level=1, remember=False)

    assert len(big_simple.nodes) < len(small_detailed.nodes)
    assert big_simple.extents()[1] > small_detailed.extents()[1]


# --------------------------------------------------------------------------- #
# 28. Variant recipe
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("backend", ["procedural", "mesh"])
def test_a_variant_keeps_only_what_changed(session, mesh_service, backend):
    lab = labs(session, mesh_service)[backend]
    knob = next(k for k in lab.params() if k.bounded)
    lab.build({knob.name: float(knob.max)})
    recipe = lab.save_variant("tuned")

    assert recipe.base == lab.component_id
    assert recipe.params == {knob.name: pytest.approx(float(knob.max))}
    assert all(name in lab.component.params for name in recipe.params)
    assert recipe.coverage == CANDIDATE


def test_a_variant_rebuilds_the_same_geometry_it_was_saved_from(session):
    lab = ComponentLab(session, PROCEDURAL)
    knob = next(k for k in lab.params() if k.bounded)
    tuned = lab.build({knob.name: float(knob.max)})
    recipe = lab.save_variant("dragon_eye")

    from app.core.session import Options

    again = session.build(recipe.to_plan(), Options(check=True))
    assert again.ok
    assert again.triangles == tuned.triangles
    assert np.allclose(again.scene().bounds(), tuned.bounds(), atol=1e-9)


def test_a_variant_file_is_tiny_and_holds_no_geometry(session, tmp_path):
    lab = ComponentLab(session, PROCEDURAL)
    lab.randomize(5)
    recipe = lab.save_variant("random_eye", description="whatever came out")
    path = recipe.save(tmp_path / "v.json")
    raw = path.read_text(encoding="utf-8")

    assert path.stat().st_size < 700
    assert "mesh" not in raw and "glb" not in raw
    assert json.loads(raw)["base"] == PROCEDURAL
    assert not list(tmp_path.glob("*.glb"))


def test_a_variant_name_that_could_become_a_path_is_refused(session):
    lab = ComponentLab(session, PROCEDURAL)
    with pytest.raises(AuthoringError) as exc:
        lab.save_variant("../escape")
    assert exc.value.code == "AUTHORING_NAME_INVALID"


def test_the_yellow_to_green_bridge_is_a_state_and_not_a_provider(session):
    lab = ComponentLab(session, PROCEDURAL)
    recipe = lab.save_variant("dragon_eye")

    assert recipe.coverage == CANDIDATE, "giallo: da ispezionare"
    assert recipe.promote().coverage == VALIDATED, "verde: l'utente ha deciso"
    # Nessun provider AI dietro: e' un campo, e il codice non ne nomina uno.
    body = code_of("app/authoring/variant.py")
    for forbidden in ("provider", "LLMProvider", "complete_json", "Planner",
                      "make_provider"):
        assert forbidden not in body, forbidden


def test_a_variant_of_a_variant_is_not_a_thing(session):
    """Una ricetta nomina un componente installato, non un'altra ricetta.

    Dichiarato invece che gestito: una catena di ricette avrebbe bisogno di una
    risoluzione ricorsiva dei parametri, cioe' di un secondo sistema di
    composizione accanto al piano. La base e' sempre un `Component`.
    """
    recipe = VariantRecipe(base="creature:bulging_eye", name="a")
    second = VariantRecipe(base=recipe.base, name="b", params=dict(recipe.params))

    assert second.base == "creature:bulging_eye"
    plan = second.to_plan()
    assert plan["root"]["ref"] == "creature:bulging_eye"


def test_an_unknown_component_cannot_be_opened_in_the_lab(session):
    with pytest.raises(AuthoringError) as exc:
        ComponentLab(session, "nowhere:nothing")
    assert exc.value.code == "AUTHORING_UNKNOWN_COMPONENT"
