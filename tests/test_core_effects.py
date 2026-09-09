"""Gli effetti: cosa cambia rispetto a quello che i componenti direbbero da soli.

Come per il resolver, due famiglie. I test **del core** costruiscono effetti e
componenti senza significato e verificano il meccanismo — stadi, ambiti,
conflitti, provenienza. I test **incrociati** prendono i tre effetti veri
(`lanky`, `bend`, `perspective_exaggeration`) e li applicano a un umanoide con
la testa di rana e a una casa su un pianeta, con la stessa pipeline.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from app.core.capability import Capability, Requirement, mount
from app.core.component import Component, Piece
from app.core.effect import (EffectContext, EffectedComposition,
                             EffectPipeline, PlannedEffect, Scope,
                             apply_effects)
from app.core.graph import FROM_EFFECT, CompositionGraph
from app.core.params import DISTANCE, RATIO, ParamSpec
from app.core.registry import Registry, load
from app.core.resolver import resolve
from app.core.vocabulary import (RECOVERABLE, SCOPE_GROUP, SCOPE_MODEL,
                                 SCOPE_PART, SCOPE_ROLE, SCOPE_SUBTREE,
                                 STAGE_FINAL, STAGE_GLOBAL, STAGE_LOCAL,
                                 STAGE_PROPORTION, STAGE_STRUCTURAL,
                                 STAGE_STYLE, STAGES, EffectSpec, ParamRule)

QUI = Path(__file__).resolve().parent
INTERNI = QUI.parent / "app" / "plugins"


def _pezzo(v, ctx):
    return Piece(mesh=None)


def componente(id: str, **kwargs) -> Component:
    return Component(id=id, build=_pezzo, **kwargs)


PEZZO = dict(params={"length": ParamSpec(1.0, DISTANCE, min=0.01, max=10.0,
                                         semantic_role="length"),
                     "girth": ParamSpec(0.2, DISTANCE, min=0.01, max=10.0,
                                        semantic_role="girth")})


def allunga(id: str = "prova:allunga", **kwargs) -> EffectSpec:
    """Un effetto di proporzione qualunque: piu' lungo."""
    base = dict(
        stage=STAGE_PROPORTION,
        scopes=(SCOPE_MODEL, SCOPE_PART, SCOPE_SUBTREE, SCOPE_GROUP, SCOPE_ROLE),
        amount=ParamSpec(1.0, RATIO, min=0.0, max=1.0),
        changes=(ParamRule(semantic_role="length", expression="value * (1 + amount)"),))
    base.update(kwargs)
    return EffectSpec(id=id, **base)


def registro(*cose) -> Registry:
    r = Registry()
    for cosa in cose:
        if isinstance(cosa, Component):
            r.register_component(cosa)
        else:
            r.register_effect(cosa)
    return r


def catena(reg: Registry, *effetti, detail_level: int = 2) -> EffectedComposition:
    """Radice + due figli, piu' gli effetti chiesti."""
    g = CompositionGraph(detail_level=detail_level)
    g.set_root("r", "prova:radice")
    g.add_child("a", "prova:pezzo", "r", requirement=Requirement(capability="attacco"))
    g.add_child("b", "prova:pezzo", "a", requirement=Requirement(capability="attacco"))
    for tipo, scope, quanto in effetti:
        g.effect(tipo, scope=scope, amount=quanto)
    return apply_effects(resolve(g, reg), reg)


def mondo_base() -> Registry:
    r = Registry()
    r.load_directory(INTERNI)
    return r


@pytest.fixture(scope="module")
def mondo() -> Registry:
    """Vocabolario del mondo piu' gli effetti veri."""
    r = load([INTERNI])
    assert not r.report.errors(), r.report.describe()
    return r.freeze()


@pytest.fixture
def semplice() -> Registry:
    """Radice con due innesti, e un pezzo con lunghezza e spessore."""
    return registro(
        componente("prova:radice", mounts=(mount("attacco", socket_id="posto",
                                                 capacity=0),),
                   role="tronco", tags=frozenset({"legno"}), **PEZZO),
        componente("prova:pezzo", provides=(Capability("attacco"),),
                   mounts=(mount("attacco", socket_id="posto", capacity=0),),
                   role="ramo", tags=frozenset({"legno"}), **PEZZO),
        allunga())


# --------------------------------------------------------------------------- #
# Ricerca e dichiarazione
# --------------------------------------------------------------------------- #
def test_an_effect_is_found_through_the_registry(semplice):
    assert semplice.effect("prova:allunga") is not None
    assert semplice.effect("allunga") is not None, "nome nudo, non ambiguo"


def test_an_unknown_effect_is_reported_with_alternatives(semplice):
    fatto = catena(semplice, ("mai_sentito", SCOPE_MODEL, 1.0))
    assert "EFFECT_NOT_FOUND" in fatto.report.codes()
    voce = [d for d in fatto.report if d.code == "EFFECT_NOT_FOUND"][0]
    assert "prova:allunga" in voce.alternatives


