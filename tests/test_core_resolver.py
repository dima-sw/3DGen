"""Il resolver: come realizzo quello che voglio con quello che esiste.

Due famiglie di test, con due scopi diversi.

I test **del core** usano componenti costruiti qui, senza significato: `alfa`,
`beta`, `ramo`. Verificano il meccanismo.

I test **incrociati** usano i plugin veri sotto `app/plugins/`, che invece
rappresentano cose del mondo — umanoidi, pesci, draghi, case, pianeti. Servono a
dimostrare l'unica cosa che conta davvero: che lo stesso resolver collega una
testa di drago a un corpo di pesce e una casa a un pianeta senza sapere che cosa
sia nessuna delle quattro.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from app.core.budget import NODES, Budget, standard, unlimited
from app.core.capability import (CAPABILITY, CAPABILITY_AND_SIDE,
                                 CAPABILITY_AND_TAGS, EXACT_ID, FALLBACK,
                                 Capability, Requirement, mount)
from app.core.component import Attachment, Component, Piece
from app.core.constraints import CLAMP, Constraint
from app.core.errors import WARNING
from app.core.graph import CompositionGraph
from app.core.params import DISTANCE, RATIO, ParamSpec
from app.core.registry import Registry
from app.core.resolver import Resolver, resolve

QUI = Path(__file__).resolve().parent
INTERNI = QUI.parent / "app" / "plugins"


def _pezzo(v, ctx):
    return Piece(mesh=None)


def componente(id: str, **kwargs) -> Component:
    return Component(id=id, build=_pezzo, **kwargs)


def registro(*componenti: Component) -> Registry:
    r = Registry()
    for c in componenti:
        r.register_component(c)
    return r


@pytest.fixture(scope="module")
def mondo() -> Registry:
    """Il vocabolario del mondo, caricato una volta sola e congelato."""
    r = Registry()
    r.load_directory(INTERNI)
    assert not r.report.errors(), r.report.describe()
    return r.freeze()


def chiedi(capability: str = "", **kwargs) -> Requirement:
    return Requirement(capability=capability, **kwargs)


# --------------------------------------------------------------------------- #
# Risoluzione di base
# --------------------------------------------------------------------------- #
def test_a_qualified_reference_resolves_to_its_component():
    reg = registro(componente("prova:alfa"))
    g = CompositionGraph()
    g.set_root("r", "prova:alfa")

    out = resolve(g, reg)
    assert out.ok
    assert out.node("r").ref == "prova:alfa"
    assert out.refs() == ["prova:alfa"]


def test_the_original_plan_stays_available():
    """Piano e risultato, uno accanto all'altro: senza il primo non si capisce
    perche' il secondo e' venuto cosi'."""
    reg = registro(componente("prova:alfa"))
    g = CompositionGraph()
    g.set_root("r", "prova:alfa")
    out = resolve(g, reg)
    assert out.graph is g


def test_a_missing_plugin_is_named_as_such():
    reg = registro(componente("prova:alfa"))
    g = CompositionGraph()
    g.set_root("r", "assente:alfa")

    out = resolve(g, reg)
    assert "PLUGIN_NOT_FOUND" in out.report.codes()
    assert not out.ok and out.unresolved == ["r"]
    assert "prova" in out.report.entries[0].alternatives


def test_a_missing_component_lists_what_the_plugin_has():
    reg = registro(componente("prova:alfa"), componente("prova:beta"))
    g = CompositionGraph()
    g.set_root("r", "prova:inesistente")

    out = resolve(g, reg)
    voce = [d for d in out.report if d.code == "COMPONENT_NOT_FOUND"][0]
    assert set(voce.alternatives) == {"prova:alfa", "prova:beta"}


def test_nothing_is_invented_when_something_is_missing():
    """Nessun componente magico, nessun plugin creato al volo."""
    reg = registro(componente("prova:alfa"))
    g = CompositionGraph()
    g.set_root("r", "prova:alfa")
    g.add_child("x", "prova:mai_visto", "r")

    out = resolve(g, reg)
    assert len(out) == 1 and out.unresolved == ["x"]
    assert len(reg) == 1, "il registry non e' stato toccato"


def test_an_unresolved_branch_does_not_stop_its_siblings():
    reg = registro(componente("prova:alfa", mounts=(mount("attacco"),)),
                   componente("prova:beta", provides=(Capability("attacco"),)))
    g = CompositionGraph()
    g.set_root("r", "prova:alfa")
    g.add_child("rotto", "prova:mai_visto", "r")
    g.add_child("buono", "prova:beta", "r", requirement=chiedi("attacco"))

    out = resolve(g, reg)
    assert "buono" in out and "rotto" not in out


def test_a_structurally_broken_plan_is_not_resolved():
    """Prima si aggiusta il grafo, poi si guarda se i pezzi esistono."""
    reg = registro(componente("prova:alfa"))
    g = CompositionGraph()
    g.set_root("a", "prova:alfa")
    g.add_child("b", "prova:alfa", "a")
    g.parents["a"] = "b"                       # ciclo

    out = resolve(g, reg)
    assert "GRAPH_CYCLE" in out.report.codes()
    assert "GRAPH_INVALID" in out.report.codes()
    assert len(out) == 0


# --------------------------------------------------------------------------- #
# Sostituzione
# --------------------------------------------------------------------------- #
def _due_pezzi() -> Registry:
    return registro(
        componente("prova:contenitore", mounts=(mount("attacco", socket_id="posto"),)),
        componente("prova:originale", provides=(Capability("attacco"),)),
        componente("altrove:sostituto", provides=(Capability("attacco"),)),
        componente("altrove:secondo", provides=(Capability("attacco"),)))


def test_a_swap_resolves_to_the_replacement_only():
    reg = _due_pezzi()
    g = CompositionGraph()
    g.set_root("r", "prova:contenitore")
    g.add_child("t", "prova:originale", "r", requirement=chiedi("attacco"))
    g.swap("t", "altrove:sostituto")

    out = resolve(g, reg)
    assert out.node("t").ref == "altrove:sostituto"
    assert "prova:originale" not in out.refs(), "il sostituito non si costruisce"
    assert len(out) == 2, "e non compare come nodo in piu'"


def test_the_resolved_node_remembers_what_it_replaced():
    reg = _due_pezzi()
    g = CompositionGraph()
    g.set_root("r", "prova:contenitore")
    g.add_child("t", "prova:originale", "r", requirement=chiedi("attacco"))
    g.swap("t", "altrove:sostituto")

    out = resolve(g, reg)
    nodo = out.node("t")
    assert nodo.substituted and nodo.swapped_from == "prova:originale"
    assert out.substitutions() == {"t": ("prova:originale", "altrove:sostituto")}


def test_a_second_swap_wins_over_the_first():
    reg = _due_pezzi()
    g = CompositionGraph()
    g.set_root("r", "prova:contenitore")
    g.add_child("t", "prova:originale", "r", requirement=chiedi("attacco"))
    g.swap("t", "altrove:sostituto")
    g.swap("t", "altrove:secondo")

    out = resolve(g, reg)
    assert out.node("t").ref == "altrove:secondo"
    assert out.refs().count("altrove:sostituto") == 0
    assert len(out) == 2


def test_the_plan_keeps_the_whole_history_of_a_swap():
    reg = _due_pezzi()
    g = CompositionGraph()
    g.set_root("r", "prova:contenitore")
    g.add_child("t", "prova:originale", "r", requirement=chiedi("attacco"))
    g.swap("t", "altrove:sostituto")
    resolve(g, reg)

    swaps = [op for op in g.operations if op.kind == "swap"]
    assert swaps[0].detail == {"from": "prova:originale", "to": "altrove:sostituto"}
    assert g.node("t").ref == "prova:originale", "il piano non e' stato riscritto"


