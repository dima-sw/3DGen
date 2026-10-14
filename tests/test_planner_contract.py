"""V3.5 — il contratto fra il planner e i due livelli che esistevano gia'.

Non c'e' nessuna rete qui dentro, e non si misura se un modello indovina. Si
misura se **cio' che gli viene mostrato basta a scegliere**, e se una forma
JSON sbagliata ma leggibile in un solo modo sopravvive.

Le due domande, separate perche' hanno due risposte diverse:

    vocabolario   un trait strutturale e' visibile, e si distingue da uno
                  semantico?                                      §1
    prompt        il testo mandato al modello dice sotto quale chiave del
                  piano si scrive, e che cosa quel trait conta?    §2
    effetti       un `params` annidato ma inequivocabile si normalizza, e tutto
                  il resto resta fatale?                           §3

## Perche' un fornitore che legge il prompt, e non un planner finto

Il difetto che V3.5 corregge era questo: il livello strutturale funzionava, e
il modello non lo chiamava. Un planner finto che leggesse gli oggetti del
vocabolario non direbbe niente su quel difetto — gli oggetti erano completi
anche prima. Quello che mancava stava nel **testo**: la chiave del piano non
compariva da nessuna parte, gli alias italiani venivano buttati e nessuno
diceva che `character:arm_count` conta parti con ruolo `arm`.

Quindi il fornitore di §2 non vede il registry e non vede il vocabolario: vede
la stessa stringa che vedrebbe un modello, e ne ricava il piano. Se togliere un
plugin fa sparire il trait dal testo, il piano non lo nomina — e' il test 4.

Nessuna di queste classi conosce le parole braccio, ruota o coda. Le prendono
dal testo, come le prende un modello.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.ai.provider import LLMProvider
from app.core.planner.planner import LLMPlanner, PlanRequest
from app.core.planner.plans import validate_plan
from app.core.planner.retrieval import shortlist
from app.core.planner.vocabulary import (PLAN_KEY_STRUCTURAL, PLAN_KEY_TRAITS,
                                         build_vocabulary)
from app.core.registry import Registry, load
from app.core.session import Options, Session

PLUGIN = Path(__file__).resolve().parent.parent / "app" / "plugins"

# I nomi dei numeri sono comprensione del testo, non conoscenza del dominio 3D:
# stanno qui perche' qui sta il finto modello, e un modello vero li sa.
NUMERI = {"uno": 1, "due": 2, "tre": 3, "quattro": 4, "cinque": 5, "sei": 6,
          "sette": 7, "otto": 8, "nove": 9, "one": 1, "two": 2, "three": 3,
          "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9}


@pytest.fixture(scope="module")
def catalogo():
    r = load([PLUGIN])
    assert not r.report.errors(), r.report.describe()
    return r.freeze()


def vocabolario_per(catalogo, prompt: str):
    """Il vocabolario che il planner vedrebbe per questa richiesta.

    Passa dalla rosa, come la pipeline vera: senza di lei si misurerebbe la
    libreria intera, che e' proprio il caso che V1 ha tolto dalla produzione.
    """
    rosa = shortlist(catalogo, prompt, style="low_poly")
    return build_vocabulary(catalogo, style="low_poly",
                            components=rosa.components)


def prompt_per(catalogo, prompt: str, compact: bool = False) -> str:
    richiesta = PlanRequest(prompt=prompt,
                            vocabulary=vocabolario_per(catalogo, prompt),
                            style="low_poly", detail_level=2)
    return LLMPlanner._render_message(richiesta, compact=compact)[0]


def senza(plugin: str) -> Registry:
    """Il registry con tutti i plugin **tranne** uno.

    Serve alla prova che conta piu' delle altre: togliere il trait dal registry
    deve farlo sparire dal prompt, non comparire come nome inventato.
    """
    r = Registry()
    for cartella in sorted(p for p in PLUGIN.iterdir() if p.is_dir()):
        if cartella.name == plugin or not (cartella / "plugin.json").exists():
            continue
        r.load_plugin(cartella)
    return r.freeze()


# --------------------------------------------------------------------------- #
# Il finto modello: legge il prompt, e nient'altro
# --------------------------------------------------------------------------- #
class LettoreDiPrompt(LLMProvider):
    """Un fornitore deterministico che ricava il piano dal **testo** ricevuto.

    Fa le tre letture che a un modello servivano e che il prompt non
    permetteva:

    1. trova la sezione dei trait strutturali e ne legge la **chiave del
       piano**, che il titolo dichiara fra virgolette;
    2. di ogni voce legge gli id e gli alias (separati da `|`) e cio' che
       dichiara di selezionare (`selects=`);
    3. sceglie la voce i cui nomi o bersagli compaiono nella richiesta, e le
       da' il numero scritto nella richiesta.

    Non importa `app.core` per decidere: vede `system` e `user` come li vede un
    modello. Il `ref` della radice glielo passa il test, perche' qui non si
    misura come si scelga una radice — si misura se la richiesta strutturale
    arriva al livello strutturale.
    """

    name = "lettore"
    key = "lettore"

    def __init__(self, root_ref: str = "") -> None:
        self.root_ref = root_ref
        self.chiamate: list[dict] = []

    def available(self) -> bool:
        return True

    # ------------------------------------------------------------ lettura #
    @staticmethod
    def sezioni(user: str) -> dict[str, list[str]]:
        fuori: dict[str, list[str]] = {}
        titolo = ""
        for riga in user.splitlines():
            if riga.startswith("## "):
                titolo = riga[3:]
                fuori[titolo] = []
            elif titolo and riga.startswith("- "):
                fuori[titolo].append(riga[2:])
        return fuori

    @staticmethod
    def chiave_del_piano(titolo: str) -> str:
        """La chiave JSON che il titolo della sezione dichiara."""
        trovato = re.search(r'chiave del piano "([a-z_]+)"', titolo)
        return trovato.group(1) if trovato else ""

    @staticmethod
    def parole(testo: str) -> set[str]:
        return {p for p in re.split(r"[^a-z0-9]+", testo.lower()) if len(p) > 2}

    @classmethod
    def voce(cls, riga: str) -> tuple[tuple[str, ...], set[str]]:
        """I nomi di un trait, e le parole con cui si fa riconoscere."""
        nomi = tuple(riga.split(" ")[0].split("|"))
        selects = re.search(r"selects=([^ |]+)", riga)
        bersagli = cls.parole(selects.group(1)) if selects else set()
        return nomi, set(cls.parole(" ".join(nomi))) | bersagli

    def complete_json(self, system, user, temperature=0.2, schema=None):
        self.chiamate.append({"system": system, "user": user})
        richiesta = user.split("\n\nVINCOLI")[0]
        parole = self.parole(richiesta)
        quanti = next((NUMERI[p] for p in richiesta.lower().split()
                       if p.strip(".,") in NUMERI
                       for p in [p.strip(".,")]), 0)

        piano: dict = {"style": "low_poly", "detail_level": 2,
                       "root": {"id": "soggetto", "ref": self.root_ref}}
        for titolo, righe in self.sezioni(user).items():
            chiave = self.chiave_del_piano(titolo)
            if chiave != PLAN_KEY_STRUCTURAL or not quanti:
                continue
            scelte = []
            for riga in righe:
                nomi, parole_voce = self.voce(riga)
                if parole_voce & parole:
                    scelte.append({"trait": nomi[0], "value": quanti})
            if scelte:
                # A pari merito il primo in ordine di id: deterministico, e la
                # scelta non e' cio' che questo test misura.
                piano[chiave] = scelte[:1]
        return piano


# --------------------------------------------------------------------------- #
# 1. Il vocabolario: visibile, e distinguibile
# --------------------------------------------------------------------------- #
def test_an_installed_structural_trait_is_visible_in_the_vocabulary(catalogo):
    """Test 1. Il caso misurato del PRODUCT-AUDIT V3: non lo era.

    Con «un robot con quattro braccia» il modello vedeva un solo trait
    strutturale, `std:instance_count`, perche' la rosa non conteneva nessun
    pezzo con ruolo `arm` e il filtro di rilevanza tolgieva `character:
    arm_count`. Il ponte fra `braccia` e `braccio`/`arm` adesso lo dichiara
    `multi_arm_extension` nel proprio manifest, e la rosa trova le braccia.
    """
    for prompt in ("Un robot con quattro braccia.",
                   "una persona con quattro braccia",
                   "humanoid with four arms"):
        vocabolario = vocabolario_per(catalogo, prompt)
        visibili = {t.id for t in vocabolario.structural_traits}
        assert "character:arm_count" in visibili, prompt

    ruote = vocabolario_per(catalogo, "Una jeep cartoon con sei ruote.")
    assert "vehicle:wheel_count" in {t.id for t in ruote.structural_traits}
    code = vocabolario_per(catalogo, "Un drago cartoon con ali, corna e coda.")
    assert "fantasy:tail_count" in {t.id for t in code.structural_traits}


def test_the_word_bridge_that_finds_those_parts_is_library_data(catalogo):
    """Il ponte sta nel manifest del plugin, non nel core.

    Regola 11 del progetto: «una jeep e' un'automobile» e' conoscenza della
    libreria. Lo stesso vale per «braccia e' il plurale di braccio». Se questo
    test cade perche' qualcuno ha spostato le parole nel core, il difetto e'
    la posizione, non il test.
    """
    ponti = catalogo.synonyms()
    assert "arm" in ponti.get("braccia", ()), ponti.get("braccia")
    assert "wheel" in ponti.get("ruote", ())
    assert "tail" in ponti.get("code", ())

    from app.assets.semantic import THESAURUS
    for parola in ("braccia", "ruote", "code"):
        assert parola not in THESAURUS, \
            "%s e' un ponte di dominio: appartiene a un plugin" % parola

    dichiarati = {p.id for p in catalogo.plugins() if p.synonyms}
    assert {"multi_arm_extension", "multi_wheel_extension",
            "multi_tail_extension"} <= dichiarati


def test_a_structural_trait_declares_what_it_counts_and_a_semantic_one_does_not(catalogo):
    """Test 2. I metadati che distinguono i due generi, e che mancavano.

    Prima di V3.5 le due voci erano indistinguibili: `- arm_count float
    modes=... range=0..64` contro `- body_mass float ops=... range=0..1`. Un
    modello vedeva due manopole numeriche e non aveva modo di sapere che una
    cambia il numero delle parti e l'altra le proporzioni di quelle che ci sono.
    """
    vocabolario = vocabolario_per(catalogo, "humanoid with four arms")
    strutturale = next(t for t in vocabolario.structural_traits
                       if t.id == "character:arm_count")
    semantico = next(t for t in vocabolario.traits if t.id == "std:body_mass")

    # la chiave del piano, che e' la differenza operativa
    assert strutturale.plan_key == PLAN_KEY_STRUCTURAL
    assert semantico.plan_key == PLAN_KEY_TRAITS
    assert strutturale.plan_key != semantico.plan_key

    # che cosa conta, letto dal bersaglio che la regola dichiara
    assert "role:arm" in strutturale.selects
    assert "tag:arm" in strutturale.selects
    assert strutturale.purpose, "un trait senza purpose e' un numero senza nome"
    assert "arm" in strutturale.purpose

    # gli alias sono le parole della richiesta, e sono **tutti**
    assert "braccia" in strutturale.aliases and "arm_count" in strutturale.aliases
    assert strutturale.id not in strutturale.aliases


def test_the_generic_structural_trait_declares_no_target(catalogo):
    """`std:instance_count` e' il ripiego, e si vede che lo e'.

    E' il trait che il modello aveva scelto in V3, e l'aveva scelto perche' era
    il solo mostrato. Non dichiara nessun bersaglio — e' la richiesta a dover
    puntare un nodo con `on` — e adesso quella differenza e' leggibile.
    """
    vocabolario = vocabolario_per(catalogo, "humanoid with four arms")
    generico = next(t for t in vocabolario.structural_traits
                    if t.id == "std:instance_count")
    specifico = next(t for t in vocabolario.structural_traits
                     if t.id == "character:arm_count")
    assert generico.selects == ()
    assert specifico.selects, "un trait con una regola dichiara cio' che conta"
    assert "on" in generico.purpose


def test_an_alias_declared_by_two_plugins_is_never_offered():
    """Un alias ambiguo non si propone: scriverlo diventerebbe TRAIT_AMBIGUOUS.

    Mostrare **tutti** gli alias e' giusto; mostrarne uno che non risolve
    sarebbe un invito a sbagliare. Il filtro e' il registry stesso.
    """
    from app.core.params import ParamSpec
    from app.core.structural import StructuralTraitSpec

    r = Registry()
    for owner in ("uno", "due"):
        r.register_structural_trait(StructuralTraitSpec(
            id="%s:thing_count" % owner, aliases=("thing_count", "conteso"),
            description="count of things", value=ParamSpec(1, min=0, max=8),
            owner=owner))
    vocabolario = build_vocabulary(r.freeze())
    for voce in vocabolario.structural_traits:
        assert "conteso" not in voce.aliases
        assert "thing_count" not in voce.aliases


def test_the_restricted_vocabulary_never_names_a_component_outside_the_shortlist(catalogo):
    """`selects=component:...` segue la rosa, come fa `CapabilityEntry`.

    Un elenco di id dentro la riga di un trait riporterebbe nel prompt la
    libreria che il retrieval ha appena escluso, e il carico tornerebbe a
    crescere con i plugin installati — cioe' il difetto che V1 ha chiuso.
    """
    rosa = shortlist(catalogo, "Una volpe cartoon low-poly.", style="low_poly")
    ristretto = build_vocabulary(catalogo, style="low_poly",
                                 components=rosa.components)
    ammessi = set(rosa.ids)
    for voce in ristretto.structural_traits + ristretto.traits:
        for select in voce.selects:
            genere, _, id = select.partition(":")
            if genere == "component":
                assert id in ammessi, select


# --------------------------------------------------------------------------- #
# 2. Il prompt: la chiave del piano, e chi la usa
# --------------------------------------------------------------------------- #
def test_the_prompt_names_both_plan_keys_and_the_difference_between_them(catalogo):
    """La causa prima, in forma di test.

    Il prompt di sistema di V3 non conteneva la stringa `structural_traits` in
    nessun punto: le due forme di piano mostrate elencavano `root`, `params`,
    `effects` e `children`, e l'unico posto dove un trait compariva era
    `concept.adaptations`. Un modello che voleva dire «quattro braccia» aveva
    un solo slot documentato, e lo ha usato.
    """
    from app.core.planner.planner import SISTEMA

    assert PLAN_KEY_STRUCTURAL in SISTEMA
    assert '"%s"' % PLAN_KEY_TRAITS in SISTEMA
    # e la distinzione, non solo i nomi
    assert "QUANTE parti" in SISTEMA
    assert "PROPRIETA'" in SISTEMA
    # e il divieto, in forma generale e senza esempi di dominio
    assert "Non inventare un campo di conteggio" in SISTEMA
    # Parole intere: `detail_level` contiene «tail» e non parla di code.
    for parola in ("arm", "arms", "braccia", "braccio", "wheel", "wheels",
                   "ruote", "tail", "tails", "coda", "code"):
        assert not re.search(r"\b%s\b" % parola, SISTEMA), \
            "il prompt resta generico: '%s' appartiene alla libreria" % parola


@pytest.mark.parametrize("compact", [False, True])
def test_the_rendered_prompt_says_under_which_key_a_trait_is_written(catalogo, compact):
    """Il titolo della sezione dichiara la chiave, in **entrambe** le forme.

    La forma compatta e' quella che prendono i fornitori con il corpo piccolo,
    cioe' esattamente quelli che in V3 sbagliavano piu' spesso. Teneva meno
    informazione proprio dove serviva di piu'.
    """
    testo = prompt_per(catalogo, "humanoid with four arms", compact=compact)
    assert 'chiave del piano "%s"' % PLAN_KEY_STRUCTURAL in testo
    assert 'chiave del piano "%s"' % PLAN_KEY_TRAITS in testo
    assert "character:arm_count" in testo
    assert "braccia" in testo
    assert "selects=role:arm" in testo


def test_a_prompt_reader_writes_the_installed_structural_trait(catalogo):
    """Test 3. La regressione che la milestone chiede, alla lettera.

    Il fornitore non vede il registry: ricava tutto dal testo. Che il piano
    contenga `character:arm_count` vuol dire che il testo basta.
    """
    fornitore = LettoreDiPrompt(root_ref="humanoid_anatomical:body")
    richiesta = PlanRequest(
        prompt="humanoid with four arms",
        vocabulary=vocabolario_per(catalogo, "humanoid with four arms"),
        style="low_poly", detail_level=2)
    piano = LLMPlanner(fornitore).plan(richiesta).plan

    assert piano[PLAN_KEY_STRUCTURAL] == [
        {"trait": "character:arm_count", "value": 4}]
    assert "instance_count" not in json.dumps(piano)


@pytest.mark.parametrize("prompt,trait,valore,root", [
    ("humanoid with four arms", "character:arm_count", 4,
     "humanoid_anatomical:body"),
    ("un corpo umanoide con sei braccia", "character:arm_count", 6,
     "humanoid_anatomical:body"),
    ("a car with six wheels", "vehicle:wheel_count", 6,
     "vehicle_stylized:car"),
    ("una volpe con tre code", "fantasy:tail_count", 3, "fox_stylized:fox"),
])
def test_the_same_reading_works_for_every_installed_count_trait(
        catalogo, prompt, trait, valore, root):
    """Lo stesso meccanismo per braccia, ruote e code: nessun caso speciale.

    Se uno di questi passasse e gli altri no, vorrebbe dire che la conoscenza
    sta in un posto sbagliato — nel core, o in un test.
    """
    fornitore = LettoreDiPrompt(root_ref=root)
    richiesta = PlanRequest(prompt=prompt,
                            vocabulary=vocabolario_per(catalogo, prompt),
                            style="low_poly", detail_level=2)
    piano = LLMPlanner(fornitore).plan(richiesta).plan
    assert piano.get(PLAN_KEY_STRUCTURAL) == [{"trait": trait, "value": valore}]


def test_a_trait_that_is_not_installed_is_not_invented():
    """Test 4. Togliere il plugin deve togliere la richiesta, non falsificarla.

    E' la prova che la soluzione dipende dal vocabolario installato e non da
    una tabella scritta da qualche parte. Senza `multi_arm_extension` il trait
    non esiste, non compare nel testo, e il piano non lo nomina.
    """
    catalogo = senza("multi_arm_extension")
    prompt = "humanoid with four arms"
    assert catalogo.structural_trait("character:arm_count") is None

    testo = prompt_per(catalogo, prompt)
    assert "arm_count" not in testo

    fornitore = LettoreDiPrompt(root_ref="humanoid_anatomical:body")
    richiesta = PlanRequest(prompt=prompt,
                            vocabulary=vocabolario_per(catalogo, prompt),
                            style="low_poly", detail_level=2)
    piano = LLMPlanner(fornitore).plan(richiesta).plan
    assert "arm_count" not in json.dumps(piano)
    assert not piano.get(PLAN_KEY_STRUCTURAL)


def test_a_structural_trait_the_registry_does_not_have_is_declared_lost():
    """E se un modello lo scrivesse comunque, resta la politica di V3.

    Avviso, piano vivo, richiesta dichiarata persa. Qui serve a dire che le due
    difese sono distinte: il vocabolario evita di invitare all'errore, la
    validazione sopravvive all'errore.
    """
    catalogo = senza("multi_arm_extension")
    piano = {"style": "low_poly", "detail_level": 2,
             "structural_traits": [{"trait": "character:arm_count", "value": 4}],
             "root": {"id": "corpo", "ref": "humanoid_anatomical:body"}}
    grafo, referto = validate_plan(piano, catalogo)
    assert grafo is not None, referto.describe()
    assert referto.ok
    assert "UNKNOWN_TRAIT_SKIPPED" in referto.codes()
    assert grafo.structural_traits == []


def test_the_request_that_reaches_the_structural_layer_builds_the_parts(catalogo):
    """Il giro completo, offline: dal piano alle quattro braccia costruite.

    Chiude il cerchio del prompt 3 del PRODUCT-AUDIT: V3 dimostrava che il
    livello funziona, V3.5 che la richiesta ci arriva. Qui si verifica che
    arrivarci produce davvero le parti, e che `structural_changes()` lo dice.
    """
    from app.ai.provider import OfflineProvider
    from app.core.planner.planner import MockPlanner

    sessione = Session(provider=OfflineProvider(), planner=MockPlanner())
    piano = {"style": "low_poly", "detail_level": 2,
             PLAN_KEY_STRUCTURAL: [{"trait": "character:arm_count", "value": 4}],
             "root": {"id": "soggetto", "ref": "humanoid_anatomical:body"}}
    risultato = sessione.build(piano, Options(style="low_poly", seed=7))

    assert risultato.ok, risultato.describe()
    spalle = [n for n in risultato.resolved.walk()
              if n.ref == "humanoid_anatomical:shoulder"]
    assert len(spalle) == 4, [n.id for n in risultato.resolved.walk()]
    righe = risultato.structural_changes()
    assert len(righe) == 1 and "character:arm_count" in righe[0]
    assert risultato.skipped() == []


# --------------------------------------------------------------------------- #
# 3. Gli effetti: una forma sbagliata e inequivocabile
# --------------------------------------------------------------------------- #
def piano_con(effetto: dict) -> dict:
    return {"style": "low_poly", "detail_level": 2,
            "root": {"id": "house1", "ref": "architecture:house",
                     "effects": [effetto]}}


def test_a_nested_params_object_on_a_known_effect_is_flattened(catalogo):
    """Test 5. Il prompt 6 del PRODUCT-AUDIT, che un fornitore su tre uccideva."""
    piano = piano_con({"type": "fx:bend", "amount": 0.2,
                       "params": {"along": "Y", "axis": "Z"}})
    grafo, referto = validate_plan(piano, catalogo)

    assert grafo is not None, referto.describe()
    assert referto.ok
    assert piano["root"]["effects"][0] == {"type": "fx:bend", "amount": 0.2,
                                           "along": "Y", "axis": "Z"}


def test_the_flattened_plan_and_the_flat_plan_are_the_same_plan(catalogo):
    """Test 6. Non «somigliano»: sono lo stesso piano normalizzato.

    Si confrontano i grafi via `to_dict()`, cioe' la forma che finisce in un
    `.my3d`: se due fornitori scrivono la stessa richiesta in due forme, il
    progetto salvato non deve ricordare quale dei due ha risposto.
    """
    annidato = piano_con({"type": "fx:bend", "amount": 0.2,
                          "params": {"along": "Y", "axis": "Z"}})
    piatto = piano_con({"type": "fx:bend", "amount": 0.2,
                        "along": "Y", "axis": "Z"})

    uno, referto_uno = validate_plan(annidato, catalogo)
    due, referto_due = validate_plan(piatto, catalogo)

    assert uno is not None and due is not None
    assert uno.to_dict() == due.to_dict()
    assert annidato == piatto, "anche il JSON del piano converge"
    # e la richiesta di effetto sul nodo, che e' cio' che il prompt 6 perdeva
    assert [vars(e) for e in uno.node("house1").effects] \
        == [vars(e) for e in due.node("house1").effects]
    assert uno.node("house1").effects[0].params == {"along": "Y", "axis": "Z"}
    assert referto_uno.codes() == {"EFFECT_PARAMS_FLATTENED"}
    assert referto_due.codes() == set()


def test_the_two_forms_build_the_same_geometry(catalogo):
    """La prova che vale piu' del confronto fra dizionari: gli stessi triangoli."""
    from app.ai.provider import OfflineProvider
    from app.core.planner.planner import MockPlanner

    fuori = []
    for effetto in ({"type": "fx:bend", "amount": 0.2,
                     "params": {"along": "Y", "axis": "Z"}},
                    {"type": "fx:bend", "amount": 0.2,
                     "along": "Y", "axis": "Z"}):
        sessione = Session(provider=OfflineProvider(), planner=MockPlanner())
        risultato = sessione.build(piano_con(effetto),
                                   Options(style="low_poly", seed=7))
        assert risultato.ok, risultato.describe()
        fuori.append((risultato.triangles,
                      [round(float(v), 6) for v in risultato.mesh().bounds.ravel()]))
    assert fuori[0] == fuori[1]
    assert fuori[0][0] > 0


