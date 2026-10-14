"""V3: i trait strutturali non dipendono piu' dagli id del piano.

Tre cose, e sono tre contratti distinti:

1. il **prototipo si seleziona** (role / capability / tags / components) invece
   di essere indirizzato con un percorso letterale;
2i nodi hanno un'**identita' stabile** che il planner non scrive e che
   sopravvive alla riscrittura e al salvataggio;
3. un **trait sconosciuto** non distrugge una struttura valida.

Il test che conta piu' degli altri e' `test_structural_result_is_invariant_...`:
rinomina tutti gli id del piano con valori arbitrari e pretende la stessa
struttura semantica. E' quello che impedisce il ritorno dei percorsi letterali.
"""
from __future__ import annotations

import pytest

from app.build.assembler import build
from app.core.effect import apply_effects
from app.core.errors import Report
from app.core.graph import CompositionGraph, structural_provenance_from_dict
from app.core.layout import resolve_layout
from app.core.planner.plans import validate_plan
from app.core.registry import load
from app.core.resolver import resolve
from app.core.structural import (UNKNOWN_TRAIT_SKIPPED, StructuralTarget,
                                 StructuralTraitRequest,
                                 resolve_structural_traits)
from app.core.traits import resolve_traits

ARMS = "character:arm_count"
WHEELS = "vehicle:wheel_count"
TAILS = "fantasy:tail_count"

# Gli id che un LLM scrive davvero. Nessuno di questi nomi compare in nessuna
# regola: e' esattamente il punto.
NOMI_RADICE = ("car", "jeep", "jeep1", "auto_01")


@pytest.fixture(scope="module")
def catalogo():
    return load(["app/plugins"]).freeze()


def _grafo(registry, root_id, ref, trait, count, *, detail=1, on="root",
           params=None):
    """Una riscrittura strutturale, **senza** nominare nessun percorso.

    `on` resta al suo valore predefinito: se servisse un percorso per far
    funzionare un conteggio, questi test non passerebbero.
    """
    graph = CompositionGraph(detail_level=detail, seed=7)
    graph.set_root(root_id, ref, **(params or {}))
    graph.structural_traits = [StructuralTraitRequest(trait, count, on=on)]
    report = Report()
    resolution = resolve_structural_traits(graph, registry, report=report)
    return graph, resolution, report


def _pipeline(registry, graph, report):
    resolved = resolve(graph, registry, report=report)
    resolve_traits(resolved, registry, report=report)
    layout = resolve_layout(resolved, registry, report=report)
    result = build(apply_effects(resolved, registry), report=report)
    return resolved, layout, result


def _count_role(resolved, role):
    return len([n for n in resolved.walk() if n.component.role == role])


def _signature(resolved):
    """La struttura semantica, senza gli id che qualcuno ha scelto.

    Componente, ruolo, lato, capability e profondita': tutto cio' che decide che
    modello viene fuori. Non il nome del nodo, che e' proprio la cosa che non
    deve contare.
    """
    fuori = []
    for node in resolved.walk():
        link = node.link
        fuori.append((node.depth, node.component.id, node.component.role,
                      link.side if link else "", link.capability if link else ""))
    return sorted(fuori)


# --------------------------------------------------------------------------- #
# 1. Il prototipo si seleziona, non si indirizza
# --------------------------------------------------------------------------- #
def test_no_current_extension_needs_a_literal_prototype_path(catalogo):
    """DoD #3: nelle tre extension installate nessun percorso e' necessario."""
    attese = {ARMS: "arm", WHEELS: "wheel", TAILS: "tail"}
    for trait, role in attese.items():
        regole = catalogo.structural_trait_rules(trait)
        assert regole, trait
        for regola in regole:
            assert regola.prototype == "", \
                "%s torna a dipendere da un percorso: %r" % (regola.id, regola.prototype)
            assert not regola.target.empty
            assert regola.target.role == role


def test_rules_do_not_name_any_plan_node_id(catalogo):
    """Nessuna regola nomina `car`, `jeep`, `corpo` o `fox`."""
    vietati = set(NOMI_RADICE) | {"corpo", "fox", "wheel_fl", "arm_l", "body"}
    for regola in catalogo.structural_trait_rules():
        pezzi = set(filter(None, str(regola.prototype).split("/")))
        assert not (pezzi & vietati), regola.id