def test_a_swap_to_something_missing_is_diagnosed():
    reg = _due_pezzi()
    g = CompositionGraph()
    g.set_root("r", "prova:contenitore")
    g.add_child("t", "prova:originale", "r", requirement=chiedi("attacco"))
    g.swap("t", "altrove:che_non_c_e")

    out = resolve(g, reg)
    assert "COMPONENT_NOT_FOUND" in out.report.codes()
    assert "sostituzione" in out.report.entries[0].why


# --------------------------------------------------------------------------- #
# Collegamenti: i cinque livelli
# --------------------------------------------------------------------------- #
def _padre_con_innesti() -> Component:
    return componente(
        "prova:padre",
        mounts=(mount("attacco", socket_id="preciso"),
                mount("attacco", socket_id="sinistro", side="l"),
                mount("attacco", socket_id="destro", side="r"),
                mount("attacco", socket_id="etichettato", tags=("alto",)),
                mount("attacco", socket_id="qualunque")))


def _collega(requisito: Requirement, figlio: Component | None = None):
    figlio = figlio or componente("prova:figlio", provides=(Capability("attacco"),))
    reg = registro(_padre_con_innesti(), figlio)
    g = CompositionGraph()
    g.set_root("p", "prova:padre")
    g.add_child("f", figlio.id, "p", requirement=requisito)
    return resolve(g, reg)


def test_an_exact_socket_id_wins():
    out = _collega(Requirement(capability="attacco", socket_id="destro"))
    assert out.node("f").link.parent_socket == "destro"
    assert out.node("f").link.score == EXACT_ID
    assert out.node("f").link.how == "socket esatto"


def test_capability_and_side_come_next():
    out = _collega(Requirement(capability="attacco", side="l"))
    assert out.node("f").link.parent_socket == "sinistro"
    assert out.node("f").link.score == CAPABILITY_AND_SIDE


def test_capability_and_tags_come_after_the_side():
    out = _collega(Requirement(capability="attacco", tags=frozenset({"alto"})))
    assert out.node("f").link.parent_socket == "etichettato"
    assert out.node("f").link.score == CAPABILITY_AND_TAGS


def test_capability_alone_still_connects():
    out = _collega(Requirement(capability="attacco"))
    assert out.node("f").link.score == CAPABILITY
    assert out.ok


def test_a_requirement_that_asks_nothing_is_answered_by_the_child():
    """Se il figlio fornisce cio' che l'innesto accetta, la corrispondenza c'e'.

    L'ha dichiarata il figlio invece del requisito, ma e' una dichiarazione di
    contratto, non una casualita': vale quanto una corrispondenza per capability.
    """
    out = _collega(Requirement())
    assert out.ok and out.node("f").link.score == CAPABILITY


def test_a_requirement_that_asks_nothing_is_not_a_licence():
    """Se nemmeno il figlio dichiara di starci, non si attacca niente."""
    padre = componente("prova:padre", mounts=(mount("attacco", socket_id="posto"),))
    estraneo = componente("prova:estraneo", provides=(Capability("altro"),))
    reg = registro(padre, estraneo)
    g = CompositionGraph()
    g.set_root("p", "prova:padre")
    g.add_child("f", "prova:estraneo", "p")

    out = resolve(g, reg)
    assert "SOCKET_INCOMPATIBLE" in out.report.codes()
    assert out.unresolved == ["f"], "attaccabili non vuol dire compatibili"


def test_the_wrong_side_is_refused_unless_the_contract_allows_it():
    """Un ripiego si concede, non si deduce.

    Senza questa regola «nessuna richiesta resta senza risposta» degenera in
    «attacca comunque qualcosa da qualche parte»: un pezzo mancante si vede, un
    pezzo attaccato nel posto sbagliato sembra voluto.
    """
    padre = componente("prova:padre",
                       mounts=(mount("attacco", socket_id="destro", side="r"),))
    figlio = componente("prova:figlio", provides=(Capability("attacco"),))
    reg = registro(padre, figlio)
    g = CompositionGraph()
    g.set_root("p", "prova:padre")
    g.add_child("f", "prova:figlio", "p", requirement=chiedi("attacco", side="l"))

    out = resolve(g, reg)
    assert "SOCKET_INCOMPATIBLE" in out.report.codes()
    voce = [d for d in out.report if d.code == "SOCKET_INCOMPATIBLE"][0]
    assert "il ripiego non e' dichiarato" in voce.why


def test_who_asks_can_declare_that_a_fallback_is_acceptable():
    padre = componente("prova:padre",
                       mounts=(mount("attacco", socket_id="destro", side="r"),))
    figlio = componente("prova:figlio", provides=(Capability("attacco"),))
    reg = registro(padre, figlio)
    g = CompositionGraph()
    g.set_root("p", "prova:padre")
    g.add_child("f", "prova:figlio", "p",
                requirement=Requirement(capability="attacco", side="l",
                                        allow_fallback=True))

    out = resolve(g, reg)
    assert out.ok and out.node("f").link.score == FALLBACK
    assert "MOUNT_FALLBACK" in out.report.codes()


def test_who_offers_can_declare_a_mount_as_a_fallback():
    """Un attacco di servizio: dichiarato tale da chi lo espone."""
    padre = componente("prova:padre",
                       mounts=(mount("attacco", socket_id="ripiego", side="r",
                                     allow_fallback=True),))
    figlio = componente("prova:figlio", provides=(Capability("attacco"),))
    reg = registro(padre, figlio)
    g = CompositionGraph()
    g.set_root("p", "prova:padre")
    g.add_child("f", "prova:figlio", "p", requirement=chiedi("attacco", side="l"))

    assert resolve(g, reg).ok


def test_compatibility_is_a_filter_not_a_score():
    """Prima si filtra, poi si ordina. Nessun punteggio salva un incompatibile.

    L'unico innesto rimasto libero e' quello dal lato sbagliato: si rifiuta,
    invece di prenderlo perche' era il meno peggio.
    """
    padre = componente("prova:padre",
                       mounts=(mount("attacco", socket_id="sinistro", side="l"),
                               mount("attacco", socket_id="destro", side="r")))
    figlio = componente("prova:figlio", provides=(Capability("attacco"),))
    reg = registro(padre, figlio)
    g = CompositionGraph()
    g.set_root("p", "prova:padre")
    g.add_child("uno", "prova:figlio", "p", requirement=chiedi("attacco", side="l"))
    g.add_child("due", "prova:figlio", "p", requirement=chiedi("attacco", side="l"))

    out = resolve(g, reg)
    assert out.node("uno").link.parent_socket == "sinistro"
    assert out.node("due").link.parent_socket == "sinistro",         "affollato, ma sul lato giusto"
    assert "MOUNT_CROWDED" in out.report.codes()


def test_an_incompatible_requirement_is_refused_with_alternatives():
    padre = componente("prova:padre", mounts=(mount("attacco", socket_id="posto"),))
    figlio = componente("prova:figlio", provides=(Capability("altro"),))
    ospite = componente("prova:ospite", mounts=(mount("altro", socket_id="giusto"),))
    reg = registro(padre, figlio, ospite)
    g = CompositionGraph()
    g.set_root("p", "prova:padre")
    g.add_child("f", "prova:figlio", "p", requirement=chiedi("altro"))

    out = resolve(g, reg)
    assert "SOCKET_INCOMPATIBLE" in out.report.codes()
    voce = [d for d in out.report if d.code == "SOCKET_INCOMPATIBLE"][0]
    assert "prova:ospite" in voce.alternatives, "chi quell'innesto ce l'ha"
    assert out.unresolved == ["f"]


def test_a_parent_without_mounts_says_so():
    reg = registro(componente("prova:padre"),
                   componente("prova:figlio", provides=(Capability("attacco"),)))
    g = CompositionGraph()
    g.set_root("p", "prova:padre")
    g.add_child("f", "prova:figlio", "p", requirement=chiedi("attacco"))

    out = resolve(g, reg)
    assert "NO_MOUNTS" in out.report.codes()