def test_an_unknown_key_inside_params_stays_fatal(catalogo):
    """Test 7. Una chiave che l'effetto non dichiara: non c'e' una lettura sola."""
    piano = piano_con({"type": "fx:bend", "amount": 0.2,
                       "params": {"along": "Y", "nonesiste": 1}})
    grafo, referto = validate_plan(piano, catalogo)

    assert grafo is None
    assert "EFFECT_PARAM_NOT_FOUND" in referto.codes()
    assert "EFFECT_PARAMS_FLATTENED" not in referto.codes()
    assert piano["root"]["effects"][0]["params"] == {"along": "Y", "nonesiste": 1}


def test_a_conflict_between_nested_and_top_level_stays_fatal(catalogo):
    """Test 8. Due valori per `along`: scegliere sarebbe decidere al posto d'altri.

    E' la stessa distinzione che tiene fatale un trait **ambiguo** mentre uno
    sconosciuto si ignora. Il confine della politica e' «quanta scelta serve»,
    non «quanto e' grave».
    """
    piano = piano_con({"type": "fx:bend", "amount": 0.2, "along": "X",
                       "params": {"along": "Y"}})
    grafo, referto = validate_plan(piano, catalogo)

    assert grafo is None
    assert "EFFECT_PARAM_NOT_FOUND" in referto.codes()
    assert piano["root"]["effects"][0]["along"] == "X", "niente e' stato sovrascritto"


