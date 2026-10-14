"""Il registry: che cosa esiste, e niente altro.

I plugin usati qui stanno in `tests/plugins/` e sono deliberatamente privi di
significato — `alfa`, `beta`, `zeta`, piu' un plugin "di terze parti" che parla
di blob quantistici. Se il registry funzionasse solo con vocabolari che il core
conosce, questi test non passerebbero.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.core.capability import Capability, mount
from app.core.component import BuildContext, Component, Piece
from app.core.registry import Registry, RegistryError, load
from app.core.vocabulary import EffectSpec, StyleProfile

QUI = Path(__file__).resolve().parent
ECOSISTEMA = QUI / "plugins" / "ecosistema"
TERZE_PARTI = QUI / "plugins" / "terze_parti"
MALFATTI = QUI / "plugins" / "malfatti"
INTERNI = QUI.parent / "app" / "plugins"


def _niente(v, ctx):
    return Piece(mesh=None)


def componente(id: str, **kwargs) -> Component:
    return Component(id=id, build=_niente, **kwargs)


@pytest.fixture
def ecosistema() -> Registry:
    r = Registry()
    r.load_directory(ECOSISTEMA)
    return r


@pytest.fixture
def esterno() -> Registry:
    r = Registry()
    r.load_directory(TERZE_PARTI)
    return r


# --------------------------------------------------------------------------- #
# Registrazione a mano
# --------------------------------------------------------------------------- #
def test_a_component_is_registered_and_found_again():
    r = Registry()
    assert r.register_component(componente("prova:pezzo"))
    assert r.component("prova:pezzo") is not None
    assert len(r) == 1 and "prova:pezzo" in r


def test_an_unqualified_id_is_qualified_by_the_plugin():
    r = Registry()
    r.register_component(componente("pezzo"), plugin_id="prova")
    assert r.component("prova:pezzo") is not None
    assert r.component("pezzo") is not None, "il nome nudo basta se non e' ambiguo"


def test_a_component_cannot_squat_another_plugins_namespace():
    r = Registry()
    assert not r.register_component(componente("altro:pezzo"), plugin_id="prova")
    assert "COMPONENT_ID_MISMATCH" in r.report.codes()
    assert len(r) == 0


def test_the_same_qualified_id_cannot_be_registered_twice():
    r = Registry()
    r.register_component(componente("prova:pezzo"))
    assert not r.register_component(componente("prova:pezzo"))
    assert "DUPLICATE_COMPONENT" in r.report.codes()
    assert len(r) == 1


def test_the_same_local_name_in_two_plugins_is_legitimate(ecosistema):
    """`alfa:nodo` e `beta:nodo` sono due cose diverse, e va bene cosi'."""
    assert ecosistema.component("alfa:nodo") is not None
    assert ecosistema.component("beta:nodo") is not None
    assert [c.id for c in ecosistema.named("nodo")] == ["alfa:nodo", "beta:nodo"]


def test_an_ambiguous_bare_name_resolves_to_nothing(ecosistema):
    """Meglio niente che il primo che capita: sceglierne uno sarebbe arbitrario."""
    assert ecosistema.component("nodo") is None
    assert ecosistema.component("foglia") is not None, "questo invece e' unico"


# --------------------------------------------------------------------------- #
# Scoperta
# --------------------------------------------------------------------------- #
def test_a_directory_of_plugins_is_discovered(ecosistema):
    assert [p.id for p in ecosistema.plugins()] == ["alfa", "beta", "zeta"]


def test_the_manifest_is_read_whole(ecosistema):
    alfa = ecosistema.plugin("alfa")
    assert alfa.version == "1.0.0" and alfa.name == "Alfa"
    assert alfa.author == "suite di test"
    assert alfa.tags == frozenset({"prova"})
    assert alfa.metadata == {"nota": "esiste solo per i test"}


def test_a_broken_plugin_does_not_stop_the_others(ecosistema):
    """`guasto` ed `esplosivo` stanno in mezzo, in ordine alfabetico."""
    codici = ecosistema.report.codes()
    assert "INVALID_MANIFEST" in codici, "manifest illeggibile"
    assert "PLUGIN_LOAD_FAILED" in codici, "modulo che esplode"
    assert {"alfa", "beta", "zeta"} <= set(p.id for p in ecosistema.plugins())
    assert "guasto" not in [p.id for p in ecosistema.plugins()]
    assert "esplosivo" not in [p.id for p in ecosistema.plugins()]


def test_a_plugin_that_fails_halfway_leaves_nothing_behind(ecosistema):
    """Mezzo vocabolario registrato sarebbe peggio di nessun vocabolario."""
    assert ecosistema.plugin("esplosivo") is None
    assert not [c for c in ecosistema.components() if c.plugin == "esplosivo"]