# --------------------------------------------------------------------------- #
# Provides contro mounts
# --------------------------------------------------------------------------- #
def test_the_parent_accepts_and_the_child_provides():
    """La direzione conta: si cerca l'innesto nel padre, la fornitura nel figlio."""
    padre = componente("prova:padre", mounts=(mount("attacco", socket_id="posto"),))
    figlio = componente("prova:figlio", provides=(Capability("attacco"),))
    reg = registro(padre, figlio)

    assert padre.accepts("attacco") and not padre.provides_capability("attacco")
    assert figlio.provides_capability("attacco") and not figlio.accepts("attacco")

    g = CompositionGraph()
    g.set_root("p", "prova:padre")
    g.add_child("f", "prova:figlio", "p", requirement=chiedi("attacco"))
    assert resolve(g, reg).ok


def test_a_child_that_does_not_provide_is_refused():
    """Un innesto per una testa non accetta qualunque cosa ci si infili."""
    padre = componente("prova:padre", mounts=(mount("attacco", socket_id="posto"),))
    intruso = componente("prova:intruso", provides=(Capability("altra_cosa"),))
    giusto = componente("prova:giusto", provides=(Capability("attacco"),))
    reg = registro(padre, intruso, giusto)
    g = CompositionGraph()
    g.set_root("p", "prova:padre")
    g.add_child("f", "prova:intruso", "p", requirement=chiedi("attacco"))

    out = resolve(g, reg)
    assert "PROVIDER_INCOMPATIBLE" in out.report.codes()
    voce = [d for d in out.report if d.code == "PROVIDER_INCOMPATIBLE"][0]
    assert "prova:giusto" in voce.alternatives
    assert "altra_cosa" in voce.why


def test_a_mount_takes_one_child_and_says_when_it_is_crowded():
    padre = componente("prova:padre", mounts=(mount("attacco", socket_id="posto"),))
    figlio = componente("prova:figlio", provides=(Capability("attacco"),))
    reg = registro(padre, figlio)
    g = CompositionGraph()
    g.set_root("p", "prova:padre")
    g.add_child("uno", "prova:figlio", "p", requirement=chiedi("attacco"))
    g.add_child("due", "prova:figlio", "p", requirement=chiedi("attacco"))

    out = resolve(g, reg)
    assert "MOUNT_CROWDED" in out.report.codes()
    assert out.ok, "si attacca comunque: un pezzo mancante sarebbe peggio"
    assert len(out) == 3


def test_a_mount_can_declare_how_many_it_takes():
    """capacity = N: al massimo N. Una capienza dichiarata, non misurata."""
    padre = componente("prova:padre",
                       mounts=(mount("attacco", socket_id="posto", capacity=2),))
    figlio = componente("prova:figlio", provides=(Capability("attacco"),))
    reg = registro(padre, figlio)
    g = CompositionGraph()
    g.set_root("p", "prova:padre")
    for nome in ("uno", "due"):
        g.add_child(nome, "prova:figlio", "p", requirement=chiedi("attacco"))
    assert "MOUNT_CROWDED" not in resolve(g, reg).report.codes()

    g.add_child("tre", "prova:figlio", "p", requirement=chiedi("attacco"))
    assert "MOUNT_CROWDED" in resolve(g, reg).report.codes()


def test_a_mount_can_declare_that_it_takes_many():
    padre = componente("prova:padre",
                       mounts=(mount("attacco", socket_id="superficie", capacity=0),))
    figlio = componente("prova:figlio", provides=(Capability("attacco"),))
    reg = registro(padre, figlio)
    g = CompositionGraph()
    g.set_root("p", "prova:padre")
    for nome in ("uno", "due", "tre"):
        g.add_child(nome, "prova:figlio", "p", requirement=chiedi("attacco"))

    out = resolve(g, reg)
    assert "MOUNT_CROWDED" not in out.report.codes()


def test_a_free_mount_beats_a_better_but_taken_one():
    """Fra i compatibili, un innesto libero viene prima di uno migliore ma pieno."""
    padre = componente("prova:padre",
                       mounts=(mount("attacco", socket_id="sinistro", side="l"),
                               mount("attacco", socket_id="destro", side="r")))
    figlio = componente("prova:figlio", provides=(Capability("attacco"),))
    reg = registro(padre, figlio)
    chiesto = Requirement(capability="attacco", side="l", allow_fallback=True)
    g = CompositionGraph()
    g.set_root("p", "prova:padre")
    g.add_child("uno", "prova:figlio", "p", requirement=chiesto)
    g.add_child("due", "prova:figlio", "p", requirement=chiesto)

    out = resolve(g, reg)
    assert out.node("uno").link.parent_socket == "sinistro"
    assert out.node("due").link.parent_socket == "destro", "libero batte occupato"


# --------------------------------------------------------------------------- #
# Ambiguita'
# --------------------------------------------------------------------------- #
def test_a_bare_name_owned_by_two_plugins_is_ambiguous():
    reg = registro(componente("uno:testa"), componente("due:testa"))
    g = CompositionGraph()
    g.set_root("r", "testa")

    out = resolve(g, reg)
    assert "AMBIGUOUS_COMPONENT" in out.report.codes()
    voce = [d for d in out.report if d.code == "AMBIGUOUS_COMPONENT"][0]
    assert sorted(voce.alternatives) == ["due:testa", "uno:testa"]
    assert len(out) == 0, "non se ne sceglie uno a caso"


def test_a_qualified_reference_removes_the_ambiguity():
    reg = registro(componente("uno:testa"), componente("due:testa"))
    g = CompositionGraph()
    g.set_root("r", "due:testa")
    out = resolve(g, reg)
    assert out.ok and out.node("r").ref == "due:testa"


def test_a_bare_name_can_be_read_as_a_capability():
    """«mettici qualcosa che fornisce questo», quando ce n'e' uno solo."""
    reg = registro(componente("prova:unico", provides=(Capability("superficie"),)))
    g = CompositionGraph()
    g.set_root("r", "superficie")

    out = resolve(g, reg)
    assert out.ok and out.node("r").ref == "prova:unico"


def test_several_providers_of_a_capability_are_ambiguous():
    reg = registro(componente("uno:cosa", provides=(Capability("superficie"),)),
                   componente("due:cosa", provides=(Capability("superficie"),)))
    g = CompositionGraph()
    g.set_root("r", "superficie")

    out = resolve(g, reg)
    assert "AMBIGUOUS_PROVIDER" in out.report.codes()
    assert len(out) == 0


def test_who_only_accepts_a_capability_is_not_a_candidate():
    """Un torso che accetta una testa non e' una testa."""
    reg = registro(componente("uno:cosa", provides=(Capability("superficie"),)),
                   componente("due:ospite", mounts=(mount("superficie"),)))
    g = CompositionGraph()
    g.set_root("r", "superficie")

    out = resolve(g, reg)
    assert out.ok and out.node("r").ref == "uno:cosa"


def test_the_requirement_breaks_the_tie_between_candidates():
    reg = registro(componente("uno:testa", provides=(Capability("head_mount"),)),
                   componente("due:testa"))
    padre = componente("prova:padre", mounts=(mount("head_mount", socket_id="collo"),))
    reg.register_component(padre)
    g = CompositionGraph()
    g.set_root("p", "prova:padre")
    g.add_child("t", "testa", "p", requirement=chiedi("head_mount"))

    out = resolve(g, reg)
    assert out.ok and out.node("t").ref == "uno:testa"


def test_ambiguity_is_reported_the_same_way_every_time():
    reg = registro(componente("uno:testa"), componente("due:testa"),
                   componente("tre:testa"))
    g = CompositionGraph()
    g.set_root("r", "testa")
    atteso = None
    for _ in range(5):
        voce = [d for d in resolve(g, reg).report
                if d.code == "AMBIGUOUS_COMPONENT"][0]
        atteso = atteso or voce.alternatives
        assert voce.alternatives == atteso


# --------------------------------------------------------------------------- #
# Parametri
# --------------------------------------------------------------------------- #
def _con_parametri() -> Component:
    return componente(
        "prova:pezzo",
        params={"width": ParamSpec(0.5, DISTANCE, min=0.1, max=2.0),
                "ratio": ParamSpec(0.25, RATIO, min=0.0, max=1.0)})