def test_an_effect_without_a_valid_stage_is_refused():
    reg = registro(componente("prova:radice", **PEZZO),
                   allunga(stage="quando_capita"))
    g = CompositionGraph()
    g.set_root("r", "prova:radice")
    g.effect("allunga", scope=SCOPE_MODEL, amount=1.0)

    fatto = apply_effects(resolve(g, reg), reg)
    assert "EFFECT_INCOMPATIBLE" in fatto.report.codes()
    voce = [d for d in fatto.report if d.code == "EFFECT_INCOMPATIBLE"][0]
    assert set(voce.alternatives) == set(STAGES)


def test_an_effect_declares_which_scopes_it_understands(semplice):
    stretto = allunga(id="prova:stretto", scopes=(SCOPE_PART,))
    semplice.register_effect(stretto)
    fatto = catena(semplice, ("stretto", SCOPE_MODEL, 1.0))
    assert "EFFECT_INCOMPATIBLE" in fatto.report.codes()


# --------------------------------------------------------------------------- #
# Ambiti
# --------------------------------------------------------------------------- #
def test_the_model_scope_reaches_everything(semplice):
    fatto = catena(semplice, ("allunga", SCOPE_MODEL, 1.0))
    assert fatto.applied[0].targets == ("r", "a", "b")


def test_a_part_scope_reaches_one_node(semplice):
    fatto = catena(semplice, ("allunga", "part:a", 1.0))
    assert fatto.applied[0].targets == ("a",)
    assert fatto.node("b").values["length"] == 1.0, "il figlio non e' toccato"


def test_a_subtree_scope_reaches_the_node_and_its_descendants(semplice):
    fatto = catena(semplice, ("allunga", "subtree:a", 1.0))
    assert fatto.applied[0].targets == ("a", "b")
    assert fatto.node("r").values["length"] == 1.0


def test_a_group_scope_reaches_a_tag(semplice):
    fatto = catena(semplice, ("allunga", "group:legno", 1.0))
    assert set(fatto.applied[0].targets) == {"r", "a", "b"}


def test_a_role_scope_reaches_a_role(semplice):
    fatto = catena(semplice, ("allunga", "role:ramo", 1.0))
    assert set(fatto.applied[0].targets) == {"a", "b"}


def test_a_scope_that_names_nothing_uses_the_node_it_was_asked_on(semplice):
    """`part:` da solo vuol dire «questo»."""
    g = CompositionGraph()
    g.set_root("r", "prova:radice")
    g.add_child("a", "prova:pezzo", "r", requirement=Requirement(capability="attacco"))
    g.effect("allunga", scope="part", target="a", amount=1.0)

    fatto = apply_effects(resolve(g, semplice), semplice)
    assert fatto.applied[0].targets == ("a",)


def test_a_scope_pointing_at_a_missing_node_is_diagnosed(semplice):
    fatto = catena(semplice, ("allunga", "part:fantasma", 1.0))
    assert "EFFECT_TARGET_NOT_FOUND" in fatto.report.codes()
    assert not fatto.applied


def test_a_scope_that_finds_nothing_is_a_warning(semplice):
    fatto = catena(semplice, ("allunga", "role:mai_visto", 1.0))
    assert "EFFECT_SCOPE_EMPTY" in fatto.report.codes()
    assert fatto.ok, "il modello resta costruibile"


def test_scopes_know_nothing_about_categories():
    """`role:qualunque_cosa` funziona se qualcuno dichiara quel ruolo, e basta."""
    assert Scope.parse("role:una_parola_inventata").kind == SCOPE_ROLE
    assert Scope.parse("group:un_tag_qualsiasi").value == "un_tag_qualsiasi"
    assert Scope.parse("").kind == SCOPE_MODEL


# --------------------------------------------------------------------------- #
# Ordine
# --------------------------------------------------------------------------- #
def _tracciante(id: str, stage: str, priority: int = 0) -> EffectSpec:
    return EffectSpec(id=id, stage=stage, priority=priority,
                      scopes=(SCOPE_MODEL,),
                      changes=(ParamRule(semantic_role="length",
                                         expression="value + 1"),))


def test_the_stages_run_in_the_declared_order(semplice):
    for stadio in (STAGE_FINAL, STAGE_STYLE, STAGE_GLOBAL, STAGE_LOCAL):
        semplice.register_effect(EffectSpec(id="prova:%s" % stadio, stage=stadio,
                                            scopes=(SCOPE_MODEL,), apply=lambda m, c: m))
    fatto = catena(semplice,
                   ("prova:final", SCOPE_MODEL, 1.0),
                   ("prova:local", SCOPE_MODEL, 1.0),
                   ("prova:style", SCOPE_MODEL, 1.0),
                   ("prova:global", SCOPE_MODEL, 1.0))
    assert [e.stage for e in fatto.planned] == [STAGE_LOCAL, STAGE_GLOBAL,
                                                STAGE_STYLE, STAGE_FINAL]


def test_priority_decides_inside_a_stage(semplice):
    semplice.register_effect(_tracciante("prova:tardi", STAGE_PROPORTION, priority=1))
    semplice.register_effect(_tracciante("prova:presto", STAGE_PROPORTION, priority=9))
    fatto = catena(semplice, ("tardi", SCOPE_MODEL, 1.0), ("presto", SCOPE_MODEL, 1.0))
    assert [e.id for e in fatto.applied] == ["prova:presto", "prova:tardi"]