def test_a_directory_that_is_not_a_plugin_is_not_an_error():
    r = Registry()
    r.load_directory(QUI / "plugins")     # contiene solo sottocartelle
    assert not r.report.errors(), r.report.describe()
    assert len(r) == 0


def test_a_missing_directory_is_reported():
    r = Registry()
    r.load_directory(QUI / "non_esiste_affatto")
    assert "PLUGIN_DIR_MISSING" in r.report.codes()


def test_a_directory_that_is_itself_a_plugin_is_loaded():
    r = Registry()
    r.load_directory(ECOSISTEMA / "alfa")
    assert [p.id for p in r.plugins()] == ["alfa"]


def test_a_manifest_without_version_is_refused():
    r = Registry()
    r.load_plugin(MALFATTI / "senza_versione")
    assert "INVALID_MANIFEST" in r.report.codes()


def test_a_declared_file_that_is_missing_refuses_the_plugin():
    r = Registry()
    r.load_plugin(MALFATTI / "file_mancante")
    assert "MISSING_COMPONENT_FILE" in r.report.codes()
    assert r.plugin("file_mancante") is None


def test_malformed_dependencies_refuse_the_plugin():
    r = Registry()
    r.load_plugin(MALFATTI / "dipendenza_malformata")
    assert "INVALID_DEPENDENCY" in r.report.codes()
    assert r.plugin("dipendenza_malformata") is None


def test_a_plugin_that_registers_in_another_namespace_keeps_its_own_parts():
    """L'intruso viene respinto, il componente legittimo no."""
    r = Registry()
    r.load_plugin(MALFATTI / "id_altrui")
    assert "COMPONENT_ID_MISMATCH" in r.report.codes()
    assert "DUPLICATE_COMPONENT" in r.report.codes()
    assert [c.id for c in r.components()] == ["id_altrui:mio"]


def test_two_plugins_with_the_same_id_are_not_both_loaded():
    r = Registry()
    r.load_plugin(ECOSISTEMA / "alfa")
    r._paths["alfa"] = "un/altro/posto"        # simula una seconda installazione
    r.load_plugin(ECOSISTEMA / "alfa")
    assert "DUPLICATE_PLUGIN" in r.report.codes()


def test_a_missing_manifest_is_reported():
    r = Registry()
    r.load_plugin(QUI)
    assert "MANIFEST_MISSING" in r.report.codes()


# --------------------------------------------------------------------------- #
# Plugin interni
# --------------------------------------------------------------------------- #
def test_the_internal_plugins_load_from_the_application_tree():
    r = Registry()
    r.load_directory(INTERNI)
    assert not r.report.errors(), r.report.describe()
    assert r.component("primitives:block") is not None
    assert r.component("primitives:tube") is not None


def test_an_internal_component_actually_builds():
    """Il registry non costruisce niente, ma cio' che indicizza deve costruire."""
    from app.core.params import resolve

    r = Registry()
    r.load_directory(INTERNI)
    blocco = r.component("primitives:block")
    pezzo = blocco.build(resolve(blocco.params, {"length": 2.0}), BuildContext())
    assert pezzo.mesh is not None and pezzo.triangles > 0
    assert pezzo.mesh.bounds[0][0] == pytest.approx(0.0), "la base sta all'origine"
    assert "base" in pezzo.sockets and "tip" in pezzo.sockets


def test_declared_mounts_match_the_sockets_that_get_built():
    """La dichiarazione serve a indicizzare a freddo: deve dire la verita'."""
    from app.core.params import resolve

    r = Registry()
    r.load_directory(INTERNI)
    for componente_ in r.components(plugin="primitives"):
        pezzo = componente_.build(resolve(componente_.params), BuildContext())
        dichiarati = {m.socket_id for m in componente_.mounts if m.socket_id}
        assert dichiarati <= set(pezzo.sockets), componente_.id


# --------------------------------------------------------------------------- #
# Capability
# --------------------------------------------------------------------------- #
def test_a_capability_can_have_several_providers(ecosistema):
    """Il registry elenca. Non sceglie."""
    trovati = [c.id for c in ecosistema.providers(capability="innesto_generico")]
    assert trovati == ["alfa:foglia", "alfa:nodo", "beta:nodo", "zeta:pezzo"]