def test_a_parameter_without_orders_keeps_its_default():
    reg = registro(_con_parametri())
    g = CompositionGraph()
    g.set_root("r", "prova:pezzo")

    nodo = resolve(g, reg).node("r")
    assert nodo.values["width"] == 0.5
    assert nodo.source("width") == "default"


def test_an_override_wins_over_the_default_and_says_so():
    reg = registro(_con_parametri())
    g = CompositionGraph()
    g.set_root("r", "prova:pezzo", width=1.5)

    nodo = resolve(g, reg).node("r")
    assert nodo.values["width"] == 1.5
    assert nodo.source("width") == "override"
    assert nodo.sources["width"].origin == "r"


def test_an_override_outside_the_range_is_brought_back_and_noted():
    reg = registro(_con_parametri())
    g = CompositionGraph()
    g.set_root("r", "prova:pezzo", width=99.0)

    out = resolve(g, reg)
    assert out.node("r").values["width"] == 2.0
    assert "PARAM_CLAMPED" in out.report.codes()


def test_a_derived_parameter_reads_its_own_values():
    pezzo = componente("prova:pezzo",
                       params={"width": ParamSpec(0.4, DISTANCE, min=0.01, max=3.0),
                               "height": ParamSpec(0.0, DISTANCE, min=0.0, max=9.0,
                                                   derived="width * 2")})
    g = CompositionGraph()
    g.set_root("r", "prova:pezzo", width=0.6)

    nodo = resolve(g, registro(pezzo)).node("r")
    assert nodo.values["height"] == pytest.approx(1.2)
    assert nodo.source("height") == "derived"
    assert nodo.sources["height"].expression == "width * 2"


def test_a_derived_parameter_can_read_its_parent():
    padre = componente("prova:padre",
                       params={"height": ParamSpec(2.0, DISTANCE, min=0.1, max=9.0)},
                       mounts=(mount("attacco", socket_id="posto"),))
    figlio = componente("prova:figlio", provides=(Capability("attacco"),),
                        params={"height": ParamSpec(0.0, DISTANCE, min=0.0, max=9.0,
                                                    derived="parent.height * 0.25")})
    g = CompositionGraph()
    g.set_root("p", "prova:padre", height=3.2)
    g.add_child("f", "prova:figlio", "p", requirement=chiedi("attacco"))

    out = resolve(g, registro(padre, figlio))
    assert out.node("f").values["height"] == pytest.approx(0.8)


def test_a_derived_parameter_can_read_the_root():
    """Tre livelli: il nipote misura se stesso sulla radice, non sul padre."""
    radice = componente("prova:radice",
                        params={"height": ParamSpec(2.0, DISTANCE, min=0.1, max=9.0)},
                        mounts=(mount("attacco", socket_id="posto"),))
    mezzo = componente("prova:mezzo", provides=(Capability("attacco"),),
                       params={"height": ParamSpec(0.5, DISTANCE, min=0.1, max=9.0)},
                       mounts=(mount("attacco", socket_id="posto"),))
    foglia = componente("prova:foglia", provides=(Capability("attacco"),),
                        params={"height": ParamSpec(0.0, DISTANCE, min=0.0, max=9.0,
                                                    derived="root.height * 0.1")})
    g = CompositionGraph()
    g.set_root("r", "prova:radice", height=4.0)
    g.add_child("m", "prova:mezzo", "r", requirement=chiedi("attacco"))
    g.add_child("f", "prova:foglia", "m", requirement=chiedi("attacco"))

    out = resolve(g, registro(radice, mezzo, foglia))
    assert out.node("f").values["height"] == pytest.approx(0.4)


def test_an_unreadable_expression_falls_back_to_the_default():
    pezzo = componente("prova:pezzo",
                       params={"width": ParamSpec(0.7, DISTANCE, min=0.1, max=3.0,
                                                  derived="parent.mai_visto * 2")})
    g = CompositionGraph()
    g.set_root("r", "prova:pezzo")

    out = resolve(g, registro(pezzo))
    assert out.node("r").values["width"] == 0.7
    assert "PARAM_EXPRESSION" in out.report.codes()


def test_an_unknown_parameter_is_ignored_with_a_note():
    reg = registro(_con_parametri())
    g = CompositionGraph()
    g.set_root("r", "prova:pezzo", larghezza_sbagliata=1.0)

    out = resolve(g, reg)
    assert "PARAM_UNKNOWN" in out.report.codes()
    assert out.ok


def test_a_violated_constraint_is_reported():
    pezzo = componente(
        "prova:pezzo",
        params={"width": ParamSpec(1.0, DISTANCE, min=0.1, max=3.0),
                "eye_spacing": ParamSpec(0.3, DISTANCE, min=0.0, max=3.0)},
        constraints=(Constraint("eye_spacing < width",
                                message="gli occhi non stanno nella testa"),))
    g = CompositionGraph()
    g.set_root("r", "prova:pezzo", eye_spacing=2.0, width=1.0)

    out = resolve(g, registro(pezzo))
    assert "CONSTRAINT_VIOLATED" in out.report.codes()
    assert not out.ok


def test_a_clamping_constraint_corrects_instead_of_complaining():
    pezzo = componente(
        "prova:pezzo",
        params={"width": ParamSpec(1.0, DISTANCE, min=0.1, max=3.0),
                "eye_spacing": ParamSpec(0.3, DISTANCE, min=0.0, max=3.0)},
        constraints=(Constraint("eye_spacing < width", severity=CLAMP,
                                target="eye_spacing", to="width * 0.9"),))
    g = CompositionGraph()
    g.set_root("r", "prova:pezzo", eye_spacing=2.0, width=1.0)

    out = resolve(g, registro(pezzo))
    assert out.node("r").values["eye_spacing"] == pytest.approx(0.9)
    assert out.ok


# --------------------------------------------------------------------------- #
# Espansione e dettaglio
# --------------------------------------------------------------------------- #
def _albero() -> Registry:
    def figli(v, ctx):
        return [Attachment(id="fine", component="prova:dettaglio", level=3,
                           requirement=Requirement(capability="attacco")),
                Attachment(id="grosso", component="prova:grosso", level=1,
                           requirement=Requirement(capability="attacco"))]

    return registro(
        Component(id="prova:tronco", build=_pezzo, children=figli,
                  mounts=(mount("attacco", socket_id="posto", capacity=0),)),
        componente("prova:dettaglio", provides=(Capability("attacco"),)),
        componente("prova:grosso", provides=(Capability("attacco"),)))


def test_a_component_expands_its_own_children():
    g = CompositionGraph(detail_level=3)
    g.set_root("r", "prova:tronco")

    out = resolve(g, _albero())
    assert out.refs() == ["prova:tronco", "prova:dettaglio", "prova:grosso"]
    assert out.node("r/fine").from_plan is False


def test_the_detail_level_decides_how_deep_the_expansion_goes():
    g = CompositionGraph(detail_level=1)
    g.set_root("r", "prova:tronco")

    out = resolve(g, _albero())
    assert out.refs() == ["prova:tronco", "prova:grosso"]


def test_the_plan_wins_over_the_declaration():
    """Se il piano ha gia' messo quel pezzo, il componente non ne aggiunge un altro."""
    g = CompositionGraph(detail_level=3)
    g.set_root("r", "prova:tronco")
    g.add_child("grosso", "prova:grosso", "r", requirement=chiedi("attacco"),
                level=1)

    out = resolve(g, _albero())
    assert out.refs().count("prova:grosso") == 1
    assert "grosso" in out and "r/grosso" not in out


def test_a_swapped_plan_child_still_replaces_the_declared_one():
    reg = _albero()
    reg.register_component(componente("altrove:diverso",
                                      provides=(Capability("attacco"),)))
    g = CompositionGraph(detail_level=3)
    g.set_root("r", "prova:tronco")
    g.add_child("grosso", "prova:grosso", "r", requirement=chiedi("attacco"))
    g.swap("grosso", "altrove:diverso")

    out = resolve(g, reg)
    assert "prova:grosso" not in out.refs(), "sostituito, non raddoppiato"
    assert out.refs().count("altrove:diverso") == 1