def test_the_id_breaks_a_tie_so_nothing_depends_on_the_json(semplice):
    semplice.register_effect(_tracciante("prova:zulu", STAGE_PROPORTION))
    semplice.register_effect(_tracciante("prova:alfa", STAGE_PROPORTION))
    fatto = catena(semplice, ("zulu", SCOPE_MODEL, 1.0), ("alfa", SCOPE_MODEL, 1.0))
    assert [e.id for e in fatto.applied] == ["prova:alfa", "prova:zulu"]

    altro = catena(semplice, ("alfa", SCOPE_MODEL, 1.0), ("zulu", SCOPE_MODEL, 1.0))
    assert [e.id for e in altro.applied] == ["prova:alfa", "prova:zulu"], \
        "l'ordine in cui sono stati chiesti non conta"


# --------------------------------------------------------------------------- #
# Intensita' e parametri
# --------------------------------------------------------------------------- #
def test_the_amount_is_clamped_to_the_declared_range(semplice):
    fatto = catena(semplice, ("allunga", SCOPE_MODEL, 4.0))
    assert fatto.applied[0].amount == 1.0
    assert "EFFECT_OUT_OF_RANGE" in fatto.report.codes()


def test_a_negative_amount_can_be_legitimate():
    reg = registro(componente("prova:radice", **PEZZO),
                   allunga(amount=ParamSpec(0.0, RATIO, min=-1.0, max=1.0)))
    g = CompositionGraph()
    g.set_root("r", "prova:radice")
    g.effect("allunga", scope=SCOPE_MODEL, amount=-0.5)

    fatto = apply_effects(resolve(g, reg), reg)
    assert fatto.node("r").values["length"] == pytest.approx(0.5)
    assert "EFFECT_OUT_OF_RANGE" not in fatto.report.codes()


def test_an_effect_has_its_own_parameters(semplice):
    con_parametri = EffectSpec(
        id="prova:con_parametri", stage=STAGE_LOCAL, scopes=(SCOPE_MODEL,),
        params={"axis": ParamSpec("Z", "enum", choices=("X", "Y", "Z"))},
        apply=lambda m, c: m)
    semplice.register_effect(con_parametri)
    g = CompositionGraph()
    g.set_root("r", "prova:radice")
    g.effect("con_parametri", scope=SCOPE_MODEL, amount=1.0, axis="Y")

    fatto = apply_effects(resolve(g, semplice), semplice)
    assert fatto.planned[0].params["axis"] == "Y"


def test_an_effect_cannot_push_a_parameter_out_of_its_range():
    """Un effetto puo' spingere, non sfondare."""
    reg = registro(
        componente("prova:radice",
                   params={"length": ParamSpec(1.0, DISTANCE, min=0.1, max=1.2,
                                               semantic_role="length")}),
        allunga())
    g = CompositionGraph()
    g.set_root("r", "prova:radice")
    g.effect("allunga", scope=SCOPE_MODEL, amount=1.0)

    fatto = apply_effects(resolve(g, reg), reg)
    assert fatto.node("r").values["length"] == 1.2
    assert "EFFECT_OUT_OF_RANGE" in fatto.report.codes()


# --------------------------------------------------------------------------- #
# Conflitti
# --------------------------------------------------------------------------- #
def test_two_effects_in_conflict_are_both_refused(semplice):
    """Tenerne uno vorrebbe dire scegliere al posto di chi ha scritto il piano."""
    semplice.register_effect(allunga(id="prova:accorcia",
                                     conflicts=frozenset({"allunga"}),
                                     changes=(ParamRule(semantic_role="length",
                                                        expression="value * 0.5"),)))
    fatto = catena(semplice, ("allunga", SCOPE_MODEL, 1.0),
                   ("accorcia", SCOPE_MODEL, 1.0))
    assert "EFFECT_CONFLICT" in fatto.report.codes()
    assert not fatto.applied
    assert fatto.node("r").values["length"] == 1.0, "niente e' stato cambiato"


def test_a_conflict_is_symmetric(semplice):
    """Basta che lo dichiari uno dei due."""
    semplice.register_effect(allunga(id="prova:altro"))
    semplice.register_effect(allunga(id="prova:geloso",
                                     conflicts=frozenset({"altro"})))
    fatto = catena(semplice, ("altro", SCOPE_MODEL, 1.0), ("geloso", SCOPE_MODEL, 1.0))
    assert "EFFECT_CONFLICT" in fatto.report.codes()


def test_effects_that_do_not_conflict_compose(semplice):
    semplice.register_effect(allunga(
        id="prova:assottiglia",
        changes=(ParamRule(semantic_role="girth", expression="value * 0.5"),)))
    fatto = catena(semplice, ("allunga", SCOPE_MODEL, 1.0),
                   ("assottiglia", SCOPE_MODEL, 1.0))
    assert len(fatto.applied) == 2
    assert fatto.node("a").values["length"] == pytest.approx(2.0)
    assert fatto.node("a").values["girth"] == pytest.approx(0.1)