@pytest.mark.parametrize("params", ["Y", 3, ["Y"], True])
def test_a_params_that_is_not_an_object_stays_fatal(catalogo, params):
    """Non si srotola cio' che non e' un oggetto: non si sa in che cosa."""
    grafo, referto = validate_plan(
        piano_con({"type": "fx:bend", "amount": 0.2, "params": params}), catalogo)
    assert grafo is None
    assert "EFFECT_PARAM_NOT_FOUND" in referto.codes()


def test_an_unknown_effect_stays_fatal_even_with_a_valid_nested_params(catalogo):
    """Test 9. La normalizzazione non e' un'indulgenza sugli effetti.

    L'elemento non esiste: non c'e' nessuno `spec.params` da cui leggere, e
    ignorarlo cambierebbe la geometria in silenzio. La politica di V3 su questo
    punto non e' cambiata.
    """
    grafo, referto = validate_plan(
        piano_con({"type": "fx:nonesiste", "amount": 0.2,
                   "params": {"along": "Y"}}), catalogo)
    assert grafo is None
    assert "EFFECT_NOT_FOUND" in referto.codes()
    assert "EFFECT_PARAMS_FLATTENED" not in referto.codes()


def test_an_effect_that_really_declares_params_is_left_alone():
    """Un effetto che dichiara **davvero** un parametro `params`.

    Il caso che una regola scritta per `fx:bend` si sarebbe mangiata: qui
    `params` e' un valore, e interpretarlo sarebbe il difetto al contrario.
    """
    from app.core.params import ParamSpec
    from app.core.vocabulary import EffectSpec

    r = Registry()
    r.register_effect(EffectSpec(
        id="terzi:strano", stage="local",
        params={"params": ParamSpec("", "string")},
        deform=lambda punti, ctx: punti))
    from app.core.capability import Capability
    from app.core.component import Component, Piece
    r.register_component(Component(id="terzi:pezzo", build=lambda v, c: Piece(),
                                   provides=(Capability("anchor"),)))
    catalogo = r.freeze()

    piano = {"style": "", "detail_level": 2,
             "root": {"id": "p", "ref": "terzi:pezzo",
                      "effects": [{"type": "terzi:strano", "params": "ciao"}]}}
    grafo, referto = validate_plan(piano, catalogo)
    assert grafo is not None, referto.describe()
    assert referto.codes() == set()
    assert piano["root"]["effects"][0]["params"] == "ciao"