def test_children_can_take_the_place_of_the_parent_geometry():
    """`replaces_parent`: compaiono i figli, non entrambi."""
    def figli(v, ctx):
        return [Attachment(id="a", component="prova:mezzo", level=2,
                           replaces_parent=True,
                           requirement=Requirement(capability="segmento")),
                Attachment(id="b", component="prova:mezzo", level=2,
                           replaces_parent=True,
                           requirement=Requirement(capability="segmento"))]

    reg = registro(
        Component(id="prova:intero", build=_pezzo, children=figli,
                  mounts=(mount("segmento", socket_id="dentro", capacity=0),)),
        componente("prova:mezzo", provides=(Capability("segmento"),)))
    g = CompositionGraph(detail_level=2)
    g.set_root("r", "prova:intero")

    out = resolve(g, reg)
    assert out.node("r").builds_geometry is False, "il tutto non si costruisce"
    assert [n.ref for n in out.geometry()] == ["prova:mezzo", "prova:mezzo"]
    assert len(out) == 3, "il nodo resta, come contenitore"


def test_a_child_can_replace_a_sibling():
    def figli(v, ctx):
        return [Attachment(id="semplice", component="prova:pezzo", level=1,
                           requirement=Requirement(capability="attacco")),
                Attachment(id="ricco", component="prova:pezzo", level=2,
                           replaces="semplice",
                           requirement=Requirement(capability="attacco"))]

    reg = registro(
        Component(id="prova:tronco", build=_pezzo, children=figli,
                  mounts=(mount("attacco", socket_id="posto", capacity=0),)),
        componente("prova:pezzo", provides=(Capability("attacco"),)))

    semplice = resolve(CompositionGraph(detail_level=1), reg)
    g1 = CompositionGraph(detail_level=1)
    g1.set_root("r", "prova:tronco")
    assert [n.id for n in resolve(g1, reg).walk()] == ["r", "r/semplice"]

    g2 = CompositionGraph(detail_level=2)
    g2.set_root("r", "prova:tronco")
    assert [n.id for n in resolve(g2, reg).walk()] == ["r", "r/ricco"]


def test_an_explicit_request_opens_a_corridor_below_the_detail_level():
    """«una testa semplice, ma con questo pezzo attaccato»."""
    reg = registro(
        componente("prova:radice", mounts=(mount("attacco", socket_id="posto"),)),
        componente("prova:mezzo", provides=(Capability("attacco"),),
                   mounts=(mount("attacco", socket_id="posto"),)),
        componente("prova:punta", provides=(Capability("attacco"),)))

    g = CompositionGraph(detail_level=1)
    g.set_root("r", "prova:radice")
    g.add_child("m", "prova:mezzo", "r", requirement=chiedi("attacco"), level=3)
    g.attach("p", "prova:punta", "m", requirement=chiedi("attacco"))

    out = resolve(g, reg)
    assert [n.id for n in out.walk()] == ["r", "m", "p"], \
        "il pezzo chiesto entra, e con lui chi lo porta"


def test_without_the_request_the_detail_level_holds():
    reg = registro(
        componente("prova:radice", mounts=(mount("attacco", socket_id="posto"),)),
        componente("prova:mezzo", provides=(Capability("attacco"),)))
    g = CompositionGraph(detail_level=1)
    g.set_root("r", "prova:radice")
    g.add_child("m", "prova:mezzo", "r", requirement=chiedi("attacco"), level=3)

    assert [n.id for n in resolve(g, reg).walk()] == ["r"]


# --------------------------------------------------------------------------- #
# Ricorsione
# --------------------------------------------------------------------------- #
def _ricorsivo(passo: float = 0.5) -> Registry:
    """Un componente che contiene se stesso, sempre piu' piccolo."""
    def figli(v, ctx):
        if v["size"] <= 0.1:
            return []
        return [Attachment(id="dentro", component="prova:ramo", level=2,
                           params={"size": v["size"] * passo},
                           requirement=Requirement(capability="ramo"))]

    return registro(Component(
        id="prova:ramo", build=_pezzo, children=figli,
        params={"size": ParamSpec(1.0, DISTANCE, min=0.001, max=10.0)},
        provides=(Capability("ramo"),),
        mounts=(mount("ramo", socket_id="cima"),)))


def test_recursion_goes_as_deep_as_the_structure_asks():
    g = CompositionGraph()
    g.set_root("r", "prova:ramo", size=1.0)

    out = resolve(g, _ricorsivo())
    assert len(out) == 5, "1.0 0.5 0.25 0.125 0.0625: si ferma da solo"
    assert out.node("r/dentro/dentro/dentro/dentro") is not None
    assert out.ok


def test_recursion_without_progress_stops_by_itself():
    """Stesso componente, stessi parametri: non e' ricorsione, e' un ciclo."""
    g = CompositionGraph()
    g.set_root("r", "prova:ramo", size=1.0)

    out = resolve(g, _ricorsivo(passo=1.0))
    assert "RECURSION_WITHOUT_PROGRESS" in out.report.codes()
    assert len(out) == 1, "il figlio e' gia' identico al padre: non entra"
    assert out.ok, "e' una nota, non un errore: il modello resta costruibile"


def test_there_is_no_fixed_depth_limit():
    g = CompositionGraph()
    g.set_root("r", "prova:ramo", size=1.0)
    out = resolve(g, _ricorsivo(passo=0.9))
    assert len(out) > 20, "si scende finche' la struttura lo chiede"


# --------------------------------------------------------------------------- #
# Budget
# --------------------------------------------------------------------------- #
def test_the_node_budget_stops_the_expansion():
    g = CompositionGraph()
    g.set_root("r", "prova:ramo", size=1.0)

    out = resolve(g, _ricorsivo(passo=0.99), budget=Budget(nodes=6))
    assert len(out) == 6
    assert "BUDGET_EXCEEDED" in out.report.codes()


def test_the_budget_diagnostic_says_where_it_stopped():
    g = CompositionGraph(detail_level=4)
    g.set_root("r", "prova:ramo", size=1.0)

    out = resolve(g, _ricorsivo(passo=0.99), budget=Budget(nodes=3))
    voce = [d for d in out.report if d.code == "BUDGET_EXCEEDED"][0]
    assert voce.where.startswith("r/dentro")
    assert "3" in voce.why and "dettaglio chiesto 4" in voce.why


def test_a_generation_without_a_budget_still_has_one():
    """`unlimited()` non e' il predefinito di niente che generi davvero.

    Una ricorsione valida non e' una ricorsione che finisce: un componente che
    si annida riducendo un parametro resta legittimo a ogni passo e non arriva
    mai in fondo. Senza budget non lo ferma nessuno.
    """
    g = CompositionGraph()
    g.set_root("r", "prova:ramo", size=1.0)

    out = resolve(g, _ricorsivo(passo=0.999))       # scenderebbe per sempre
    assert out.budget.nodes is not None, "il predefinito ha dei tetti"
    assert out.budget.seconds is not None
    assert len(out) == out.budget.nodes, "si e' fermato, e ha detto perche'"
    assert "BUDGET_EXCEEDED" in out.report.codes()


def test_asking_for_no_limits_at_all_has_to_be_explicit():
    g = CompositionGraph()
    g.set_root("r", "prova:ramo", size=1.0)

    predefinito = resolve(g, _ricorsivo()).budget
    esplicito = resolve(g, _ricorsivo(), budget=unlimited()).budget
    assert predefinito.limit(NODES) is not None
    assert esplicito.limit(NODES) is None, "solo se lo si chiede"


def test_a_generous_budget_stops_on_the_structure_instead():
    g = CompositionGraph()
    g.set_root("r", "prova:ramo", size=1.0)

    out = resolve(g, _ricorsivo(), budget=Budget(nodes=1000))
    assert "BUDGET_EXCEEDED" not in out.report.codes()
    assert len(out) == 5


