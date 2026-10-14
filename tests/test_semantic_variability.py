"""V5: un componente e' una famiglia di forme, non una forma.

Quattro cose, e la terza e' la piu' importante:

1. un parametro di un componente dati puo' dichiarare una **scala** oppure un
   **effetto installato**, e nient'altro;
2. un trait semantico raggiunge una mesh importata attraverso `semantic_role`,
   senza che nessuno sappia che quella geometria viene da un file;
3. lo **stesso** trait raggiunge un componente procedurale e un componente GLB
   quando entrambi dichiarano lo stesso ruolo semantico — e' la prova che il
   livello semantico e' indipendente dal backend geometrico;
4. le quattro deformazioni di forma che mancavano esistono, passano dalla
   `EffectPipeline` e muovono vertici e socket con la stessa mappa.
"""
from __future__ import annotations

import copy
from pathlib import Path

import numpy as np
import pytest

from app.ai.provider import OfflineProvider
from app.core.component import BuildContext, Component, Piece
from app.core.data_plugin import DataPluginError, load_component
from app.core.planner.planner import MockPlanner
from app.core.planner.vocabulary import build_vocabulary
from app.core.registry import PluginInfo, Registry, load
from app.core.session import Options, Session
from app.core.vocabulary import ParamEffect
from tests.data_plugin_fixtures import (box_along_x, box_mesh, socket_data,
                                        write_json, write_plugin,
                                        write_variable_plugin)

BUILTINS = Path(__file__).resolve().parents[1] / "app" / "plugins"
PROBE = Path(__file__).resolve().parent / "plugins" / "variabilita"
MISURE = ("length", "girth", "width", "height", "scale")


def session_for(registry):
    return Session(registry=registry, provider=OfflineProvider(),
                   planner=MockPlanner())


@pytest.fixture(scope="module")
def builtins():
    return load([BUILTINS]).freeze()


@pytest.fixture(scope="module")
def probes():
    """La libreria installata piu' il componente procedurale di prova."""
    registry = load([BUILTINS, PROBE]).freeze()
    assert registry.report.ok, registry.report.describe()
    return registry


@pytest.fixture
def variable(tmp_path):
    """La libreria installata piu' il plugin dati con i knob semantici."""
    folder = write_variable_plugin(tmp_path)
    registry = load([BUILTINS, folder]).freeze()
    assert registry.report.ok, registry.report.describe()
    return folder, registry


def plan_for(ref, *, params=None, traits=None, effects=None, detail=2,
             children=None):
    root = {"id": "subject", "ref": ref}
    if params is not None:
        root["params"] = params
    if effects is not None:
        root["effects"] = effects
    if children is not None:
        root["children"] = children
    return {"version": "1.3", "style": "low_poly", "detail_level": detail,
            "seed": 7, "traits": traits or [], "root": root}


def component_of(tmp_path, **overrides):
    """Un componente dati minimo, scritto su disco e caricato davvero."""
    definition = {"id": "unit:piece", "mesh": "../meshes/piece.glb",
                  "sockets": [socket_data("base", (0, 0, 0), (0, -1, 0))]}
    definition.update(overrides)
    folder = tmp_path / "unit"
    write_json(folder / "components/piece.json", definition)
    destination = folder / "meshes" / "piece.glb"
    destination.parent.mkdir(parents=True, exist_ok=True)
    box_mesh().export(str(destination), file_type="glb")
    return load_component(folder / "components/piece.json", folder)


def extents(result, node_id):
    return result.build.nodes[node_id].mesh.extents


# --------------------------------------------------------------------------- #
# 1. Il formato: una strategia per parametro, dichiarata
# --------------------------------------------------------------------------- #
def test_a_parameter_declares_a_transform_or_an_effect_but_not_both(tmp_path):
    scala = component_of(tmp_path, params={
        "width": {"default": 1.0, "min": 0.2, "max": 3.0, "transform": "scale_x"}})
    assert scala.param_effects == ()

    piegato = component_of(tmp_path, params={
        "curve": {"default": 0.0, "min": -1.0, "max": 1.0,
                  "effect": {"type": "fx:bend", "parameter": "amount"}}})
    assert len(piegato.param_effects) == 1
    binding = piegato.param_effects[0]
    assert (binding.param, binding.type, binding.parameter) == ("curve", "fx:bend",
                                                                 "amount")
    assert binding.scope == "part"

    with pytest.raises(DataPluginError) as entrambi:
        component_of(tmp_path, params={
            "x": {"default": 1.0, "transform": "scale_x",
                  "effect": {"type": "fx:bend"}}})
    assert entrambi.value.code == "DATA_PARAM_UNSUPPORTED"

    with pytest.raises(DataPluginError) as nessuno:
        component_of(tmp_path, params={"x": {"default": 1.0}})
    assert nessuno.value.code == "DATA_PARAM_UNSUPPORTED"


