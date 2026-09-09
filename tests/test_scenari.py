"""Gli scenari: una frase entra, un modello esce.

    prompt -> planner -> piano JSON -> registry -> resolver -> effetti -> mesh

Sono i test che valgono per tutti gli altri messi insieme, perche' l'unica cosa
che conta davvero e' se il giro completo produce geometria utile. Passano tutti
dalla stessa porta — `Session.generate` — e nessuno di loro chiede niente alla
rete: il planner finto e' deterministico, e dove serve un piano che una scelta
lessicale non indovinerebbe, il piano e' dichiarato come fixture.

Quello che i test **non** fanno e' giudicare la bellezza: la qualita' la misura
il validatore, con dei numeri sempre uguali. Nessun modello linguistico decide
se un modello e' venuto bene.
"""
from __future__ import annotations

import numpy as np
import pytest

from app.ai.provider import OfflineProvider
from app.core.planner.planner import MockPlanner
from app.core.session import Options, Session

# --------------------------------------------------------------------------- #
# I piani dichiarati
# --------------------------------------------------------------------------- #
# Due scenari nominano pezzi che nessuna corrispondenza lessicale potrebbe
# scegliere — «gambe di spada» vuol dire una sostituzione, non un componente. Il
# piano e' scritto qui, e ha la forma esatta che un modello linguistico produce:
# e' il suo posto in un test, non un ripiego nascosto.
PERSONA_RANA = {
    "style": "low_poly", "detail_level": 2,
    "root": {
        "id": "corpo", "ref": "humanoid:body", "params": {"height": 1.8},
        "effects": [{"type": "lanky", "scope": "model", "amount": 0.8}],
        "children": [{
            "id": "torso", "ref": "humanoid:torso",
            "at": {"capability": "core_mount"},
            "children": [
                {"id": "collo", "ref": "humanoid:neck",
                 "at": {"capability": "head_mount"}, "insert": 0.3,
                 "children": [{"id": "testa", "ref": "humanoid:head",
                               "swap": "creature:frog_head",
                               "at": {"capability": "head_mount"},
                               "insert": 0.25}]},
                {"id": "braccio_l", "ref": "humanoid:arm", "insert": 1.15,
                 "at": {"capability": "limb_mount", "side": "l"}},
                {"id": "braccio_r", "ref": "humanoid:arm", "insert": 1.15,
                 "at": {"capability": "limb_mount", "side": "r"}},
                {"id": "gamba_l", "ref": "humanoid:leg", "insert": 0.9,
                 "swap": "weapon:sword", "scale_mode": "fit_replaced",
                 "at": {"capability": "limb_mount", "side": "l"}},
                {"id": "gamba_r", "ref": "humanoid:leg", "insert": 0.9,
                 "swap": "weapon:sword", "scale_mode": "fit_replaced",
                 "at": {"capability": "limb_mount", "side": "r"}},
            ]}]}}

MOSTRO_COMPLETO = {
    "style": "low_poly", "detail_level": 2,
    "root": {
        "id": "corpo", "ref": "humanoid:body", "params": {"height": 1.8},
        "effects": [{"type": "lanky", "scope": "model", "amount": 0.8}],
        "children": [{
            "id": "torso", "ref": "humanoid:torso", "swap": "fish:fish_body",
            "at": {"capability": "core_mount"},
            "children": [
                {"id": "collo", "ref": "humanoid:neck", "insert": 0.3,
                 "at": {"capability": "head_mount"},
                 "children": [{"id": "testa", "ref": "humanoid:head",
                               "swap": "creature:frog_head", "insert": 0.25,
                               "at": {"capability": "head_mount"},
                               "children": [
                                   {"id": "capelli", "ref": "humanoid:hair",
                                    "at": {"capability": "hair_mount"},
                                    "optional": True, "scale_mode": "socket",
                                    "children": [{"id": "casco",
                                                  "ref": "accessories:helmet",
                                                  "at": {"capability": "gear_mount"},
                                                  "optional": True,
                                                  "scale_mode": "socket"}]}]}]},
                {"id": "braccio_l", "ref": "humanoid:arm", "insert": 1.15,
                 "at": {"capability": "limb_mount", "side": "l"}},
                {"id": "braccio_r", "ref": "humanoid:arm", "insert": 1.15,
                 "at": {"capability": "limb_mount", "side": "r"}},
                {"id": "gamba_l", "ref": "humanoid:leg", "insert": 0.9,
                 "swap": "weapon:sword", "scale_mode": "fit_replaced",
                 "at": {"capability": "limb_mount", "side": "l"}},
                {"id": "gamba_r", "ref": "humanoid:leg", "insert": 0.9,
                 "swap": "weapon:sword", "scale_mode": "fit_replaced",
                 "at": {"capability": "limb_mount", "side": "r"}},
            ]}],
    }}