def test_the_normalization_is_visible_in_the_diagnostics(catalogo):
    """Test 10. Non fatale non vuol dire invisibile.

    Una normalizzazione silenziosa sarebbe lo stesso difetto spostato di un
    metro: chi legge un piano salvato deve sapere che il piano ricevuto era
    scritto in un'altra forma.
    """
    from app.ai.provider import OfflineProvider
    from app.core.planner.planner import MockPlanner

    sessione = Session(provider=OfflineProvider(), planner=MockPlanner())
    risultato = sessione.build(
        piano_con({"type": "fx:bend", "amount": 0.2,
                   "params": {"along": "Y", "axis": "Z"}}),
        Options(style="low_poly", seed=7))

    assert risultato.ok
    voci = [d for d in risultato.diagnostics if d.code == "EFFECT_PARAMS_FLATTENED"]
    assert len(voci) == 1
    assert "along" in voci[0].message and "axis" in voci[0].message
    assert voci[0].severity != "error"
    assert "EFFECT_PARAMS_FLATTENED" in risultato.to_dict()["report"] \
        if "report" in risultato.to_dict() else True
    codici = {d["code"] for d in risultato.to_dict()["diagnostics"]}
    assert "EFFECT_PARAMS_FLATTENED" in codici


def test_the_refusal_to_normalize_says_why(catalogo):
    """Quando non si srotola, la diagnosi dice che ci era andata vicina.

    Serve alla correzione unica: `EFFECT_PARAM_NOT_FOUND` da solo dice «non
    c'e' un parametro params», che e' vero e non aiuta a capire che bastava
    togliere una chiave.
    """
    grafo, referto = validate_plan(
        piano_con({"type": "fx:bend", "amount": 0.2,
                   "params": {"along": "Y", "nonesiste": 1}}), catalogo)
    assert grafo is None
    voce = next(d for d in referto.sorted()
                if d.code == "EFFECT_PARAMS_NOT_FLATTENED")
    assert "nonesiste" in voce.why
    assert voce.severity != "error", "il verdetto fatale e' dell'altro codice"


