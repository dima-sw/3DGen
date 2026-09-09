"""Composition graph e budget: il piano, e quanto ci si puo' permettere.

Nessun componente di questi test rappresenta qualcosa del mondo. Si chiamano
`alfa`, `beta`, `gamma`: se il grafo funzionasse solo con umanoidi e case,
questi test non passerebbero, ed e' esattamente il punto.
"""
from __future__ import annotations

import pytest

from app.core.budget import (EXPANSIONS, NODES, SECONDS, TRIANGLES, Budget,
                             unlimited)
from app.core.capability import Requirement
from app.core.errors import Report
from app.core.graph import (FROM_OVERRIDE, CompositionGraph, EffectRequest,
                            GraphError)


def catena(profondita: int) -> CompositionGraph:
    """Una catena di nodi generici, profonda quanto si vuole."""
    g = CompositionGraph()
    g.set_root("n0", "prova:alfa")
    for i in range(1, profondita):
        g.add_child("n%d" % i, "prova:beta", "n%d" % (i - 1), size=1.0 / (i + 1))
    return g


# --------------------------------------------------------------------------- #
# Un solo tipo di nodo
# --------------------------------------------------------------------------- #
def test_there_is_one_kind_of_node():
    """Struttura e decorazione sono lo stesso tipo, montato diversamente."""
    g = CompositionGraph()
    radice = g.set_root("r", "prova:alfa")
    strutturale = g.add_child("s", "prova:beta", "r")
    decorativo = g.attach("d", "altrove:gamma", "r")

    assert type(radice) is type(strutturale) is type(decorativo)
    assert strutturale.attachment.structural
    assert not decorativo.attachment.structural


def test_the_three_operations_are_distinct_in_the_api():
    """add_child, attach e swap dicono cose diverse, e si vede nel registro."""
    g = CompositionGraph()
    g.set_root("r", "prova:alfa")
    g.add_child("s", "prova:beta", "r")
    g.attach("d", "altrove:gamma", "r")
    g.swap("s", "altrove:delta")
    g.override("r", size=2.0)

    fatte = [op.kind for op in g.operations]
    assert fatte == ["add_child", "add_child", "attach", "swap", "override"]


# --------------------------------------------------------------------------- #
# Test 1 della specifica: A -> B -> C, indirizzamento, override
# --------------------------------------------------------------------------- #
def test_a_three_level_graph_is_addressable_and_overridable():
    g = CompositionGraph()
    g.set_root("a", "prova:alfa")
    g.add_child("b", "prova:beta", "a")
    g.add_child("c", "prova:gamma", "b", size=1.0)

    assert g.path("c") == "a/b/c"
    assert g.node("c") is g.node("a/b/c"), "id e percorso sono due indirizzi dello stesso nodo"

    g.override("a/b/c", size=0.25, twist=0.5)
    assert g.node("c").overrides == {"size": 0.25, "twist": 0.5}

    assert g.validate().ok
    assert [n.id for n in g.walk()] == ["a", "b", "c"], "visita deterministica"


def test_the_walk_order_is_stable():
    g = CompositionGraph()
    g.set_root("r", "prova:alfa")
    for nome in ("zeta", "alfa", "mu"):
        g.add_child(nome, "prova:beta", "r")
    for _ in range(5):
        assert [n.id for n in g.walk()] == ["r", "zeta", "alfa", "mu"], \
            "ordine di inserimento, non alfabetico ne' casuale"


def test_a_duplicate_id_is_refused_at_once():
    g = CompositionGraph()
    g.set_root("r", "prova:alfa")
    with pytest.raises(GraphError, match="gia' usato"):
        g.add_child("r", "prova:beta", "r")


def test_attaching_to_a_missing_parent_is_refused():
    g = CompositionGraph()
    g.set_root("r", "prova:alfa")
    with pytest.raises(GraphError, match="inesistente"):
        g.add_child("x", "prova:beta", "non_esiste")


