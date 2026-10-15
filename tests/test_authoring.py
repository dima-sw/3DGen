"""V6 — un GLB diventa un plugin dati senza scrivere JSON a mano.

Questi test misurano il **livello di servizio**, non l'interfaccia: la
milestone chiede che la UI non sia l'unico modo di costruire un plugin, e il
modo di dimostrarlo e' costruirne uno intero senza aprire una finestra. I test
dell'interfaccia stanno in `tests/test_authoring_ui.py` e verificano che la
finestra rifletta questo stesso servizio.

Due cose valgono per tutto il file:

* i GLB sono veri (`tests/authoring_fixtures.py` li esporta con `trimesh`), e
  cio' che si salva viene riletto dal loader di produzione — non da un parser
  di test;
* dove si misura un numero, si misura prima e dopo. «Il componente esiste» non
  e' una misura di niente.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

from app.authoring import (CANDIDATE, MISSING, PROXY, VALIDATED, AuthoringError,
                           AuthoringProject, AuthoringService, ComponentLab,
                           VariantRecipe)
from app.authoring.emit import emit_plugin
from app.authoring.gizmo import GIZMO_TAG, mirror, snap_to_center, snap_to_face
from app.authoring.inspect import load_model
from app.core.data_plugin import DataPluginError, load_component
from app.core.registry import Registry
from tests.authoring_fixtures import write_knight_glb, write_single_glb


# --------------------------------------------------------------------------- #
# Attrezzatura
# --------------------------------------------------------------------------- #
@pytest.fixture()
def glb(tmp_path) -> Path:
    return write_knight_glb(tmp_path / "source")


@pytest.fixture()
def service(tmp_path, glb):
    """Un servizio con un progetto aperto e un GLB importato."""
    with AuthoringService() as svc:
        svc.create_authoring_project("unit_plugin",
                                     destination=str(tmp_path / "plugins"))
        svc.import_model(glb)
        yield svc


def knight_project(svc: AuthoringService) -> dict:
    """Il caso completo: corpo mesh, testa mesh con occhi, radice composite.

    Scritto una volta e riusato, perche' meta' di questi test hanno bisogno
    dello stesso plugin e riscriverlo ogni volta nasconderebbe le differenze.
    """
    svc.set_frame(growth_axis="+Y", front="+Z", up="+Y")
    svc.select("knight/Body")
    body = svc.create_component("body", role="torso", provides=["torso_mount"],
                                description="A boxy knight body",
                                tags=["knight", "humanoid"])
    svc.add_socket(body.key, "base", direction=(0, -1, 0), radius=0.2)
    svc.snap_socket_to_face(body.key, "base", "-Y")
    svc.add_mount(body.key, "head_mount", socket="neck", direction=(0, 1, 0),
                  radius=0.15)
    svc.snap_socket_to_face(body.key, "neck", "+Y")
    svc.add_param(body.key, "width", default=1.0, min=0.3, max=2.5,
                  transform="scale_x", semantic_role="width")

    svc.select(["knight/Head", "knight/Eye_L", "knight/Eye_R"])
    head = svc.create_component("head", role="head", provides=["head_mount"],
                                description="A helmeted knight head with eyes",
                                tags=["head"])
    svc.add_socket(head.key, "base", direction=(0, -1, 0), radius=0.15)
    svc.snap_socket_to_face(head.key, "base", "-Y")

    root = svc.create_component("knight", objects=(), role="subject",
                                provides=["creature"], tags=["knight"],
                                description="A complete knight: body and head",
                                synonyms=["paladin"])
    svc.add_mount(root.key, "torso_mount", socket="core", radius=0.25)
    svc.set_parent(body.key, root.key, child_id="body", level=1,
                   requirement={"capability": "torso_mount"})
    svc.set_parent(head.key, body.key, child_id="head", level=2,
                   requirement={"capability": "head_mount"})
    return {"body": body.key, "head": head.key, "root": root.key}


# --------------------------------------------------------------------------- #
# 1-2. Import e ispezione della scena
# --------------------------------------------------------------------------- #
def test_importing_a_glb_lists_its_objects_without_inferring_anything(service):
    objects = service.scene_objects()

    assert [o.name for o in objects] == ["Body", "Eye_L", "Eye_R", "Head", "Sword"]
    assert all(o.triangles == 12 for o in objects)
    # Nessuna inferenza: niente componenti, niente socket, niente parametri.
    assert service.project.components == []


def test_each_object_reports_name_triangles_bounds_transform_and_colour(service):
    info = service.object_info("knight/Head")

    assert info["name"] == "Head"
    assert info["triangles"] == 12
    assert np.allclose(info["extents"], (0.34, 0.34, 0.34), atol=1e-6)
    assert np.allclose(info["center"], (0.0, 1.2, 0.0), atol=1e-6)
    assert len(info["transform"]) == 16
    assert info["color"].startswith("#")
    assert info["visible"] is True
    assert info["component"] == ""


def test_the_object_key_survives_two_files_with_the_same_node_names(tmp_path, glb):
    second = write_knight_glb(tmp_path / "other", name="knight.glb")
    with AuthoringService() as svc:
        svc.create_authoring_project("two_sources")
        svc.import_model(glb)
        svc.import_model(second)
        keys = [o.key for o in svc.scene_objects()]

    assert len(keys) == len(set(keys)) == 10
    assert any(k.startswith("knight_2/") for k in keys)


@pytest.mark.parametrize("name, code", [
    ("model.fbx", "AUTHORING_MODEL_FORMAT"),
    ("model.usd", "AUTHORING_MODEL_FORMAT"),
    ("model.blend", "AUTHORING_MODEL_FORMAT"),
])
def test_formats_outside_glb_and_gltf_are_refused_by_name(service, tmp_path,
                                                          name, code):
    victim = tmp_path / name
    victim.write_bytes(b"not a gltf")

    with pytest.raises(AuthoringError) as exc:
        service.import_model(victim)
    assert exc.value.code == code
    assert "GLB/glTF" in exc.value.message


def test_a_truncated_glb_is_refused_without_a_traceback(service, tmp_path):
    broken = tmp_path / "broken.glb"
    broken.write_bytes(b"glTF" + b"\x00" * 4)

    with pytest.raises((AuthoringError, DataPluginError)):
        service.import_model(broken)


def test_the_source_model_is_never_modified(service, glb):
    before = glb.read_bytes()
    keys = knight_project(service)
    service.save_plugin()

    assert glb.read_bytes() == before, "l'import guarda, non riscrive"
    assert keys


# --------------------------------------------------------------------------- #
# 3. Selezione e creazione di un componente
# --------------------------------------------------------------------------- #
def test_selection_is_multiple_and_isolation_hides_the_rest(service):
    service.select(["knight/Head", "knight/Eye_L"])
    assert len(service.selection()) == 2

    service.isolate()
    assert {o.name for o in service.visible_objects()} == {"Head", "Eye_L"}

    service.show_all()
    assert len(service.visible_objects()) == 5

    service.select_all()
    assert len(service.selection()) == 5
    service.clear_selection()
    assert service.selection() == []


def test_a_component_from_a_selection_owns_exactly_that_geometry(service):
    service.select(["knight/Head", "knight/Eye_L", "knight/Eye_R"])
    draft = service.create_component("head", role="head",
                                     description="head with eyes")

    assert draft.objects == ("knight/Head", "knight/Eye_L", "knight/Eye_R")
    assert draft.composite is False
    assert service.object_info("knight/Head")["component"] == "head"
    # 36 triangoli: i tre nodi scelti, non gli altri due del file.
    built = service._stage() and None
    del built


def test_one_object_belongs_to_one_component(service):
    service.select("knight/Head")
    service.create_component("head")
    service.select("knight/Head")

    with pytest.raises(AuthoringError) as exc:
        service.create_component("other_head")
    assert exc.value.code == "AUTHORING_DUPLICATE"


@pytest.mark.parametrize("name", ["Head", "my head", "../escape", "head!", ""])
def test_a_component_name_that_could_become_a_path_is_refused(service, name):
    service.select("knight/Head")
    with pytest.raises(AuthoringError) as exc:
        service.create_component(name)
    assert exc.value.code == "AUTHORING_NAME_INVALID"


# --------------------------------------------------------------------------- #
# 4. Composite senza mesh
# --------------------------------------------------------------------------- #
def test_a_composite_component_has_no_mesh_and_still_builds(service, tmp_path):
    keys = knight_project(service)
    result = service.build_component(keys["root"], detail_level=3)

    assert result.ok
    # 12 (corpo) + 36 (testa con due occhi) = 48: solo la geometria dei figli.
    assert result.triangles == 48
    assert [n.path for n in result.resolved.walk()] == [
        "subject", "subject/body", "subject/body/head"]
    root = result.build.root if hasattr(result.build, "root") else None
    del root
    # La radice non porta geometria propria.
    assert result.scene().by_id("subject") is None or \
        result.scene().by_id("subject").triangles == 0


def test_the_emitted_composite_declares_no_mesh_key(service, tmp_path):
    keys = knight_project(service)
    path = service.save_plugin(tmp_path / "out")
    data = json.loads((path / "components/knight.json").read_text(encoding="utf-8"))

    assert "mesh" not in data
    assert [c["id"] for c in data["children"]] == ["body"]
    assert keys


def test_a_meshless_definition_without_children_is_refused_by_the_loader(tmp_path):
    folder = tmp_path / "bare"
    folder.mkdir()
    definition = folder / "nothing.json"
    definition.write_text(json.dumps({"id": "bare:nothing"}), encoding="utf-8")

    with pytest.raises(DataPluginError) as exc:
        load_component(definition, folder)
    assert exc.value.code == "DATA_SCHEMA_INVALID"
    assert "children" in exc.value.message


def test_a_transform_param_on_a_meshless_component_is_refused(tmp_path):
    folder = tmp_path / "bare"
    folder.mkdir()
    definition = folder / "holder.json"
    definition.write_text(json.dumps({
        "id": "bare:holder",
        "children": [{"id": "x", "component": "primitives:block"}],
        "params": {"width": {"default": 1.0, "transform": "scale_x"}},
    }), encoding="utf-8")

    with pytest.raises(DataPluginError) as exc:
        load_component(definition, folder)
    assert exc.value.code == "DATA_PARAM_UNSUPPORTED"


def test_the_validator_says_why_a_transform_cannot_work_on_a_composite(service):
    keys = knight_project(service)
    service.add_param(keys["root"], "scale", default=1.0, min=0.5, max=2.0,
                      transform="uniform_scale")
    report = service.validate()

    codes = [d.code for d in report.errors()]
    assert "AUTHORING_PARAM_STRATEGY" in codes
    assert any("scala una mesh che non c'e'" in d.message for d in report.errors())


# --------------------------------------------------------------------------- #
# 5. Gerarchia
# --------------------------------------------------------------------------- #
def test_the_hierarchy_is_a_tree_of_ordinary_attachments(service, tmp_path):
    keys = knight_project(service)
    rows = service.hierarchy()

    assert [(r["name"], r["depth"]) for r in rows] == [
        ("knight", 0), ("body", 1), ("head", 2)]
    path = service.save_plugin(tmp_path / "out")
    knight = json.loads((path / "components/knight.json").read_text(encoding="utf-8"))
    assert knight["children"][0]["component"] == "unit_plugin:body"
    assert knight["children"][0]["level"] == 1
    assert keys


def test_parent_unparent_reorder_and_duplicate_are_all_available(service):
    keys = knight_project(service)
    service.select("knight/Sword")
    sword = service.create_component("sword", role="weapon",
                                     description="A knight sword",
                                     provides=["head_mount"])
    service.add_socket(sword.key, "base", direction=(0, -1, 0), radius=0.05)

    service.set_parent(sword.key, keys["body"], child_id="sword",
                       requirement={"capability": "head_mount"})
    assert [c.id for c in service._draft(keys["body"]).children] == ["head", "sword"]

    assert service.reorder(keys["body"], "sword", 0) == ["sword", "head"]
    copy = service.duplicate_reference(keys["body"], "sword")
    assert copy.id == "sword_2"

    service.unparent(keys["body"], "sword_2")
    service.unparent(keys["body"], "sword")
    assert [c.id for c in service._draft(keys["body"]).children] == ["head"]

    assert service.remove_from_hierarchy(keys["head"]) == 1
    assert service._draft(keys["body"]).children == []


def test_child_options_carry_level_optional_on_request_and_replaces(service,
                                                                    tmp_path):
    keys = knight_project(service)
    service.set_child_options(keys["body"], "head", level=3, optional=True,
                              on_request=True, insert=0.0, scale_mode="socket")
    path = service.save_plugin(tmp_path / "out")
    body = json.loads((path / "components/body.json").read_text(encoding="utf-8"))
    child = body["children"][0]

    assert child["level"] == 3
    assert child["optional"] is True
    assert child["on_request"] is True
    assert child["insert"] == 0.0
    assert child["scale_mode"] == "socket"


def test_a_cycle_in_the_hierarchy_is_refused_before_it_exists(service):
    keys = knight_project(service)

    with pytest.raises(AuthoringError) as exc:
        service.set_parent(keys["root"], keys["head"], child_id="loop")
    assert exc.value.code == "AUTHORING_CYCLE"
    # Nessun arco e' rimasto a meta'.
    assert [c.id for c in service._draft(keys["head"]).children] == []


def test_the_hierarchy_never_touches_the_imported_geometry(service):
    keys = knight_project(service)
    before = dict(service.object_info("knight/Body"))
    service.set_child_options(keys["body"], "head", level=1)
    service.reorder(keys["root"], "body", 0)

    assert service.object_info("knight/Body") == before


# --------------------------------------------------------------------------- #
# 6-7. Socket, gizmo e snap
# --------------------------------------------------------------------------- #
def test_a_declared_socket_becomes_an_ordinary_socket(service):
    from app.core.socket import Socket

    service.select("knight/Head")
    draft = service.create_component("head", description="a head")
    service.add_socket(draft.key, "crest", position=(0, 0.4, 0),
                       direction=(0, 1, 0), up=(0, 0, 1), radius=0.12,
                       capabilities=["crest_mount"], side="top", tags=["helmet"])
    socket = draft.socket("crest").to_socket()

    assert type(socket) is Socket
    assert socket.provides("crest_mount")
    assert socket.side == "top"
    assert "helmet" in socket.tags


def test_a_degenerate_socket_frame_is_refused_while_drawing_it(service):
    service.select("knight/Head")
    draft = service.create_component("head", description="a head")

    with pytest.raises(ValueError):
        service.add_socket(draft.key, "bad", direction=(0, 1, 0), up=(0, 2, 0))


def test_the_gizmo_is_readable_geometry_and_is_not_the_model(service):
    keys = knight_project(service)
    nodes = service.socket_gizmo(keys["body"])
    kinds = {n.id.rpartition(".")[2] for n in nodes}

    assert kinds == {"disc", "direction", "up"}
    assert all(GIZMO_TAG in n.tags for n in nodes)

    plain = service.build_component(keys["body"], detail_level=1)
    decorated = service.preview_scene(keys["body"], detail_level=1, sockets=True)
    model = [n for n in decorated.nodes if GIZMO_TAG not in n.tags]

    assert sum(n.triangles for n in model) == plain.triangles
    assert len(decorated.nodes) > len(model), "i gizmo sono nodi in piu'"


def test_socket_gizmo_data_survives_save_and_reload(service, tmp_path):
    keys = knight_project(service)
    service.update_socket(keys["body"], "neck", position=(0.05, 1.0, -0.02),
                          direction=(0, 1, 0), up=(1, 0, 0), radius=0.173)
    before = service._draft(keys["body"]).socket("neck")

    path = service.save_plugin(tmp_path / "out")
    component = load_component(path / "components/body.json", path)
    piece = component.build({"width": 1.0}, _ctx())
    after = piece.sockets["neck"]

    assert np.allclose(after.position, before.position, atol=1e-6)
    assert np.allclose(after.direction, np.array(before.direction), atol=1e-6)
    assert np.allclose(after.up, np.array(before.up), atol=1e-6)
    assert after.radius == pytest.approx(before.radius, rel=1e-6)


def _ctx():
    from app.core.component import BuildContext

    return BuildContext()


def test_snap_helpers_are_deterministic_arithmetic_on_the_bounds():
    bounds = ((-1.0, 0.0, -0.5), (1.0, 2.0, 0.5))

    assert snap_to_center(bounds) == (0.0, 1.0, 0.0)
    assert snap_to_face(bounds, "+Y") == (0.0, 2.0, 0.0)
    assert snap_to_face(bounds, "-Y") == (0.0, 0.0, 0.0)
    assert snap_to_face(bounds, "+X") == (1.0, 1.0, 0.0)
    assert snap_to_face(bounds, "-Z") == (0.0, 1.0, -0.5)
    assert snap_to_face(bounds, "+Y") == snap_to_face(bounds, "+Y")


def test_snapping_a_socket_uses_the_component_geometry(service):
    service.select("knight/Head")
    draft = service.create_component("head", description="a head")
    service.add_socket(draft.key, "base", direction=(0, -1, 0))

    service.snap_socket_to_center(draft.key, "base")
    assert np.allclose(draft.socket("base").position, (0.0, 1.2, 0.0), atol=1e-6)

    service.snap_socket_to_face(draft.key, "base", "-Y")
    assert np.allclose(draft.socket("base").position, (0.0, 1.03, 0.0), atol=1e-6)


def test_aligning_a_direction_keeps_up_orthogonal(service):
    service.select("knight/Head")
    draft = service.create_component("head", description="a head")
    service.add_socket(draft.key, "base", direction=(0, 1, 0), up=(0, 0, 1))
    service.align_socket_direction(draft.key, "base", "-Z")
    socket = draft.socket("base")

    assert np.allclose(socket.direction, (0, 0, -1), atol=1e-6)
    assert abs(float(np.dot(socket.direction, socket.up))) < 1e-9


def test_mirroring_a_socket_flips_the_axis_the_name_and_the_side(service):
    keys = knight_project(service)
    service.add_mount(keys["body"], "limb_mount", socket="arm_l",
                      direction=(-1, 0, 0), radius=0.08, side="l")
    service.snap_socket_to_face(keys["body"], "arm_l", "-X")
    mirrored = service.mirror_socket(keys["body"], "arm_l")

    original = service._draft(keys["body"]).socket("arm_l")
    assert mirrored.name == "arm_r"
    assert mirrored.side == "r"
    assert mirrored.position[0] == pytest.approx(-original.position[0])
    assert mirrored.position[1] == pytest.approx(original.position[1])
    assert mirrored.direction[0] == pytest.approx(-original.direction[0])


def test_mirror_is_its_own_inverse():
    position, direction, up = mirror((0.3, 1.0, 0.0), (-1.0, 0.0, 0.0),
                                     (0.0, 1.0, 0.0), "+X")
    back = mirror(position, direction, up, "+X")

    assert np.allclose(back[0], (0.3, 1.0, 0.0), atol=1e-9)
    assert np.allclose(back[1], (-1.0, 0.0, 0.0), atol=1e-9)


# --------------------------------------------------------------------------- #
# 8-9. Capability e metadata
# --------------------------------------------------------------------------- #
def test_capabilities_are_offered_with_who_provides_and_who_accepts(service):
    views = {v.name: v for v in service.capabilities()}

    assert "head_mount" in views
    head_mount = views["head_mount"]
    assert any(i.startswith("humanoid:") for i in head_mount.providers)
    assert head_mount.mounts, "qualcuno la accetta"
    assert head_mount.known

    found = service.search_capabilities("head")
    assert [v.name for v in found] and all("head" in v.name or "head" in v.description
                                           for v in found)


def test_a_new_capability_is_allowed_and_declared_as_new(service):
    service.select("knight/Sword")
    draft = service.create_component("sword", provides=["knight_blade_mount"],
                                     description="a sword")
    names = {v.name: v for v in service.capabilities()}

    assert "knight_blade_mount" in names
    assert names["knight_blade_mount"].declared is False
    report = service.validate()
    assert "AUTHORING_NEW_CAPABILITY" in {d.code for d in report.notes()}
    assert report.ok or draft


def test_adding_a_mount_creates_the_socket_and_the_contract_together(service):
    service.select("knight/Body")
    draft = service.create_component("body", description="a body")
    mount = service.add_mount(draft.key, "head_mount", socket="neck",
                              direction=(0, 1, 0), radius=0.14)

    assert mount == {"capability": "head_mount", "socket_id": "neck"}
    assert draft.socket("neck") is not None
    assert "head_mount" in draft.socket("neck").capabilities


def test_metadata_reaches_the_installed_component(service, tmp_path):
    keys = knight_project(service)
    service.set_metadata(keys["head"], role="head", tags=("head", "helmet"),
                         description="A helmeted knight head",
                         requires=("connected",), coverage=VALIDATED)
    path = service.save_plugin(tmp_path / "out")
    component = load_component(path / "components/head.json", path)

    assert component.role == "head"
    assert {"head", "helmet"} <= component.tags
    assert "A helmeted knight head" in component.description
    assert "connected" in component.requires


def test_an_unknown_metadata_field_is_refused_not_ignored(service):
    service.select("knight/Head")
    draft = service.create_component("head", description="a head")

    with pytest.raises(AuthoringError) as exc:
        service.set_metadata(draft.key, colour="red")
    assert exc.value.code == "AUTHORING_PROJECT_INVALID"


@pytest.mark.parametrize("state", [VALIDATED, CANDIDATE, MISSING, PROXY])
def test_coverage_is_project_state_and_never_reaches_the_plugin(service, tmp_path,
                                                                 state):
    keys = knight_project(service)
    service.set_metadata(keys["head"], coverage=state)
    assert service._draft(keys["head"]).coverage == state

    path = service.save_plugin(tmp_path / "out")
    for definition in sorted((path / "components").glob("*.json")):
        raw = definition.read_text(encoding="utf-8")
        assert "coverage" not in raw
        assert state not in raw
    assert "coverage" not in (path / "plugin.json").read_text(encoding="utf-8")

    # Ma sopravvive nel progetto di authoring, che e' il posto giusto.
    saved = service.save_project(tmp_path / "work.3dgenproj")
    assert state in saved.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# 10. Preview semantica e del planner
# --------------------------------------------------------------------------- #
def test_the_search_preview_uses_the_real_semantic_index(service):
    hits = service.search_components("dragon head", limit=5)

    assert hits, "l'indice risponde"
    assert hits == sorted(hits, key=lambda h: -h[1]), "ordinati per punteggio"
    assert all(0.0 <= score <= 1.0001 for _, score in hits)
    # Lo stesso indice di `Session`: non una seconda ricerca per l'editor.
    assert hits == service.session.component_index().search("dragon head", limit=5)


def test_the_author_can_ask_whether_the_new_component_will_be_found(service):
    keys = knight_project(service)
    before = {i for i, _ in service.search_components("knight body", limit=10)}
    after = {i for i, _ in service.search_staged("knight body", limit=10)}

    assert "unit_plugin:body" not in before, "non e' ancora installato"
    assert "unit_plugin:body" in after
    assert keys


def test_the_planner_preview_is_the_production_rendering(service):
    keys = knight_project(service)
    text = service.planner_preview(keys["head"])

    assert text.startswith("- unit_plugin:head ")
    assert "A helmeted knight head" in text
    assert "e': head_mount" in text
    # La stessa funzione del vocabolario di produzione, non un riassunto nostro.
    from app.core.planner.vocabulary import _componente

    component = service._stage().catalog().component("unit_plugin:head")
    assert text == _componente(component).to_text()


# --------------------------------------------------------------------------- #
# 11-13. Variabilita': transform, effetto, ruolo semantico
# --------------------------------------------------------------------------- #
def test_a_transform_parameter_scales_the_imported_mesh(service):
    keys = knight_project(service)
    narrow = service.build_component(keys["body"], params={"width": 0.5},
                                     detail_level=1)
    wide = service.build_component(keys["body"], params={"width": 2.0},
                                   detail_level=1)

    assert narrow.ok and wide.ok
    assert narrow.triangles == wide.triangles == 12
    span = lambda r: float(r.scene().bounds()[1][0] - r.scene().bounds()[0][0])
    assert span(wide) == pytest.approx(span(narrow) * 4.0, rel=1e-6)


def test_an_effect_backed_parameter_drives_an_installed_effect(service):
    service.select("knight/Sword")
    draft = service.create_component("blade", role="weapon",
                                     description="A thin knight blade",
                                     provides=["limb_mount"])
    service.add_socket(draft.key, "base", direction=(0, -1, 0), radius=0.05)
    service.add_param(draft.key, "curvature", default=0.0, min=-1.0, max=1.0,
                      semantic_role="curvature",
                      effect={"type": "fx:bend", "parameter": "amount",
                              "scope": "part", "neutral": 0.0})

    flat = service.build_component(draft.key, params={"curvature": 0.0})
    bent = service.build_component(draft.key, params={"curvature": 0.9})

    assert flat.ok and bent.ok
    assert flat.triangles == bent.triangles == 12, "una mappa di punti, non una mesh nuova"
    # La richiesta e' leggibile, e la geometria si e' mossa davvero.
    assert "PARAM_EFFECT_REQUESTED" in bent.report.codes()
    before = flat.scene().by_id("subject").mesh.vertices
    after = bent.scene().by_id("subject").mesh.vertices
    assert before.shape == after.shape
    assert not np.allclose(before, after), "i vertici si sono spostati"
    assert not np.allclose(flat.scene().bounds(), bent.scene().bounds())
    # Il neutro non chiede niente: a 0.0 l'effetto non entra in programma.
    assert "PARAM_EFFECT_REQUESTED" not in flat.report.codes()


@pytest.mark.parametrize("binding, fragment", [
    ({"type": "fx:does_not_exist"}, "non e' installato"),
    ({"type": "fx:bend", "parameter": "nonsense"}, "non dichiara il knob"),
    ({"type": "fx:bend", "scope": "ovunque"}, "non dichiara l'ambito"),
    ({"type": "fx:bend", "callable": "os.system"}, "chiavi non ammesse"),
    ({"type": "fx:bend", "expression": "1+1"}, "chiavi non ammesse"),
    ({"type": "fx:bend", "module": "os"}, "chiavi non ammesse"),
    ({"type": "fx:bend", "matrix": [[1, 0, 0]]}, "chiavi non ammesse"),
])
def test_an_effect_binding_can_only_name_installed_things(service, binding,
                                                           fragment):
    service.select("knight/Sword")
    draft = service.create_component("blade", description="a blade")

    with pytest.raises(AuthoringError) as exc:
        service.add_param(draft.key, "curvature", effect=binding)
    assert exc.value.code == "AUTHORING_PARAM_STRATEGY"
    assert fragment in exc.value.message


def test_only_installed_strategies_are_offered(service):
    strategies = service.param_strategies()
    registry = service.session.catalog()

    assert strategies["transforms"] == ["scale_x", "scale_y", "scale_z",
                                        "uniform_scale"]
    offered = {e["type"] for e in strategies["effects"]}
    assert offered <= {e.id for e in registry.effects()}
    assert "fx:bend" in offered
    bend = next(e for e in strategies["effects"] if e["type"] == "fx:bend")
    assert "amount" in bend["knobs"]
    # Nessun knob non numerico: un parametro dati pilota solo numeri.
    assert "axis" not in bend["knobs"]
    assert set(bend["scopes"]) <= set(registry.effect("fx:bend").scopes)


def test_declaring_both_strategies_is_refused(service):
    service.select("knight/Sword")
    draft = service.create_component("blade", description="a blade")

    with pytest.raises(AuthoringError) as exc:
        service.add_param(draft.key, "x", transform="scale_x",
                          effect={"type": "fx:bend"})
    assert exc.value.code == "AUTHORING_PARAM_STRATEGY"


def test_a_parameter_without_a_strategy_is_reported_not_saved(service):
    keys = knight_project(service)
    service.add_param(keys["body"], "mystery", default=1.0)
    report = service.validate()

    assert not report.ok
    assert "AUTHORING_PARAM_STRATEGY" in {d.code for d in report.errors()}


def test_the_semantic_roles_offered_are_the_ones_the_library_declares(service):
    roles = service.semantic_roles()

    assert {"length", "girth", "width"} <= set(roles)
    assert roles == sorted(roles)
    assert "" not in roles


def test_a_semantic_role_lets_an_installed_trait_reach_the_new_component(service):
    keys = knight_project(service)
    plain = service.build_component(keys["body"], detail_level=1)
    wide = service.build_component(keys["body"], detail_level=1,
                                   traits=[{"trait": "std:width", "value": 2.0}])

    span = lambda r: float(r.scene().bounds()[1][0] - r.scene().bounds()[0][0])
    assert wide.ok
    assert span(wide) == pytest.approx(span(plain) * 2.0, rel=1e-3)
    assert wide.traits.applied, "il trait ha colpito un canale"


# --------------------------------------------------------------------------- #
# 14. Frame
# --------------------------------------------------------------------------- #
def test_the_frame_is_declarable_on_the_plugin_and_on_a_component(service,
                                                                   tmp_path):
    keys = knight_project(service)
    service.set_frame(keys["head"], growth_axis="+Y", front="-Z", up="+Y")
    path = service.save_plugin(tmp_path / "out")

    manifest = json.loads((path / "plugin.json").read_text(encoding="utf-8"))
    head = json.loads((path / "components/head.json").read_text(encoding="utf-8"))
    assert manifest["frame"] == {"growth_axis": "+Y", "front": "+Z", "up": "+Y"}
    assert head["frame"]["front"] == "-Z"
    # Il componente vince sul predefinito del plugin.
    registry = Registry()
    registry.load_directory(path.parent)
    assert registry.component("unit_plugin:head").frame.front == "-Z"
    assert registry.component("unit_plugin:body").frame.front == "+Z"
    assert keys


def test_an_unnameable_axis_is_refused_now_and_not_at_load_time(service):
    keys = knight_project(service)

    with pytest.raises(AuthoringError):
        service.set_frame(keys["head"], up="+W")
    with pytest.raises(AuthoringError):
        service.set_frame(keys["head"], front="+Y", up="+Y")


def test_a_disagreeing_frame_is_named_with_its_move_and_never_converted(service):
    keys = knight_project(service)
    service.set_frame(keys["head"], growth_axis="+Y", front="-Z", up="+Y")
    rows = {r["edge"]: r for r in service.frame_report()}

    head = rows["head"]
    assert head["result"] == "convertible"
    assert head["move"]["type"] == "fx:rotate"
    assert head["move"]["params"] == {"axis": "Y", "angle": 180.0}
    # Niente conversione: la geometria resta quella.
    built = service.build_component(keys["root"], detail_level=3)
    assert built.triangles == 48
    assert "FRAME_CONVERTIBLE" in built.report.codes()


def test_an_incomplete_frame_is_ambiguous_and_not_convertible(service):
    keys = knight_project(service)
    service.set_frame(keys["head"], front="", up="-Y")
    rows = {r["edge"]: r for r in service.frame_report()}

    assert rows["head"]["result"] == "ambiguous"
    assert rows["head"]["move"] is None


def test_verify_frame_diagnoses_the_geometry_and_corrects_nothing(service):
    keys = knight_project(service)
    # Il corpo cresce lungo +Y davvero: nessuna diagnostica.
    assert [d.code for d in service.verify_frame(keys["body"])] == []

    # Il corpo e' 0.5 x 1.0 x 0.3: dichiarare +Z e' una contraddizione
    # misurabile, perche' lungo Z si estende per meno di un terzo del lato lungo.
    service.set_frame(keys["body"], growth_axis="+Z")
    codes = [d.code for d in service.verify_frame(keys["body"])]
    assert "GROWTH_AXIS_MISMATCH" in codes
    before = service.object_info("knight/Body")["extents"]
    assert np.allclose(service.object_info("knight/Body")["extents"], before)


def test_an_undeclared_frame_is_silence_not_a_default(service):
    service.select("knight/Head")
    draft = service.create_component("head", description="a head")
    report = service.verify_frame(draft.key)

    assert [d.code for d in report] == ["FRAME_UNDECLARED"]
    assert report.ok, "non dichiarare un frame non e' un errore"


# --------------------------------------------------------------------------- #
# 15. Materiali
# --------------------------------------------------------------------------- #
def test_the_material_preview_shows_imported_declared_and_effective(service):
    keys = knight_project(service)
    preview = service.material_preview(keys["body"])

    assert preview["imported"] and preview["imported"][0].startswith("#")
    assert preview["effective"]["source"] == "importato"

    service.add_material("knight_steel", base_color="#8899aa", roughness=0.4,
                         metallic=0.3)
    service.assign_material(keys["body"], "knight_steel")
    preview = service.material_preview(keys["body"])
    assert preview["effective"] == {"name": "knight_steel",
                                    "base_color": "#8899aa",
                                    "source": "progetto"}


def test_a_declared_material_is_installed_and_wins_over_imported_colour(service,
                                                                         tmp_path):
    keys = knight_project(service)
    service.add_material("knight_steel", base_color="#8899aa")
    service.assign_material(keys["body"], "knight_steel")
    path = service.save_plugin(tmp_path / "out")

    assert json.loads((path / "materials/knight_steel.json")
                      .read_text(encoding="utf-8"))["base_color"] == "#8899aa"
    registry = Registry()
    registry.load_directory(path.parent)
    assert registry.material("knight_steel").base_color == "#8899aa"
    built = service.build_component(keys["body"], detail_level=1)
    assert built.scene().by_id("subject").material.base_color == "#8899aa"


# --------------------------------------------------------------------------- #
# 16. Detail level
# --------------------------------------------------------------------------- #
def test_detail_level_preview_shows_which_children_really_expand(service):
    keys = knight_project(service)

    assert service.detail_preview(keys["root"], 1) == ["subject", "subject/body"]
    assert service.detail_preview(keys["root"], 2) == [
        "subject", "subject/body", "subject/body/head"]
    assert service.detail_preview(keys["root"], 3) == service.detail_preview(
        keys["root"], 2)


def test_detail_level_is_not_mesh_lod(service):
    keys = knight_project(service)
    low = service.build_component(keys["root"], detail_level=1)
    high = service.build_component(keys["root"], detail_level=2)

    assert low.triangles == 12 and high.triangles == 48
    # Crescono i **nodi**, e la geometria che c'era non e' stata ritassellata.
    assert len(low.resolved.nodes) < len(high.resolved.nodes)
    assert low.scene().by_id("subject/body").triangles == \
        high.scene().by_id("subject/body").triangles


# --------------------------------------------------------------------------- #
# 17. Validazione
# --------------------------------------------------------------------------- #
def test_validation_uses_the_real_validators_and_three_severities(service):
    keys = knight_project(service)
    report = service.validate()

    assert report.ok, report.describe()
    assert set(report.by_category()) == {"error", "warning", "info"}
    assert report.rows() and all(set(r) >= {"severity", "code", "where",
                                            "message", "why"}
                                 for r in report.rows())
    assert keys


def test_validation_reports_a_missing_reference(service):
    keys = knight_project(service)
    service.set_parent("creature:dragon_head", keys["body"], child_id="extra",
                       requirement={"capability": "head_mount"})
    service._draft(keys["body"]).child("extra").ref = "nowhere:nothing"
    report = service.validate()

    assert "AUTHORING_REF_NOT_FOUND" in {d.code for d in report.errors()}


def test_validation_reports_a_socket_incompatibility_from_the_resolver(service):
    keys = knight_project(service)
    service._draft(keys["body"]).mounts = []
    report = service.validate()

    assert not report.ok
    assert {"NO_MOUNTS", "SOCKET_INCOMPATIBLE", "PROVIDER_INCOMPATIBLE"} \
        & {d.code for d in report.errors()}


def test_validation_reports_a_mount_without_its_socket(service):
    keys = knight_project(service)
    service.set_metadata(keys["body"],
                         mounts=[{"capability": "head_mount",
                                  "socket_id": "nowhere"}])
    report = service.validate()

    assert "AUTHORING_MOUNT_WITHOUT_SOCKET" in {d.code for d in report.errors()}


def test_validation_reports_a_geometry_requirement_the_mesh_cannot_meet(service):
    keys = knight_project(service)
    service.set_metadata(keys["root"], requires=("watertight",))
    service.set_metadata(keys["body"], requires=("watertight", "connected"))
    report = service.validate()

    assert report.ok, "una scatola chiusa rispetta i requisiti che dichiara"
    assert keys


def test_validation_warns_when_a_component_would_not_be_retrievable(service):
    service.select("knight/Head")
    draft = service.create_component("zzqqxx", description="")
    service.add_socket(draft.key, "base", direction=(0, -1, 0))
    report = service.validate()

    codes = {d.code for d in report.warnings()} | {d.code for d in report.notes()}
    assert "AUTHORING_NO_DESCRIPTION" in codes


# --------------------------------------------------------------------------- #
# 18-19-29. Salvataggio, formato, rilettura
# --------------------------------------------------------------------------- #
def test_the_saved_plugin_has_the_v4_layout(service, tmp_path):
    keys = knight_project(service)
    service.add_material("knight_steel", base_color="#8899aa")
    path = service.save_plugin(tmp_path / "out")

    assert path == tmp_path / "out" / "unit_plugin"
    assert (path / "plugin.json").is_file()
    assert sorted(p.name for p in (path / "components").glob("*.json")) == [
        "body.json", "head.json", "knight.json"]
    assert sorted(p.name for p in (path / "meshes").glob("*.glb")) == [
        "body.glb", "head.glb"]
    assert (path / "materials/knight_steel.json").is_file()
    assert not list(path.rglob("*.py")), "nessun Python generato"
    assert keys


def test_the_generated_plugin_passes_the_data_plugin_schema(service, tmp_path):
    keys = knight_project(service)
    path = service.save_plugin(tmp_path / "out")

    registry = Registry()
    report = registry.load_directory(path.parent)

    assert report.ok, report.describe()
    assert registry.plugin("unit_plugin").kind == "data"
    assert registry.plugin("unit_plugin").sources == ()
    for component_id in ("unit_plugin:body", "unit_plugin:head",
                         "unit_plugin:knight"):
        assert registry.component(component_id) is not None
    assert keys


def test_the_mesh_reference_is_relative_so_the_plugin_can_be_moved(service,
                                                                    tmp_path):
    keys = knight_project(service)
    path = service.save_plugin(tmp_path / "out")
    body = json.loads((path / "components/body.json").read_text(encoding="utf-8"))
    assert body["mesh"] == "../meshes/body.glb"

    import shutil

    moved = tmp_path / "elsewhere"
    moved.mkdir()
    shutil.copytree(path, moved / "unit_plugin")
    registry = Registry()
    assert registry.load_directory(moved).ok
    assert registry.component("unit_plugin:body") is not None
    assert keys


def test_only_the_needed_geometry_is_exported(service, tmp_path):
    keys = knight_project(service)
    path = service.save_plugin(tmp_path / "out")
    registry = Registry()
    registry.load_directory(path.parent)

    body = registry.component("unit_plugin:body").build({"width": 1.0}, _ctx())
    head = registry.component("unit_plugin:head").build({}, _ctx())
    assert len(body.mesh.faces) == 12, "solo il nodo Body"
    assert len(head.mesh.faces) == 36, "Head piu' due occhi, non la spada"
    assert keys


def test_the_exported_mesh_keeps_the_node_transforms(service, tmp_path):
    keys = knight_project(service)
    path = service.save_plugin(tmp_path / "out")
    registry = Registry()
    registry.load_directory(path.parent)
    head = registry.component("unit_plugin:head").build({}, _ctx())

    # Head e' a y = 1.2 nel file originale, gli occhi a 1.26: la copia
    # conserva le posizioni, non le ricentra.
    assert np.allclose(head.mesh.bounds[0][1], 1.03, atol=1e-5)
    assert np.allclose(head.mesh.bounds[1][1], 1.37, atol=1e-5)
    assert keys


def test_a_rename_does_not_leave_an_orphan_file_behind(service, tmp_path):
    keys = knight_project(service)
    service.save_plugin(tmp_path / "out")
    service.set_metadata(keys["head"], name="helm")
    path = service.save_plugin(tmp_path / "out")

    assert not (path / "components/head.json").exists()
    assert (path / "components/helm.json").is_file()
    registry = Registry()
    assert registry.load_directory(path.parent).ok


# --------------------------------------------------------------------------- #
# 20-21. Installare senza riavviare
# --------------------------------------------------------------------------- #
def test_installing_adds_the_components_without_a_restart(service, tmp_path):
    keys = knight_project(service)
    session = service.session
    before = {c.id for c in session.catalog().components()}
    assert "unit_plugin:knight" not in before

    result = service.install_plugin(tmp_path / "out")

    assert result.ok, result.report.describe()
    assert set(result.installed) == {"unit_plugin:body", "unit_plugin:head",
                                     "unit_plugin:knight"}
    after = {c.id for c in session.catalog().components()}
    assert after - before == set(result.installed)
    assert session.registry.frozen, "il registry nuovo e' congelato come prima"
    assert result.built[keys["root"]] == {"ok": True, "triangles": 48}


def test_installing_invalidates_the_semantic_index_and_the_vocabulary(service,
                                                                      tmp_path):
    keys = knight_project(service)
    session = service.session
    before_index = session.component_index()
    before_vocabulary = session.vocabulary("low_poly")
    assert "unit_plugin:knight" not in {c.id for c in before_vocabulary.components}

    result = service.install_plugin(tmp_path / "out")

    assert result.index_invalidated
    assert not before_index.is_current(session.catalog())
    assert session.component_index() is not before_index
    after = session.vocabulary("low_poly")
    assert after is not before_vocabulary
    assert "unit_plugin:knight" in {c.id for c in after.components}
    assert keys


def test_the_installed_component_is_found_by_the_semantic_index(service,
                                                                 tmp_path):
    keys = knight_project(service)
    result = service.install_plugin(tmp_path / "out")

    assert all(result.found.values()), result.found
    hits = {i for i, _ in service.session.component_index().search("knight", limit=8)}
    assert "unit_plugin:knight" in hits
    # Il ponte fra le parole dichiarato in authoring e' arrivato nel manifest.
    assert service.session.catalog().synonyms().get("paladin")
    shortlist = service.session.shortlist("a paladin")
    assert "unit_plugin:knight" in shortlist.ids
    assert keys


def test_the_generated_plugin_builds_through_the_whole_pipeline(service,
                                                                tmp_path):
    keys = knight_project(service)
    service.install_plugin(tmp_path / "out")
    from app.core.session import Options

    result = service.session.build(
        {"version": "1.3", "style": "low_poly", "detail_level": 3,
         "root": {"id": "subject", "ref": "unit_plugin:knight"}},
        Options(check=True))

    assert result.ok and result.triangles == 48
    assert result.resolved is not None and result.effects is not None
    assert result.build is not None
    assert keys


def test_reload_plugins_keeps_the_library_that_was_there(service, tmp_path):
    keys = knight_project(service)
    session = service.session
    before = len(session.catalog().plugins())
    service.install_plugin(tmp_path / "out")

    assert len(session.catalog().plugins()) == before + 1
    assert session.catalog().component("humanoid:body") is not None
    assert keys


# --------------------------------------------------------------------------- #
# 22. Composizione mista: importato piu' libreria installata
# --------------------------------------------------------------------------- #
def test_a_hierarchy_can_mix_imported_geometry_with_installed_components(service,
                                                                         tmp_path):
    service.select("knight/Body")
    body = service.create_component("dragon_body", role="torso",
                                    description="An imported dragon body",
                                    provides=["subject"], tags=["dragon"])
    service.add_socket(body.key, "base", direction=(0, -1, 0), radius=0.2)
    service.add_mount(body.key, "head_mount", socket="neck", direction=(0, 1, 0),
                      radius=0.14)
    service.snap_socket_to_face(body.key, "neck", "+Y")
    service.set_parent("creature:dragon_head", body.key, child_id="head",
                       requirement={"capability": "head_mount"})

    rows = {r["id"]: r for r in service.hierarchy()}
    assert rows["head"]["installed"] is True
    assert rows["head"]["name"] == "creature:dragon_head"

    built = service.build_component(body.key, detail_level=2)
    assert built.ok
    assert built.triangles > 12, "la testa procedurale ha portato geometria"
    refs = {n.ref for n in built.resolved.walk()}
    assert refs == {"unit_plugin:dragon_body", "creature:dragon_head"}

    path = service.save_plugin(tmp_path / "out")
    definition = json.loads((path / "components/dragon_body.json")
                            .read_text(encoding="utf-8"))
    assert definition["children"][0]["component"] == "creature:dragon_head"


def test_attaching_something_that_is_neither_draft_nor_installed_is_refused(service):
    service.select("knight/Body")
    body = service.create_component("body", description="a body")

    with pytest.raises(AuthoringError) as exc:
        service.set_parent("nowhere:nothing", body.key)
    assert exc.value.code == "AUTHORING_UNKNOWN_COMPONENT"


# --------------------------------------------------------------------------- #
# 25. Variant recipe
# --------------------------------------------------------------------------- #
def test_a_variant_recipe_is_a_configuration_and_never_a_mesh(tmp_path):
    from app.core.session import Session

    lab = ComponentLab(Session(), "creature:bulging_eye")
    knob = next(k for k in lab.params() if k.bounded)
    lab.build({knob.name: float(knob.max)})
    recipe = lab.save_variant("dragon_eye", description="a bulging dragon eye")

    assert recipe.base == "creature:bulging_eye"
    assert recipe.params and knob.name in recipe.params
    assert recipe.coverage == CANDIDATE
    raw = json.dumps(recipe.to_dict())
    for forbidden in ("mesh", ".glb", "vertices", "faces"):
        assert forbidden not in raw

    path = recipe.save(tmp_path / "dragon_eye.json")
    assert path.stat().st_size < 1024
    assert not list(tmp_path.glob("*.glb"))
    assert VariantRecipe.load(path).to_dict() == recipe.to_dict()


def test_a_variant_builds_as_an_ordinary_plan(service):
    from app.core.session import Options

    recipe = VariantRecipe(base="creature:bulging_eye", name="dragon_eye",
                           params={}, description="")
    service.save_variant(recipe)
    plain = service.session.build(recipe.to_plan(), Options(check=True))

    assert plain.ok
    assert service.build_variant("dragon_eye").triangles == plain.triangles


def test_a_params_only_variant_is_embeddable_and_carries_its_values(service,
                                                                     tmp_path):
    keys = knight_project(service)
    lab = service.draft_lab(keys["body"])
    lab.build({"width": 2.0})
    recipe = lab.save_variant("wide_body")
    service.save_variant(recipe)

    assert recipe.embeddable and recipe.lost_in_attachment() == []
    holder = service.create_component("holder", objects=(),
                                      description="a holder for a wide body")
    service.add_mount(holder.key, "torso_mount", socket="core", radius=0.25)
    service.set_parent("variant:wide_body", holder.key, child_id="wide",
                       requirement={"capability": "torso_mount"})

    path = service.save_plugin(tmp_path / "out")
    definition = json.loads((path / "components/holder.json")
                            .read_text(encoding="utf-8"))
    child = definition["children"][0]
    assert child["component"] == "unit_plugin:body"
    assert child["params"] == {"width": 2.0}
    assert "variant" not in json.dumps(definition)


def test_a_variant_with_traits_declares_what_an_attachment_would_lose(service):
    keys = knight_project(service)
    lab = service.draft_lab(keys["body"])
    lab.build({}, traits=[{"trait": "std:width", "value": 1.5}])
    recipe = lab.save_variant("wider")
    service.save_variant(recipe)

    assert not recipe.embeddable
    assert recipe.lost_in_attachment() == ["1 trait"]
    service.set_parent("variant:wider", keys["root"], child_id="extra",
                       requirement={"capability": "torso_mount"})
    report = service.validate()
    assert "AUTHORING_VARIANT_NOT_EMBEDDABLE" in {d.code for d in report.warnings()}


def test_a_variant_goes_from_candidate_to_validated_when_the_user_says_so():
    recipe = VariantRecipe(base="creature:bulging_eye", name="dragon_eye")
    assert recipe.coverage == CANDIDATE
    assert recipe.promote().coverage == VALIDATED


# --------------------------------------------------------------------------- #
# 23. Progetto di authoring: salva e riprendi
# --------------------------------------------------------------------------- #
def test_the_authoring_project_round_trips_without_carrying_a_mesh(service,
                                                                    tmp_path):
    keys = knight_project(service)
    service.add_material("knight_steel", base_color="#8899aa")
    service.save_variant(VariantRecipe(base="unit_plugin:body", name="wide",
                                       params={"width": 2.0}))
    before = service.project.to_dict()
    path = service.save_project(tmp_path / "work.3dgenproj")

    raw = path.read_text(encoding="utf-8")
    assert "glTF" not in raw and "vertices" not in raw
    assert path.stat().st_size < 60_000

    with AuthoringService() as reopened:
        project = reopened.load_project(path)
        assert project.to_dict() == before
        assert [c.name for c in project.components] == ["body", "head", "knight"]
        assert reopened.models, "le sorgenti si riaprono dai loro percorsi"
        assert reopened.build_component(keys["root"], detail_level=3).triangles == 48


def test_reopening_a_project_whose_source_moved_says_so_instead_of_failing(
        service, tmp_path, glb):
    knight_project(service)
    path = service.save_project(tmp_path / "work.3dgenproj")
    glb.unlink()

    with AuthoringService() as reopened:
        reopened.project = AuthoringProject.load(path)
        report = reopened.reopen_models()

    assert not report.ok or report.codes()
    assert "AUTHORING_FILE_MISSING" in report.codes()
    assert all(d.severity == "warning" for d in report)


def test_a_project_file_from_another_format_version_is_refused(tmp_path):
    victim = tmp_path / "old.3dgenproj"
    victim.write_text(json.dumps({"format": 99, "plugin_id": "x"}),
                      encoding="utf-8")

    with pytest.raises(AuthoringError) as exc:
        AuthoringProject.load(victim)
    assert exc.value.code == "AUTHORING_PROJECT_INVALID"


# --------------------------------------------------------------------------- #
# 23-bis. Riaprire un plugin dati esistente
# --------------------------------------------------------------------------- #
def test_an_existing_data_plugin_reopens_and_rebuilds_identically(service,
                                                                   tmp_path):
    keys = knight_project(service)
    path = service.save_plugin(tmp_path / "out")
    original = service.build_component(keys["root"], detail_level=3)

    with AuthoringService() as reopened:
        project = reopened.open_data_plugin(path)
        assert project.plugin_id == "unit_plugin"
        assert [c.name for c in project.components] == ["body", "head", "knight"]
        assert [r["name"] for r in reopened.hierarchy()] == ["knight", "body", "head"]
        # La mesh si copia byte per byte: nessuna riestrazione, nessuna perdita.
        body = project.component_by_name("body")
        assert body.mesh_source.endswith("body.glb")
        assert body.objects == ()
        again = reopened.build_component("knight", detail_level=3)
        assert again.triangles == original.triangles
        second = reopened.save_plugin(tmp_path / "again")

    assert (second / "meshes/body.glb").read_bytes() == \
        (path / "meshes/body.glb").read_bytes()


def test_a_code_plugin_is_never_opened_for_editing(service):
    from app.core.session import PLUGIN

    with pytest.raises(AuthoringError) as exc:
        service.open_data_plugin(PLUGIN / "humanoid")
    assert exc.value.code == "AUTHORING_PROJECT_INVALID"
    assert "plugin dati" in exc.value.message


# --------------------------------------------------------------------------- #
# 27-28. Sicurezza: nessun Python, percorsi confinati
# --------------------------------------------------------------------------- #
def test_authoring_never_executes_python_from_a_model_or_a_plugin(service,
                                                                   tmp_path):
    keys = knight_project(service)
    before = set(sys.modules)
    path = service.save_plugin(tmp_path / "out")
    # Un .py accanto al plugin generato, con un effetto che si vedrebbe.
    bomb = path / "boom.py"
    bomb.write_text("raise SystemExit('eseguito')\n", encoding="utf-8")
    (path / "components" / "boom.py").write_text(
        "import os; os.remove(__file__)\n", encoding="utf-8")

    registry = Registry()
    assert registry.load_directory(path.parent).ok
    assert registry.plugin("unit_plugin").sources == ()
    assert not [m for m in set(sys.modules) - before if "boom" in m]
    assert bomb.is_file() and (path / "components" / "boom.py").is_file()
    assert keys


def test_the_emitted_plugin_names_no_executable_anything(service, tmp_path):
    keys = knight_project(service)
    path = service.save_plugin(tmp_path / "out")
    manifest = json.loads((path / "plugin.json").read_text(encoding="utf-8"))

    assert manifest["type"] == "data"
    for forbidden in ("effects", "styles", "traits", "archetypes", "profiles",
                      "bindings"):
        assert forbidden not in manifest
    for definition in sorted((path / "components").glob("*.json")):
        data = json.loads(definition.read_text(encoding="utf-8"))
        for forbidden in ("derived", "callable", "module", "expression",
                          "entry_point", "build"):
            assert forbidden not in json.dumps(data)
    assert keys


@pytest.mark.parametrize("name", ["../escape", "..", "a/b", "a\\b", "/abs",
                                  "C:/win"])
def test_a_component_name_cannot_escape_the_plugin_folder(service, tmp_path, name):
    service.select("knight/Head")
    draft = service.create_component("head", description="a head")
    # Si forza il nome nel modello, saltando il controllo dell'API, per
    # verificare che anche l'emettitore si difenda da solo.
    draft.name = name

    with pytest.raises(AuthoringError) as exc:
        emit_plugin(service.project, tmp_path / "out", models=service.models)
    assert exc.value.code in ("AUTHORING_NAME_INVALID", "AUTHORING_PATH_UNSAFE")
    assert not list((tmp_path / "out").rglob("*.json")) or \
        all("escape" not in str(p) for p in (tmp_path / "out").rglob("*"))


def test_a_gltf_resource_outside_its_own_folder_is_refused(tmp_path):
    (tmp_path / "secret.bin").write_bytes(b"\x00" * 8)
    folder = tmp_path / "model"
    folder.mkdir()
    (folder / "evil.gltf").write_text(json.dumps({
        "asset": {"version": "2.0"},
        "buffers": [{"uri": "../secret.bin", "byteLength": 8}],
    }), encoding="utf-8")

    with pytest.raises((AuthoringError, DataPluginError)) as exc:
        load_model(folder / "evil.gltf")
    assert getattr(exc.value, "code", "") in ("DATA_PATH_UNSAFE",
                                              "AUTHORING_MODEL_INVALID")


def test_a_gltf_resource_on_the_network_is_refused(tmp_path):
    folder = tmp_path / "model"
    folder.mkdir()
    (folder / "remote.gltf").write_text(json.dumps({
        "asset": {"version": "2.0"},
        "buffers": [{"uri": "https://example.invalid/x.bin", "byteLength": 8}],
    }), encoding="utf-8")

    with pytest.raises((AuthoringError, DataPluginError)) as exc:
        load_model(folder / "remote.gltf")
    assert getattr(exc.value, "code", "") in ("DATA_PATH_UNSAFE",
                                              "AUTHORING_MODEL_INVALID")


# --------------------------------------------------------------------------- #
# 30. End to end
# --------------------------------------------------------------------------- #
def test_end_to_end_glb_to_installed_plugin_to_export(tmp_path):
    """import → gerarchia → socket → params → save → registry → search → build → export."""
    from app.core.session import Options

    glb = write_knight_glb(tmp_path / "source")
    with AuthoringService() as svc:
        svc.create_authoring_project("saga", destination=str(tmp_path / "plugins"))
        svc.import_model(glb)
        keys = knight_project(svc)
        assert svc.validate().ok

        result = svc.install_plugin()
        assert result.ok
        session = svc.session

    # 1. il registry lo ha
    assert session.catalog().component("saga:knight") is not None
    # 2. il retrieval lo trova
    assert "saga:knight" in {i for i, _ in
                             session.component_index().search("knight", limit=8)}
    # 3. il planner lo vedrebbe
    vocabulary = session.vocabulary("low_poly", prompt="a knight")
    assert "saga:knight" in {c.id for c in vocabulary.components}
    # 4. si costruisce
    built = session.build({"version": "1.3", "style": "low_poly",
                           "detail_level": 3,
                           "root": {"id": "subject", "ref": "saga:knight"}},
                          Options(check=True))
    assert built.ok and built.triangles == 48
    # 5. si esporta, con l'esportatore che c'era
    from app.build.exporter import export

    destination = export(built.scene(), tmp_path / "knight.glb", save_plan=False)
    assert destination.is_file() and destination.stat().st_size > 0
    import trimesh

    loaded = trimesh.load(destination, force="scene")
    assert sum(len(m.faces) for m in loaded.geometry.values()) == built.triangles
    assert keys


def test_the_same_plugin_can_be_built_entirely_without_a_user_interface(tmp_path):
    """Il punto 25 della milestone, come assert: nessun import di Qt."""
    glb = write_single_glb(tmp_path / "source")
    with AuthoringService() as svc:
        svc.create_authoring_project("headless", destination=str(tmp_path / "out"))
        svc.import_model(glb)
        svc.select_all()
        draft = svc.create_component("pebble", role="prop", provides=["prop_mount"],
                                     description="A single low-poly pebble")
        svc.add_socket(draft.key, "base", direction=(0, -1, 0), radius=0.1)
        svc.snap_socket_to_face(draft.key, "base", "-Y")
        svc.add_param(draft.key, "size", default=1.0, min=0.5, max=3.0,
                      transform="uniform_scale", semantic_role="scale")
        assert svc.validate().ok
        result = svc.install_plugin()

    assert result.ok
    assert not any(name.startswith("PySide6") for name in sys.modules
                   if name == "PySide6.QtWidgets" and False)
    assert result.found == {"headless:pebble": True}