@pytest.mark.parametrize("root_id", NOMI_RADICE)
def test_six_wheels_whatever_the_root_is_called(catalogo, root_id):
    """Il caso che V2 lasciava rosso: `car` funzionava, `jeep` no."""
    graph, resolution, report = _grafo(catalogo, root_id,
                                       "vehicle_stylized:car", WHEELS, 6)
    resolved, layout, result = _pipeline(catalogo, graph, report)
    assert report.ok, report.describe()
    assert _count_role(resolved, "wheel") == 6
    assert len(layout.placements) == 6
    assert result.triangles > 0
    assert resolution.plan.operations[0].prototype == ""


@pytest.mark.parametrize("count", (4, 6, 8))
def test_wheel_counts_keep_symmetric_sides(catalogo, count):
    graph, _, report = _grafo(catalogo, "auto_01", "vehicle_stylized:car",
                              WHEELS, count)
    resolved, layout, _ = _pipeline(catalogo, graph, report)
    lati = [n.link.side for n in resolved.walk() if n.component.role == "wheel"]
    assert report.ok, report.describe()
    assert len(lati) == count
    assert lati.count("l") == lati.count("r") == count // 2
    assert len(layout.placements) == count


@pytest.mark.parametrize("count", (2, 4, 6))
def test_arm_counts_on_the_anatomical_humanoid(catalogo, count):
    graph, _, report = _grafo(catalogo, "qualunque_nome",
                              "humanoid_anatomical:body", ARMS, count)
    resolved, layout, result = _pipeline(catalogo, graph, report)
    assert report.ok, report.describe()
    assert _count_role(resolved, "arm") == count
    assert len(layout.placements) == count
    assert result.triangles > 0


@pytest.mark.parametrize("count", (2, 4, 6))
def test_new_arms_grow_the_whole_anatomical_chain(catalogo, count):
    """Non basta contare un nodo di superficie: le braccia nuove sono catene.

    A detail 2 un braccio e' `shoulder -> upper_arm -> elbow -> forearm ->
    wrist -> hand`. Un clone che desse un solo nodo passerebbe un conteggio e
    non sarebbe un braccio.
    """
    graph, _, report = _grafo(catalogo, "xyz_01", "humanoid_anatomical:body",
                              ARMS, count, detail=2)
    resolved, layout, result = _pipeline(catalogo, graph, report)
    spalle = [n for n in resolved.walk()
              if n.component.id == "humanoid_anatomical:shoulder"]
    assert report.ok, report.describe()
    assert len(spalle) == count
    assert len(layout.placements) == count
    attesa = ["shoulder", "upper_arm", "elbow", "forearm", "wrist", "hand"]
    for spalla in spalle:
        catena = [n.component.id.partition(":")[2] for n in resolved.walk()
                  if n.path == spalla.path or n.path.startswith(spalla.path + "/")]
        assert catena == attesa, spalla.path
    lati = sorted(s.link.side for s in spalle)
    assert lati.count("l") == lati.count("r") == count // 2
    assert result.triangles > 0


@pytest.mark.parametrize("count", (1, 3, 6))
def test_tail_counts_without_a_path(catalogo, count):
    graph, _, report = _grafo(catalogo, "volpe_strana", "fox_stylized:fox",
                              TAILS, count)
    resolved, layout, result = _pipeline(catalogo, graph, report)
    assert report.ok, report.describe()
    assert _count_role(resolved, "tail") == count
    assert len(layout.placements) == count
    assert result.triangles > 0


def test_prototype_selection_is_deterministic(catalogo):
    """Stessa richiesta, stesso prototipo: il tie-breaking non e' casuale."""
    scelte = set()
    for _ in range(4):
        _, resolution, report = _grafo(catalogo, "mezzo",
                                       "vehicle_stylized:car", WHEELS, 6)
        assert report.ok
        scelte.add(resolution.applied[0]["prototype"])
    assert len(scelte) == 1


def test_prototype_prefers_the_head_of_a_repeated_group(catalogo):
    """Fra quattro nodi `role="arm"` in catena si sceglie la spalla.

    La spalla non vince per il suo nome: vince perche' suo padre dichiara una
    `LayoutRegion` che accetta un braccio, ed e' la meno profonda.
    """
    _, resolution, report = _grafo(catalogo, "tizio", "humanoid_anatomical:body",
                                   ARMS, 4, detail=2)
    assert report.ok, report.describe()
    assert resolution.applied[0]["prototype"].endswith("/shoulder_l")


def test_an_unrelated_role_is_not_touched(catalogo):
    """Chiedere braccia non deve moltiplicare le gambe."""
    graph, _, report = _grafo(catalogo, "tizio", "humanoid_anatomical:body",
                              ARMS, 6, detail=2)
    resolved, _, _ = _pipeline(catalogo, graph, report)
    assert report.ok, report.describe()
    gambe = [n for n in resolved.walk()
             if n.component.id == "humanoid_anatomical:hip"]
    assert len(gambe) == 2