@pytest.mark.parametrize("effect, code", [
    ({"type": ""}, "DATA_SCHEMA_INVALID"),
    ({"type": 7}, "DATA_SCHEMA_INVALID"),
    ({}, "DATA_SCHEMA_INVALID"),
    ({"type": "fx:bend", "parameter": ""}, "DATA_SCHEMA_INVALID"),
    ({"type": "fx:bend", "scope": "ovunque"}, "DATA_PARAM_UNSUPPORTED"),
    ({"type": "fx:bend", "neutral": "zero"}, "DATA_SCHEMA_INVALID"),
    ({"type": "fx:bend", "callable": "mod:fn"}, "DATA_SCHEMA_INVALID"),
    ({"type": "fx:bend", "expression": "1+1"}, "DATA_SCHEMA_INVALID"),
    ({"type": "fx:bend", "module": "os"}, "DATA_SCHEMA_INVALID"),
    ({"type": "fx:bend", "matrix": [[1, 0, 0]]}, "DATA_SCHEMA_INVALID"),
])
def test_an_effect_binding_can_only_name_things(tmp_path, effect, code):
    """Niente codice, niente espressioni, niente matrici: solo nomi e numeri.

    Le ultime quattro righe sono il punto della sicurezza: un plugin dati non
    puo' nemmeno **nominare** un callable, un modulo o una trasformazione
    scriptabile, perche' una chiave non prevista viene rifiutata e non ignorata.
    """
    with pytest.raises(DataPluginError) as errore:
        component_of(tmp_path, params={
            "curve": {"default": 0.0, "min": -1.0, "max": 1.0, "effect": effect}})
    assert errore.value.code == code


def test_an_effect_backed_value_may_be_negative_while_a_scale_may_not(tmp_path):
    """Il verso di una piega e' un segno; un fattore di scala negativo specchia."""
    curvo = component_of(tmp_path, params={
        "curve": {"default": -0.5, "min": -1.0, "max": 1.0,
                  "effect": {"type": "fx:bend", "parameter": "amount"}}})
    assert curvo.params["curve"].default == -0.5
    assert curvo.params["curve"].min == -1.0

    with pytest.raises(DataPluginError):
        component_of(tmp_path, params={
            "width": {"default": -1.0, "transform": "scale_x"}})
    with pytest.raises(DataPluginError):
        component_of(tmp_path, params={
            "width": {"default": 1.0, "min": -2.0, "transform": "scale_x"}})


def test_a_semantic_role_is_declarable_on_both_strategies(tmp_path):
    component = component_of(tmp_path, params={
        "width": {"default": 1.0, "min": 0.2, "max": 3.0, "transform": "scale_x",
                  "semantic_role": "width"},
        "curve": {"default": 0.0, "min": -1.0, "max": 1.0,
                  "semantic_role": "curvature",
                  "effect": {"type": "fx:bend", "parameter": "amount"}}})
    assert component.params["width"].semantic_role == "width"
    assert component.params["curve"].semantic_role == "curvature"


# --------------------------------------------------------------------------- #
# 2. Il registry verifica che l'effetto nominato esista
# --------------------------------------------------------------------------- #
def _con_binding(**kwargs):
    registry = Registry()
    registry.register_plugin(PluginInfo(id="unit", version="1.0.0"))
    registry.register_component(Component(
        id="unit:piece", build=lambda v, c: Piece(),
        params={"curve": __import__("app.core.params", fromlist=["ParamSpec"])
                .ParamSpec(0.0)},
        param_effects=(ParamEffect(**kwargs),)), "unit")
    registry.verify()
    return registry


def test_a_binding_to_a_missing_effect_is_an_error_not_a_warning():
    registry = _con_binding(param="curve", type="fx:nonexistent")
    assert not registry.report.ok
    diagnosi = [d for d in registry.report.entries
                if d.code == "COMPONENT_EFFECT_NOT_FOUND"]
    assert len(diagnosi) == 1
    assert "fx:nonexistent" in diagnosi[0].message
    assert diagnosi[0].fatal


def test_a_binding_to_an_unknown_parameter_of_the_component_is_reported():
    registry = _con_binding(param="assente", type="fx:bend")
    assert "COMPONENT_EFFECT_PARAM_UNKNOWN" in [d.code for d in registry.report.entries]