def test_the_normalization_does_not_know_any_effect_by_name():
    """Nessun id di effetto dentro il codice che normalizza.

    La prova che la politica vale per qualunque `EffectSpec` installato: se
    domani un plugin dichiara `terzi:piega` con i suoi parametri, funziona
    senza che nessuno tocchi `plans.py`.
    """
    sorgente = (Path(__file__).resolve().parent.parent / "app" / "core" /
                "planner" / "plans.py").read_text(encoding="utf-8")
    inizio = sorgente.index("def _appiattisci_params")
    fine = sorgente.index("def _on", inizio)
    corpo = sorgente[inizio:fine]
    # La docstring cita il caso misurato — `fx:bend` con `along` — e deve
    # citarlo: e' la ragione per cui questo codice esiste. Si guarda il
    # **codice**, che e' cio' che decide.
    virgolette = corpo.index('"""')
    codice = corpo[corpo.index('"""', virgolette + 3) + 3:]
    for proibito in ("fx:", "bend", "along", "axis", "lanky"):
        assert proibito not in codice, proibito


# --------------------------------------------------------------------------- #
# 4. La correzione unica, su una richiesta strutturale incompatibile
# --------------------------------------------------------------------------- #
def test_an_incompatible_structural_request_is_worth_one_repair():
    """Il difetto che V3.5 ha creato, e il meccanismo che esisteva per curarlo.

    Da quando il planner scrive davvero `structural_traits`, esiste un piano
    nuovo e plausibile: il trait giusto su una radice che non possiede quella
    parte. Misurato sul prompt 3 del PRODUCT-AUDIT con un LLM reale —
    `character:arm_count = 4` con radice `humanoid:leg`, zero triangoli.

    `STRUCTURAL_PROTOTYPE_NOT_FOUND` non era fra i codici correggibili, quindi
    la correzione unica non partiva nemmeno: un piano recuperabile restava a
    zero. La diagnosi porta sia il bersaglio cercato sia i ruoli presenti, cioe'
    tutto quello che serve a una riscrittura.
    """
    from app.core.errors import Report
    from app.core.planner.repair import CORREGGIBILI, repair_brief

    assert "STRUCTURAL_PROTOTYPE_NOT_FOUND" in CORREGGIBILI
    # e non tutto cio' che e' strutturale: un conflitto fra due conteggi non
    # dice quale dei due l'autore volesse.
    assert "STRUCTURAL_VALUE_CONFLICT" not in CORREGGIBILI

    referto = Report()
    referto.add("STRUCTURAL_PROTOTYPE_NOT_FOUND",
                "nessun nodo corrisponde al prototipo richiesto",
                where="robot_leg_base", why="role=arm tags=arm",
                alternatives=["leg", "hand", "foot"])
    rimedio = repair_brief(referto)
    assert rimedio.worth_retrying
    testo = rimedio.to_text()
    assert "role=arm" in testo and "leg" in testo