# --------------------------------------------------------------------------- #
# Test 2 della specifica: swap che non tocca il resto
# --------------------------------------------------------------------------- #
def test_a_swap_replaces_the_target_and_leaves_the_rest_alone():
    g = CompositionGraph()
    g.set_root("r", "prova:alfa")
    g.add_child("a", "prova:beta", "r")
    g.add_child("b", "prova:gamma", "a")
    g.add_child("c", "prova:delta", "r")

    g.swap("b", "altrove:esterno")

    assert g.resolved_ref("b") == "altrove:esterno"
    assert g.node("b").ref == "prova:gamma", "l'intenzione di partenza resta leggibile"
    assert g.parents["b"] == "a", "il padre non cambia"
    assert g.resolved_ref("c") == "prova:delta", "gli altri rami non si toccano"
    assert len(g.nodes) == 4, "nessun nodo duplicato"
    assert g.path("b") == "r/a/b", "l'indirizzo resta lo stesso"
    assert g.validate().ok


def test_a_swap_is_recorded_not_destructive():
    """Il piano deve restare leggibile: si vede cosa era e cosa e' diventato."""
    g = CompositionGraph()
    g.set_root("r", "prova:alfa")
    g.add_child("t", "prova:beta", "r")
    g.swap("t", "altrove:gamma")

    swap = [op for op in g.operations if op.kind == "swap"][0]
    assert swap.detail == {"from": "prova:beta", "to": "altrove:gamma"}
    assert "-> altrove:gamma" in g.describe().replace("  ", " ")


def test_a_swap_forgets_the_old_parameters():
    """I parametri del vecchio componente parlano un'altra lingua."""
    g = CompositionGraph()
    g.set_root("r", "prova:alfa")
    g.add_child("t", "prova:beta", "r", larghezza=3.0)
    g.swap("t", "altrove:gamma")
    assert g.node("t").overrides == {}


def test_a_swap_can_carry_its_own_parameters():
    g = CompositionGraph()
    g.set_root("r", "prova:alfa")
    g.add_child("t", "prova:beta", "r", larghezza=3.0)
    g.swap("t", "altrove:gamma", raggio=0.5)
    assert g.node("t").overrides == {"raggio": 0.5}


def test_a_swapped_node_has_exactly_one_provider():
    """Tracciabilita' nel piano, un solo componente nel risolto.

    Il nodo sostituito conserva il nome di partenza per chi legge, ma non deve
    mai finire nella geometria: due provider per un nodo vorrebbero dire due
    mesh dove ne serviva una.
    """
    g = CompositionGraph()
    g.set_root("r", "prova:alfa")
    g.add_child("t", "prova:beta", "r")
    prima = len(g)

    g.swap("t", "altrove:gamma")

    fornitori = g.providers()
    assert len(fornitori) == len(g) == prima, "uno swap non aggiunge nodi"
    assert fornitori["t"] == "altrove:gamma"
    assert "prova:beta" not in fornitori.values(), "il sostituito non si costruisce"
    assert g.swapped() == {"t": ("prova:beta", "altrove:gamma")}, "ma resta leggibile"


def test_wanting_both_components_is_an_attach_not_a_swap():
    """Chi vuole tutte e due le teste aggiunge un nodo: e' un'altra intenzione."""
    g = CompositionGraph()
    g.set_root("r", "prova:alfa")
    g.add_child("t", "prova:beta", "r")
    g.attach("t2", "altrove:gamma", "r")
    assert sorted(g.providers().values()) == ["altrove:gamma", "prova:alfa",
                                              "prova:beta"]


def test_a_second_swap_replaces_the_first():
    """Non si accumulano: resta comunque un provider solo."""
    g = CompositionGraph()
    g.set_root("r", "prova:alfa")
    g.add_child("t", "prova:beta", "r")
    g.swap("t", "altrove:gamma")
    g.swap("t", "altrove:delta")
    assert g.providers()["t"] == "altrove:delta"
    assert len(g.providers()) == 2
    assert [op.kind for op in g.operations].count("swap") == 2, "il registro tiene entrambe"


def test_swapping_a_missing_node_is_refused():
    g = CompositionGraph()
    g.set_root("r", "prova:alfa")
    with pytest.raises(GraphError, match="nessun nodo"):
        g.swap("fantasma", "altrove:x")