def test_providers_covers_both_being_and_accepting(ecosistema):
    """Un componente serve una capability se la e' oppure se la accetta.

    Chi cerca non sa in anticipo quale dei due casi gli serve: e' proprio
    l'informazione che sta cercando.
    """
    fornitori = {c.id for c in ecosistema.providers(capability="innesto_generico")}
    assert "alfa:foglia" in fornitori, "la fornisce"
    assert "alfa:nodo" in fornitori, "la accetta"


def test_socket_providers_is_the_narrow_query(ecosistema):
    trovati = [c.id for c in ecosistema.socket_providers("innesto_generico")]
    assert trovati == ["alfa:nodo", "beta:nodo"]


def test_the_side_filters_the_mounts(ecosistema):
    assert [c.id for c in ecosistema.socket_providers("innesto_generico", side="l")] \
        == ["alfa:nodo"]
    assert [c.id for c in ecosistema.socket_providers("innesto_generico", side="r")] \
        == ["beta:nodo"]


def test_an_unsided_mount_answers_any_side():
    """Disponibilita', non scelta: un innesto senza lato va bene per entrambi."""
    r = Registry()
    r.register_component(componente("prova:ambidestro",
                                    mounts=(mount("innesto"),)))
    assert r.socket_providers("innesto", side="l")
    assert r.socket_providers("innesto", side="r")


def test_capabilities_are_listed_whether_declared_or_merely_used(ecosistema):
    nomi = ecosistema.capabilities()
    assert "innesto_generico" in nomi, "dichiarata nel manifest di alfa"
    assert "cosa_beta" in nomi, "mai dichiarata, solo usata da un componente"


def test_a_capability_says_who_offers_it_and_who_takes_it(ecosistema):
    info = ecosistema.capability("innesto_generico")
    assert info.providers == ("alfa:foglia", "zeta:pezzo")
    assert info.mounts == ("alfa:nodo", "beta:nodo")
    assert info.description == "un attacco senza pretese"
    assert info.plugins == ("alfa", "beta", "zeta")


def test_an_unknown_capability_answers_without_failing(ecosistema):
    info = ecosistema.capability("cosa_che_non_esiste")
    assert not info.known and info.providers == ()


def test_tags_filter_components(ecosistema):
    assert [c.id for c in ecosistema.components(tags={"beta"})] == ["beta:nodo"]
    assert len(ecosistema.components(tags={"prova"})) == 4


def test_there_is_no_query_by_world_category(ecosistema):
    """Nessun `find_animals`. I tag sono dati, non metodi."""
    for proibito in ("find_animals", "find_humanoids", "find_vehicles",
                     "humanoids", "animals", "buildings"):
        assert not hasattr(ecosistema, proibito)


# --------------------------------------------------------------------------- #
# Effetti e stili
# --------------------------------------------------------------------------- #
def test_effects_are_registered_with_the_components(ecosistema):
    assert ecosistema.effect("alfa:allunga") is not None
    assert ecosistema.effect("allunga") is not None, "nome nudo, non ambiguo"


def test_effects_can_be_filtered_by_scope(ecosistema):
    modello = [e.id for e in ecosistema.effects(scope="model")]
    assert modello == ["alfa:allunga"]
    assert len(ecosistema.effects(scope="part")) == 2


def test_a_scope_with_a_target_still_matches(ecosistema):
    assert ecosistema.effect("alfa:allunga").fits_scope("part:qualcosa")


def test_effects_for_a_capability(ecosistema):
    per_alfa = [e.id for e in ecosistema.effects_for(capability="cosa_alfa")]
    assert per_alfa == ["alfa:allunga", "alfa:solo_su_alfa"]
    altrove = [e.id for e in ecosistema.effects_for(capability="cosa_beta")]
    assert altrove == ["alfa:allunga"], "chi non dichiara vincoli vale ovunque"


def test_styles_are_registered_and_looked_up(ecosistema):
    stile = ecosistema.style("spigoloso")
    assert stile is not None and stile.get("lati") == 4
    assert stile.plugin == "alfa"


def test_more_styles_can_coexist():
    r = load([ECOSISTEMA, TERZE_PARTI])
    assert [s.id for s in r.styles()] == ["alfa:spigoloso",
                                          "external_test_plugin:cristallino"]


def test_a_style_can_be_registered_by_hand():
    r = Registry()
    assert r.register_style(StyleProfile(id="prova:anime",
                                         params={"contorni": True}))
    assert r.style("prova:anime").get("contorni") is True


def test_a_style_carries_numbers_the_core_does_not_read():
    """Il core garantisce identita' e ricerca, non il significato dei numeri."""
    r = Registry()
    r.register_style(StyleProfile(id="x:strano",
                                  params={"una_cosa_mai_vista": [1, 2, 3]}))
    assert r.style("x:strano").get("una_cosa_mai_vista") == [1, 2, 3]


