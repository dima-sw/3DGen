"""Il planner vero: una chiamata, uno schema, al massimo una correzione.

Non c'e' nessuna rete qui dentro. I fornitori sono finti e **deterministici**:
si misura che cosa il sistema chiede a un modello, quante volte glielo chiede e
che cosa fa della risposta — non se un modello indovina.

    provider     chi sa rispondere in JSON, chiunque sia
    schema       la forma di un piano, indipendente dai plugin
    planner      una chiamata sola
    riparazione  una sola, e solo se puo' migliorare qualcosa
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.ai.provider import LLMError, LLMProvider
from app.core.errors import Report
from app.core.planner.planner import LLMPlanner, MockPlanner, PlanRequest
from app.core.planner.plans import validate_plan
from app.core.planner.repair import PlanScore, plan_score, repair_brief
from app.core.planner.schema import PLAN_SCHEMA, SCHEMA_VERSION, plan_schema
from app.core.planner.vocabulary import build_vocabulary
from app.core.registry import load
from app.core.session import Options, Session

PLUGIN = Path(__file__).resolve().parent.parent / "app" / "plugins"

PIANO_BUONO = {
    "style": "low_poly", "detail_level": 2,
    "root": {"id": "casa", "ref": "architecture:house",
             "params": {"width": 8.0},
             "children": [{"id": "pianeta", "ref": "space:planet",
                           "at": {"capability": "surface"}}]}}


@pytest.fixture(scope="module")
def catalogo():
    r = load([PLUGIN])
    assert not r.report.errors(), r.report.describe()
    return r.freeze()


@pytest.fixture(scope="module")
def vocabolario(catalogo):
    return build_vocabulary(catalogo)


# --------------------------------------------------------------------------- #
# Fornitori finti
# --------------------------------------------------------------------------- #
class Fornitore(LLMProvider):
    """Un fornitore che risponde quello che gli si dice, e registra le domande."""

    name = "finto"
    key = "finto"

    def __init__(self, risposte, structured: bool = False) -> None:
        self.risposte = list(risposte)
        self._structured = structured
        self.chiamate: list[dict] = []

    @property
    def structured(self) -> bool:
        return self._structured

    def available(self) -> bool:
        return True

    def complete_json(self, system, user, temperature=0.2, schema=None):
        self.chiamate.append({"system": system, "user": user,
                              "schema": schema, "temperature": temperature})
        if not self.risposte:
            raise LLMError("il finto ha finito le risposte")
        return self.risposte.pop(0)


class Rotto(LLMProvider):
    name = "rotto"
    key = "rotto"

    def available(self) -> bool:
        return True

    def complete_json(self, system, user, temperature=0.2, schema=None):
        raise LLMError("guasto simulato")


# --------------------------------------------------------------------------- #
# Lo schema
# --------------------------------------------------------------------------- #
def test_the_schema_is_independent_of_the_plugins(catalogo):
    """Nessun id di componente, effetto o stile dentro lo schema.

    Se ce ne fosse uno, installare un plugin obbligherebbe a rigenerare lo
    schema — e uno schema che si rigenera non e' un contratto, e' una
    fotografia.
    """
    testo = json.dumps(PLAN_SCHEMA)
    for componente in catalogo.components():
        assert componente.id not in testo, componente.id
    for effetto in catalogo.effects():
        assert effetto.id not in testo, effetto.id
    assert "humanoid" not in testo and "architecture" not in testo


def test_the_schema_describes_a_tree_of_any_depth():
    nodo = PLAN_SCHEMA["$defs"]["nodo"]
    assert nodo["properties"]["children"]["items"] == {"$ref": "#/$defs/nodo"}
    assert "maxDepth" not in json.dumps(PLAN_SCHEMA)


def test_the_schema_is_a_copy_not_the_original():
    uno = plan_schema()
    uno["properties"].pop("root")
    assert "root" in plan_schema()["properties"]


def test_a_good_plan_satisfies_the_schema():
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.validate(PIANO_BUONO, PLAN_SCHEMA)


@pytest.mark.parametrize("piano", [
    {},                                                   # senza radice
    {"root": {"id": "x"}},                                # senza ref
    {"root": {"ref": "a:b", "children": {"id": "y"}}},    # figli non in elenco
    {"root": {"ref": "a:b"}, "detail_level": 99},         # dettaglio impossibile
    {"root": {"ref": "a:b", "inventato": 1}},             # chiave sconosciuta
])
def test_a_malformed_plan_fails_the_schema(piano):
    jsonschema = pytest.importorskip("jsonschema")
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(piano, PLAN_SCHEMA)


def test_the_schema_is_versioned():
    assert SCHEMA_VERSION and PLAN_SCHEMA["$id"].endswith(SCHEMA_VERSION)


# --------------------------------------------------------------------------- #
# Che cosa arriva al modello
# --------------------------------------------------------------------------- #
def test_a_structured_provider_receives_the_schema(vocabolario):
    fornitore = Fornitore([PIANO_BUONO], structured=True)
    LLMPlanner(fornitore).plan(PlanRequest(prompt="una casa",
                                           vocabulary=vocabolario))
    assert fornitore.chiamate[0]["schema"]["$id"] == PLAN_SCHEMA["$id"]


def test_a_plain_provider_gets_the_schema_and_may_ignore_it(vocabolario):
    """Lo schema si manda comunque: chi non lo sa usare lo scarta da solo."""
    fornitore = Fornitore([PIANO_BUONO], structured=False)
    risposta = LLMPlanner(fornitore).plan(
        PlanRequest(prompt="una casa", vocabulary=vocabolario))
    assert risposta.plan == PIANO_BUONO
    assert not risposta.notes, "senza vincolo non si promette niente"


def test_the_system_prompt_says_what_the_planner_is_and_is_not(vocabolario):
    fornitore = Fornitore([PIANO_BUONO])
    LLMPlanner(fornitore).plan(PlanRequest(prompt="una casa",
                                           vocabulary=vocabolario))
    sistema = fornitore.chiamate[0]["system"].lower()
    for atteso in ("planner", "non sei un modellatore", "vocabolario",
                   "non inventare", "json"):
        assert atteso in sistema, atteso


def test_the_constraints_travel_with_the_request(vocabolario):
    fornitore = Fornitore([PIANO_BUONO])
    LLMPlanner(fornitore).plan(PlanRequest(
        prompt="una casa", vocabulary=vocabolario, style="low_poly",
        detail_level=3))
    messaggio = fornitore.chiamate[0]["user"]
    assert "dettaglio: 3" in messaggio and "low_poly" in messaggio


def test_nothing_internal_reaches_the_model(vocabolario):
    fornitore = Fornitore([PIANO_BUONO])
    LLMPlanner(fornitore).plan(PlanRequest(prompt="una casa",
                                           vocabulary=vocabolario))
    tutto = fornitore.chiamate[0]["system"] + fornitore.chiamate[0]["user"]
    for proibito in ("def ", "import ", "trimesh", "Traceback", ".py",
                     "app/", "self."):
        assert proibito not in tutto, proibito


# --------------------------------------------------------------------------- #
# Una generazione, al massimo una correzione
# --------------------------------------------------------------------------- #
def test_a_good_plan_costs_one_call(catalogo):
    fornitore = Fornitore([PIANO_BUONO])
    sessione = Session(provider=fornitore, planner=LLMPlanner(fornitore),
                       registry=catalogo)
    risultato = sessione.generate("una casa con un pianeta")

    assert len(fornitore.chiamate) == 1
    assert risultato.ok and not risultato.repaired


def test_a_broken_plan_costs_exactly_two(catalogo):
    """Una generazione piu' una correzione. Mai tre, mai un ciclo."""
    rotto = {"root": {"id": "casa", "ref": "architecture:house",
                      "children": [{"id": "t", "ref": "creature:dragon_head",
                                    "at": {"capability": "opening"}}]}}
    fornitore = Fornitore([rotto, PIANO_BUONO])
    sessione = Session(provider=fornitore, planner=LLMPlanner(fornitore),
                       registry=catalogo)
    risultato = sessione.generate("una casa con una testa di drago")

    assert len(fornitore.chiamate) == 2
    assert risultato.repaired and risultato.ok