def test_budget_and_detail_stop_for_different_reasons():
    g = CompositionGraph(detail_level=1)
    g.set_root("r", "prova:tronco")
    stretto = resolve(g, _albero(), budget=Budget(nodes=1))
    assert "BUDGET_EXCEEDED" in stretto.report.codes()

    largo = resolve(g, _albero(), budget=Budget(nodes=100))
    assert "BUDGET_EXCEEDED" not in largo.report.codes()
    assert len(largo) == 2, "si e' fermato sul dettaglio, non sul budget"


# --------------------------------------------------------------------------- #
# Stile
# --------------------------------------------------------------------------- #
def test_a_component_without_declared_styles_fits_any():
    reg = registro(componente("prova:pezzo"))
    g = CompositionGraph(style="qualunque_stile")
    g.set_root("r", "prova:pezzo")
    assert resolve(g, reg).ok


def test_a_component_made_for_another_style_is_refused():
    reg = registro(componente("prova:realistico",
                              provides=(Capability("testa"),),
                              styles=frozenset({"realistic"})),
                   componente("prova:cartone", provides=(Capability("testa"),),
                              styles=frozenset({"low_poly"})))
    g = CompositionGraph(style="low_poly")
    g.set_root("r", "prova:realistico")

    out = resolve(g, reg)
    assert "STYLE_INCOMPATIBLE" in out.report.codes()
    voce = [d for d in out.report if d.code == "STYLE_INCOMPATIBLE"][0]
    assert "prova:cartone" in voce.alternatives, "chi lo stile giusto ce l'ha"


def test_nothing_is_converted_from_one_style_to_another():
    reg = registro(componente("prova:realistico", styles=frozenset({"realistic"})))
    g = CompositionGraph(style="low_poly")
    g.set_root("r", "prova:realistico")

    out = resolve(g, reg)
    assert len(out) == 0, "non si adatta un componente a uno stile che non parla"


def test_the_style_narrows_the_candidates_of_a_bare_reference():
    reg = registro(componente("uno:testa", provides=(Capability("head_mount"),),
                              styles=frozenset({"realistic"})),
                   componente("due:testa", provides=(Capability("head_mount"),),
                              styles=frozenset({"low_poly"})))
    g = CompositionGraph(style="low_poly")
    g.set_root("r", "head_mount")

    out = resolve(g, reg)
    assert out.ok and out.node("r").ref == "due:testa"


def test_the_style_can_be_imposed_from_outside_the_plan():
    reg = registro(componente("prova:pezzo", styles=frozenset({"realistic"})))
    g = CompositionGraph(style="realistic")
    g.set_root("r", "prova:pezzo")
    assert resolve(g, reg).ok
    assert not resolve(g, reg, style="low_poly").ok


# --------------------------------------------------------------------------- #
# Incroci fra plugin: il punto di tutto
# --------------------------------------------------------------------------- #
def _umanoide(detail_level: int = 2) -> CompositionGraph:
    g = CompositionGraph(detail_level=detail_level)
    g.set_root("corpo", "humanoid:body", height=1.8)
    g.add_child("torso", "humanoid:torso", "corpo", requirement=chiedi("core_mount"))
    g.add_child("testa", "humanoid:head", "torso", requirement=chiedi("head_mount"))
    g.add_child("braccio_l", "humanoid:arm", "torso",
                requirement=chiedi("limb_mount", side="l", tags=frozenset({"alto"})))
    g.add_child("braccio_r", "humanoid:arm", "torso",
                requirement=chiedi("limb_mount", side="r", tags=frozenset({"alto"})))
    return g


def test_a_plain_humanoid_resolves(mondo):
    out = resolve(_umanoide(), mondo)
    assert out.ok, out.report.describe()
    assert out.refs() == ["humanoid:body", "humanoid:torso", "humanoid:head",
                          "humanoid:arm", "humanoid:arm"]
    assert out.node("braccio_l").link.parent_socket == "spalla_l"
    assert out.node("braccio_r").link.parent_socket == "spalla_r"


def test_a_frog_head_goes_on_a_human_neck(mondo):
    g = _umanoide()
    g.swap("testa", "creature:frog_head")

    out = resolve(g, mondo)
    assert out.ok, out.report.describe()
    assert out.node("testa").ref == "creature:frog_head"
    assert out.node("testa").link.parent_socket == "collo"
    assert "humanoid:head" not in out.refs()


def test_a_fish_body_carries_human_arms_and_a_dragon_head(mondo):
    """Il caso che deve funzionare senza che il resolver sappia cosa siano."""
    g = _umanoide()
    g.swap("torso", "fish:fish_body")
    g.swap("testa", "creature:dragon_head")

    out = resolve(g, mondo)
    assert out.ok, out.report.describe()
    assert out.refs() == ["humanoid:body", "fish:fish_body",
                          "creature:dragon_head", "humanoid:arm", "humanoid:arm",
                          "fish:tail"], "il corpo di pesce si porta dietro la coda"
    assert out.node("testa").link.parent_socket == "testa", "l'innesto del pesce"
    assert out.node("braccio_l").link.parent_socket == "pinna_l"


def test_swords_instead_of_legs(mondo):
    g = _umanoide()
    g.add_child("gamba_l", "humanoid:leg", "torso",
                requirement=chiedi("limb_mount", side="l",
                                   tags=frozenset({"basso"})))
    g.swap("gamba_l", "weapon:sword")

    out = resolve(g, mondo)
    assert out.ok, out.report.describe()
    assert out.node("gamba_l").ref == "weapon:sword"
    assert out.node("gamba_l").link.parent_socket == "anca_l"


def test_the_three_swaps_of_the_vertical_slice(mondo):
    """Umanoide con testa di rana, corpo di pesce e gambe di spada."""
    g = _umanoide()
    g.add_child("gamba_l", "humanoid:leg", "torso",
                requirement=chiedi("limb_mount", side="l", tags=frozenset({"basso"})))
    g.swap("testa", "creature:frog_head")
    g.swap("torso", "fish:fish_body")
    g.swap("gamba_l", "weapon:sword")

    out = resolve(g, mondo)
    assert set(out.refs()) == {"humanoid:body", "fish:fish_body",
                               "creature:frog_head", "humanoid:arm",
                               "weapon:sword", "fish:tail"}
    assert len(out.substitutions()) == 3
    assert not [d for d in out.report if d.code in ("SOCKET_INCOMPATIBLE",
                                                    "PROVIDER_INCOMPATIBLE")]


def test_a_house_stands_on_a_planet(mondo):
    """Lo stesso resolver, un vocabolario che non ha niente a che vedere."""
    g = CompositionGraph()
    g.set_root("casa", "architecture:house")
    g.add_child("mondo", "space:planet", "casa", requirement=chiedi("surface"))

    out = resolve(g, mondo)
    assert out.ok, out.report.describe()
    assert out.node("mondo").link.capability == "surface"
    assert out.node("mondo").link.parent_socket == "fondamenta"


def test_the_house_expands_its_own_parts(mondo):
    g = CompositionGraph()
    g.set_root("casa", "architecture:house", height=5.0)

    out = resolve(g, mondo)
    assert out.node("casa/porta").ref == "architecture:door"
    assert out.node("casa/porta").values["height"] == pytest.approx(2.5), \
        "derivato da parent.height"


def test_a_torso_becomes_pelvis_and_chest_at_high_detail(mondo):
    out = resolve(_umanoide(detail_level=3), mondo)
    assert out.node("torso").builds_geometry is False
    assert [n.ref for n in out.geometry() if "torso" in n.id] == \
        ["humanoid:pelvis", "humanoid:chest"]


def test_a_nose_appears_only_at_high_detail(mondo):
    assert "testa/naso" not in resolve(_umanoide(), mondo)
    assert "testa/naso" in resolve(_umanoide(detail_level=3), mondo)