def test_a_swap_is_not_a_parameter_override():
    """Due intenzioni diverse, due operazioni diverse."""
    g = CompositionGraph()
    g.set_root("r", "prova:alfa")
    g.add_child("t", "prova:beta", "r")

    g.override("t", width=0.5)
    assert g.resolved_ref("t") == "prova:beta", "l'override non cambia il componente"

    g.swap("t", "altrove:gamma")
    assert g.resolved_ref("t") == "altrove:gamma"


# --------------------------------------------------------------------------- #
# Test 3 della specifica: il dettaglio non blocca una richiesta esplicita
# --------------------------------------------------------------------------- #
def test_an_explicit_attachment_ignores_the_detail_level():
    """«una parte semplice, ma con questo pezzo attaccato»."""
    g = CompositionGraph(detail_level=1)
    g.set_root("a", "prova:alfa")
    fine = g.add_child("b", "prova:beta", "a", level=3)
    g.add_child("c", "prova:gamma", "b", level=3)
    chiesto = g.attach("d", "altrove:delta", "b")

    assert not g.wanted(fine), "il dettaglio automatico si ferma al livello 1"
    assert g.wanted(chiesto), "cio' che e' stato chiesto entra lo stesso"
    assert g.path("d") == "a/b/d"


def test_detail_level_is_a_policy_not_a_depth_limit():
    """Con dettaglio alto si scende; con dettaglio basso i nodi esistono lo
    stesso nel piano, semplicemente non vengono voluti."""
    g = catena(6)
    for nodo in list(g.walk())[1:]:
        nodo.attachment.level = 2

    g.detail_level = 1
    assert sum(1 for n in g.walk() if g.wanted(n)) == 1
    g.detail_level = 2
    assert sum(1 for n in g.walk() if g.wanted(n)) == 6
    assert len(g) == 6, "il piano non cambia: cambia quanto se ne vuole"


def test_there_is_no_maximum_detail_level():
    g = catena(3)
    for livello in (1, 2, 5, 10, 40):
        g.detail_level = livello
        assert g.validate().ok


# --------------------------------------------------------------------------- #
# Test 4 della specifica: ricorsione profonda, senza limite semantico
# --------------------------------------------------------------------------- #
def test_arbitrary_nesting_has_no_semantic_limit():
    """A -> B -> C -> D -> E -> F, e oltre. Nessun MAX_DEPTH."""
    g = catena(6)
    assert [n.id for n in g.walk()] == ["n0", "n1", "n2", "n3", "n4", "n5"]
    assert g.path("n5") == "n0/n1/n2/n3/n4/n5"
    assert g.validate().ok


def test_nesting_of_twenty_levels_is_still_valid():
    g = catena(20)
    assert len(g) == 20
    assert g.validate().ok
    assert len(g.ancestors("n19")) == 19


def test_recursion_that_changes_something_is_legitimate():
    """Un componente dentro se stesso va bene se i parametri scendono."""
    g = CompositionGraph()
    g.set_root("ramo0", "prova:ramo", size=1.0)
    g.add_child("ramo1", "prova:ramo", "ramo0", size=0.5)
    g.add_child("ramo2", "prova:ramo", "ramo1", size=0.25)
    g.add_child("foglia", "prova:foglia", "ramo2")
    assert g.validate().ok, g.validate().describe()


def test_repetition_without_progress_is_flagged():
    """Stesso componente e stessi parametri dentro se stesso: non e' ricorsione."""
    g = CompositionGraph()
    g.set_root("x0", "prova:ramo", size=1.0)
    g.add_child("x1", "prova:ramo", "x0", size=1.0)
    report = g.validate()
    assert "RECURSION_WITHOUT_PROGRESS" in report.codes()
    assert report.ok, "e' un avviso, non un errore: il piano resta costruibile"


# --------------------------------------------------------------------------- #
# Test 5 della specifica: cicli
# --------------------------------------------------------------------------- #
def test_a_cycle_in_the_parent_chain_is_diagnosed():
    """A -> B -> C -> A."""
    g = CompositionGraph()
    g.set_root("a", "prova:alfa")
    g.add_child("b", "prova:beta", "a")
    g.add_child("c", "prova:gamma", "b")
    g.parents["a"] = "c"                    # il ciclo, forzato

    report = g.validate()
    assert "GRAPH_CYCLE" in report.codes()
    assert not report.ok