ROBOT_MISTO = {
    "style": "low_poly", "detail_level": 2,
    "root": {
        "id": "telaio", "ref": "humanoid:body", "params": {"height": 2.2},
        "children": [{
            "id": "corpo", "ref": "humanoid:torso", "swap": "fish:fish_body",
            "at": {"capability": "core_mount"},
            "children": [
                {"id": "testa", "ref": "creature:dragon_head",
                 "at": {"capability": "head_mount"}, "scale_mode": "socket"},
                {"id": "ala_l", "ref": "fantasy:wing", "scale_mode": "socket",
                 "at": {"capability": "limb_mount", "side": "l"}},
                {"id": "ala_r", "ref": "fantasy:wing", "scale_mode": "socket",
                 "at": {"capability": "limb_mount", "side": "r"}},
                {"id": "cristallo_dorso", "ref": "fantasy:crystal",
                 "at": {"capability": "gear_mount"}, "optional": True,
                 "scale_mode": "socket"},
                {"id": "coda", "ref": "fish:tail",
                 "at": {"capability": "tail_mount"}},
            ]}]}}

# Lo stesso mostro, ma con la posa chiesta: e' il caso del §4 — «orienta le
# braccia verso il basso» senza toccare il plugin del pesce, che e' quello che
# mette le braccia di lato dichiarando le proprie pinne pettorali.
import copy as _copy

MOSTRO_IN_POSA = _copy.deepcopy(MOSTRO_COMPLETO)
MOSTRO_IN_POSA["root"]["effects"].append(
    {"type": "align", "scope": "role:arm", "direction": "down"})

COPIONI = {
    "una persona con la testa di rana e le gambe di spada, molto alta e magra":
        PERSONA_RANA,
    "persona con testa di rana, corpo di pesce, gambe di spada, capelli con "
    "casco, piercing al naso, molto alta e magra": MOSTRO_COMPLETO,
    "un robot con testa di drago, corpo di pesce, ali e cristalli luminosi":
        ROBOT_MISTO,
    "persona con testa di rana, corpo di pesce, gambe di spada, capelli con "
    "casco, piercing al naso, molto alta e magra, con le braccia lungo il corpo":
        MOSTRO_IN_POSA,
}


@pytest.fixture(scope="module")
def sessione() -> Session:
    """Una sessione senza rete: il planner finto, e i plugin veri."""
    return Session(provider=OfflineProvider(), planner=MockPlanner(scripts=COPIONI))


def gravi(risultato) -> list:
    return [d for d in risultato.diagnostics if d.fatal]


def riferimenti(risultato) -> set[str]:
    return {n.ref for n in risultato.resolved.walk()}


# --------------------------------------------------------------------------- #
# Scenario 1 — una persona con la testa di rana e le gambe di spada
# --------------------------------------------------------------------------- #
def test_scenario_a_person_with_a_frog_head_and_sword_legs(sessione):
    risultato = sessione.generate(
        "una persona con la testa di rana e le gambe di spada, molto alta e magra")

    assert risultato.ok, risultato.describe()
    assert not gravi(risultato), risultato.report.describe()
    assert {"humanoid:body", "creature:frog_head", "weapon:sword"} <= \
        riferimenti(risultato)
    assert "humanoid:head" not in riferimenti(risultato), "la testa e' stata sostituita"
    assert risultato.triangles > 200