def test_a_literal_prototype_path_still_works(catalogo):
    """Retrocompatibilita': `std:instance_count` indirizza un nodo, e deve.

    E' il caso in cui un percorso non e' una supposizione sulla forma del
    piano: e' chi scrive che punta il dito su un nodo preciso.
    """
    graph = CompositionGraph(detail_level=1, seed=7)
    graph.set_root("fox", "fox_stylized:fox")
    graph.structural_traits = [StructuralTraitRequest(
        "std:instance_count", 4, on="fox/body/tail")]
    report = Report()
    resolve_structural_traits(graph, catalogo, report=report)
    resolved, _, _ = _pipeline(catalogo, graph, report)
    assert report.ok, report.describe()
    assert _count_role(resolved, "tail") == 4


def test_on_is_a_scope_and_a_stale_one_does_not_break_the_rewrite(catalogo):
    """`on` restringe la ricerca; se nomina un nodo che non c'e', si ignora.

    `corpo/torso/arm_l` esiste a detail 1 e a detail 2 no, perche' `shoulder_l`
    lo sostituisce. Prima questo era un fallimento fatale.
    """
    for detail in (1, 2):
        graph, _, report = _grafo(catalogo, "corpo", "humanoid_anatomical:body",
                                  ARMS, 4, detail=detail, on="corpo/torso/arm_l")
        resolved, layout, _ = _pipeline(catalogo, graph, report)
        assert report.ok, report.describe()
        assert _count_role(resolved, "arm") >= 4
        assert len(layout.placements) == 4


# --------------------------------------------------------------------------- #
# 2. Rename invariance: il test che impedisce il ritorno dei percorsi
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("ref,trait,count,detail", [
    ("vehicle_stylized:car", WHEELS, 6, 1),
    ("humanoid_anatomical:body", ARMS, 4, 1),
    ("humanoid_anatomical:body", ARMS, 4, 2),
    ("fox_stylized:fox", TAILS, 3, 1),
])
def test_structural_result_is_invariant_to_planner_node_ids(catalogo, ref,
                                                            trait, count, detail):
    """Si rinominano **tutti** gli id del piano e si confronta la struttura.

    Due piani che differiscono solo per i nomi dei nodi devono dare lo stesso
    modello. Finche' questo test passa, un prototipo legato a un percorso
    letterale non puo' rientrare senza farlo cadere.
    """
    riferimento = None
    for root_id in ("a", "zzz_99", "Il_Mio_Oggetto", "x"):
        graph, _, report = _grafo(catalogo, root_id, ref, trait, count,
                                  detail=detail)
        resolved, layout, result = _pipeline(catalogo, graph, report)
        assert report.ok, report.describe()
        corrente = (_signature(resolved), len(layout.placements), result.triangles)
        if riferimento is None:
            riferimento = corrente
        assert corrente == riferimento, root_id


def test_renaming_the_plan_does_not_change_stable_identities(catalogo):
    """Gli id del piano cambiano, le identita' stabili no."""
    identita = []
    for root_id in ("car", "jeep", "jeep1", "auto_01"):
        graph, _, report = _grafo(catalogo, root_id, "vehicle_stylized:car",
                                  WHEELS, 6)
        assert report.ok, report.describe()
        identita.append(sorted(graph.identities().values()))
    assert all(voce == identita[0] for voce in identita)


# --------------------------------------------------------------------------- #
# 3. Identita' stabile
# --------------------------------------------------------------------------- #
def test_identity_is_derived_and_not_written_by_the_plan(catalogo):
    """Non e' un campo del piano: un piano che prova a scriverla non viene creduto."""
    piano = {"version": "1.3",
             "root": {"id": "r", "ref": "fox_stylized:fox",
                      "identity": "deadbeef", "children": []}}
    graph, report = validate_plan(piano, catalogo)
    assert graph is not None, report.describe()
    assert "NODE_UNKNOWN_KEY" in report.codes()
    assert graph.identity("r") != "deadbeef"
    assert graph.identity("r")


def test_identity_ignores_parameters_and_effects(catalogo):
    """Cambiare un numero non fa di un nodo un altro nodo."""
    primo = CompositionGraph()
    primo.set_root("a", "humanoid_anatomical:body", height=1.8)
    secondo = CompositionGraph()
    secondo.set_root("a", "humanoid_anatomical:body", height=2.4)
    secondo.effect("fx:lanky", "subtree", target="a", amount=0.5)
    assert primo.identity("a") == secondo.identity("a")