def test_two_effects_on_the_same_parameter_compose_in_order(semplice):
    semplice.register_effect(_tracciante("prova:uno", STAGE_PROPORTION, priority=2))
    semplice.register_effect(_tracciante("prova:due", STAGE_PROPORTION, priority=1))
    fatto = catena(semplice, ("uno", SCOPE_MODEL, 1.0), ("due", SCOPE_MODEL, 1.0))
    assert fatto.node("a").values["length"] == pytest.approx(3.0), "1 + 1 + 1"


# --------------------------------------------------------------------------- #
# Provenienza
# --------------------------------------------------------------------------- #
def test_a_changed_parameter_remembers_who_changed_it(semplice):
    fatto = catena(semplice, ("allunga", "part:a", 0.5))
    voce = fatto.node("a").sources["length"]
    assert voce.source == FROM_EFFECT
    assert voce.origin == "prova:allunga"
    assert voce.previous == 1.0 and voce.value == pytest.approx(1.5)
    assert voce.expression == "value * (1 + amount)"


def test_an_untouched_parameter_keeps_its_own_provenance(semplice):
    fatto = catena(semplice, ("allunga", "part:a", 0.5))
    assert fatto.node("a").source("girth") == "default"
    assert fatto.node("b").source("length") == "default"


def test_the_provenance_survives_two_effects(semplice):
    semplice.register_effect(_tracciante("prova:secondo", STAGE_PROPORTION))
    fatto = catena(semplice, ("allunga", SCOPE_MODEL, 1.0),
                   ("secondo", SCOPE_MODEL, 1.0))
    voce = fatto.node("a").sources["length"]
    assert voce.source == FROM_EFFECT and voce.origin == "prova:secondo"


# --------------------------------------------------------------------------- #
# Una volta sola per discendenza
# --------------------------------------------------------------------------- #
def test_an_effect_is_not_applied_twice_down_the_same_role():
    """Il difetto che aveva sfasciato il chibi, tenuto sotto un test.

    Braccio e avambraccio hanno lo stesso ruolo. Accorciarli entrambi accorcia
    l'avambraccio dentro un braccio gia' accorciato: il risultato non e' "piu'
    corto", e' rotto.
    """
    reg = registro(
        componente("prova:tronco", mounts=(mount("segmento", socket_id="dentro",
                                                 capacity=0),), **PEZZO),
        componente("prova:arto", provides=(Capability("segmento"),),
                   mounts=(mount("segmento", socket_id="dentro", capacity=0),),
                   role="arto", **PEZZO),
        allunga())
    g = CompositionGraph()
    g.set_root("r", "prova:tronco")
    g.add_child("arto", "prova:arto", "r", requirement=Requirement(capability="segmento"))
    g.add_child("pezzo", "prova:arto", "arto",
                requirement=Requirement(capability="segmento"))
    g.effect("allunga", scope=SCOPE_MODEL, amount=1.0)

    fatto = apply_effects(resolve(g, reg), reg)
    assert fatto.node("arto").values["length"] == pytest.approx(2.0)
    assert fatto.node("pezzo").values["length"] == 1.0, "non due volte"
    assert "EFFECT_SKIPPED_IN_LINEAGE" in fatto.report.codes()


def test_two_nodes_with_the_same_role_on_different_branches_are_both_changed():
    """La regola e' per discendenza, non per ruolo in assoluto."""
    reg = registro(
        componente("prova:tronco", mounts=(mount("segmento", socket_id="dentro",
                                                 capacity=0),), **PEZZO),
        componente("prova:arto", provides=(Capability("segmento"),), role="arto",
                   **PEZZO),
        allunga())
    g = CompositionGraph()
    g.set_root("r", "prova:tronco")
    for nome in ("uno", "due"):
        g.add_child(nome, "prova:arto", "r",
                    requirement=Requirement(capability="segmento"))
    g.effect("allunga", scope=SCOPE_MODEL, amount=1.0)

    fatto = apply_effects(resolve(g, reg), reg)
    assert fatto.node("uno").values["length"] == pytest.approx(2.0)
    assert fatto.node("due").values["length"] == pytest.approx(2.0)


def test_a_component_without_a_role_is_always_changed(semplice):
    """Senza un ruolo non c'e' una discendenza da proteggere."""
    reg = registro(
        componente("prova:tronco", mounts=(mount("segmento", socket_id="dentro",
                                                 capacity=0),), **PEZZO),
        componente("prova:pezzo", provides=(Capability("segmento"),),
                   mounts=(mount("segmento", socket_id="dentro", capacity=0),),
                   **PEZZO),
        allunga())
    g = CompositionGraph()
    g.set_root("r", "prova:tronco")
    g.add_child("a", "prova:pezzo", "r", requirement=Requirement(capability="segmento"))
    g.add_child("b", "prova:pezzo", "a", requirement=Requirement(capability="segmento"))
    g.effect("allunga", scope=SCOPE_MODEL, amount=1.0)

    fatto = apply_effects(resolve(g, reg), reg)
    assert fatto.node("a").values["length"] == pytest.approx(2.0)
    assert fatto.node("b").values["length"] == pytest.approx(2.0)