def test_a_piercing_can_be_asked_for_on_a_simple_head(mondo):
    """detail_level 1, ma il piercing chiesto: testa, naso e piercing entrano."""
    g = CompositionGraph(detail_level=1)
    g.set_root("corpo", "humanoid:body", height=1.8)
    g.add_child("torso", "humanoid:torso", "corpo", requirement=chiedi("core_mount"),
                level=1)
    g.add_child("testa", "humanoid:head", "torso", requirement=chiedi("head_mount"),
                level=3)
    g.add_child("naso", "humanoid:nose", "testa", requirement=chiedi("face_mount"),
                level=3)
    g.attach("piercing", "accessories:piercing", "naso", requirement=chiedi("anchor"))

    out = resolve(g, mondo)
    assert out.ok, out.report.describe()
    assert [n.id for n in out.walk()] == ["corpo", "torso", "testa", "naso",
                                          "piercing"]


def test_a_robot_head_is_refused_in_a_low_poly_plan(mondo):
    g = _umanoide()
    g.swap("testa", "robot:head")

    out = resolve(g, mondo)
    assert "STYLE_INCOMPATIBLE" in out.report.codes()
    voce = [d for d in out.report if d.code == "STYLE_INCOMPATIBLE"][0]
    assert "creature:frog_head" in voce.alternatives or \
           "humanoid:head" in voce.alternatives


def test_a_bare_head_is_ambiguous_in_a_full_vocabulary(mondo):
    g = CompositionGraph()
    g.set_root("corpo", "humanoid:body", height=1.8)
    g.add_child("torso", "humanoid:torso", "corpo", requirement=chiedi("core_mount"))
    g.add_child("testa", "head", "torso", requirement=chiedi("head_mount"))

    out = resolve(g, mondo)
    assert "AMBIGUOUS_COMPONENT" in out.report.codes()
    voce = [d for d in out.report if d.code == "AMBIGUOUS_COMPONENT"][0]
    assert set(voce.alternatives) == {"humanoid:head", "robot:head"}


def test_a_bare_capability_finds_the_only_provider(mondo):
    g = CompositionGraph()
    g.set_root("casa", "architecture:house")
    g.add_child("sotto", "surface", "casa", requirement=chiedi("surface"))

    out = resolve(g, mondo)
    assert out.ok and out.node("sotto").ref == "space:planet"


def test_several_heads_make_a_bare_capability_ambiguous(mondo):
    g = CompositionGraph()
    g.set_root("corpo", "humanoid:body", height=1.8)
    g.add_child("torso", "humanoid:torso", "corpo", requirement=chiedi("core_mount"))
    g.add_child("testa", "head_mount", "torso", requirement=chiedi("head_mount"))

    out = resolve(g, mondo)
    assert "AMBIGUOUS_PROVIDER" in out.report.codes()


def test_a_fish_body_carries_four_human_limbs(mondo):
    """Le pinne di un pesce accettano braccia e gambe umane: dichiarano `limb_mount`.

    Il corpo di pesce ha quattro innesti per arti — due pettorali e due
    ventrali — e i quattro arti dell'umanoide trovano posto ciascuno sul
    proprio, lato e altezza compresi. Nessuno dei due plugin sa dell'altro.
    """
    g = _umanoide()
    for nome, lato in (("gamba_l", "l"), ("gamba_r", "r")):
        g.add_child(nome, "humanoid:leg", "torso",
                    requirement=chiedi("limb_mount", side=lato,
                                       tags=frozenset({"basso"})))
    g.swap("torso", "fish:fish_body")

    out = resolve(g, mondo)
    assert out.ok
    assert "MOUNT_CROWDED" not in out.report.codes()
    innesti = sorted(n.link.parent_socket for n in out.walk()
                     if n.ref in ("humanoid:arm", "humanoid:leg"))
    assert innesti == ["pinna_l", "pinna_r", "ventrale_l", "ventrale_r"]


def test_a_mount_that_runs_out_says_so(mondo):
    """Due teste su un collo solo: la seconda si attacca, e si dice che e' pieno."""
    g = _umanoide()
    g.add_child("testa_due", "humanoid:head", "torso",
                requirement=chiedi("head_mount"))

    out = resolve(g, mondo)
    assert "MOUNT_CROWDED" in out.report.codes()


# --------------------------------------------------------------------------- #
# Determinismo
# --------------------------------------------------------------------------- #
def test_the_same_plan_resolves_the_same_way_five_times(mondo):
    g = _umanoide(detail_level=3)
    g.swap("torso", "fish:fish_body")
    atteso = None
    for _ in range(5):
        out = resolve(g, mondo)
        firma = [(n.id, n.ref, n.link.parent_socket if n.link else "")
                 for n in out.walk()]
        atteso = atteso if atteso is not None else firma
        assert firma == atteso


def test_two_independent_registries_give_the_same_result():
    """Stesso vocabolario, oggetti diversi, stesso risultato."""
    uno, due = Registry(), Registry()
    uno.load_directory(INTERNI)
    due.load_directory(INTERNI)
    g = _umanoide(detail_level=3)
    g.swap("testa", "creature:dragon_head")

    primo, secondo = resolve(g, uno), resolve(g, due)
    assert primo.refs() == secondo.refs()
    assert primo.to_dict() == secondo.to_dict()


def test_the_resolved_graph_survives_a_dictionary(mondo):
    g = _umanoide()
    g.swap("testa", "creature:frog_head")
    dati = resolve(g, mondo).to_dict()

    assert dati["root"]["id"] == "corpo"
    testa = dati["root"]["children"][0]["children"][0]
    assert testa["ref"] == "creature:frog_head" and testa["was"] == "humanoid:head"
    assert testa["link"]["socket"] == "collo"


# --------------------------------------------------------------------------- #
# Confini
# --------------------------------------------------------------------------- #
def test_the_resolver_never_names_a_thing_of_the_world():
    """Se comparisse `if plugin == "humanoid"`, l'architettura sarebbe finita."""
    proibite = ("humanoid", "umanoid", "animal", "animale", "fish", "pesce",
                "dragon", "drago", "house", "casa", "planet", "pianeta",
                "vehicle", "veicolo", "weapon", "arma", "tree", "albero",
                "frog", "rana", "robot")
    for file in ("resolver.py", "resolved.py"):
        testo = (Path(__file__).resolve().parent.parent / "app" / "core"
                 / file).read_text(encoding="utf-8").lower()
        codice = "\n".join(r for r in testo.splitlines()
                           if not r.strip().startswith("#"))
        for parola in proibite:
            assert "'%s'" % parola not in codice and '"%s"' % parola not in codice, \
                "%s nomina %s" % (file, parola)


def test_the_resolver_builds_no_geometry(mondo):
    """Nessuna mesh, nessuna coordinata: quelle nascono nel builder."""
    out = resolve(_umanoide(detail_level=3), mondo)
    for nodo in out.walk():
        assert not hasattr(nodo, "mesh")
        assert nodo.link is None or not hasattr(nodo.link, "transform")


def test_the_resolver_keeps_the_scale_mode_without_applying_it(mondo):
    """La scala vera dipende dal raggio del socket, che qui non esiste ancora."""
    g = _umanoide()
    g.swap("testa", "creature:dragon_head", scale_mode="socket")
    out = resolve(g, mondo)
    assert out.node("testa").link.scale_mode == "socket"


def test_a_replacement_keeps_its_own_measures_unless_asked(mondo):
    """Una spada al posto di una gamba e' lunga quanto una spada.

    Portarla al raggio dell'innesto la scalerebbe finche' la sua sezione non
    riempie l'anca: per un pezzo lungo e sottile vuol dire moltiplicarne la
    lunghezza per sette.
    """
    g = _umanoide()
    g.add_child("gamba_l", "humanoid:leg", "torso",
                requirement=chiedi("limb_mount", side="l", tags=frozenset({"basso"})))
    g.swap("gamba_l", "weapon:sword")
    assert resolve(g, mondo).node("gamba_l").link.scale_mode == "none"