def test_a_binding_to_an_unknown_knob_or_scope_of_the_effect_is_reported(tmp_path):
    folder = write_plugin(tmp_path, plugin_id="broken_knob", components=[{
        "id": "broken_knob:piece", "mesh": "../meshes/piece.glb",
        "sockets": [socket_data("base", (0, 0, 0), (0, -1, 0))],
        "params": {"curve": {"default": 0.0, "min": -1.0, "max": 1.0,
                             "effect": {"type": "fx:bend",
                                        "parameter": "inesistente"}}}}],
        meshes={"piece.glb": box_mesh()})
    registry = load([BUILTINS, folder])
    codici = [d.code for d in registry.report.entries]
    assert "COMPONENT_EFFECT_KNOB_UNKNOWN" in codici

    altro = write_plugin(tmp_path / "secondo", plugin_id="broken_scope", components=[{
        "id": "broken_scope:piece", "mesh": "../meshes/piece.glb",
        "sockets": [socket_data("base", (0, 0, 0), (0, -1, 0))],
        "params": {"deep": {"default": 0.0, "min": 0.0, "max": 1.0,
                            "effect": {"type": "fx:perspective_exaggeration",
                                       "scope": "part"}}}}],
        meshes={"piece.glb": box_mesh()})
    secondo = load([BUILTINS, altro / ".."])
    assert "COMPONENT_EFFECT_SCOPE_UNSUPPORTED" in [d.code
                                                     for d in secondo.report.entries]


# --------------------------------------------------------------------------- #
# 3. Un parametro mesh-backed pilota un effetto installato
# --------------------------------------------------------------------------- #
def test_an_effect_backed_parameter_deforms_mesh_and_sockets_by_the_same_map(variable):
    """Il test centrale del punto 7 della milestone.

    Il socket `tip` del fixture sta esattamente sulla punta della coda: se la
    geometria si piegasse e gli innesti restassero dov'erano, quel socket
    uscirebbe dalla mesh e un figlio si attaccherebbe nel vuoto.
    """
    _, registry = variable
    session = session_for(registry)
    dritta = session.build(plan_for("mesh_variable:tail", params={"curvature": 0.0}))
    curva = session.build(plan_for("mesh_variable:tail", params={"curvature": 0.9}))
    assert dritta.ok and curva.ok

    assert not np.allclose(dritta.build.nodes["subject"].mesh.vertices,
                           curva.build.nodes["subject"].mesh.vertices)
    assert dritta.triangles == curva.triangles          # una mappa, non una mesh nuova

    prima = dritta.build.nodes["subject"]
    dopo = curva.build.nodes["subject"]
    assert not np.allclose(prima.sockets["tip"].position,
                           dopo.sockets["tip"].position)
    # il socket `corner` del fixture sta **esattamente** su un vertice della
    # mesh importata: se la piega muovesse i vertici e non gli innesti, quel
    # vertice e quel socket si separerebbero, e un figlio si attaccherebbe
    # nel vuoto
    indice = np.flatnonzero(np.all(np.isclose(
        np.asarray(prima.mesh.vertices), prima.sockets["corner"].position), axis=1))
    assert len(indice) == 1
    assert np.allclose(np.asarray(dopo.mesh.vertices)[indice[0]],
                       dopo.sockets["corner"].position, atol=1e-9)
    assert np.all(np.isfinite(dopo.mesh.vertices))
    for nome, innesto in dopo.sockets.items():
        assert np.all(np.isfinite(innesto.position)), nome
        assert float(np.linalg.norm(innesto.direction)) > 1e-9, nome


def test_the_effect_backed_parameter_is_readable_in_the_diagnostics(variable):
    _, registry = variable
    session = session_for(registry)
    result = session.build(plan_for("mesh_variable:tail", params={"curvature": 0.9}))
    richieste = [d for d in result.diagnostics if d.code == "PARAM_EFFECT_REQUESTED"]
    assert len(richieste) == 1
    assert "curvature" in richieste[0].message and "fx:bend" in richieste[0].message
    assert "mesh_variable:tail" in richieste[0].why
    assert not richieste[0].fatal


def test_the_neutral_value_asks_for_nothing(variable):
    _, registry = variable
    session = session_for(registry)
    neutra = session.build(plan_for("mesh_variable:tail", params={"curvature": 0.0}))
    assert [d.code for d in neutra.diagnostics
            if d.code == "PARAM_EFFECT_REQUESTED"] == []
    assert neutra.effects.planned == []


def test_the_source_mesh_is_never_touched_and_the_result_is_deterministic(variable):
    _, registry = variable
    session = session_for(registry)
    primo = session.build(plan_for("mesh_variable:tail", params={"curvature": 0.8}))
    dritta = session.build(plan_for("mesh_variable:tail", params={"curvature": 0.0}))
    secondo = session.build(plan_for("mesh_variable:tail", params={"curvature": 0.8}))

    assert np.allclose(primo.build.nodes["subject"].mesh.vertices,
                       secondo.build.nodes["subject"].mesh.vertices)
    # la terza build con curvatura zero torna identica alla prima dritta: la
    # deformazione non si e' accumulata sulla mesh caricata una volta sola
    terza = session.build(plan_for("mesh_variable:tail", params={"curvature": 0.0}))
    assert np.allclose(dritta.build.nodes["subject"].mesh.vertices,
                       terza.build.nodes["subject"].mesh.vertices)