# --------------------------------------------------------------------------- #
# Ricalcolo dei derivati
# --------------------------------------------------------------------------- #
def test_a_derived_parameter_follows_a_parent_changed_by_an_effect():
    """Senza questo, la casa cresce e la porta resta della misura di prima."""
    reg = registro(
        componente("prova:casa",
                   params={"height": ParamSpec(4.0, DISTANCE, min=0.1, max=99.0,
                                               semantic_role="length")},
                   mounts=(mount("apertura", socket_id="muro"),)),
        componente("prova:porta", provides=(Capability("apertura"),),
                   params={"height": ParamSpec(2.0, DISTANCE, min=0.1, max=99.0,
                                               derived="parent.height * 0.5")}),
        allunga())
    g = CompositionGraph()
    g.set_root("casa", "prova:casa")
    g.add_child("porta", "prova:porta", "casa",
                requirement=Requirement(capability="apertura"))
    g.effect("allunga", scope="part:casa", amount=1.0)

    fatto = apply_effects(resolve(g, reg), reg)
    assert fatto.node("casa").values["height"] == pytest.approx(8.0)
    assert fatto.node("porta").values["height"] == pytest.approx(4.0)
    assert fatto.node("porta").sources["height"].previous == pytest.approx(2.0)


def test_a_parameter_an_effect_touched_is_not_recomputed():
    """La decisione piu' recente vince: la formula non cancella la richiesta."""
    reg = registro(
        componente("prova:casa",
                   params={"height": ParamSpec(4.0, DISTANCE, min=0.1, max=99.0)},
                   mounts=(mount("apertura", socket_id="muro"),)),
        componente("prova:porta", provides=(Capability("apertura"),),
                   params={"height": ParamSpec(2.0, DISTANCE, min=0.1, max=99.0,
                                               semantic_role="length",
                                               derived="parent.height * 0.5")}),
        allunga())
    g = CompositionGraph()
    g.set_root("casa", "prova:casa")
    g.add_child("porta", "prova:porta", "casa",
                requirement=Requirement(capability="apertura"))
    g.effect("allunga", scope="part:porta", amount=1.0)

    fatto = apply_effects(resolve(g, reg), reg)
    assert fatto.node("porta").values["height"] == pytest.approx(4.0)
    assert fatto.node("porta").source("height") == FROM_EFFECT


# --------------------------------------------------------------------------- #
# Effetti geometrici: programmati, non eseguiti
# --------------------------------------------------------------------------- #
def test_a_geometric_effect_is_scheduled_not_applied(semplice):
    piega = EffectSpec(id="prova:piega", stage=STAGE_LOCAL,
                       scopes=(SCOPE_PART, SCOPE_MODEL), apply=lambda m, c: m)
    semplice.register_effect(piega)
    fatto = catena(semplice, ("piega", "part:a", 0.5))

    assert not fatto.applied and len(fatto.planned) == 1
    programmato = fatto.planned[0]
    assert programmato.targets == ("a",) and programmato.amount == 0.5
    assert fatto.for_node("a") == [programmato]


def test_the_pipeline_never_touches_geometry(semplice):
    """La mesh non esiste ancora: inventarla per deformarla sarebbe sbagliare due volte."""
    piega = EffectSpec(id="prova:piega", stage=STAGE_LOCAL, scopes=(SCOPE_MODEL,),
                       apply=lambda m, c: 1 / 0)
    semplice.register_effect(piega)
    fatto = catena(semplice, ("piega", SCOPE_MODEL, 0.5))
    assert fatto.ok, "non e' stato chiamato: e' solo in programma"


def test_the_stages_are_kept_apart(semplice):
    semplice.register_effect(EffectSpec(id="prova:geometrico", stage=STAGE_GLOBAL,
                                        scopes=(SCOPE_MODEL,), apply=lambda m, c: m))
    fatto = catena(semplice, ("allunga", SCOPE_MODEL, 1.0),
                   ("geometrico", SCOPE_MODEL, 1.0))
    assert [e.id for e in fatto.applied] == ["prova:allunga"]
    assert [e.id for e in fatto.planned] == ["prova:geometrico"]


# --------------------------------------------------------------------------- #
# Effetti strutturali
# --------------------------------------------------------------------------- #
def test_a_structural_effect_runs_before_anything_else(semplice):
    visti = []

    def struttura(composizione, ctx):
        visti.append(tuple(n.id for n in composizione.walk()))

    semplice.register_effect(EffectSpec(id="prova:struttura",
                                        stage=STAGE_STRUCTURAL,
                                        scopes=(SCOPE_MODEL,), apply=struttura))
    fatto = catena(semplice, ("allunga", SCOPE_MODEL, 1.0),
                   ("struttura", SCOPE_MODEL, 1.0))
    assert visti == [("r", "a", "b")]
    assert [e.id for e in fatto.applied] == ["prova:struttura", "prova:allunga"]


def test_a_structural_effect_can_change_the_resolved_graph(semplice):
    def togli(composizione, ctx):
        composizione.nodes.pop("b", None)
        composizione.order.remove("b")

    semplice.register_effect(EffectSpec(id="prova:pota", stage=STAGE_STRUCTURAL,
                                        scopes=(SCOPE_MODEL,), apply=togli))
    fatto = catena(semplice, ("pota", SCOPE_MODEL, 1.0))
    assert [n.id for n in fatto.walk()] == ["r", "a"]