def test_the_second_call_carries_the_diagnostics_and_the_previous_plan(catalogo):
    rotto = {"root": {"id": "r", "ref": "plugin:inventato"}}
    fornitore = Fornitore([rotto, PIANO_BUONO])
    sessione = Session(provider=fornitore, planner=LLMPlanner(fornitore),
                       registry=catalogo)
    sessione.generate("qualcosa")

    seconda = fornitore.chiamate[1]["user"]
    assert "PIANO PRECEDENTE" in seconda
    assert "plugin:inventato" in seconda
    assert "PROBLEMI" in seconda


def test_nothing_that_cannot_be_rewritten_is_sent_back(catalogo):
    """Un piano valido con un budget stretto non spreca la correzione."""
    from app.core.budget import Budget

    fornitore = Fornitore([PIANO_BUONO])
    sessione = Session(provider=fornitore, planner=LLMPlanner(fornitore),
                       registry=catalogo)
    sessione.generate("una casa", Options(budget=Budget(triangles=10)))
    assert len(fornitore.chiamate) == 1


def test_a_worse_repair_is_thrown_away(catalogo):
    """Se la correzione peggiora, si tiene la prima. E si scrive perche'."""
    quasi = {"root": {"id": "casa", "ref": "architecture:house",
                      "children": [{"id": "t", "ref": "creature:dragon_head",
                                    "at": {"capability": "opening"}}]}}
    peggio = {"root": {"id": "casa", "ref": "plugin:inesistente",
                       "children": [{"id": "t", "ref": "altro:inesistente"}]}}
    fornitore = Fornitore([quasi, peggio])
    sessione = Session(provider=fornitore, planner=LLMPlanner(fornitore),
                       registry=catalogo)
    risultato = sessione.generate("una casa strana")

    assert len(fornitore.chiamate) == 2
    assert not risultato.repaired, "si e' tenuta la prima"
    assert "REPAIR_NOT_BETTER" in risultato.report.codes()
    assert risultato.plan is not None and risultato.ok