def test_the_plan_wins_over_the_declared_binding(variable):
    """Stessa regola dei parametri e dei figli: il piano non viene raddoppiato."""
    _, registry = variable
    session = session_for(registry)
    result = session.build(plan_for(
        "mesh_variable:tail", params={"curvature": 0.9},
        effects=[{"type": "fx:bend", "scope": "part:subject", "amount": -0.4}]))
    assert result.ok
    pieghe = [e for e in result.effects.planned if e.id == "fx:bend"]
    assert len(pieghe) == 1
    assert pieghe[0].amount == pytest.approx(-0.4)
    assert "PARAM_EFFECT_SUPERSEDED" in [d.code for d in result.diagnostics]


def test_a_procedural_component_may_drive_an_effect_too(probes):
    """`ParamEffect` non e' una cosa dei plugin dati: e' dei componenti."""
    component = probes.component("procedural_probe:head")
    assert component.param_effects[0].type == "fx:bend"
    session = session_for(probes)
    dritto = session.build(plan_for("procedural_probe:head", params={"curve": 0.0}))
    curvo = session.build(plan_for("procedural_probe:head", params={"curve": 0.9}))
    assert dritto.ok and curvo.ok
    assert not np.allclose(dritto.build.nodes["subject"].mesh.vertices,
                           curvo.build.nodes["subject"].mesh.vertices)
    assert dritto.triangles == curvo.triangles


# --------------------------------------------------------------------------- #
# 4. Lo stesso trait su procedurale e mesh-backed
# --------------------------------------------------------------------------- #
def test_a_semantic_trait_reaches_a_mesh_backed_component(variable):
    _, registry = variable
    session = session_for(registry)
    base = session.build(plan_for("mesh_variable:head"))
    larga = session.build(plan_for("mesh_variable:head",
                                   traits=[{"trait": "std:width", "value": 2.0}]))
    assert larga.ok
    assert [a["channel"] for a in larga.traits.applied] == ["subject.width"]
    assert extents(larga, "subject")[0] == pytest.approx(
        extents(base, "subject")[0] * 2.0)
    assert extents(larga, "subject")[1] == pytest.approx(extents(base, "subject")[1])


def test_the_trait_resolver_has_no_branch_for_mesh_backed_components():
    """La prova per grep: il livello semantico non sa cosa sia una mesh.

    Non e' un test di stile: se un `if mesh_backed` entrasse nel `TraitResolver`
    il punto 6 della milestone sarebbe fallito anche con i numeri giusti.
    """
    sorgente = (Path(__file__).resolve().parents[1] / "app" / "core"
                / "traits.py").read_text(encoding="utf-8")
    for parola in ("mesh_backed", "mesh", "glb", "gltf", "data_plugin"):
        assert parola not in sorgente.lower()


@pytest.mark.parametrize("trait, param, mesh_ref", [
    ("std:width", "width", "mesh_variable:head"),
    ("std:part_scale", "width", "mesh_variable:head"),
    ("std:length", "length", "mesh_variable:tail"),
    ("std:part_scale", "length", "mesh_variable:tail"),
])
def test_the_same_trait_hits_procedural_and_mesh_through_the_same_role(
        tmp_path, trait, param, mesh_ref):
    """Il test fondamentale del punto 8: una richiesta, due backend.

    `procedural_probe:head` costruisce con il kernel poligonale e
    `mesh_variable:head` carica un GLB. Entrambi dichiarano un parametro con
    `semantic_role` uguale, e lo stesso trait li cambia entrambi — nello stesso
    piano, con la stessa riga.
    """
    folder = write_variable_plugin(tmp_path)
    registry = load([BUILTINS, PROBE, folder]).freeze()
    assert registry.report.ok, registry.report.describe()
    procedurale = registry.component("procedural_probe:head")
    importato = registry.component(mesh_ref)
    # lo stesso ruolo semantico, dichiarato da un plugin di codice e da un
    # plugin di dati: e' l'unica cosa che i due hanno in comune
    ruolo = procedurale.params[param].semantic_role
    assert ruolo and importato.params[param].semantic_role == ruolo

    session = session_for(registry)
    for ref in ("procedural_probe:head", mesh_ref):
        base = session.build(plan_for(ref))
        cambiato = session.build(plan_for(ref, traits=[{"trait": trait,
                                                        "value": 2.0}]))
        assert cambiato.ok, [d.code for d in cambiato.diagnostics]
        canali = [a["channel"] for a in cambiato.traits.applied]
        assert "subject.%s" % param in canali, (ref, canali)
        assert not np.allclose(extents(base, "subject"),
                               extents(cambiato, "subject"))