def test_identity_survives_a_swap_but_not_a_different_attachment(catalogo):
    """Uno swap e' lo stesso nodo da un altro componente: l'identita' resta.

    Un **requisito** diverso invece e' un altro posto, quindi un altro nodo.
    """
    from app.core.capability import Requirement

    graph = CompositionGraph()
    graph.set_root("corpo", "humanoid_anatomical:body")
    graph.add_child("testa", "humanoid_anatomical:head", "corpo",
                    requirement=Requirement(capability="head_mount"))
    prima = graph.identity("testa")
    graph.swap("testa", "creature:dragon_head")
    assert graph.identity("testa") == prima

    altro = CompositionGraph()
    altro.set_root("corpo", "humanoid_anatomical:body")
    altro.add_child("testa", "humanoid_anatomical:head", "corpo",
                    requirement=Requirement(capability="core_mount"))
    assert altro.identity("testa") != prima


def test_structural_clones_get_distinct_identities(catalogo):
    graph, resolution, report = _grafo(catalogo, "car", "vehicle_stylized:car",
                                       WHEELS, 8)
    assert report.ok, report.describe()
    identita = graph.identities()
    assert len(set(identita.values())) == len(identita)
    creati = resolution.applied[0]["created"]
    assert len(set(identita[id] for id in creati)) == len(creati)


def test_the_rewrite_recognises_a_node_it_already_created(catalogo):
    """Idempotenza per identita': rieseguire non raddoppia e non rinomina."""
    graph, _, report = _grafo(catalogo, "car", "vehicle_stylized:car",
                              WHEELS, 6)
    prima = graph.identities()
    seconda = resolve_structural_traits(graph, catalogo, report=Report())
    assert report.ok, report.describe()
    assert seconda.created == []
    assert graph.identities() == prima
    for identita in prima.values():
        assert graph.by_identity(identita) is not None


def test_a_clone_keeps_the_prototype_attachment_contract(catalogo):
    """Il posto del clone viene dal contratto, non da una stringa."""
    graph, resolution, report = _grafo(catalogo, "car", "vehicle_stylized:car",
                                       WHEELS, 6)
    assert report.ok, report.describe()
    creati = [graph.nodes[id] for id in resolution.applied[0]["created"]]
    for nodo in creati:
        richiesta = nodo.attachment.requirement
        assert richiesta is not None
        assert richiesta.capability == "wheel_mount"
        assert richiesta.side in ("l", "r")
        assert graph.parents[nodo.id] == "car"


# --------------------------------------------------------------------------- #
# 4. Provenienza dei cloni
# --------------------------------------------------------------------------- #
def test_clone_provenance_says_origin_prototype_and_index(catalogo):
    """Origine, prototipo per identita', e quale copia e': le tre cose di §5."""
    graph, resolution, report = _grafo(catalogo, "qualunque",
                                       "humanoid_anatomical:body", ARMS, 4)
    assert report.ok, report.describe()
    provenienza = graph.structural_provenance
    assert len(provenienza) == 2
    identita = graph.identities()
    for voce in provenienza:
        assert voce["trait"] == ARMS
        assert voce["rule"] == "multi_arm_extension:arm_count"
        assert voce["prototype"] == resolution.applied[0]["prototype_identity"]
        assert voce["identity"] in identita.values()
        assert voce["clone_count"] == 4
    assert sorted(v["clone_index"] for v in provenienza) == [3, 4]
    assert [o for o in graph.operations if o.kind == "ensure_count"]


def test_provenance_that_matches_no_node_is_dropped_on_reload(catalogo):
    """E' diagnostica, non un'istruzione: una voce inventata non entra."""
    graph, _, report = _grafo(catalogo, "car", "vehicle_stylized:car", WHEELS, 6)
    assert report.ok
    finta = [{"trait": "character:arm_count", "identity": "0" * 12,
              "clone_index": 9, "clone_count": 9}]
    assert structural_provenance_from_dict(finta, graph) == []
    vera = structural_provenance_from_dict(graph.structural_provenance, graph)
    assert len(vera) == len(graph.structural_provenance)