def test_a_dead_provider_falls_back_and_says_so(catalogo):
    """Nessun ripiego silenzioso: chi guarda il risultato sa chi ha lavorato."""
    sessione = Session(provider=Rotto(), planner=LLMPlanner(Rotto()),
                       registry=catalogo)
    risultato = sessione.generate("una casa con un pianeta enorme sopra")

    assert risultato.planner == "mock_fallback"
    assert risultato.ok, "un modello si ottiene lo stesso"
    assert any("non ha risposto" in d.message for d in risultato.diagnostics)


def test_a_non_object_answer_is_refused_not_guessed(catalogo, vocabolario):
    fornitore = Fornitore([["non", "un", "oggetto"]])
    risposta = LLMPlanner(fornitore).plan(
        PlanRequest(prompt="x", vocabulary=vocabolario))
    assert risposta.plan == {}
    assert risposta.notes


# --------------------------------------------------------------------------- #
# Il punteggio di un piano
# --------------------------------------------------------------------------- #
def test_a_clean_plan_scores_zero():
    class Risolto:
        root = "r"
        unresolved: list = []

    assert plan_score(Report(), Risolto(), plan=object()).total == 0


def test_no_plan_at_all_is_the_worst_thing_that_can_happen():
    """Un piano che non produce niente non puo' sembrare migliore di uno a meta'.

    E' il caso che ha fatto nascere questo termine: un piano rifiutato in blocco
    aveva **meno** diagnosi di uno risolto per tre quarti, e la correzione
    sembrava un miglioramento mentre cancellava il modello.
    """
    class Mezzo:
        root = "r"
        unresolved = ["testa", "braccio"]

    referto = Report()
    referto.add("SOCKET_INCOMPATIBLE", "x")
    a_meta = plan_score(referto, Mezzo(), plan=object())
    niente = plan_score(Report(), None, plan=None)
    assert a_meta < niente


def test_the_score_orders_by_how_bad_the_defect_is():
    """Un pezzo che non entra nel modello pesa piu' di un parametro fuori scala."""
    nodo_perso = Report()

    class Risolto:
        root = "r"
        unresolved = ["testa"]

    parametro = Report()
    parametro.note("PARAM_OUT_OF_RANGE", "x")

    class Intero:
        root = "r"
        unresolved: list = []

    assert plan_score(parametro, Intero(), plan=object())         < plan_score(nodo_perso, Risolto(), plan=object())


def test_the_score_counts_the_unresolved_nodes():
    class Risolto:
        root = "r"
        unresolved = ["a", "b", "c"]

    punteggio = plan_score(Report(), Risolto(), plan=object())
    assert punteggio.unresolved == 3
    assert "unresolved=3" in punteggio.describe()


def test_the_score_is_deterministic(catalogo):
    piano = {"root": {"id": "r", "ref": "plugin:inventato"}}
    punteggi = set()
    for _ in range(3):
        _, referto = validate_plan(piano, catalogo)
        punteggi.add(plan_score(referto).total)
    assert len(punteggi) == 1


def test_the_score_never_asks_a_model_anything():
    """Il confronto fra due piani e' fatto di conteggi, e resta tale."""
    import inspect

    import app.core.planner.repair as modulo

    codice = inspect.getsource(modulo)
    for proibito in ("provider", "complete_json", "LLMPlanner", "prompt"):
        assert proibito not in codice, proibito


def test_two_scores_compare_like_numbers():
    assert PlanScore(fatal=1) < PlanScore(fatal=2)
    assert PlanScore(fatal=2) >= PlanScore(fatal=1)


# --------------------------------------------------------------------------- #
# Il riassunto per la correzione
# --------------------------------------------------------------------------- #
def test_the_repair_brief_is_compact(catalogo):
    piano = {"root": {"id": "r", "ref": "plugin:inventato",
                      "children": [{"id": "b", "ref": "altro:inventato"},
                                   {"id": "c", "ref": "terzo:inventato"}]}}
    _, referto = validate_plan(piano, catalogo)
    testo = repair_brief(referto).to_text()
    assert 0 < len(testo.splitlines()) <= 30
    assert "inventato" in testo


def test_the_repair_brief_survives_an_empty_report():
    rimedio = repair_brief(Report())
    assert not rimedio.worth_retrying and rimedio.to_text() == ""