def test_one_plan_changes_a_procedural_and_a_mesh_part_at_once(tmp_path):
    """La stessa riga di trait, su un albero misto, colpisce entrambi i rami."""
    folder = write_variable_plugin(tmp_path)
    registry = load([BUILTINS, PROBE, folder]).freeze()
    session = session_for(registry)
    piano = plan_for("mesh_variable:host", children=[
        {"id": "mesh_head", "ref": "mesh_variable:head",
         "at": {"capability": "head_mount"}, "insert": 0.0}])
    base = session.build(piano)
    assert base.ok, [d.code for d in base.diagnostics]
    largo = session.build(plan_for("mesh_variable:host", children=[
        {"id": "mesh_head", "ref": "mesh_variable:head",
         "at": {"capability": "head_mount"}, "insert": 0.0}],
        traits=[{"trait": "std:width", "value": 1.8, "scope": "subtree"}]))
    assert largo.ok
    assert extents(largo, "mesh_head")[0] > extents(base, "mesh_head")[0]


# --------------------------------------------------------------------------- #
# 5. Il vocabolario delle proporzioni sulla libreria installata
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("trait", ["std:part_scale", "std:width", "std:length",
                                   "std:head_scale", "std:hand_scale",
                                   "std:limb_length"])
def test_every_new_trait_is_installed_with_rules_and_a_purpose(builtins, trait):
    spec = builtins.trait(trait)
    assert spec is not None
    assert spec.purpose and spec.description
    assert spec.aliases
    assert spec.value.min is not None and spec.value.max is not None
    rules = builtins.trait_rules(trait)
    assert rules
    for rule in rules:
        assert rule.patches and all(p.semantic_role for p in rule.patches)
        assert not any(p.param for p in rule.patches)        # mai un nome


def test_no_alias_of_the_new_traits_is_ambiguous(builtins):
    for trait in ("std:part_scale", "std:width", "std:length", "std:head_scale",
                  "std:hand_scale", "std:limb_length"):
        for alias in builtins.trait(trait).aliases:
            assert not builtins.trait_ambiguous(alias), alias
            assert builtins.trait(alias) is builtins.trait(trait)


@pytest.mark.parametrize("trait, value, bigger", [
    ("std:part_scale", 1.6, True),
    ("std:width", 1.6, True),
    ("std:length", 1.4, True),
    ("std:head_scale", 2.4, True),
    ("std:hand_scale", 2.2, True),
    ("std:limb_length", 0.5, False),
])
def test_each_trait_changes_the_installed_humanoid_geometry(builtins, trait, value,
                                                             bigger):
    session = session_for(builtins)
    base = session.build(plan_for("humanoid_anatomical:body"))
    cambiato = session.build(plan_for("humanoid_anatomical:body",
                                      traits=[{"trait": trait, "value": value}]))
    assert base.ok and cambiato.ok
    assert cambiato.traits.applied, trait
    prima = base.scene().bounds()
    dopo = cambiato.scene().bounds()
    assert not np.allclose(prima, dopo), trait
    altezza_prima = float(prima[1][1] - prima[0][1])
    altezza_dopo = float(dopo[1][1] - dopo[0][1])
    if trait in ("std:part_scale", "std:length", "std:head_scale",
                 "std:limb_length"):
        assert (altezza_dopo > altezza_prima) is bigger, trait