def test_one_repair_recovers_a_structural_request_on_a_wrong_root(catalogo):
    """Il giro completo: piano rotto, una correzione, quattro braccia.

    Il fornitore risponde due volte — la prima con la radice sbagliata che il
    modello reale ha scelto, la seconda con una compatibile — e si verifica che
    il sistema chieda la correzione **una volta** e tenga il piano migliore.
    Niente rete: il punto non e' se un modello indovini, e' che il meccanismo
    gli dia la possibilita' di indovinare.
    """
    from app.ai.provider import LLMError

    strutturale = [{"trait": "character:arm_count", "value": 4, "mode": "exact"}]

    class DueRisposte(LLMProvider):
        name = key = "due"

        def __init__(self):
            self.chiamate = []

        def available(self):
            return True

        def complete_json(self, system, user, temperature=0.2, schema=None):
            self.chiamate.append(user)
            if len(self.chiamate) == 1:
                return {"style": "low_poly", "detail_level": 2,
                        PLAN_KEY_STRUCTURAL: strutturale,
                        "root": {"id": "robot_leg_base", "ref": "humanoid:leg"}}
            if len(self.chiamate) == 2:
                return {"style": "low_poly", "detail_level": 2,
                        PLAN_KEY_STRUCTURAL: strutturale,
                        "root": {"id": "robot", "ref": "humanoid_anatomical:body"}}
            raise LLMError("una correzione, non un ciclo")

    fornitore = DueRisposte()
    sessione = Session(provider=fornitore, planner=LLMPlanner(fornitore))
    risultato = sessione.generate("Un robot con quattro braccia.",
                                  Options(style="low_poly", seed=7))

    assert len(fornitore.chiamate) == 2, "una correzione sola"
    assert "nessun nodo corrisponde al prototipo richiesto" in fornitore.chiamate[1]
    assert risultato.repaired
    assert risultato.ok, risultato.describe()
    spalle = [n for n in risultato.resolved.walk()
              if n.ref == "humanoid_anatomical:shoulder"]
    assert len(spalle) == 4
    assert any("character:arm_count" in r for r in risultato.structural_changes())