def test_the_effect_of_the_first_scenario_is_visible(sessione):
    """«Molto alta e magra» deve **vedersi**, non solo comparire nel piano."""
    magra = sessione.generate(
        "una persona con la testa di rana e le gambe di spada, molto alta e magra")
    piano = dict(PERSONA_RANA)
    piano["root"] = {k: v for k, v in PERSONA_RANA["root"].items() if k != "effects"}
    normale = sessione.build(piano)

    assert magra.build.size[1] > normale.build.size[1] * 1.15
    assert magra.build.size[0] / magra.build.size[1] < \
        normale.build.size[0] / normale.build.size[1]


def test_the_swords_are_as_long_as_the_legs_they_replace(sessione):
    """`fit_replaced`: una spada al posto di una gamba resta lunga come la gamba."""
    risultato = sessione.generate(
        "una persona con la testa di rana e le gambe di spada, molto alta e magra")
    spada = risultato.build.node("gamba_l")
    braccio = risultato.build.node("braccio_l")
    lunghezza = float(spada.mesh.bounds[1][1] - spada.mesh.bounds[0][1])
    riferimento = float(braccio.mesh.bounds[1][1] - braccio.mesh.bounds[0][1])
    assert 0.4 < lunghezza / max(riferimento, 1e-6) < 3.0, lunghezza


# --------------------------------------------------------------------------- #
# Scenario 2 — una casa con un pianeta enorme sopra
# --------------------------------------------------------------------------- #
def test_scenario_a_house_with_a_huge_planet(sessione):
    """Nessun copione: la scelta e' del planner, sul vocabolario installato."""
    risultato = sessione.generate("una casa con un pianeta enorme sopra")

    assert risultato.ok, risultato.describe()
    assert not gravi(risultato), risultato.report.describe()
    assert {"architecture:house", "space:planet"} <= riferimenti(risultato)
    assert risultato.planner == "mock", "scelto per vocabolario, non per copione"


def test_the_house_and_the_planet_go_through_the_same_pipeline(sessione):
    """Due vocabolari senza niente in comune, e la stessa identica strada."""
    casa = sessione.generate("una casa con un pianeta enorme sopra")
    persona = sessione.generate(
        "una persona con la testa di rana e le gambe di spada, molto alta e magra")

    for risultato in (casa, persona):
        assert risultato.plan is not None
        assert risultato.resolved is not None
        assert risultato.effects is not None
        assert risultato.build is not None


def test_the_planet_is_enormous_and_the_house_is_still_a_house(sessione):
    risultato = sessione.generate("una casa con un pianeta enorme sopra")
    pianeta = risultato.build.node("planet")
    casa = risultato.build.node("house")
    assert float(pianeta.mesh.extents.max()) > float(casa.mesh.extents.max()) * 5


# --------------------------------------------------------------------------- #
# Scenario 3 — un albero con un nido e un uccello
# --------------------------------------------------------------------------- #
def test_scenario_a_tree_with_a_nest_and_a_bird(sessione):
    """Un vocabolario nuovo di zecca, scelto senza copione e senza toccare il core."""
    risultato = sessione.generate("un albero con un nido e un uccello sopra")

    assert risultato.ok, risultato.describe()
    assert not gravi(risultato), risultato.report.describe()
    assert {"nature:tree", "nature:nest", "nature:bird"} <= riferimenti(risultato)


def test_the_bird_sits_in_the_nest_and_the_nest_on_a_branch(sessione):
    """La catena si legge dagli innesti, non da una regola sul mondo."""
    risultato = sessione.generate("un albero con un nido e un uccello sopra")
    nido = risultato.resolved.node("nest")
    uccello = risultato.resolved.node("bird")

    assert nido.link.capability == "branch_mount"
    assert uccello.link.parent == "nest"
    assert uccello.link.capability == "perch_mount"

    alto = risultato.build.node("bird").mesh.bounds[0][1]
    tronco = risultato.build.node("tree").mesh
    assert alto > float(tronco.bounds[0][1] + tronco.extents[1] * 0.5), \
        "l'uccello sta in alto, dove sta il ramo"