def test_the_cartoon_benchmark_is_expressible_in_one_plan(builtins):
    """«Umanoide cartoon con testa enorme, gambe corte e mani grandi».

    Tre richieste semantiche, tre ruoli diversi, nessun percorso di nodo, e
    nessuna delle tre conosce l'id che il planner ha dato alla radice.
    """
    session = session_for(builtins)
    base = session.build(plan_for("humanoid_anatomical:body"))
    cartoon = session.build(plan_for("humanoid_anatomical:body", traits=[
        {"trait": "head_scale", "value": 2.4},
        {"trait": "limb_length", "value": 0.55},
        {"trait": "hand_scale", "value": 2.0}]))
    assert cartoon.ok
    assert cartoon.report.ok, [d.code for d in cartoon.diagnostics if d.fatal]

    traits_applicati = {a["trait"] for a in cartoon.traits.applied}
    assert traits_applicati == {"std:head_scale", "std:limb_length",
                                "std:hand_scale"}
    # i tre trait non si pestano i piedi: canali disgiunti, nessun conflitto
    assert cartoon.traits.conflicts == []

    def testa(result):
        nodo = [n for n in result.resolved.walk()
                if n.component.role == "head"][0]
        costruito = result.build.nodes[nodo.id]
        return float(np.max(costruito.mesh.extents))

    def somma(result, role):
        """La misura dei pezzi con quel ruolo che hanno davvero geometria.

        Un contenitore senza mesh - un'anca che esiste solo per portare la
        coscia - non ha un ingombro da sommare, e includerlo darebbe un numero
        che dipende da quanti contenitori ha quel plugin.
        """
        nodi = [n for n in result.resolved.walk() if n.component.role == role]
        costruiti = [result.build.nodes[n.id] for n in nodi
                     if result.build.nodes.get(n.id) is not None]
        return sum(float(np.max(c.mesh.extents)) for c in costruiti
                   if c.mesh is not None and len(c.mesh.vertices))

    def gambe(result):
        return somma(result, "leg")

    def mani(result):
        return somma(result, "hand")

    assert testa(cartoon) > testa(base) * 1.5
    assert gambe(cartoon) < gambe(base) * 0.8
    assert mani(cartoon) > mani(base) * 1.3
    assert np.all(np.isfinite(cartoon.scene().bounds()))


def test_a_role_selective_trait_is_invariant_to_the_root_node_id(builtins):
    """La lezione di V3 applicata ai trait semantici: selezionare, non indirizzare."""
    session = session_for(builtins)
    misure = set()
    for nome in ("subject", "pupazzo", "guy_01", "x"):
        piano = plan_for("humanoid_anatomical:body",
                         traits=[{"trait": "std:head_scale", "value": 2.0}])
        piano["root"]["id"] = nome
        result = session.build(piano)
        assert result.ok
        assert len(result.traits.applied) > 0
        misure.add(round(float(result.scene().bounds()[1][1]), 6))
    assert len(misure) == 1


def test_addressing_a_declared_child_by_name_still_fails_and_says_so(builtins):
    """Perche' i tre trait selettivi esistono, detto con una diagnostica.

    `on: "head"` e' quello che un autore scrive per primo, e non funziona: la
    testa e' un figlio dichiarato dal componente, quindi il suo id e' il
    percorso `subject/torso/neck/head`. Il trait selettivo evita la domanda.
    """
    session = session_for(builtins)
    result = session.build(plan_for("humanoid_anatomical:body", traits=[
        {"trait": "std:part_scale", "value": 2.0, "on": "head"}]))
    assert "TRAIT_TARGET_NOT_FOUND" in [d.code for d in result.diagnostics]

    buono = session.build(plan_for("humanoid_anatomical:body", traits=[
        {"trait": "std:part_scale", "value": 2.0,
         "on": "subject/torso/neck/head", "scope": "local"}]))
    assert buono.traits.applied


def test_detail_level_and_variability_stay_separate(builtins):
    """Un modello L1 gigante non diventa L3: punto 13 della milestone.

    `detail_level` decide **quali** componenti esistono, i trait decidono come
    sono fatti quelli che esistono. Sono due domande, e il sistema non le
    confonde: la scala cambia le misure e non il conteggio dei nodi.
    """
    session = session_for(builtins)
    for livello in (1, 2, 3):
        base = session.build(plan_for("humanoid_anatomical:body", detail=livello))
        gigante = session.build(plan_for("humanoid_anatomical:body", detail=livello,
                                         traits=[{"trait": "std:part_scale",
                                                  "value": 2.5}]))
        assert gigante.ok
        assert len(list(gigante.resolved.walk())) == len(list(base.resolved.walk()))
        assert gigante.triangles == base.triangles
        assert float(gigante.scene().bounds()[1][1]) > \
            float(base.scene().bounds()[1][1])
    uno = session.build(plan_for("humanoid_anatomical:body", detail=1,
                                 traits=[{"trait": "std:part_scale", "value": 2.5}]))
    tre = session.build(plan_for("humanoid_anatomical:body", detail=3))
    assert len(list(uno.resolved.walk())) < len(list(tre.resolved.walk()))


# --------------------------------------------------------------------------- #
# 6. Le quattro deformazioni di forma
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("effect", ["fx:squash", "fx:elongate", "fx:taper",
                                    "fx:twist"])
def test_the_new_effects_are_ordinary_installed_effects(builtins, effect):
    spec = builtins.effect(effect)
    assert spec is not None
    assert spec.plugin == "fx"
    assert spec.stage == "local"
    assert spec.scopes                                  # l'ambito e' dichiarato
    assert spec.description
    assert spec.amount.min is not None and spec.amount.max is not None
    assert spec.deform is not None and spec.apply is None
    assert spec.moves_points                            # socket con i vertici
    for name, param in spec.params.items():
        assert param.choices or (param.min is not None and param.max is not None)