def test_path_and_ancestors_survive_a_cycle():
    """La diagnosi non deve dipendere da funzioni che si impiccano sul ciclo."""
    g = CompositionGraph()
    g.set_root("a", "prova:alfa")
    g.add_child("b", "prova:beta", "a")
    g.parents["a"] = "b"
    assert g.path("b")                       # non va in ricorsione infinita
    assert len(g.ancestors("b")) <= len(g.nodes)


def test_a_cycle_is_detected_on_references_not_on_categories():
    """La rilevazione guarda gli id, non che cosa i componenti rappresentino."""
    g = CompositionGraph()
    g.set_root("uno", "vocabolario_ignoto:cosa_a")
    g.add_child("due", "vocabolario_ignoto:cosa_b", "uno")
    g.parents["uno"] = "due"
    assert "GRAPH_CYCLE" in g.validate().codes()


# --------------------------------------------------------------------------- #
# Validazione strutturale
# --------------------------------------------------------------------------- #
def test_a_graph_without_a_root_is_invalid():
    assert "GRAPH_NO_ROOT" in CompositionGraph().validate().codes()


def test_a_node_without_a_reference_is_invalid():
    g = CompositionGraph()
    g.set_root("r", "prova:alfa")
    g.add_child("x", "prova:beta", "r")
    g.nodes["x"].ref = ""
    assert "NODE_NO_REF" in g.validate().codes()


def test_an_unqualified_reference_is_a_warning_not_an_error():
    """Manca il plugin: si puo' ancora tentare di risolverlo, ma va detto."""
    g = CompositionGraph()
    g.set_root("r", "alfa")
    report = g.validate()
    assert "REF_NOT_QUALIFIED" in report.codes() and report.ok


def test_a_missing_parent_is_diagnosed_with_alternatives():
    g = CompositionGraph()
    g.set_root("r", "prova:alfa")
    g.add_child("x", "prova:beta", "r")
    g.parents["x"] = "svanito"
    report = g.validate()
    assert "PARENT_MISSING" in report.codes()
    assert "r" in report.entries[0].alternatives


def test_an_unreachable_node_is_reported():
    g = CompositionGraph()
    g.set_root("r", "prova:alfa")
    g.add_child("x", "prova:beta", "r")
    g.order["r"] = []                        # scollegato dalla visita
    assert "NODE_UNREACHABLE" in g.validate().codes()


def test_graph_validation_does_not_check_compatibility():
    """Compatibilita' e' del resolver: qui si guarda solo se il grafo sta in piedi.

    Tenerle separate significa che un errore di struttura non viene mascherato
    da un errore di socket, e viceversa.
    """
    g = CompositionGraph()
    g.set_root("r", "plugin_che_non_esiste:componente_immaginario")
    g.add_child("x", "un_altro:pezzo", "r",
                requirement=Requirement(capability="capacita_mai_vista"))
    assert g.validate().ok, "il grafo e' valido; sara' il resolver a dire di no"


# --------------------------------------------------------------------------- #
# Provenienza e effetti
# --------------------------------------------------------------------------- #
def test_an_override_keeps_its_provenance():
    """Non un sistema di ereditarieta': la memoria di chi ha deciso un numero."""
    g = CompositionGraph()
    g.set_root("r", "prova:alfa")
    g.override("r", width=0.5)
    assert g.node("r").overrides["width"] == 0.5
    assert FROM_OVERRIDE == "override"


def test_effects_are_recorded_not_interpreted():
    """Il graph non sa cosa voglia dire 'lanky'. Lo registra e basta."""
    g = CompositionGraph()
    g.set_root("r", "prova:alfa")
    g.effect("una_deformazione_qualsiasi", scope="role:qualcosa", amount=0.6, axis="X")
    effetto = g.node("r").effects[0]
    assert isinstance(effetto, EffectRequest)
    assert effetto.type == "una_deformazione_qualsiasi"
    assert effetto.params == {"axis": "X"} and effetto.amount == 0.6