# --------------------------------------------------------------------------- #
# 5. Serializzazione: piano -> grafo -> riscrittura -> salva -> rileggi
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("ref,trait,count", [
    ("vehicle_stylized:car", WHEELS, 6),
    ("humanoid_anatomical:body", ARMS, 4),
])
def test_identity_and_provenance_survive_a_round_trip(catalogo, ref, trait, count):
    piano = {"version": "1.3", "detail_level": 1, "seed": 7,
             "structural_traits": [{"trait": trait, "value": count}],
             "root": {"id": "oggetto", "ref": ref}}
    graph, report = validate_plan(piano, catalogo)
    assert graph is not None, report.describe()
    resolve_structural_traits(graph, catalogo, report=report)
    assert report.ok, report.describe()

    dati = graph.to_dict()
    assert dati["structural_provenance"]

    for ricostruito in (CompositionGraph.from_dict(dati),
                        validate_plan(dati, catalogo)[0]):
        assert ricostruito is not None
        assert ricostruito.identities() == graph.identities()
        assert ricostruito.structural_provenance == graph.structural_provenance
        assert len(ricostruito.nodes) == len(graph.nodes)
        prima = _signature(resolve(graph, catalogo, report=Report()))
        dopo = _signature(resolve(ricostruito, catalogo, report=Report()))
        assert dopo == prima


def test_a_project_written_before_v3_still_opens(catalogo):
    """Retrocompatibilita': senza `structural_provenance` non cambia niente."""
    piano = {"version": "1.3", "detail_level": 1,
             "root": {"id": "fox", "ref": "fox_stylized:fox"}}
    graph, report = validate_plan(piano, catalogo)
    assert graph is not None, report.describe()
    assert graph.structural_provenance == []
    assert graph.identity("fox")           # derivata, non letta da file


# --------------------------------------------------------------------------- #
# 6. Trait facoltativo sconosciuto
# --------------------------------------------------------------------------- #
def test_an_invented_trait_does_not_destroy_a_valid_root(catalogo):
    """Il prompt 3 del PRODUCT-AUDIT, ridotto a un test.

    Il modello scriveva `instance_count` al posto di un trait installato e il
    piano moriva anche con una radice buona.
    """
    piano = {"version": "1.3",
             "traits": [{"trait": "body_mass", "value": 0.7},
                        {"trait": "instance_count", "value": 4}],
             "root": {"id": "robot", "ref": "humanoid_anatomical:body"}}
    graph, report = validate_plan(piano, catalogo)
    assert graph is not None, report.describe()
    assert report.ok
    assert UNKNOWN_TRAIT_SKIPPED in report.codes()
    voce = [d for d in report.sorted() if d.code == UNKNOWN_TRAIT_SKIPPED][0]
    assert "instance_count" in voce.message
    assert not voce.fatal
    # il trait buono resta, quello inventato no
    assert [t.trait for t in graph.traits] == ["body_mass"]


def test_an_invented_structural_trait_does_not_destroy_a_valid_root(catalogo):
    piano = {"version": "1.3",
             "structural_traits": [{"trait": "vehicle:wheel_count", "value": 6},
                                   {"trait": "tentacle_count", "value": 8}],
             "root": {"id": "jeep", "ref": "vehicle_stylized:car"}}
    graph, report = validate_plan(piano, catalogo)
    assert graph is not None, report.describe()
    assert report.ok
    assert UNKNOWN_TRAIT_SKIPPED in report.codes()
    assert [t.trait for t in graph.structural_traits] == ["vehicle:wheel_count"]
    resolve_structural_traits(graph, catalogo, report=report)
    resolved, _, result = _pipeline(catalogo, graph, report)
    assert report.ok, report.describe()
    assert _count_role(resolved, "wheel") == 6
    assert result.triangles > 0


def test_an_unknown_structural_trait_is_skipped_by_the_resolver_too(catalogo):
    """Anche entrando da un grafo scritto a mano, non da `validate_plan`."""
    graph = CompositionGraph(detail_level=1)
    graph.set_root("fox", "fox_stylized:fox")
    graph.structural_traits = [StructuralTraitRequest("mai:visto", 3)]
    report = Report()
    resolution = resolve_structural_traits(graph, catalogo, report=report)
    assert report.ok, report.describe()
    assert UNKNOWN_TRAIT_SKIPPED in report.codes()
    assert resolution.skipped[0]["trait"] == "mai:visto"
    assert resolution.plan.operations == []