def test_a_wing_from_another_plugin_fits_the_bird(sessione):
    """`limb_mount` non e' di nessuno: un'ala di fantasia su un uccello di natura."""
    piano = {"root": {"id": "uccello", "ref": "nature:bird",
                      "children": [{"id": "ala", "ref": "fantasy:wing",
                                    "scale_mode": "socket",
                                    "at": {"capability": "limb_mount", "side": "l"}}]}}
    risultato = sessione.build(piano)
    assert risultato.ok and not gravi(risultato), risultato.report.describe()
    assert risultato.resolved.node("ala").link.parent == "uccello"


# --------------------------------------------------------------------------- #
# Scenario 4 — mescolanza arbitraria
# --------------------------------------------------------------------------- #
def test_scenario_a_robot_with_a_dragon_head_a_fish_body_wings_and_crystals(sessione):
    """Cinque vocabolari in un modello, e il core non ne conosce nessuno."""
    risultato = sessione.generate(
        "un robot con testa di drago, corpo di pesce, ali e cristalli luminosi")

    assert risultato.ok, risultato.describe()
    assert not gravi(risultato), risultato.report.describe()
    usati = riferimenti(risultato)
    assert {"humanoid:body", "fish:fish_body", "creature:dragon_head",
            "fantasy:wing", "fantasy:crystal"} <= usati
    assert len({r.partition(":")[0] for r in usati}) >= 4


def test_the_robot_head_is_hidden_by_the_style_and_not_by_a_rule(sessione):
    """`robot:head` esiste, dichiara un altro stile, e il vocabolario non lo offre.

    E' il caso del §10 e del §45 visto da vicino: due implementazioni della
    stessa capability convivono, e a scegliere e' lo stile chiesto — non un
    elenco di eccezioni nel core.
    """
    basso = sessione.vocabulary("low_poly")
    assert basso.component("robot:head") is None
    assert "creature:dragon_head" in basso.ids()

    piano = {"root": {"id": "t", "ref": "robot:head"}}
    risultato = sessione.build(piano)
    assert "PLAN_STYLE_INCOMPATIBLE" in risultato.report.codes() \
        or "STYLE_INCOMPATIBLE" in risultato.report.codes()


def test_the_crystal_is_faceted_on_purpose_and_the_gate_knows(sessione):
    """Un cristallo ha una normale per faccia, e lo dichiara: niente diagnosi."""
    risultato = sessione.generate(
        "un robot con testa di drago, corpo di pesce, ali e cristalli luminosi")
    assert "STYLE_QUALITY" not in risultato.report.codes(), \
        risultato.report.describe()


# --------------------------------------------------------------------------- #
# Il traguardo (§46)
# --------------------------------------------------------------------------- #
def test_the_milestone_prompt_produces_a_real_mesh(sessione):
    """La frase del traguardo, per intero, dalla porta unica."""
    risultato = sessione.generate(
        "persona con testa di rana, corpo di pesce, gambe di spada, capelli con "
        "casco, piercing al naso, molto alta e magra")

    assert risultato.ok, risultato.describe()
    assert not gravi(risultato), risultato.report.describe()
    usati = riferimenti(risultato)
    assert {"creature:frog_head", "fish:fish_body", "weapon:sword",
            "humanoid:hair", "accessories:helmet"} <= usati
    assert risultato.triangles > 300
    assert risultato.mesh() is not None
    assert np.all(np.isfinite(risultato.build.bounds))