def test_effects_can_target_a_specific_node():
    g = CompositionGraph()
    g.set_root("r", "prova:alfa")
    g.add_child("x", "prova:beta", "r")
    g.effect("piega", scope="part:x", target="x", amount=0.3)
    assert not g.node("r").effects and len(g.node("x").effects) == 1


# --------------------------------------------------------------------------- #
# JSON
# --------------------------------------------------------------------------- #
def test_a_graph_survives_a_round_trip():
    g = CompositionGraph(style="low_poly", detail_level=3, seed=99)
    g.set_root("r", "prova:alfa", height=1.8)
    g.add_child("a", "prova:beta", "r", requirement=Requirement(capability="mount"))
    g.attach("d", "altrove:gamma", "a")
    g.swap("a", "altrove:delta")
    g.effect("qualcosa", scope="model", amount=0.9)

    ricostruito = CompositionGraph.from_dict(g.to_dict())
    assert ricostruito.detail_level == 3 and ricostruito.seed == 99
    assert [n.id for n in ricostruito.walk()] == [n.id for n in g.walk()]
    assert ricostruito.resolved_ref("a") == "altrove:delta"
    assert ricostruito.node("d").attachment.on_request
    assert ricostruito.node("r").effects[0].type == "qualcosa"
    assert ricostruito.node("r").overrides == {"height": 1.8}


def test_the_json_is_readable_by_a_human():
    g = CompositionGraph()
    g.set_root("corpo", "prova:alfa")
    g.attach("ciondolo", "altrove:beta", "corpo",
             requirement=Requirement(capability="anchor"))
    dati = g.to_dict()
    assert dati["root"]["id"] == "corpo"
    figlio = dati["root"]["children"][0]
    assert figlio["at"] == {"capability": "anchor"}
    assert figlio["on_request"] is True and figlio["scale_mode"] == "socket"


# --------------------------------------------------------------------------- #
# Budget
# --------------------------------------------------------------------------- #
def test_a_budget_without_limits_is_valid():
    b = unlimited()
    assert b.ok and b.remaining(TRIANGLES) is None
    assert b.spend(TRIANGLES, 10**9)


def test_spending_consumes_and_then_stops():
    b = Budget(triangles=1000)
    assert b.spend(TRIANGLES, 600, where="a")
    assert b.remaining(TRIANGLES) == 400
    assert not b.spend(TRIANGLES, 500, where="a/b")
    assert b.exhausted() == TRIANGLES


def test_a_spend_that_fits_exactly_is_accepted():
    """Chi chiama paga prima di costruire: l'ultimo pezzo che ci sta va tenuto.

    Se `spend` rispondesse "dopo di te non resta niente", il pezzo pagato
    verrebbe scartato e ogni budget renderebbe uno meno del suo tetto.
    """
    b = Budget(nodes=3)
    assert [b.spend(NODES, 1) for _ in range(3)] == [True, True, True]
    assert not b.spend(NODES, 1), "il quarto no: sfora"
    assert b.exhausted() == NODES, "esaurito comunque: margine finito"


def test_the_budget_remembers_where_it_stopped():
    b = Budget(triangles=100)
    b.spend(TRIANGLES, 50, where="testa")
    b.spend(TRIANGLES, 80, where="testa/capelli")
    assert b.stopped_at == "testa/capelli" and b.stopped_on == TRIANGLES


def test_afford_asks_without_spending():
    b = Budget(nodes=3)
    assert b.afford(NODES, 3) and not b.afford(NODES, 4)
    assert b.used(NODES) == 0


@pytest.mark.parametrize("tipo,tetto,spesa", [
    (TRIANGLES, 100, 200), (NODES, 5, 9), (EXPANSIONS, 2, 3),
])
def test_every_limit_can_stop_the_expansion(tipo, tetto, spesa):
    b = Budget(**{{"triangoli": "triangles", "nodi": "nodes",
                   "espansioni": "expansions"}[tipo]: tetto})
    b.spend(tipo, spesa, where="x")
    assert b.exhausted() == tipo