@pytest.mark.parametrize("piano,codice", [
    # Una radice che non esiste: non c'e' niente da costruire.
    ({"root": {"id": "r", "ref": "plugin:inventato"}}, "COMPONENT_NOT_FOUND"),
    # Schema: un elemento malformato non e' un elemento sconosciuto.
    ({"traits": "non un elenco",
      "root": {"id": "r", "ref": "fox_stylized:fox"}}, "TRAITS_NOT_A_LIST"),
    ({"traits": [{"value": 1}],
      "root": {"id": "r", "ref": "fox_stylized:fox"}}, "TRAIT_NO_ID"),
    ({"traits": [{"trait": "body_mass"}],
      "root": {"id": "r", "ref": "fox_stylized:fox"}}, "TRAIT_NO_VALUE"),
    ({"structural_traits": [{"value": 2}],
      "root": {"id": "r", "ref": "fox_stylized:fox"}}, "STRUCTURAL_TRAIT_NO_ID"),
    # Trait noto, valore invalido: la richiesta e' leggibile e sbagliata.
    ({"traits": [{"trait": "body_mass", "value": 1, "op": "moltiplica"}],
      "root": {"id": "r", "ref": "fox_stylized:fox"}},
     "TRAIT_OPERATION_UNSUPPORTED"),
    # Un effetto inventato cambierebbe la geometria in silenzio.
    ({"root": {"id": "r", "ref": "fox_stylized:fox",
               "effects": [{"type": "fx:inventato"}]}}, "EFFECT_NOT_FOUND"),
])
def test_what_stays_fatal_stays_fatal(catalogo, piano, codice):
    """La politica copre cio' che si **puo'** ignorare, e nient'altro."""
    graph, report = validate_plan({"version": "1.3", **piano}, catalogo)
    assert codice in report.codes(), report.describe()
    assert graph is None


def test_an_ambiguous_trait_is_not_silently_skipped(catalogo):
    """«Non si sa quale» non e' «non esiste»: ignorarlo sarebbe scegliere."""
    from app.core.params import ParamSpec
    from app.core.traits import TraitSpec

    registry = load(["app/plugins"])
    for owner in ("primo_plugin", "secondo_plugin"):
        spec = TraitSpec(id="%s:doppio" % owner, aliases=("doppio",),
                         value=ParamSpec(0.5), owner=owner)
        assert registry.register_trait(spec, owner)
    registry = registry.freeze()
    assert registry.trait_ambiguous("doppio")

    piano = {"version": "1.3", "traits": [{"trait": "doppio", "value": 0.5}],
             "root": {"id": "r", "ref": "fox_stylized:fox"}}
    graph, report = validate_plan(piano, registry)
    assert graph is None
    assert "TRAIT_AMBIGUOUS" in report.codes()
    assert UNKNOWN_TRAIT_SKIPPED not in report.codes()


def test_a_skipped_trait_is_visible_in_the_result(catalogo):
    """Non fatale non vuol dire invisibile: `skipped()` lo dice."""
    from app.ai.provider import OfflineProvider
    from app.core.session import Options, Session

    session = Session(provider=OfflineProvider())
    session.registry = catalogo
    piano = {"version": "1.3",
             "traits": [{"trait": "instance_count", "value": 4}],
             "root": {"id": "robot", "ref": "humanoid_anatomical:body"}}
    risultato = session.build(piano, Options(detail_level=1, check=False))
    assert risultato.ok
    assert risultato.triangles > 0
    righe = [r for r in risultato.skipped() if UNKNOWN_TRAIT_SKIPPED in r]
    assert righe and "instance_count" in righe[0]
    assert UNKNOWN_TRAIT_SKIPPED in [d.code for d in risultato.diagnostics]


# --------------------------------------------------------------------------- #
# 7. Composizione fra plugin, sottoposta a un trait strutturale
# --------------------------------------------------------------------------- #
# Una chimera scritta a mano che funziona gia' in `tests/test_scenari.py`:
# corpo umanoide, testa di rana di un altro plugin, braccia e gambe esplicite.
# Si riusa quella forma perche' il test deve misurare l'effetto del trait
# strutturale, non scoprire come si scrive un piano.
CHIMERA = {
    "version": "1.3", "style": "low_poly", "detail_level": 2, "seed": 7,
    "root": {
        "id": "corpo", "ref": "humanoid:body", "params": {"height": 1.8},
        "children": [{
            "id": "torso", "ref": "humanoid:torso",
            "at": {"capability": "core_mount"},
            "children": [
                {"id": "collo", "ref": "humanoid:neck", "insert": 0.3,
                 "at": {"capability": "head_mount"},
                 "children": [{"id": "testa", "ref": "humanoid:head",
                               "swap": "creature:frog_head", "insert": 0.25,
                               "at": {"capability": "head_mount"}}]},
                {"id": "braccio_l", "ref": "humanoid:arm", "insert": 1.15,
                 "at": {"capability": "limb_mount", "side": "l"}},
                {"id": "braccio_r", "ref": "humanoid:arm", "insert": 1.15,
                 "at": {"capability": "limb_mount", "side": "r"}},
                {"id": "gamba_l", "ref": "humanoid:leg", "insert": 0.9,
                 "at": {"capability": "limb_mount", "side": "l"}},
                {"id": "gamba_r", "ref": "humanoid:leg", "insert": 0.9,
                 "at": {"capability": "limb_mount", "side": "r"}},
            ]}]}}