# --------------------------------------------------------------------------- #
# Fallimenti
# --------------------------------------------------------------------------- #
def test_an_effect_that_fails_says_so(semplice):
    def esplode(composizione, ctx):
        raise RuntimeError("non ci riesco")

    semplice.register_effect(EffectSpec(id="prova:rotto", stage=STAGE_STRUCTURAL,
                                        scopes=(SCOPE_MODEL,), apply=esplode,
                                        on_failure=RECOVERABLE))
    fatto = catena(semplice, ("rotto", SCOPE_MODEL, 1.0))
    assert "EFFECT_APPLICATION_FAILED" in fatto.report.codes()
    assert fatto.ok, "recuperabile: il modello resta"


def test_an_effect_declared_indispensable_makes_the_failure_fatal(semplice):
    def esplode(composizione, ctx):
        raise RuntimeError("non ci riesco")

    semplice.register_effect(EffectSpec(id="prova:vitale", stage=STAGE_STRUCTURAL,
                                        scopes=(SCOPE_MODEL,), apply=esplode,
                                        on_failure="fatal"))
    fatto = catena(semplice, ("vitale", SCOPE_MODEL, 1.0))
    assert not fatto.ok


def test_an_unreadable_expression_does_not_break_the_model(semplice):
    semplice.register_effect(allunga(
        id="prova:storto",
        changes=(ParamRule(semantic_role="length", expression="value * mai_visto"),)))
    fatto = catena(semplice, ("storto", SCOPE_MODEL, 1.0))
    assert "EFFECT_APPLICATION_FAILED" in fatto.report.codes()
    assert fatto.node("a").values["length"] == 1.0


# --------------------------------------------------------------------------- #
# Determinismo
# --------------------------------------------------------------------------- #
def test_the_same_request_gives_the_same_result_five_times(semplice):
    atteso = None
    for _ in range(5):
        fatto = catena(semplice, ("allunga", SCOPE_MODEL, 0.7))
        firma = [(n.id, round(n.values["length"], 6)) for n in fatto.walk()]
        atteso = atteso if atteso is not None else firma
        assert firma == atteso


def test_two_independent_registries_give_the_same_effects(mondo):
    altro = load([INTERNI])
    g = CompositionGraph()
    g.set_root("corpo", "humanoid:body", height=1.8)
    g.effect("lanky", scope=SCOPE_MODEL, amount=0.6)

    uno = apply_effects(resolve(g, mondo), mondo).to_dict()
    due = apply_effects(resolve(g, altro), altro).to_dict()
    assert uno == due


# --------------------------------------------------------------------------- #
# Effetto e stile sono due cose diverse
# --------------------------------------------------------------------------- #
def test_a_style_is_not_an_effect(mondo):
    """Lo stile e' il linguaggio visivo; l'effetto e' una modifica chiesta."""
    g = CompositionGraph(style="low_poly")
    g.set_root("corpo", "humanoid:body", height=1.8)
    g.effect("perspective_exaggeration", scope=SCOPE_MODEL, amount=0.5)

    fatto = apply_effects(resolve(g, mondo), mondo)
    assert fatto.style == "low_poly"
    assert [e.id for e in fatto.planned] == ["fx:perspective_exaggeration"]
    assert mondo.style("low_poly") is not None, "lo stile esiste"
    assert mondo.effect("low_poly") is None, "ma non e' un effetto"
    assert "primitives:low_poly" not in [e.id for e in mondo.effects()]


# --------------------------------------------------------------------------- #
# I tre effetti veri
# --------------------------------------------------------------------------- #
def _umanoide(mondo, detail_level: int = 2) -> CompositionGraph:
    def chiedi(cap, **kw):
        return Requirement(capability=cap, **kw)

    g = CompositionGraph(detail_level=detail_level)
    g.set_root("corpo", "humanoid:body", height=1.8)
    g.add_child("torso", "humanoid:torso", "corpo", requirement=chiedi("core_mount"))
    g.add_child("testa", "humanoid:head", "torso", requirement=chiedi("head_mount"))
    g.add_child("braccio_l", "humanoid:arm", "torso",
                requirement=chiedi("limb_mount", side="l", tags=frozenset({"alto"})))
    g.add_child("gamba_l", "humanoid:leg", "torso",
                requirement=chiedi("limb_mount", side="l", tags=frozenset({"basso"})))
    return g


def test_lanky_makes_things_longer_and_thinner(mondo):
    g = _umanoide(mondo)
    g.effect("lanky", scope=SCOPE_MODEL, amount=0.8)

    fatto = apply_effects(resolve(g, mondo), mondo)
    nudo = resolve(_umanoide(mondo), mondo)
    braccio, riferimento = fatto.node("braccio_l"), nudo.node("braccio_l")

    assert braccio.values["length"] == pytest.approx(
        riferimento.values["length"] * (1 + 0.8 * 0.45))
    assert braccio.values["girth"] == pytest.approx(
        riferimento.values["girth"] * (1 - 0.8 * 0.30))
    assert fatto.ok, fatto.report.describe()