def test_an_effect_can_be_registered_by_hand():
    r = Registry()
    assert r.register_effect(EffectSpec(id="prova:piega"))
    assert not r.register_effect(EffectSpec(id="prova:piega"))
    assert "DUPLICATE_EFFECT" in r.report.codes()


# --------------------------------------------------------------------------- #
# Ricerca
# --------------------------------------------------------------------------- #
def test_search_finds_by_id(ecosistema):
    assert [c.id for c in ecosistema.search("nodo")] == ["alfa:nodo", "beta:nodo"]


def test_search_finds_by_description(ecosistema):
    trovati = [c.id for c in ecosistema.search("innesto generico")]
    assert "alfa:foglia" in trovati and "zeta:pezzo" in trovati


def test_search_ranks_by_how_many_words_match(ecosistema):
    """Nessun NLP: si contano le parole, e a pari punteggio decide l'id."""
    trovati = [c.id for c in ecosistema.search("nodo innesto generico")]
    assert trovati[0] == "alfa:nodo", "e' l'unico che le contiene tutte e tre"


def test_search_finds_by_tag(ecosistema):
    assert [c.id for c in ecosistema.search(tags={"zeta"})] == ["zeta:pezzo"]


def test_search_finds_by_capability(ecosistema):
    trovati = [c.id for c in ecosistema.search(capability="cosa_beta")]
    assert trovati == ["beta:nodo"]


def test_search_ignores_word_separators(ecosistema):
    """Chi cerca 'innesto' deve trovare anche `innesto_generico`."""
    assert ecosistema.search("innesto")


def test_search_without_arguments_lists_everything(ecosistema):
    assert len(ecosistema.search()) == len(ecosistema.components())


def test_search_can_be_capped(ecosistema):
    assert len(ecosistema.search("nodo", limit=1)) == 1


# --------------------------------------------------------------------------- #
# Dipendenze
# --------------------------------------------------------------------------- #
def test_dependencies_are_kept(ecosistema):
    assert ecosistema.dependencies("zeta") == ("alfa",)
    assert ecosistema.dependencies("alfa") == ()


def test_a_satisfied_dependency_says_nothing(ecosistema):
    assert "DEPENDENCY_MISSING" not in ecosistema.report.codes()
    assert ecosistema.missing_dependencies() == {}


def test_an_unsatisfied_dependency_is_a_warning_not_a_rejection():
    """Il plugin si carica lo stesso: sara' il resolver a spiegare cosa manca."""
    r = Registry()
    r.load_plugin(ECOSISTEMA / "zeta")
    r.verify()
    assert "DEPENDENCY_MISSING" in r.report.codes()
    assert r.plugin("zeta") is not None
    assert r.missing_dependencies() == {"zeta": ("alfa",)}


def test_dependency_order_does_not_matter():
    """`zeta` dipende da `alfa`, ma nell'ordine di caricamento viene dopo."""
    r = Registry()
    r.load_plugin(ECOSISTEMA / "zeta")
    r.load_plugin(ECOSISTEMA / "alfa")
    assert r.verify().ok
    assert r.missing_dependencies() == {}


# --------------------------------------------------------------------------- #
# Terze parti
# --------------------------------------------------------------------------- #
def test_an_unknown_plugin_is_discovered_without_touching_the_core(esterno):
    assert esterno.plugin("external_test_plugin") is not None
    assert esterno.component("external_test_plugin:quantum_blob") is not None


def test_an_unknown_capability_is_indexed_like_any_other(esterno):
    fornitori = [c.id for c in esterno.providers(capability="mysterious_object")]
    assert fornitori == ["external_test_plugin:crystal",
                         "external_test_plugin:quantum_blob"]


def test_nested_external_components_are_all_registered(esterno):
    """quantum_blob -> crystal -> glow: tre componenti, nessuna profondita' massima."""
    for nome in ("quantum_blob", "crystal", "glow"):
        assert esterno.component("external_test_plugin:%s" % nome) is not None


def test_the_external_nesting_can_be_walked_through_the_registry(esterno):
    """Il registry non espande niente, ma tutto cio' che serve e' registrato."""
    ctx = BuildContext(detail_level=3)
    catena, corrente = [], esterno.component("external_test_plugin:quantum_blob")
    while corrente is not None:
        catena.append(corrente.id)
        figli = corrente.children({}, ctx) if corrente.children else []
        corrente = esterno.component(figli[0].component) if figli else None
    assert catena == ["external_test_plugin:quantum_blob",
                      "external_test_plugin:crystal",
                      "external_test_plugin:glow"]