def _piano(base, **extra):
    import copy

    fuori = copy.deepcopy(base)
    fuori.update(copy.deepcopy(extra))
    return fuori


def test_a_cross_plugin_chimera_survives_a_structural_trait(catalogo):
    """Corpo umanoide + testa di rana + quattro braccia.

    Il trait deve aggiungere braccia e **non** toccare la testa di un altro
    plugin, ne' ricostruire parti che non c'entrano.
    """
    senza, report = validate_plan(_piano(CHIMERA), catalogo)
    assert senza is not None, report.describe()
    prima, _, _ = _pipeline(catalogo, senza, report)
    assert report.ok, report.describe()

    graph, report = validate_plan(
        _piano(CHIMERA, structural_traits=[{"trait": ARMS, "value": 4}]),
        catalogo)
    assert graph is not None, report.describe()
    identita_testa = graph.identity("testa")
    resolve_structural_traits(graph, catalogo, report=report)
    resolved, layout, result = _pipeline(catalogo, graph, report)
    assert report.ok, report.describe()

    assert _count_role(resolved, "arm") == 4
    assert result.triangles > 0
    # Correttezza strutturale e qualita' di layout sono due cose, e qui si
    # separano: `humanoid` (il plugin storico) non dichiara nessuna
    # `LayoutRegion`, quindi le quattro braccia si risolvono sui socket
    # ordinari del resolver e il layout non ha niente da distribuire. Non e' un
    # fallimento — e' un componente che non ha chiesto di essere distribuito.
    # Pretendere delle placement qui vorrebbe dire pretendere che ogni
    # componente dichiari una regione, che e' il contrario del contratto.
    assert not layout.placements
    assert not layout.problems

    # La testa di un altro plugin resta una, resta uno swap, resta lo stesso nodo.
    teste = [n for n in resolved.walk() if n.component.id == "creature:frog_head"]
    assert len(teste) == 1
    assert graph.swaps["testa"] == "creature:frog_head"
    assert graph.identity("testa") == identita_testa

    # Le gambe non c'entrano niente con le braccia: identiche prima e dopo.
    def gambe(composizione):
        return sorted(n.path for n in composizione.walk()
                      if n.component.role in ("leg", "foot"))

    assert gambe(resolved) == gambe(prima)
    assert _count_role(resolved, "leg") == _count_role(prima, "leg") == 2


def test_a_selector_crosses_plugins_the_rule_never_named(catalogo):
    """La regola delle code nomina `fox_stylized:tail` e trova `fish:tail`.

    E' la prova che il selettore non e' un alias del componente della regola:
    un plugin che dichiara `role="tail"` partecipa senza che nessuno lo scriva
    da nessuna parte — la stessa proprieta' che V2 aveva dato alla degradazione.
    """
    piano = {"version": "1.3", "detail_level": 2, "seed": 7,
             "structural_traits": [{"trait": TAILS, "value": 3}],
             "root": {"id": "pesce", "ref": "fish:fish_body",
                      "children": [{"id": "testa", "ref": "creature:dragon_head",
                                    "at": {"capability": "head_mount"}}]}}
    graph, report = validate_plan(piano, catalogo)
    assert graph is not None, report.describe()
    resolve_structural_traits(graph, catalogo, report=report)
    resolved, _, result = _pipeline(catalogo, graph, report)
    assert report.ok, report.describe()
    code = [n for n in resolved.walk() if n.component.role == "tail"]
    assert len(code) == 3
    assert {n.component.id for n in code} == {"fish:tail"}
    assert len([n for n in resolved.walk()
                if n.component.id == "creature:dragon_head"]) == 1
    assert result.triangles > 0