def test_lanky_does_not_shorten_a_forearm_inside_a_shortened_arm(mondo):
    """Il braccio ha figli con lo stesso ruolo: l'effetto entra una volta sola."""
    g = _umanoide(mondo, detail_level=3)
    g.effect("lanky", scope=SCOPE_MODEL, amount=1.0)

    fatto = apply_effects(resolve(g, mondo), mondo)
    assert fatto.node("braccio_l").source("length") == FROM_EFFECT
    assert fatto.node("braccio_l/omero").source("length") != FROM_EFFECT
    assert fatto.node("braccio_l/avambraccio").source("length") != FROM_EFFECT
    assert "EFFECT_SKIPPED_IN_LINEAGE" in fatto.report.codes()


def test_lanky_works_on_a_vocabulary_that_has_no_limbs(mondo):
    """Non cerca gambe: cerca parametri dichiarati lunghezze."""
    g = CompositionGraph()
    g.set_root("casa", "architecture:house")
    g.effect("lanky", scope=SCOPE_MODEL, amount=1.0)

    fatto = apply_effects(resolve(g, mondo), mondo)
    assert fatto.node("casa").values["height"] == pytest.approx(4.0 * 1.45)
    assert fatto.node("casa").values["width"] == pytest.approx(6.0 * 0.70)


def test_lanky_and_chunky_cannot_be_asked_together(mondo):
    g = _umanoide(mondo)
    g.effect("lanky", scope=SCOPE_MODEL, amount=0.8)
    g.effect("chunky", scope=SCOPE_MODEL, amount=0.8)

    fatto = apply_effects(resolve(g, mondo), mondo)
    assert "EFFECT_CONFLICT" in fatto.report.codes()
    assert not fatto.applied


def test_bend_is_scheduled_on_the_part_it_names(mondo):
    g = _umanoide(mondo)
    g.effect("bend", scope="part:gamba_l", amount=0.6, axis="Z")

    fatto = apply_effects(resolve(g, mondo), mondo)
    programmato = fatto.planned[0]
    assert programmato.id == "fx:bend" and programmato.stage == STAGE_LOCAL
    assert programmato.targets == ("gamba_l",)
    assert programmato.params["axis"] == "Z"


def test_bend_actually_bends_a_mesh(mondo):
    """Il contratto di una deformazione: prende una mesh, restituisce una mesh."""
    import trimesh

    from app.geometry.kernel import grow

    dritta = grow([(0.0, 0.1), (1.0, 0.1)], sides=8, length=1.0, axis=0)
    piegata = mondo.effect("bend").transform(
        dritta, EffectContext(amount=1.0, params={"axis": "Z", "along": "X"}))

    assert isinstance(piegata, trimesh.Trimesh)
    assert len(piegata.vertices) == len(dritta.vertices), "stessa topologia"
    assert piegata.bounds[1][1] > dritta.bounds[1][1] + 0.2, "si e' alzata"
    assert piegata.bounds[1][0] < dritta.bounds[1][0], "e accorciata in lunghezza"


def test_bending_by_zero_changes_nothing(mondo):
    from app.geometry.kernel import grow

    dritta = grow([(0.0, 0.1), (1.0, 0.1)], sides=8, length=1.0, axis=0)
    uguale = mondo.effect("bend").transform(dritta, EffectContext(amount=0.0))
    assert np.allclose(uguale.vertices, dritta.vertices)


def test_bending_is_the_same_at_any_scale(mondo):
    """La curvatura e' un angolo totale, non radianti al metro.

    Senza questa scelta lo stesso effetto su un modello alto sei metri
    curverebbe tre volte di piu', e i giunti si staccherebbero.
    """
    from app.geometry.kernel import grow

    forme = []
    for lunghezza in (1.0, 6.0):
        dritta = grow([(0.0, 0.1 * lunghezza), (1.0, 0.1 * lunghezza)],
                      sides=8, length=lunghezza, axis=0)
        piegata = mondo.effect("bend").transform(dritta, EffectContext(amount=0.8))
        misura = piegata.bounds[1] - piegata.bounds[0]
        forme.append(misura / lunghezza)
    assert np.allclose(forme[0], forme[1], atol=1e-6), "la forma non cambia"


def test_perspective_exaggeration_is_global(mondo):
    g = _umanoide(mondo)
    g.effect("perspective_exaggeration", scope=SCOPE_MODEL, amount=0.5)

    fatto = apply_effects(resolve(g, mondo), mondo)
    programmato = fatto.planned[0]
    assert programmato.stage == STAGE_GLOBAL
    assert len(programmato.targets) == len(list(fatto.walk()))


def test_perspective_exaggeration_cannot_be_asked_on_one_part(mondo):
    """Dichiara di essere globale: chiederla su un pezzo e' un errore, non un caso."""
    g = _umanoide(mondo)
    g.effect("perspective_exaggeration", scope="part:testa", amount=0.5)

    fatto = apply_effects(resolve(g, mondo), mondo)
    assert "EFFECT_INCOMPATIBLE" in fatto.report.codes()