def test_a_structural_request_that_cannot_be_satisfied_stays_fatal_in_exact_mode(catalogo):
    """`mode="exact"` vuol dire esattamente: se non si puo', il piano non vale.

    E' il contratto di prima di V3.5 e non e' cambiato. Il test esiste perche'
    la correzione unica adesso **parte** su questo codice, e partire non vuol
    dire perdonare: se la riscrittura non migliora niente, il piano resta rosso.
    """
    from app.ai.provider import LLMError

    class SempreUguale(LLMProvider):
        name = key = "uguale"

        def __init__(self):
            self.chiamate = 0

        def available(self):
            return True

        def complete_json(self, system, user, temperature=0.2, schema=None):
            self.chiamate += 1
            if self.chiamate > 2:
                raise LLMError("una correzione, non un ciclo")
            return {"style": "low_poly", "detail_level": 2,
                    PLAN_KEY_STRUCTURAL: [{"trait": "character:arm_count",
                                           "value": 4, "mode": "exact"}],
                    "root": {"id": "volpe", "ref": "fox_stylized:fox"}}

    fornitore = SempreUguale()
    sessione = Session(provider=fornitore, planner=LLMPlanner(fornitore))
    risultato = sessione.generate("Una volpe con quattro braccia.",
                                  Options(style="low_poly", seed=7))

    assert fornitore.chiamate == 2
    assert not risultato.ok
    assert "STRUCTURAL_PROTOTYPE_NOT_FOUND" in {d.code for d in risultato.diagnostics}