def test_the_external_plugin_also_brings_effects_and_styles(esterno):
    assert esterno.effect("external_test_plugin:risuona") is not None
    assert esterno.style("external_test_plugin:cristallino") is not None


def test_the_core_never_names_a_plugin():
    """La regola che tiene in piedi tutto: nessun `if plugin == ...` nel core."""
    proibite = ("quantum", "humanoid", "dragon", "drago", "umanoid", "casa",
                "house", "animal", "vehicle", "veicolo")
    for file in sorted((QUI.parent / "app" / "core").glob("*.py")):
        testo = file.read_text(encoding="utf-8").lower()
        codice = "\n".join(riga for riga in testo.splitlines()
                           if not riga.strip().startswith("#"))
        for parola in proibite:
            assert ("'%s'" % parola) not in codice and ('"%s"' % parola) not in codice, \
                "%s nomina %s" % (file.name, parola)


def test_two_vocabularies_coexist_without_knowing_each_other():
    r = load([ECOSISTEMA, TERZE_PARTI])
    assert len(r.plugins()) == 4
    assert r.component("alfa:nodo") and r.component("external_test_plugin:crystal")
    assert "mysterious_object" in r.capabilities()
    assert "innesto_generico" in r.capabilities()


# --------------------------------------------------------------------------- #
# Stabilita'
# --------------------------------------------------------------------------- #
def test_query_order_is_the_same_on_two_independent_loads():
    uno, due = Registry(), Registry()
    uno.load_directory(ECOSISTEMA)
    due.load_directory(ECOSISTEMA)
    assert [c.id for c in uno.components()] == [c.id for c in due.components()]
    assert [c.id for c in uno.providers(capability="innesto_generico")] == \
           [c.id for c in due.providers(capability="innesto_generico")]
    assert uno.capabilities() == due.capabilities()


def test_the_same_query_repeated_gives_the_same_order(ecosistema):
    atteso = [c.id for c in ecosistema.providers(capability="innesto_generico")]
    for _ in range(5):
        assert [c.id for c in ecosistema.providers(capability="innesto_generico")] \
            == atteso


def test_loading_the_same_directory_twice_changes_nothing(ecosistema):
    prima = ecosistema.summary()
    errori = len(ecosistema.report.errors())
    ecosistema.load_directory(ECOSISTEMA)
    assert ecosistema.summary() == prima
    assert len(ecosistema.report.errors()) == errori * 2, \
        "gli stessi due plugin rotti vengono riferiti di nuovo"
    assert "PLUGIN_ALREADY_LOADED" in ecosistema.report.codes()


def test_two_registries_do_not_share_their_components():
    """Caricare la stessa cartella due volte deve dare due vocabolari distinti."""
    uno, due = Registry(), Registry()
    uno.load_directory(ECOSISTEMA)
    due.load_directory(ECOSISTEMA)
    assert uno.component("alfa:nodo") is not due.component("alfa:nodo")


def test_a_frozen_registry_refuses_to_change(ecosistema):
    """Durante una generazione il vocabolario non si muove."""
    ecosistema.freeze()
    assert ecosistema.frozen
    with pytest.raises(RegistryError):
        ecosistema.register_component(componente("prova:tardivo"))
    with pytest.raises(RegistryError):
        ecosistema.load_directory(TERZE_PARTI)


def test_a_frozen_registry_still_answers(ecosistema):
    ecosistema.freeze()
    assert ecosistema.component("alfa:nodo") is not None
    assert ecosistema.providers(capability="innesto_generico")


# --------------------------------------------------------------------------- #
# Confini
# --------------------------------------------------------------------------- #
def test_the_registry_does_not_build_a_graph(ecosistema):
    """Registry, graph e resolver rispondono a tre domande diverse."""
    for proibito in ("graph", "compose", "resolve", "plan", "build"):
        assert not hasattr(ecosistema, proibito)


def test_the_registry_does_not_choose_a_winner(ecosistema):
    """Nessun ranking fra provider: e' una decisione del resolver."""
    fornitori = ecosistema.providers(capability="innesto_generico")
    assert len(fornitori) > 1
    assert not hasattr(ecosistema, "best_provider")


def test_the_summary_counts_what_is_installed(ecosistema):
    assert ecosistema.summary() == {"plugin": 3, "componenti": 4, "effetti": 2,
                                    "stili": 1, "trait": 0, "trait_rules": 0,
                                    "structural_traits": 1,
                                    "structural_trait_rules": 0,
                                    "layout_policies": 2,
                                    "archetypes": 0, "profiles": 0,
                                    "implementation_bindings": 0,
                                    "capability": 3}