def test_time_is_a_limit_too():
    b = Budget(seconds=0.0)
    assert b.exhausted() == SECONDS, "un tetto di zero secondi e' gia' superato"


def test_the_exhausted_limit_is_reported_in_order():
    """Se se ne superano due, si nomina sempre lo stesso: la diagnosi non balla."""
    b = Budget(triangles=1, nodes=1)
    b.spend(TRIANGLES, 5)
    b.spend(NODES, 5)
    for _ in range(5):
        assert b.exhausted() == TRIANGLES


def test_a_subtree_gets_a_share_not_the_whole_budget():
    padre = Budget(triangles=8000, nodes=100)
    figlio = padre.share(0.25, "testa")
    assert figlio.triangles == 2000 and figlio.nodes == 25


def test_a_share_never_exceeds_what_is_left():
    padre = Budget(triangles=8000)
    padre.spend(TRIANGLES, 7000)
    assert padre.share(1.0).triangles == 1000


def test_a_share_does_not_get_its_own_clock():
    """Il tempo scorre per tutti: frazionarlo darebbe scadenze senza senso."""
    padre = Budget(seconds=10.0)
    figlio = padre.share(0.5)
    assert figlio.seconds is not None and figlio.started == padre.started


def test_what_a_subtree_spends_comes_back_to_the_parent():
    padre = Budget(triangles=1000)
    figlio = padre.share(0.5, "ramo")
    figlio.spend(TRIANGLES, 400, where="ramo/foglia")
    padre.absorb(figlio)
    assert padre.used(TRIANGLES) == 400


def test_a_subtree_that_ran_out_says_so_to_the_parent():
    padre = Budget(triangles=1000)
    figlio = padre.share(0.2, "ramo")
    figlio.spend(TRIANGLES, 500, where="ramo/foglia")
    padre.absorb(figlio)
    assert padre.stopped_at == "ramo/foglia"


def test_exceeding_the_budget_is_a_diagnosis_not_a_failure():
    """Il §16 della specifica: cosa si voleva, quanto c'era, dove ci si e' fermati."""
    report = Report()
    b = Budget(triangles=3000)
    b.spend(TRIANGLES, 4200, where="testa/capelli")
    b.report_to(report, detail_level=5)

    voce = report.entries[0]
    assert voce.code == "BUDGET_EXCEEDED"
    assert voce.where == "testa/capelli"
    assert "3000" in voce.why and "4200" in voce.why and "5" in voce.why
    assert report.ok, "un budget finito non invalida il modello, lo limita"


def test_a_budget_that_held_says_nothing():
    report = Report()
    b = Budget(triangles=3000)
    b.spend(TRIANGLES, 100)
    b.report_to(report)
    assert not report.entries


# --------------------------------------------------------------------------- #
# Budget e dettaglio sono cose diverse
# --------------------------------------------------------------------------- #
def test_detail_and_budget_stop_for_different_reasons():
    """Dettaglio 10 con budget stretto si ferma sul budget, non sul dettaglio.

    E' la distinzione che impedisce di scrivere `max_depth = detail_level`, che
    smette di scendere quando ci sarebbe spazio e non smette quando non ce n'e'.
    """
    g = catena(10)
    g.detail_level = 10
    b = Budget(nodes=4)

    costruiti = []
    for nodo in g.walk():
        if not g.wanted(nodo):
            continue
        if not b.spend(NODES, 1, where=g.path(nodo.id)):
            break
        costruiti.append(nodo.id)

    assert len(costruiti) == 4, "si e' fermato sul budget"
    assert g.detail_level == 10, "il dettaglio chiesto resta quello"
    assert b.stopped_on == NODES


def test_a_generous_budget_stops_on_the_structure():
    """Non c'e' altro da espandere: ci si ferma, e non e' un errore."""
    g = catena(3)
    g.detail_level = 99
    b = Budget(nodes=1000)
    costruiti = [n.id for n in g.walk() if g.wanted(n) and b.spend(NODES, 1)]
    assert len(costruiti) == 3 and b.ok