@pytest.mark.parametrize("mode,costruisce", [("exact", False),
                                             ("best_effort", True)])
def test_best_effort_is_best_effort_and_exact_is_exact(catalogo, mode, costruisce):
    """Il bug dimostrato: `best_effort` uccideva il piano come `exact`.

    L'incoerenza c'era da V2 e non si poteva vedere, perche' nessun planner
    scriveva `structural_traits`. V3.5 ha fatto in modo che li scrivesse, e un
    modello reale ha chiesto `best_effort` sulla richiesta 3 del PRODUCT-AUDIT
    ottenendo zero triangoli: `mode` e' il campo con cui l'autore del piano dice
    se accetta un'approssimazione, e non veniva rispettato.

    Quello che **non** e' cambiato: `exact` resta fatale. Il confine e' quello
    che il piano dichiara, non una tolleranza decisa dal motore.
    """
    from app.ai.provider import OfflineProvider
    from app.core.planner.planner import MockPlanner

    sessione = Session(provider=OfflineProvider(), planner=MockPlanner())
    risultato = sessione.build(
        {"style": "low_poly", "detail_level": 2,
         PLAN_KEY_STRUCTURAL: [{"trait": "character:arm_count", "value": 4,
                                "mode": mode}],
         "root": {"id": "volpe", "ref": "fox_stylized:fox"}},
        Options(style="low_poly", seed=7))

    assert bool(risultato.ok) is costruisce
    assert risultato.triangles > 0 if costruisce else risultato.triangles == 0
    # in **entrambi** i casi la richiesta persa resta leggibile: non fatale non
    # vuol dire invisibile, e fatale non vuol dire inspiegabile.
    perse = [r for r in risultato.skipped() if "STRUCTURAL_TRAIT_NOT_APPLIED" in r]
    assert len(perse) == 1 and "character:arm_count" in perse[0]
    assert risultato.structural_changes() == []
    codici = {d.code for d in risultato.diagnostics}
    assert "STRUCTURAL_PROTOTYPE_NOT_FOUND" in codici
    fatale = {d.code for d in risultato.diagnostics if d.fatal}
    assert ("STRUCTURAL_PROTOTYPE_NOT_FOUND" in fatale) is not costruisce


def test_mode_is_documented_in_the_prompt_because_the_model_has_to_choose():
    """Se `mode` cambia l'esito, il modello deve sapere che cosa cambia."""
    from app.core.planner.planner import SISTEMA

    assert '"mode"' in SISTEMA
    assert "exact" in SISTEMA and "best_effort" in SISTEMA
    # una riga sola, a capo dove capita: si cerca il senso, non l'impaginazione
    righe = " ".join(SISTEMA.split())
    assert "fa fallire il piano" in righe
    assert "dichiara la richiesta persa" in righe


def test_the_structural_repair_brief_names_moves_and_not_only_roles(catalogo):
    """La correzione riceve mosse, non soltanto l'elenco di cio' che manca.

    Misurato: sulla richiesta 3 del PRODUCT-AUDIT la correzione unica partiva,
    riceveva `ears, head, limb, tail, torso` e non migliorava niente, perche'
    un piano non puo' assegnare un ruolo a un componente. Le mosse possibili
    sono tre e valgono per qualunque trait — e nessuna delle tre nomina una
    parte, quindi il testo resta generico.
    """
    from app.ai.provider import OfflineProvider
    from app.core.planner.planner import MockPlanner
    from app.core.planner.repair import repair_brief

    sessione = Session(provider=OfflineProvider(), planner=MockPlanner())
    risultato = sessione.build(
        {"style": "low_poly", "detail_level": 2,
         PLAN_KEY_STRUCTURAL: [{"trait": "character:arm_count", "value": 4,
                                "mode": "exact"}],
         "root": {"id": "fox", "ref": "fox_stylized:fox"}},
        Options(style="low_poly", seed=7))
    assert not risultato.ok

    testo = repair_brief(risultato.report).to_text()
    assert "role=arm" in testo, "che cosa cercava"
    assert 'mode="best_effort"' in testo, "una mossa"
    assert "radice" in testo, "un'altra mossa"
    assert "togli la richiesta" in testo, "la terza"
    for parola in ("braccio", "braccia", "wheel", "ruota"):
        assert parola not in testo.replace("role=arm", ""), parola