def test_the_milestone_goes_through_every_stage_without_shortcuts(sessione):
    """Nessun percorso alternativo: si passa da tutti e cinque i passi."""
    risultato = sessione.generate(
        "persona con testa di rana, corpo di pesce, gambe di spada, capelli con "
        "casco, piercing al naso, molto alta e magra")

    assert risultato.plan_json, "il planner ha prodotto un piano JSON"
    assert risultato.plan is not None, "il piano e' diventato un CompositionGraph"
    assert risultato.resolved.refs(), "il resolver ha scelto dei componenti"
    assert risultato.effects.applied or risultato.effects.planned, "gli effetti"
    assert risultato.build.meshes(), "il builder ha prodotto geometria"


def test_a_nose_ring_can_be_asked_for_without_redefining_the_nose(sessione):
    """`on: "testa/naso"` dentro un piano JSON: una sola nose, un solo piercing."""
    piano = {
        "detail_level": 1,
        "root": {"id": "corpo", "ref": "humanoid:body",
                 "children": [
                     {"id": "torso", "ref": "humanoid:torso", "level": 1,
                      "at": {"capability": "core_mount"},
                      "children": [{"id": "testa", "ref": "humanoid:head",
                                    "level": 1,
                                    "at": {"capability": "head_mount"}}]},
                     {"id": "anellino", "ref": "accessories:piercing",
                      "on": "testa/naso", "at": {"capability": "anchor"}}]}}

    risultato = sessione.build(piano)
    assert risultato.ok and not gravi(risultato), risultato.report.describe()
    usati = [n.ref for n in risultato.resolved.walk()]
    assert usati.count("humanoid:nose") == 1
    assert usati.count("accessories:piercing") == 1


# --------------------------------------------------------------------------- #
# Cosa la Session e' e cosa non e'
# --------------------------------------------------------------------------- #
def test_the_session_names_nothing_of_the_world():
    """Nessun `if humanoide` da nessuna parte, e il test lo legge davvero."""
    import inspect

    import app.core.session as modulo

    codice = inspect.getsource(modulo.Session)
    for parola in ("humanoid", "umanoid", "animal", "house", "casa", "fish",
                   "pesce", "creature", "dragon", "robot"):
        assert parola not in codice.lower(), parola


def test_the_session_is_the_only_door(sessione):
    """Piano e costruzione sono lo stesso giro, spezzato in due."""
    prompt = "una casa con un pianeta enorme sopra"
    solo_piano = sessione.plan(prompt)
    assert solo_piano.plan is not None
    assert solo_piano.build is None, "il piano non costruisce geometria"

    costruito = sessione.build(solo_piano.plan)
    intero = sessione.generate(prompt)
    assert costruito.triangles == intero.triangles


def test_the_result_says_what_was_chosen_and_why(sessione):
    risultato = sessione.generate("una casa con un pianeta enorme sopra")
    spiegazione = "\n".join(risultato.explain())
    assert "space:planet" in spiegazione
    assert "surface" in spiegazione
    assert risultato.to_dict()["plan"], "il piano resta leggibile"


def test_the_result_says_what_changed_and_what_was_skipped(sessione):
    risultato = sessione.generate(
        "una persona con la testa di rana e le gambe di spada, molto alta e magra")
    assert any("length" in riga or "girth" in riga for riga in risultato.changes())
    assert isinstance(risultato.skipped(), list)


def test_two_sessions_give_the_same_model(sessione):
    """Determinismo dalla frase alla mesh: due sessioni, due modelli identici."""
    prompt = "un albero con un nido e un uccello sopra"
    altra = Session(provider=OfflineProvider(), planner=MockPlanner(scripts=COPIONI))
    uno, due = sessione.generate(prompt), altra.generate(prompt)

    assert uno.plan_json == due.plan_json
    assert uno.triangles == due.triangles
    assert np.allclose(uno.build.bounds, due.build.bounds)


def test_the_quality_gate_is_deterministic_and_has_no_model_in_it(sessione):
    """Il giudizio di qualita' e' fatto di numeri, e sono sempre gli stessi."""
    prompt = "una casa con un pianeta enorme sopra"
    codici = [tuple(sorted(sessione.generate(prompt).report.codes()))
              for _ in range(3)]
    assert len(set(codici)) == 1