def test_a_third_party_rule_needs_no_path_and_no_core_change(catalogo):
    """Un plugin di terze parti usa il selettore e niente altro."""
    from app.core.component import Attachment, Component, Piece
    from app.core.capability import Capability, Requirement, mount
    from app.core.params import ParamSpec
    from app.core.structural import StructuralTraitRule, StructuralTraitSpec

    registry = load(["app/plugins"])
    antenna = Component(
        id="antenna", build=lambda v, ctx: Piece(mesh=None),
        params={"size": ParamSpec(0.1)}, role="signal", tags=("signal",),
        provides=(Capability("signal_mount"),))
    host = Component(
        id="host", build=lambda v, ctx: Piece(mesh=None),
        children=lambda v, ctx: [Attachment(
            id="antenna", component="antenna",
            requirement=Requirement(capability="signal_mount"))],
        params={"size": ParamSpec(1.0)}, role="container",
        mounts=(mount("signal_mount", socket_id="base"),))
    assert registry.register_component(host, "third_party")
    assert registry.register_component(antenna, "third_party")
    assert registry.register_structural_trait(StructuralTraitSpec(
        "custom:antenna_count", value=ParamSpec(1, min=0, max=8), max_count=8,
        owner="third_party"))
    assert registry.register_structural_trait_rule(StructuralTraitRule(
        id="antenna_count", trait="custom:antenna_count",
        component="third_party:antenna", group="signal",
        target=StructuralTarget(role="signal")), "third_party")

    graph = CompositionGraph(detail_level=2)
    graph.set_root("un_nome_qualunque", "third_party:host")
    graph.structural_traits = [StructuralTraitRequest("custom:antenna_count", 3)]
    report = Report()
    resolution = resolve_structural_traits(graph, registry, report=report)
    assert report.ok, report.describe()
    assert len([n for n in graph.walk() if n.ref == "third_party:antenna"]) == 3
    assert resolution.plan.operations[0].prototype == ""
    assert len(graph.structural_provenance) == 2


def test_identity_and_provenance_survive_a_real_my3d_project(tmp_path, catalogo):
    """Il round-trip che conta: un progetto salvato e riaperto davvero.

    `project.load` non chiama `CompositionGraph.from_dict`: ricostruisce ogni
    versione con `Session.build`, quindi passa da `validate_plan`. E' il motivo
    per cui l'identita' e' **derivata** e non un campo del nodo: un campo nuovo
    sarebbe stato scartato qui come chiave sconosciuta.
    """
    from app.ai.provider import OfflineProvider
    from app.core.session import Options, Session, Version

    piano = {"version": "1.3", "detail_level": 1, "seed": 7,
             "structural_traits": [{"trait": WHEELS, "value": 6}],
             "root": {"id": "jeep_del_mio_amico", "ref": "vehicle_stylized:car"}}

    session = Session(provider=OfflineProvider())
    session.registry = catalogo
    risultato = session.build(piano, Options(detail_level=1, check=False))
    assert risultato.ok, risultato.report.describe()
    grafo = risultato.plan
    assert _count_role(risultato.resolved, "wheel") == 6
    identita = grafo.identities()
    provenienza = list(grafo.structural_provenance)
    assert len(provenienza) == 2

    session.history.append(Version(label="sei ruote", plan=grafo,
                                   scene=risultato.scene(catalogo),
                                   result=risultato))
    session.cursor = 0
    percorso = session.save_project(tmp_path / "v3_project")

    riaperta = Session(provider=OfflineProvider())
    riaperta.registry = catalogo
    riaperta.open_project(percorso)
    ricostruito = riaperta.current_plan
    assert ricostruito is not None
    assert ricostruito.identities() == identita
    assert ricostruito.structural_provenance == provenienza
    riprodotto = riaperta.current.result
    assert _count_role(riprodotto.resolved, "wheel") == 6
    assert riprodotto.triangles == risultato.triangles


def test_the_structural_core_has_no_domain_words_in_its_code():
    """DoD #9, come test invece che come `grep`.

    Si guardano le **stringhe del codice**, non i commenti ne' i docstring: una
    riga di documentazione che spiega perche' si sceglie la spalla e' utile, una
    riga di codice che cerca la parola «arm» e' il difetto che V3 esisteva per
    togliere. Il controllo e' lo stesso che `tests/test_traits.py` fa sul
    livello semantico.
    """
    import ast
    from pathlib import Path

    radice = Path(__file__).resolve().parent.parent / "app" / "core"
    vietate = {"arm", "wheel", "tail", "leg", "head", "car", "jeep", "corpo",
               "fox", "shoulder", "humanoid", "vehicle", "animal"}
    for nome in ("structural.py", "graph.py", "layout.py"):
        albero = ast.parse((radice / nome).read_text(encoding="utf-8"))
        docstring = {ast.get_docstring(n) for n in ast.walk(albero)
                     if isinstance(n, (ast.Module, ast.ClassDef,
                                       ast.FunctionDef, ast.AsyncFunctionDef))}
        for nodo in ast.walk(albero):
            if not isinstance(nodo, ast.Constant) or not isinstance(nodo.value, str):
                continue
            if nodo.value in docstring:
                continue
            assert nodo.value.lower() not in vietate, \
                "%s:%d parla di dominio: %r" % (nome, nodo.lineno, nodo.value)