def test_squash_and_elongate_declare_each_other_as_a_conflict(builtins):
    squash = builtins.effect("fx:squash")
    elongate = builtins.effect("fx:elongate")
    assert squash.conflicts_with(elongate)
    assert elongate.conflicts_with(squash)


@pytest.mark.parametrize("effect, axis, grows", [
    ("fx:squash", "Y", False),
    ("fx:elongate", "Y", True),
])
def test_squash_and_elongate_change_the_axis_they_name(probes, effect, axis, grows):
    session = session_for(probes)
    base = session.build(plan_for("procedural_probe:head"))
    deformato = session.build(plan_for(
        "procedural_probe:head",
        effects=[{"type": effect, "scope": "part:subject", "amount": 0.9,
                  "params": {"axis": axis}}]))
    assert deformato.ok, [d.code for d in deformato.diagnostics]
    prima, dopo = extents(base, "subject"), extents(deformato, "subject")
    assert bool(dopo[1] > prima[1]) is grows
    assert bool(dopo[0] > prima[0]) is (not grows)      # la sezione fa l'opposto
    assert deformato.triangles == base.triangles        # low poly: nessun vertice in piu'


def test_taper_narrows_one_end_and_leaves_the_other(probes):
    session = session_for(probes)
    result = session.build(plan_for(
        "procedural_probe:head",
        effects=[{"type": "fx:taper", "scope": "part:subject", "amount": 1.0,
                  "params": {"axis": "Y", "end": "tip"}}]))
    assert result.ok
    vertici = np.asarray(result.build.nodes["subject"].mesh.vertices)
    alto = vertici[vertici[:, 1] > vertici[:, 1].mean()]
    basso = vertici[vertici[:, 1] <= vertici[:, 1].mean()]
    larghezza_alto = alto[:, 0].max() - alto[:, 0].min()
    larghezza_basso = basso[:, 0].max() - basso[:, 0].min()
    assert larghezza_alto < larghezza_basso * 0.5

    base = session.build(plan_for(
        "procedural_probe:head",
        effects=[{"type": "fx:taper", "scope": "part:subject", "amount": 1.0,
                  "params": {"axis": "Y", "end": "base"}}]))
    v = np.asarray(base.build.nodes["subject"].mesh.vertices)
    su = v[v[:, 1] > v[:, 1].mean()]
    giu = v[v[:, 1] <= v[:, 1].mean()]
    assert (su[:, 0].max() - su[:, 0].min()) > (giu[:, 0].max() - giu[:, 0].min()) * 2


def test_twist_rotates_the_section_without_moving_the_base(probes):
    session = session_for(probes)
    base = session.build(plan_for("procedural_probe:head"))
    torto = session.build(plan_for(
        "procedural_probe:head",
        effects=[{"type": "fx:twist", "scope": "part:subject", "amount": 1.0,
                  "params": {"axis": "Y", "angle": 90.0}}]))
    assert torto.ok
    prima = np.asarray(base.build.nodes["subject"].mesh.vertices)
    dopo = np.asarray(torto.build.nodes["subject"].mesh.vertices)
    assert not np.allclose(prima, dopo)
    assert torto.triangles == base.triangles
    # la base resta dov'era: t = 0 significa angolo 0
    bassi = prima[:, 1] <= prima[:, 1].min() + 1e-9
    assert np.allclose(prima[bassi], dopo[bassi], atol=1e-9)
    assert np.all(np.isfinite(dopo))


@pytest.mark.parametrize("effect", ["fx:squash", "fx:elongate", "fx:taper",
                                    "fx:twist"])
def test_the_new_effects_move_sockets_with_the_vertices(probes, effect):
    """La stessa misura del `fx:bend` di V4, sui quattro effetti nuovi.

    Il socket `tip` del probe sta su un vertice della geometria: se la mappa
    dei punti non fosse la stessa per vertici e innesti, i due si separerebbero.
    """
    session = session_for(probes)
    base = session.build(plan_for("procedural_probe:head"))
    deformato = session.build(plan_for(
        "procedural_probe:head",
        effects=[{"type": effect, "scope": "part:subject", "amount": 0.9}]))
    assert deformato.ok
    prima = base.build.nodes["subject"]
    dopo = deformato.build.nodes["subject"]
    # il socket `corner` del probe sta **esattamente** su un vertice: se le due
    # mappe non fossero la stessa, quel vertice e quel socket si separerebbero
    indice = np.flatnonzero(np.all(np.isclose(
        np.asarray(prima.mesh.vertices), prima.sockets["corner"].position), axis=1))
    assert len(indice) == 1
    assert np.allclose(np.asarray(dopo.mesh.vertices)[indice[0]],
                       dopo.sockets["corner"].position, atol=1e-9)
    assert not np.allclose(prima.sockets["corner"].position,
                           dopo.sockets["corner"].position) or effect == "fx:twist"
    for nome in ("base", "tip", "corner"):
        assert np.all(np.isfinite(dopo.sockets[nome].position))
        assert np.all(np.isfinite(dopo.sockets[nome].direction))
        assert float(np.linalg.norm(dopo.sockets[nome].direction)) > 1e-9