def test_the_resolver_does_not_apply_effects(mondo):
    """Gli effetti si raccolgono, non si eseguono: e' il passo dopo."""
    g = _umanoide()
    g.effect("una_deformazione", scope="model", amount=0.7)

    out = resolve(g, mondo)
    assert [tipo.type for _, tipo in out.effects] == ["una_deformazione"]
    assert out.node("corpo").values["height"] == 1.8, "nessun valore alterato"


def test_a_resolver_can_be_reused_for_two_plans(mondo):
    resolver = Resolver(mondo, budget=Budget(nodes=1000))
    primo = resolver.run(_umanoide())
    g = CompositionGraph()
    g.set_root("casa", "architecture:house")
    secondo = resolver.run(g)
    assert primo.ok and secondo.ok


# --------------------------------------------------------------------------- #
# `on`: indirizzare una parte che il piano non nomina
# --------------------------------------------------------------------------- #
def test_on_path_attaches_to_a_declared_part_without_duplicating_it(mondo):
    """`on="testa/naso"` con `detail_level = 1`: un naso solo, un piercing solo.

    E' il caso che rende `on` necessario. Il naso della testa compare al livello
    3; il piano ne vuole uno solo, e non vuole rimetterlo — rimetterlo vorrebbe
    dire sostituirlo, e riscriverne i parametri a mano.
    """
    g = CompositionGraph(detail_level=1)
    g.set_root("corpo", "humanoid:body", height=1.8)
    g.add_child("torso", "humanoid:torso", "corpo", requirement=chiedi("core_mount"),
                level=1)
    g.add_child("testa", "humanoid:head", "torso", requirement=chiedi("head_mount"),
                level=1)
    g.attach("piercing", "accessories:piercing", on="testa/naso",
             requirement=chiedi("anchor"))

    out = resolve(g, mondo)
    assert out.ok, out.report.describe()
    assert [n.ref for n in out.walk()].count("humanoid:nose") == 1
    assert [n.ref for n in out.walk()].count("accessories:piercing") == 1
    assert out.node("piercing").link.parent == "testa/naso"
    assert out.node("piercing").path == "corpo/torso/testa/naso/piercing"


def test_on_path_opens_a_corridor_and_not_the_whole_face(mondo):
    """Il naso entra sotto il suo livello; occhi, bocca e orecchie no."""
    g = CompositionGraph(detail_level=1)
    g.set_root("corpo", "humanoid:body", height=1.8)
    g.add_child("torso", "humanoid:torso", "corpo", requirement=chiedi("core_mount"),
                level=1)
    g.add_child("testa", "humanoid:head", "torso", requirement=chiedi("head_mount"),
                level=1)
    g.attach("piercing", "accessories:piercing", on="testa/naso",
             requirement=chiedi("anchor"))

    riferimenti = [n.ref for n in resolve(g, mondo).walk()]
    assert "humanoid:nose" in riferimenti
    assert "humanoid:eye" not in riferimenti
    assert "humanoid:mouth" not in riferimenti


def test_on_path_keeps_the_parameters_the_parent_declared(mondo):
    """Il naso resta quello della testa: misure derivate, non riscritte.

    E' la ragione per cui `on` non e' zucchero sintattico. Rimettere il naso nel
    piano lo farebbe ripartire dai propri predefiniti, e nessuno se ne
    accorgerebbe finche' non lo guarda.
    """
    g = CompositionGraph(detail_level=1)
    g.set_root("corpo", "humanoid:body", height=1.8)
    g.add_child("torso", "humanoid:torso", "corpo", requirement=chiedi("core_mount"),
                level=1)
    g.add_child("testa", "humanoid:head", "torso", requirement=chiedi("head_mount"),
                level=1)
    g.attach("piercing", "accessories:piercing", on="testa/naso",
             requirement=chiedi("anchor"))

    out = resolve(g, mondo)
    naso = out.node("testa/naso")
    testa = out.node("testa")
    assert naso.values["size"] == pytest.approx(testa.values["girth"] * 0.24)


def test_on_path_can_also_address_a_node_of_the_plan(mondo):
    """Un percorso e' un percorso: non distingue chi ha dichiarato cosa."""
    g = _umanoide()
    g.attach("mascherina", "accessories:mask", on="testa",
             requirement=chiedi("face_mount"))

    out = resolve(g, mondo)
    assert out.ok, out.report.describe()
    assert out.node("mascherina").link.parent == "testa"


def test_a_deferred_attachment_can_carry_another_one(mondo):
    """Un casco sui capelli dichiarati, e un'ala sul casco: due rinvii annidati.

    Il secondo bersaglio non esiste finche' il primo non si e' attaccato. Un
    solo giro lo lascerebbe fuori, e il pezzo sparirebbe senza una diagnosi.
    """
    g = CompositionGraph(detail_level=1)
    g.set_root("corpo", "humanoid:body", height=1.8)
    g.add_child("torso", "humanoid:torso", "corpo", requirement=chiedi("core_mount"),
                level=1)
    g.add_child("testa", "humanoid:head", "torso", requirement=chiedi("head_mount"),
                level=1)
    g.attach("casco", "accessories:helmet", on="testa/capelli",
             requirement=chiedi("gear_mount"), scale_mode="socket")
    g.attach("ala", "fish:fin", on="capelli/casco",
             requirement=chiedi("gear_mount"), scale_mode="socket")

    out = resolve(g, mondo)
    assert out.ok, out.report.describe()
    assert out.node("casco").link.parent == "testa/capelli"
    assert out.node("ala").link.parent == "casco"


def test_an_unreachable_on_path_is_reported_with_the_real_ones(mondo):
    """Un percorso che non esiste non inventa un nodo: si riferisce."""
    g = _umanoide()
    g.attach("anellino", "accessories:piercing", on="testa/proboscide",
             requirement=chiedi("anchor"))

    out = resolve(g, mondo)
    assert "ON_TARGET_MISSING" in out.report.codes()
    voce = [d for d in out.report if d.code == "ON_TARGET_MISSING"][0]
    assert voce.alternatives, "le alternative dicono quali percorsi esistono"
    assert "anellino" in out.unresolved


def test_two_parts_with_the_same_path_are_not_guessed(mondo):
    """Due nasi: si dice che sono due, non se ne sceglie uno."""
    g = CompositionGraph(detail_level=3)
    g.set_root("corpo", "humanoid:body", height=1.8)
    g.add_child("torso", "humanoid:torso", "corpo", requirement=chiedi("core_mount"))
    g.add_child("testa", "humanoid:head", "torso", requirement=chiedi("head_mount"))
    g.add_child("testa2", "humanoid:head", "torso", requirement=chiedi("head_mount"))
    g.attach("anellino", "accessories:piercing", on="naso",
             requirement=chiedi("anchor"))

    out = resolve(g, mondo)
    assert "ON_TARGET_AMBIGUOUS" in out.report.codes()


def test_a_path_survives_a_round_trip_through_json(mondo):
    g = CompositionGraph(detail_level=1)
    g.set_root("corpo", "humanoid:body", height=1.8)
    g.add_child("torso", "humanoid:torso", "corpo", requirement=chiedi("core_mount"),
                level=1)
    g.add_child("testa", "humanoid:head", "torso", requirement=chiedi("head_mount"),
                level=1)
    g.attach("piercing", "accessories:piercing", on="testa/naso",
             requirement=chiedi("anchor"))

    ritorno = CompositionGraph.from_dict(g.to_dict())
    out = resolve(ritorno, mondo)
    assert out.ok, out.report.describe()
    assert out.node("piercing").link.parent == "testa/naso"


def test_an_attachment_declares_where_it_hangs_and_nothing_else():
    """`Attachment` non porta piu' un `parent`: la relazione la fanno i socket.

    Il campo c'era, e nessuno lo leggeva — ne' il resolver ne' il builder ne'
    un plugin. Un campo morto in un contratto non e' innocuo: promette una
    funzione che non esiste, e prima o poi qualcuno la usa.
    """
    campi = {c.name for c in dataclasses.fields(Attachment)}
    assert "parent" not in campi
    assert "on" in campi