def test_generation_without_the_check_is_the_same_geometry(sessione):
    """Il controllo di qualita' guarda, non tocca."""
    prompt = "un albero con un nido e un uccello sopra"
    con = sessione.generate(prompt)
    senza = sessione.generate(prompt, Options(check=False))
    assert con.triangles == senza.triangles


# --------------------------------------------------------------------------- #
# Terze parti (§34) e sostituzione di un'implementazione (§10, §45)
# --------------------------------------------------------------------------- #
def test_an_external_plugin_reaches_the_planner_without_touching_the_core(tmp_path):
    """Un plugin esterno entra nel vocabolario e il planner lo usa. Zero modifiche."""
    cartella = tmp_path / "strano"
    (cartella / "components").mkdir(parents=True)
    (cartella / "plugin.json").write_text(
        '{"id": "strano", "version": "0.1.0", "name": "Strano",'
        ' "description": "un plugin di prova", "components": ["components/c.py"],'
        ' "capabilities": [{"name": "stranezza"}]}', encoding="utf-8")
    (cartella / "components" / "c.py").write_text(
        "from app.core.capability import Capability, mount\n"
        "from app.core.component import Component, Piece\n"
        "from app.core.authoring import base_socket\n"
        "from app.core.params import DISTANCE, ParamSpec\n"
        "from app.geometry.kernel import block\n"
        "\n"
        "def _c(v, ctx):\n"
        "    m = block((v['size'], v['size'], v['size']), sides=4, axis=1)\n"
        "    m.apply_translation([0, v['size'] * 0.5, 0])\n"
        "    return Piece(mesh=m, material='metal', tags=('strano',),\n"
        "                 sockets={'base': base_socket(v['size'] * 0.5, axis='+Y')})\n"
        "\n"
        "STRANO = Component(id='strange_component', build=_c,\n"
        "    description='un componente strano che non assomiglia a niente',\n"
        "    params={'size': ParamSpec(0.3, DISTANCE, min=0.01, max=3.0,\n"
        "                              semantic_role='girth')},\n"
        "    provides=(Capability('head_mount'), Capability('anchor')),\n"
        "    mounts=(mount('anchor', socket_id='base'),),\n"
        "    tags=frozenset({'strano', 'cosa'}))\n", encoding="utf-8")

    from pathlib import Path

    plugin = Path(__file__).resolve().parent.parent / "app" / "plugins"
    sessione = Session(provider=OfflineProvider(), planner=MockPlanner(),
                       plugin_paths=(str(tmp_path), str(plugin)))

    vocabolario = sessione.vocabulary()
    assert vocabolario.component("strano:strange_component") is not None

    risultato = sessione.generate("una cosa strana")
    assert "strano:strange_component" in riferimenti(risultato)
    assert risultato.ok, risultato.describe()