def test_perspective_exaggeration_actually_deforms(mondo):
    from app.geometry.kernel import block

    scatola = block((2.0, 1.0, 1.0), sides=4, axis=0)
    esagerata = mondo.effect("perspective_exaggeration").transform(
        scatola, EffectContext(amount=1.0, params={"axis": "X"}))

    misure = esagerata.bounds[1] - esagerata.bounds[0]
    assert misure[0] == pytest.approx(2.0), "la profondita' non cambia"
    assert misure[1] > 1.0, "davanti e' piu' grande"


# --------------------------------------------------------------------------- #
# Il caso completo
# --------------------------------------------------------------------------- #
def test_the_whole_vertical_slice(mondo):
    """Umanoide, testa di rana, gambe di spada, lanky, prospettiva esagerata."""
    g = _umanoide(mondo)
    g.swap("testa", "creature:frog_head")
    g.swap("gamba_l", "weapon:sword")
    g.effect("lanky", scope=SCOPE_MODEL, amount=0.8)
    g.effect("perspective_exaggeration", scope=SCOPE_MODEL, amount=0.5)

    fatto = apply_effects(resolve(g, mondo), mondo)
    assert fatto.ok, fatto.report.describe()
    assert {"humanoid:body", "humanoid:torso", "creature:frog_head",
            "humanoid:arm", "weapon:sword"} <= set(fatto.refs())
    assert [e.id for e in fatto.applied] == ["fx:lanky"]
    assert [e.id for e in fatto.planned] == ["fx:perspective_exaggeration"]
    # la spada non ha un parametro che si chiama `length`: ha `blade_length`,
    # e l'effetto lo trova perche' e' **dichiarato** come una lunghezza. E' il
    # motivo per cui una regola punta a un ruolo semantico e non a un nome.
    assert fatto.node("gamba_l").source("blade_length") == FROM_EFFECT
    assert fatto.node("gamba_l").source("handle_length") == FROM_EFFECT


def test_the_same_pipeline_on_a_house_and_a_planet(mondo):
    g = CompositionGraph()
    g.set_root("casa", "architecture:house")
    g.add_child("mondo", "space:planet", "casa",
                requirement=Requirement(capability="surface"))
    g.effect("perspective_exaggeration", scope=SCOPE_MODEL, amount=0.9)
    g.effect("bend", scope="part:casa", amount=0.2)

    fatto = apply_effects(resolve(g, mondo), mondo)
    assert fatto.ok, fatto.report.describe()
    assert [e.id for e in fatto.planned] == ["fx:bend",
                                            "fx:perspective_exaggeration"], \
        "locale prima di globale, sempre"


def test_the_effected_composition_can_be_read_as_a_dictionary(mondo):
    g = _umanoide(mondo)
    g.effect("lanky", scope="role:arm", amount=1.0)
    g.effect("perspective_exaggeration", scope=SCOPE_MODEL, amount=0.4)

    dati = apply_effects(resolve(g, mondo), mondo).to_dict()
    effetti = {e["id"]: e for e in dati["effects"]}
    assert effetti["fx:lanky"]["state"] == "applicato"
    assert effetti["fx:lanky"]["scope"] == "role:arm"
    assert effetti["fx:perspective_exaggeration"]["state"] == "in programma"


# --------------------------------------------------------------------------- #
# Confini
# --------------------------------------------------------------------------- #
def test_the_effect_system_never_names_a_thing_of_the_world():
    proibite = ("humanoid", "umanoid", "animal", "animale", "fish", "pesce",
                "dragon", "drago", "house", "casa", "planet", "pianeta",
                "leg", "gamba", "arm", "braccio", "head", "testa", "lanky",
                "bend", "chibi")
    testo = (QUI.parent / "app" / "core" / "effect.py").read_text(encoding="utf-8")
    codice = "\n".join(r for r in testo.lower().splitlines()
                       if not r.strip().startswith("#"))
    for parola in proibite:
        assert "'%s'" % parola not in codice and '"%s"' % parola not in codice, \
            "effect.py nomina %s" % parola


def test_the_pipeline_does_not_know_the_three_effects_by_name():
    """`lanky`, `bend` e `perspective_exaggeration` stanno in un plugin.

    Il core li tratta come tratterebbe un effetto che ancora non esiste.
    """
    testo = (QUI.parent / "app" / "core" / "effect.py").read_text(encoding="utf-8")
    for nome in ("lanky", "chunky", "bend", "perspective_exaggeration"):
        # nominarli in un commento va bene: e' un esempio. Nominarli in una
        # stringa vorrebbe dire che il codice si aspetta che esistano.
        assert "'%s'" % nome not in testo and '"%s"' % nome not in testo


def test_an_effect_does_not_create_a_component(semplice):
    prima = len(list(catena(semplice).walk()))
    dopo = len(list(catena(semplice, ("allunga", SCOPE_MODEL, 1.0)).walk()))
    assert prima == dopo


def test_the_resolved_composition_stays_available(semplice):
    fatto = catena(semplice, ("allunga", SCOPE_MODEL, 1.0))
    assert fatto.composition is not None
    assert fatto.composition.graph is not None, "e con lui il piano di partenza"