def test_the_new_effects_keep_the_geometry_measurable(probes):
    """Punto 17: dopo le deformazioni la geometria resta valida e misurabile."""
    from app.build.validate import validate

    session = session_for(probes)
    for effect in ("fx:squash", "fx:elongate", "fx:taper", "fx:twist"):
        result = session.build(plan_for(
            "procedural_probe:head",
            effects=[{"type": effect, "scope": "part:subject", "amount": 1.0}]))
        mesh = result.build.nodes["subject"].mesh
        assert np.all(np.isfinite(mesh.vertices))
        assert mesh.faces.shape[1] == 3                 # topologia a triangoli
        assert len(mesh.faces) == len(result.build.nodes["subject"].designed.faces)
        assert float(mesh.area) > 0.0
        report = validate(result.build)
        assert not [d for d in report.entries if d.fatal], (effect, report.describe())


def test_the_new_effects_are_not_in_the_core(builtins):
    """Punto 5: gli effetti nuovi stanno in un plugin, non nel motore."""
    forma = BUILTINS / "effects" / "effects" / "forma.py"
    assert forma.is_file()
    for nome in ("squash", "elongate", "taper", "twist"):
        for modulo in ("effect.py", "vocabulary.py", "traits.py", "resolver.py"):
            sorgente = (Path(__file__).resolve().parents[1] / "app" / "core"
                        / modulo).read_text(encoding="utf-8")
            assert nome not in sorgente.lower(), (nome, modulo)


# --------------------------------------------------------------------------- #
# 7. Che cosa vede il planner
# --------------------------------------------------------------------------- #
def test_the_vocabulary_shows_semantic_roles_in_the_rendered_text(probes):
    """Regola 16: cio' che non e' nel testo reso non esiste per il modello."""
    vocabulary = build_vocabulary(probes, style="low_poly", detail_level=2)
    voce = [c for c in vocabulary.components
            if c.id == "procedural_probe:head"][0]
    testo = voce.to_text()
    assert "ruolo width" in testo
    assert "ruolo curvature" in testo
    param = {p.name: p for p in voce.params}
    assert param["width"].role == "width"
    assert param["width"].to_dict()["role"] == "width"


def test_the_vocabulary_names_the_effect_a_knob_drives_and_nothing_more(probes):
    vocabulary = build_vocabulary(probes, style="low_poly", detail_level=2)
    voce = [c for c in vocabulary.components
            if c.id == "procedural_probe:head"][0]
    curve = {p.name: p for p in voce.params}["curve"]
    assert curve.effect == "fx:bend"
    assert "-> fx:bend" in voce.to_text()
    assert curve.to_dict()["effect"] == "fx:bend"
    # l'implementazione dell'effetto non entra nella voce del componente:
    # niente stadio, niente parametri dell'effetto, niente politica dei socket
    reso = voce.to_text()
    for dettaglio in ("local", "preserve", "along", "deform", "socket_policy"):
        assert dettaglio not in reso


def test_the_new_traits_are_visible_to_the_planner_under_their_plan_key(builtins):
    vocabulary = build_vocabulary(builtins, style="low_poly", detail_level=2)
    per_id = {t.id: t for t in vocabulary.traits}
    for trait in ("std:part_scale", "std:width", "std:length", "std:head_scale",
                  "std:hand_scale", "std:limb_length"):
        assert trait in per_id, trait
        assert per_id[trait].plan_key == "traits"
        assert per_id[trait].purpose
    reso = vocabulary.to_text()
    assert "std:head_scale" in reso and "head_scale" in reso


def test_the_payload_does_not_explode_with_the_new_vocabulary(builtins):
    """Punto 14: il vocabolario cresce, il carico resta quello della rosa."""
    session = session_for(builtins)
    from app.core.planner.retrieval import estimate_tokens

    intero = build_vocabulary(builtins, style="low_poly", detail_level=2)
    rosa = session.vocabulary("low_poly", prompt="un umanoide con la testa enorme")
    assert estimate_tokens(rosa.to_text()) < estimate_tokens(intero.to_text())
    assert estimate_tokens(rosa.to_text()) < 4500