def test_a_completely_different_implementation_can_fill_a_known_capability():
    """Il plugin realistico del §45, in miniatura: stessa capability, altro mondo.

    Non e' il plugin realistico — quello non va scritto adesso. E' la prova che
    il core lo reggerebbe: un componente con parametri propri, figli propri,
    vincoli propri e geometria propria che fornisce `head_mount`, e si attacca a
    un collo umanoide senza che nessuno cambi una riga.
    """
    from app.core.authoring import base_socket
    from app.core.capability import Capability, Requirement, mount
    from app.core.component import Attachment, Component, Piece
    from app.core.constraints import CLAMP, Constraint
    from app.core.graph import CompositionGraph
    from app.core.params import DISTANCE, RATIO, ParamSpec
    from app.core.registry import Registry, load
    from app.core.socket import socket
    from app.geometry.kernel import grow

    def _cranio(v, ctx):
        mesh = grow([(0.0, v["width"] * 0.4), (0.35, v["width"] * 0.5),
                     (0.8, v["width"] * 0.46), (1.0, v["width"] * 0.24)],
                    sides=8, length=v["height"], axis=1, flat=v["squash"])
        return Piece(mesh=mesh, material="skin", tags=("skull",), sockets={
            "base": base_socket(v["width"] * 0.4, axis="+Y"),
            "mascella": socket("mascella", (0, v["height"] * 0.2, v["width"] * 0.4),
                               (0, -0.3, 1), up=(0, 1, 0),
                               radius=v["width"] * 0.2, provides="face_mount")})

    def _mandibola(v, ctx):
        mesh = grow([(0.0, v["width"] * 0.3), (1.0, v["width"] * 0.2)],
                    sides=6, length=v["width"] * 0.5, axis=2)
        return Piece(mesh=mesh, material="skin", tags=("jaw",),
                     sockets={"base": base_socket(v["width"] * 0.3, axis="+Z")})

    testa = Component(
        id="head", build=_cranio,
        description="una testa costruita in un altro modo, con le sue regole",
        params={"width": ParamSpec(0.16, DISTANCE, min=0.02, max=1.0,
                                   semantic_role="girth"),
                "height": ParamSpec(0.26, DISTANCE, min=0.03, max=1.5,
                                    semantic_role="length"),
                "squash": ParamSpec(0.86, RATIO, min=0.4, max=1.2)},
        constraints=(Constraint("height >= width", target="height", to="width",
                                severity=CLAMP,
                                message="una testa non e' piu' larga che alta"),),
        children=lambda v, ctx: [Attachment(
            id="mascella", component="jaw", level=2, insert=0.3,
            requirement=Requirement(capability="face_mount"),
            params={"width": v["width"]})],
        provides=(Capability("head_mount"),),
        mounts=(mount("face_mount", socket_id="mascella"),),
        role="head", material="skin", tags=frozenset({"realistico", "testa"}))
    mandibola = Component(
        id="jaw", build=_mandibola, description="una mandibola",
        params={"width": ParamSpec(0.16, DISTANCE, min=0.02, max=1.0,
                                   semantic_role="girth")},
        provides=(Capability("face_mount"),),
        role="head", material="skin", tags=frozenset({"realistico"}))

    registro = Registry()
    for componente in load(["app/plugins"]).components():
        registro.register_component(componente)
    registro.register_component(testa, plugin_id="realistic_humanoid")
    registro.register_component(mandibola, plugin_id="realistic_humanoid")
    registro.freeze()

    grafo = CompositionGraph()
    grafo.set_root("corpo", "humanoid:body", height=1.8)
    grafo.add_child("torso", "humanoid:torso", "corpo",
                    requirement=Requirement(capability="core_mount"))
    grafo.add_child("testa", "realistic_humanoid:head", "torso",
                    requirement=Requirement(capability="head_mount"))

    sessione = Session(provider=OfflineProvider(), planner=MockPlanner(),
                       registry=registro)
    risultato = sessione.build(grafo)

    assert risultato.ok and not gravi(risultato), risultato.report.describe()
    assert "realistic_humanoid:head" in riferimenti(risultato)
    assert "realistic_humanoid:jaw" in riferimenti(risultato), "i suoi figli"
    assert risultato.build.node("testa").triangles > 0


# --------------------------------------------------------------------------- #
# Stili: la struttura registrabile (§8)
# --------------------------------------------------------------------------- #
def _con_stile_di_terze_parti(**params):
    """Una sessione in cui un plugin di terze parti ha portato il suo stile."""
    from app.core.registry import load
    from app.core.vocabulary import StyleProfile

    registro = load(["app/plugins"])
    registro.register_style(
        StyleProfile(id="cartoon", name="Cartoon", extends="low_poly",
                     description="come il low poly, ma piu' permissivo",
                     params=params or {"faces_per_normal_min": 1.2}),
        plugin_id="terzi")
    registro.freeze()
    return Session(provider=OfflineProvider(), planner=MockPlanner(),
                   registry=registro)


def test_a_third_party_style_is_installed_without_touching_the_core():
    sessione = _con_stile_di_terze_parti()
    identita = {s.id for s in sessione.vocabulary().styles}
    assert {"primitives:low_poly", "terzi:cartoon"} <= identita


def test_a_style_inherits_the_numbers_of_the_one_it_extends():
    """`cartoon` cambia una soglia e tiene tutto il resto. Tre righe di plugin."""
    sessione = _con_stile_di_terze_parti()
    cartoon = sessione.catalog().style("terzi:cartoon")

    assert cartoon.get("faces_per_normal_min") == 1.2, "il proprio vince"
    assert cartoon.get("triangle_budget") == 3200, "il resto si eredita"
    assert "primitives:low_poly" in cartoon.describe()


def test_a_style_that_extends_nothing_still_works():
    from app.core.registry import Registry
    from app.core.vocabulary import StyleProfile

    registro = Registry()
    registro.register_style(StyleProfile(id="orfano", extends="mai_esistito",
                                         params={"triangle_budget": 100}),
                            plugin_id="terzi")
    registro.freeze()
    assert "STYLE_BASE_MISSING" in registro.report.codes()
    assert registro.style("terzi:orfano").get("triangle_budget") == 100


def test_the_quality_gate_reads_the_style_it_was_given():
    """Il giudizio non e' cablato: sono i numeri dello stile chiesto.

    Con una soglia impossibile lo stesso identico modello viene segnalato — la
    prova che il gate legge il profilo e non una costante nascosta nel core.
    """
    piano = {"root": {"id": "casa", "ref": "architecture:house"}}
    permissivo = _con_stile_di_terze_parti(faces_per_normal_min=1.2)
    severo = _con_stile_di_terze_parti(faces_per_normal_min=9.9)

    buono = permissivo.build(piano, Options(style="terzi:cartoon"))
    cattivo = severo.build(piano, Options(style="terzi:cartoon"))

    assert "STYLE_QUALITY" not in buono.report.codes(), buono.report.describe()
    assert "STYLE_QUALITY" in cattivo.report.codes()


def test_a_pose_can_be_asked_for_in_the_plan(sessione):
    """«Con le braccia lungo il corpo»: un effetto `final` dentro il piano JSON.

    Il corpo di pesce mette le braccia di lato perche' le sue pinne pettorali
    puntano di lato, ed e' giusto cosi'. La posa la dice il piano, e nessun
    plugin cambia di una riga.
    """
    diritto = sessione.generate(
        "persona con testa di rana, corpo di pesce, gambe di spada, capelli con "
        "casco, piercing al naso, molto alta e magra")
    in_posa = sessione.generate(
        "persona con testa di rana, corpo di pesce, gambe di spada, capelli con "
        "casco, piercing al naso, molto alta e magra, con le braccia lungo il corpo")

    assert in_posa.ok and not gravi(in_posa), in_posa.report.describe()
    assert in_posa.triangles == diritto.triangles, "una posa non aggiunge geometria"
    assert in_posa.build.size[0] < diritto.build.size[0] * 0.75


def test_an_effect_parameter_travels_through_the_plan(sessione):
    """I parametri di un effetto sono parte del piano, non rumore da scartare."""
    piano = {"root": {"id": "corpo", "ref": "fish:fish_body",
                      "effects": [{"type": "rotate", "scope": "model",
                                   "axis": "X", "angle": 30.0}]}}
    fermo = sessione.build({"root": {"id": "corpo", "ref": "fish:fish_body"}})
    girato = sessione.build(piano)

    assert girato.ok and not gravi(girato), girato.report.describe()
    assert not np.allclose(girato.build.bounds, fermo.build.bounds)


def test_an_invented_effect_parameter_is_refused(sessione):
    piano = {"root": {"id": "corpo", "ref": "fish:fish_body",
                      "effects": [{"type": "rotate", "scope": "model",
                                   "inclinazione": 30.0}]}}
    risultato = sessione.build(piano)
    assert "EFFECT_PARAM_NOT_FOUND" in risultato.report.codes()
