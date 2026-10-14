"""Sessione di lavoro: la porta unica fra una richiesta e un modello.

    prompt   ->  planner  ->  piano JSON  ->  registry  ->  resolver
                                                              |
                          modello  <-  builder  <-  effetti  <-

La Session **orchestra**, non decide. Non sa che cosa sia un umanoide, una
casa o un pesce, e non deve saperlo: sceglie i pezzi il planner, li verifica il
registry, li collega il resolver, li costruisce il builder. Se qui dentro
comparisse un `if humanoide`, tutto il lavoro dei passi precedenti sarebbe
stato inutile — e sarebbe il posto piu' comodo in cui rovinarlo, perche' da
qui si vede tutto.

## Una generazione, al massimo una correzione

`generate` chiama il planner una volta. Se il piano non regge — un componente
che non esiste, un innesto incompatibile — le diagnosi diventano un riassunto
compatto e si richiede **una volta sola**. Non c'e' un ciclo, e non c'e' nessun
giudizio di qualita' affidato a un modello: la qualita' la misura il
validatore, con dei numeri, sempre gli stessi.

## Cronologia di piani, non di mesh

Ogni generazione entra nella cronologia come `Version`, e una versione porta il
**piano**. La geometria si ricostruisce: e' deterministica a parita' di piano,
plugin e seme, e un piano si puo' correggere mentre una mesh si puo' solo
guardare. E' anche il motivo per cui un progetto salvato pesa qualche kilobyte.

## Che cosa non c'e' piu'

La strada storica — `GenerationPlan`, template, campo implicito, `build_scene` —
e' stata rimossa. Chi cercava `generate_legacy`, `modify` o `revariate` trova
`generate`, un piano modificabile e `regenerate`: l'editing di un modello e'
diventato l'editing del suo piano, che e' la cosa che si voleva fin dall'inizio.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.ai.provider import LLMError, LLMProvider, make_provider
from app.assets.library import AssetLibrary, AssetRecord
from app.build.exporter import Check, export, validate
from app.core.logging_setup import get
from app.core.planner.planner import MockPlanner
from app.core.scene import Scene

log = get("session")

# Dove stanno i plugin installati. Un solo posto, e non un percorso sparso per
# il codice: cambiare cartella deve essere una riga.
PLUGIN = Path(__file__).resolve().parent.parent / "plugins"


# --------------------------------------------------------------------------- #
# Cosa si puo' chiedere, e cosa si riceve
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Options:
    """Le poche cose che chi genera puo' decidere.

    Poche apposta. Ogni opzione in piu' qui e' una decisione tolta al piano, e
    il piano e' l'unico posto in cui una decisione resta leggibile.
    """

    style: str = ""
    detail_level: int = 0
    seed: int = 0
    budget: Any = None
    repair: bool = True             # la correzione unica, se il piano non regge
    check: bool = True              # il controllo di qualita' sulla geometria

    def to_dict(self) -> dict:
        """Le opzioni che vale la pena salvare in un progetto.

        Il budget e' un oggetto e non un numero: si salva quanti triangoli
        concedeva, che e' l'unica parte che serve a rimettere le cose come
        stavano.
        """
        fuori: dict[str, Any] = {}
        for nome in ("style", "detail_level", "seed"):
            valore = getattr(self, nome)
            if valore:
                fuori[nome] = valore
        if self.budget is not None:
            from app.core.budget import LIMITS

            tetti = {k: self.budget.limit(k) for k in LIMITS}
            tetti = {k: v for k, v in sorted(tetti.items()) if v is not None}
            if tetti:
                fuori["budget"] = tetti
        return fuori

    @classmethod
    def from_dict(cls, dati: dict | None) -> "Options":
        dati = dati or {}
        return cls(style=str(dati.get("style") or ""),
                   detail_level=int(dati.get("detail_level") or 0),
                   seed=int(dati.get("seed") or 0),
                   budget=_budget(dati.get("budget")))


def _budget(dati):
    """Un budget da un dizionario di limiti, o niente."""
    if not isinstance(dati, dict) or not dati:
        return None
    from app.core.budget import EXPANSIONS, NODES, SECONDS, TRIANGLES, Budget

    campi = {TRIANGLES: "triangles", NODES: "nodes",
             EXPANSIONS: "expansions", SECONDS: "seconds"}
    return Budget(**{campi[k]: v for k, v in dati.items() if k in campi})


@dataclass
class GenerationResult:
    """Che cosa e' stato chiesto, che cosa e' stato scelto, che cosa e' uscito.

    Tutti gli strati restano accessibili — piano, risolto, effetti, geometria —
    perche' senza il primo non si capisce il secondo e senza il secondo non si
    capisce il terzo. E' la stessa regola che vale fra `graph` e `resolved`.

    E' anche cio' che l'interfaccia riceve, e le basta: non deve conoscere
    `Component`, ne' il registry, ne' il resolver.
    """

    prompt: str = ""
    plan_json: dict = field(default_factory=dict)
    plan: Any = None                 # CompositionGraph
    structural: Any = None
    resolved: Any = None
    traits: Any = None
    layout: Any = None
    concept_resolution: Any = None
    effects: Any = None
    build: Any = None
    report: Any = None
    planner: str = ""
    repaired: bool = False
    shortlist: Any = None            # la rosa di componenti mostrata al planner
    seconds: float = 0.0
    options: Any = None
    provenance: dict = field(default_factory=dict)

    @property
    def requested_provider(self) -> str:
        return str(self.provenance.get("requested_provider", ""))

    @property
    def requested_model(self) -> str:
        return str(self.provenance.get("requested_model", ""))

    @property
    def actual_provider(self) -> str:
        return str(self.provenance.get("actual_provider", ""))

    @property
    def actual_model(self) -> str:
        return str(self.provenance.get("actual_model", ""))

    @property
    def failover_count(self) -> int:
        return int(self.provenance.get("failover_count", 0) or 0)

    # ------------------------------------------------------------- lettura #
    @property
    def ok(self) -> bool:
        return self.build is not None and bool(self.build.meshes())

    @property
    def diagnostics(self) -> list:
        return self.report.sorted() if self.report is not None else []

    @property
    def triangles(self) -> int:
        return self.build.triangles if self.build is not None else 0

    def scene(self, registry=None, *, ground: bool = True) -> Scene | None:
        """La scena: nodi con nome, materiale ed etichette.

        E' la forma che export, livelli di dettaglio, libreria, animazione e
        interfaccia sanno gia' leggere. Appoggiata a terra per predefinito,
        perche' chi chiede una scena quasi sempre la sta per mostrare o
        esportare; chi vuole il modello dove i componenti l'hanno costruito
        passa `ground=False`.
        """
        from app.build.scene import to_scene

        if self.build is None:
            return None
        return to_scene(self.build, registry, plan=self.plan, ground=ground)

    def trimesh_scene(self):
        """La stessa geometria, cruda: un nodo per componente e nient'altro."""
        return self.build.scene() if self.build is not None else None

    def mesh(self):
        return self.build.combined() if self.build is not None else None

    # ---------------------------------------------------------- spiegazione #
    def explain(self) -> list[str]:
        """Perche' il modello e' venuto cosi'.

        Una riga per scelta importante, in un italiano che si puo' mostrare:
        quale componente e' stato usato, per quale capability, e se ha preso il
        posto di qualcos'altro. Serve a chi guarda un modello e non capisce da
        dove venga un pezzo — e servira' con migliaia di plugin installati.
        """
        righe = self.degradation()
        if self.resolved is None:
            return righe
        for nodo in self.resolved.walk():
            collegamento = nodo.link
            if collegamento is None:
                righe.append("'%s' e' la radice: %s" % (nodo.id, nodo.ref))
                continue
            motivo = "fornisce '%s'" % collegamento.capability \
                if collegamento.capability \
                else "si attacca a '%s'" % collegamento.parent_socket
            riga = "'%s' scelto per '%s': %s (%s)" % (
                nodo.ref, nodo.id, motivo, collegamento.how)
            if nodo.substituted:
                riga += ", al posto di '%s'" % nodo.swapped_from
            righe.append(riga)
        return righe

    def changes(self) -> list[str]:
        """Cosa e' cambiato rispetto a cio' che i componenti direbbero da soli."""
        if self.resolved is None:
            return []
        from app.core.graph import FROM_DEFAULT

        righe = []
        for nodo in self.resolved.walk():
            for nome in sorted(nodo.sources):
                voce = nodo.sources[nome]
                if voce.source == FROM_DEFAULT and not voce.modified:
                    continue
                righe.append("%s.%s %s" % (nodo.id, nome, voce.describe(nome)))
        return righe

    def skipped(self) -> list[str]:
        """Cosa non e' entrato nel modello, e resta da spiegare."""
        fuori = list(getattr(self.resolved, "unresolved", ()) or ())
        fuori += [n.id for n in getattr(self.build, "skipped", ()) or ()]
        return fuori

    def describe(self) -> str:
        pezzi = ["richiesta: %s" % self.prompt,
                 "planner: %s%s" % (self.planner,
                                     " (corretto)" if self.repaired else "")]
        if self.requested_provider:
            used = self.actual_provider or "nessuno"
            used_model = ("/%s" % self.actual_model) if self.actual_model else ""
            pezzi.append("AI: %s/%s -> %s%s | failover %d" % (
                self.requested_provider, self.requested_model or "default",
                used, used_model, self.failover_count))
        if self.build is not None:
            pezzi.append(self.build.describe())
        if self.report is not None and len(self.report):
            pezzi.append(self.report.describe())
        return "\n".join(pezzi)

    def degradation(self) -> list[str]:
        """Perche' il modello non e' esattamente cio' che era stato chiesto.

        Vuota quando non c'e' niente da dire: un'implementazione esatta non e'
        un'approssimazione e non merita una riga. Il testo viene dal piano di
        risoluzione, non da una seconda struttura che direbbe le stesse cose
        con parole diverse.
        """
        risoluzione = self.concept_resolution
        if risoluzione is None or not getattr(risoluzione, "requested_concept", ""):
            return []
        if not risoluzione.approximate and risoluzione.selected_root_implementation:
            return []
        testo = risoluzione.describe()
        return testo.split("\n") if testo else []

    def retrieval(self) -> dict:
        """Che cosa il planner ha avuto davanti, e quanto e' costato sceglierlo."""
        return self.shortlist.to_dict() if self.shortlist is not None else {}

    def to_dict(self) -> dict:
        return {"prompt": self.prompt, "planner": self.planner,
                "repaired": self.repaired, "seconds": round(self.seconds, 3),
                "plan": self.plan_json,
                "triangles": self.triangles,
                "explain": self.explain(), "changes": self.changes(),
                "skipped": self.skipped(),
                "structural": self.structural.to_dict()
                if self.structural is not None else {},
                "concept_resolution": self.concept_resolution.to_dict()
                if self.concept_resolution is not None else {},
                "traits": self.traits.to_dict() if self.traits is not None else {},
                "layout": self.layout.to_dict() if self.layout is not None else {},
                "provenance": self.provenance,
                "diagnostics": [{"code": d.code, "message": d.message,
                                 "where": d.where, "severity": d.severity}
                                for d in self.diagnostics]}


@dataclass
class Version:
    """Una tappa del lavoro: il piano, e la geometria che ne era uscita."""

    label: str
    plan: Any                        # CompositionGraph
    scene: Scene | None = None
    message: str = ""
    seconds: float = 0.0
    prompt: str = ""
    options: dict = field(default_factory=dict)
    result: GenerationResult | None = None


# --------------------------------------------------------------------------- #
# La sessione
# --------------------------------------------------------------------------- #
@dataclass
class Session:
    provider: LLMProvider | None = None
    history: list[Version] = field(default_factory=list)
    cursor: int = -1
    library: AssetLibrary | None = None
    # Copia di sicurezza periodica. Spenta per default: la accende chi ha una
    # sessione lunga da proteggere (la UI), non chi genera un oggetto e esce.
    autosave: bool = False
    # Il vocabolario installato e chi lo sa usare. Si caricano quando servono:
    # aprire la libreria o un progetto non deve leggere i plugin dal disco.
    registry: Any = None
    planner: Any = None
    plugin_paths: tuple = ()
    # plugin che un progetto aperto usava e che qui non ci sono
    missing_plugins: list = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.provider is None:
            self.provider = make_provider()
        if self.library is None:
            self.library = AssetLibrary()
        self._autosave = None
        self._vocabolari: dict[str, Any] = {}
        if self.autosave:
            self.start_autosave()

    # --------------------------------------------------------- vocabolario #
    def catalog(self):
        """Il registry dei plugin, caricato una volta e congelato.

        Congelato perche' un vocabolario che cambia mentre lo si sta usando
        renderebbe irripetibile la stessa richiesta; e caricato pigramente
        perche' meta' di questa classe non ha niente a che fare con i plugin.
        """
        if self.registry is None:
            from app.core.registry import load

            percorsi = list(self.plugin_paths) or [PLUGIN]
            registro = load(percorsi)
            if registro.report.errors():
                log.warning("plugin scartati: %s", registro.report.describe())
            self.registry = registro.freeze()
        return self.registry

    def component_index(self):
        """L'indice semantico dei componenti installati.

        Si costruisce una volta per sessione e si ricostruisce da solo se il
        registry non e' piu' quello di prima — che in pratica non succede, dato
        che il registry e' congelato, ma un indice che non sa dire di essere
        vecchio e' una cache che mente.
        """
        from app.core.planner.retrieval import build_index

        indice = getattr(self, "_indice", None)
        if indice is None or not indice.is_current(self.catalog()):
            indice = build_index(self.catalog())
            self._indice = indice
        return indice

    def shortlist(self, prompt: str, style: str = ""):
        """La rosa di componenti per una richiesta. Vuota se non c'e' richiesta."""
        from app.core.planner.retrieval import shortlist

        return shortlist(self.catalog(), prompt, index=self.component_index(),
                         style=style or "low_poly")

    def vocabulary(self, style: str = "", prompt: str = "", shortlist=None):
        """Cio' che il planner puo' nominare. Cambia se cambiano i plugin.

        Senza `prompt` e' il vocabolario intero, ed e' quello che vede chi
        chiede «che cosa e' installato». Con un prompt, e' ridotto alla rosa di
        componenti che ha a che fare con la richiesta: il carico mandato al
        modello dipende dalla rosa, non da quanti plugin sono installati.
        """
        from app.core.planner.vocabulary import build_vocabulary

        stile = style or "low_poly"
        if shortlist is None and not str(prompt or "").strip():
            if stile not in self._vocabolari:
                self._vocabolari[stile] = build_vocabulary(self.catalog(),
                                                           style=stile)
            return self._vocabolari[stile]
        rosa = shortlist if shortlist is not None else self.shortlist(prompt, stile)
        return build_vocabulary(self.catalog(), style=stile,
                                components=rosa.components)

    def _planner(self):
        if self.planner is None:
            from app.core.planner.planner import make_planner

            self.planner = make_planner(self.provider)
        return self.planner

    def configure_ai(self, provider: str | None = None, model: str | None = None,
                     failover: bool = True) -> LLMProvider:
        """Applica il provider scelto; ``model`` e' legacy e ignorato dai remoti."""
        self.provider = make_provider(provider or None, model=model or None,
                                      failover=bool(failover))
        self.planner = None
        return self.provider

    # ------------------------------------------------ dalla frase al modello #
    def plan(self, prompt: str, options: Options | None = None) -> GenerationResult:
        """Il piano, senza costruirlo. Utile a chi vuole vederlo o correggerlo."""
        return self._compose(prompt, options or Options(), costruisci=False)

    def build(self, plan, options: Options | None = None) -> GenerationResult:
        """Da un piano — grafo o JSON — al modello. Nessuna chiamata al planner."""
        opzioni = options or Options()
        inizio = time.perf_counter()
        risultato = GenerationResult(planner="nessuno", options=opzioni)
        self._costruisci(plan, risultato, opzioni)
        risultato.seconds = time.perf_counter() - inizio
        return risultato

    def generate(self, prompt: str, options: Options | None = None,
                 remember: bool = True) -> GenerationResult:
        """Il giro completo: frase, piano, risoluzione, effetti, geometria.

        E' l'unica porta. La UI, la riga di comando e un test passano di qui, e
        quello che ne esce e' sempre lo stesso oggetto: il modello, con accanto
        tutto cio' che serve a spiegarlo.
        """
        opzioni = options or Options()
        risultato = self._compose(prompt, opzioni, costruisci=True)
        if remember and risultato.plan is not None:
            self._push(self._versione(risultato))
        return risultato

    def regenerate(self, options: Options | None = None) -> GenerationResult | None:
        """Ricostruisce la geometria dal piano corrente.

        Serve dopo che qualcuno ha cambiato il piano — un parametro, un pezzo,
        un effetto — ed e' la ragione per cui la cronologia porta i piani: un
        modello si corregge correggendo il piano, non la mesh.
        """
        versione = self.current
        if versione is None:
            return None
        opzioni = options or Options.from_dict(versione.options)
        risultato = self.build(versione.plan, opzioni)
        versione.result = risultato
        versione.scene = risultato.scene(self.catalog())
        return risultato

    # ------------------------------------------------------------- interno #
    def _versione(self, risultato: GenerationResult) -> Version:
        opzioni = risultato.options or Options()
        messaggio = "; ".join(risultato.explain()[:3])
        if risultato.requested_provider:
            usato = risultato.actual_provider or "nessuno"
            modello = ("/%s" % risultato.actual_model) if risultato.actual_model else ""
            messaggio = (messaggio + "; " if messaggio else "") + (
                "AI %s/%s -> %s%s" % (risultato.requested_provider,
                                       risultato.requested_model or "default",
                                       usato, modello))
        return Version(label=risultato.prompt.strip()[:48] or "modello",
                       plan=risultato.plan,
                       scene=risultato.scene(self.catalog()),
                       message=messaggio,
                       seconds=risultato.seconds, prompt=risultato.prompt,
                       options=opzioni.to_dict(), result=risultato)

    def _compose(self, prompt: str, opzioni: Options,
                 costruisci: bool) -> GenerationResult:
        from app.core.errors import Report
        from app.core.planner.planner import PlanRequest
        from app.core.planner.repair import repair_brief

        inizio = time.perf_counter()
        rosa = self.shortlist(prompt, opzioni.style)
        vocabolario = self.vocabulary(opzioni.style, shortlist=rosa)
        planner = self._planner()
        richiesta = PlanRequest(prompt=prompt, vocabulary=vocabolario,
                                seed=opzioni.seed, style=opzioni.style,
                                detail_level=opzioni.detail_level)

        risposta = self._chiedi(planner, richiesta)
        risultato = GenerationResult(prompt=prompt, plan_json=risposta.plan,
                                     planner=risposta.source or planner.name,
                                     report=Report(), options=opzioni,
                                     shortlist=rosa)
        self._set_provenance(risultato, risposta.provenance)
        for nota in risposta.notes:
            risultato.report.note("PLANNER_NOTE", nota)
        # La materializzazione del concept non sta piu' qui: sta in `_verifica`,
        # dove passano anche `build()` e un piano scritto a mano. Un piano che
        # nomina un concetto dev'essere risolto allo stesso modo da qualunque
        # porta arrivi, altrimenti esistono due pipeline con due capacita'.
        risultato.plan_json = risposta.plan
        grafo = self._verifica(risposta.plan, risultato, opzioni,
                               semantic_source=("llm" if risposta.source == "llm"
                                                else "mock"))

        # La correzione, e una sola. Si tenta solo se c'e' qualcosa che una
        # riscrittura del piano puo' davvero cambiare: un budget esaurito non
        # si corregge cambiando dei nomi.
        rimedio = repair_brief(risultato.report)
        if (opzioni.repair and not risultato.report.ok and rimedio.worth_retrying):
            risultato = self._correggi(planner, richiesta, risposta, rimedio,
                                       risultato, opzioni)
            grafo = risultato.plan

        if costruisci and grafo is not None:
            self._costruisci(grafo, risultato, opzioni)
        risultato.seconds = time.perf_counter() - inizio
        log.info("composizione in %.2fs | planner %s | %d triangoli",
                 risultato.seconds, risultato.planner, risultato.triangles)
        return risultato

    @staticmethod
    def _chiedi(planner, richiesta):
        """La chiamata al planner, con la rete che puo' non esserci.

        Un fornitore giu', senza credito o a limite non deve trasformare una
        generazione in un'eccezione: si scende al planner finto e lo si scrive
        in `source`, cosi' chi guarda il risultato sa con che cosa e' stato
        fatto. Nascondere il ripiego sarebbe peggio che fallire.
        """
        try:
            return planner.plan(richiesta)
        except LLMError as exc:
            provider = getattr(planner, "provider", None)
            if provider is not None and not getattr(provider, "allow_local_fallback", True):
                raise
            log.warning("il planner ha fallito (%s): passo a quello locale", exc)
            risposta = MockPlanner().plan(richiesta)
            risposta.source = "mock_fallback"
            risposta.notes.append("il planner remoto non ha risposto: %s" % str(exc))
            if provider is not None:
                risposta.provenance = provider.provenance()
            return risposta

    def _correggi(self, planner, richiesta, risposta, rimedio,
                  primo: GenerationResult, opzioni: Options) -> GenerationResult:
        """Il secondo e ultimo tentativo.

        Se anche questo non regge si tiene il **migliore dei due**, misurato con
        un punteggio deterministico: preferire sempre l'ultimo vorrebbe dire che
        una correzione puo' solo peggiorare le cose senza che nessuno se ne
        accorga.
        """
        from dataclasses import replace

        from app.core.errors import Report
        from app.core.planner.repair import plan_score

        seconda = self._chiedi(planner, replace(
            richiesta, previous=risposta.plan, feedback=rimedio.to_text(),
            diagnostics=tuple(rimedio.to_dict())))
        candidato = GenerationResult(prompt=primo.prompt, plan_json=seconda.plan,
                                     planner=seconda.source or planner.name,
                                     repaired=True, report=Report(),
                                     options=opzioni)
        self._set_provenance(candidato, seconda.provenance)
        piano = self._risolvi_concept(seconda.plan, candidato, opzioni,
                                       semantic_source=("llm"
                                                        if seconda.source == "llm"
                                                        else "mock"))
        candidato.plan_json = piano
        concept_failed = (candidato.concept_resolution is not None and
                          not candidato.concept_resolution.selected_root_implementation)
        if not concept_failed:
            self._verifica(piano, candidato, opzioni)

        prima = plan_score(primo.report, primo.resolved, primo.plan)
        dopo = plan_score(candidato.report, candidato.resolved, candidato.plan)
        if dopo >= prima:
            primo.report.note(
                "REPAIR_NOT_BETTER", "la correzione non ha migliorato il piano",
                why="punteggio %s prima, %s dopo (piu' basso e' meglio)"
                    % (prima.describe(), dopo.describe()))
            return primo
        candidato.report.note(
            "REPAIRED", "il piano e' stato corretto una volta",
            why="punteggio %s prima, %s dopo" % (prima.describe(), dopo.describe()))
        return candidato

    @staticmethod
    def _set_provenance(result: GenerationResult, provenance: dict | None) -> None:
        """Copia solo metadati sicuri e utili, mai payload o credenziali."""
        data = provenance or {}
        attempts = []
        for attempt in data.get("attempts", ()) or ():
            if not isinstance(attempt, dict):
                continue
            safe = {key: str(attempt.get(key, ""))
                    for key in ("provider", "model", "outcome", "diagnostic",
                                "error_kind", "status_code", "phase")}
            if isinstance(attempt.get("request_metrics"), dict):
                safe["request_metrics"] = dict(attempt["request_metrics"])
            attempts.append(safe)
        result.provenance = {
            "requested_provider": str(data.get("requested_provider", "")),
            "requested_model": str(data.get("requested_model", "")),
            "actual_provider": str(data.get("actual_provider", "")),
            "actual_model": str(data.get("actual_model", "")),
            "failover_count": int(data.get("failover_count", 0) or 0),
            "phase": str(data.get("phase", "")),
            "attempts": attempts,
        }

    def _verifica(self, piano: dict, risultato: GenerationResult,
                  opzioni: Options, *, semantic_source: str = "local"):
        """Schema, grafo, registry, parametri; poi la risoluzione vera.

        E' la **fase comune**: ci passa `generate()`, ci passa `build()`, ci
        passa un piano scritto a mano. Qui dentro un concetto viene
        materializzato e, se non si puo', degradato — una volta sola, per
        tutti, perche' due porte con due capacita' diverse sono due pipeline.

        La risoluzione **fa parte** della verifica: un piano puo' essere
        perfettamente formato e nominare due pezzi che non si incastrano, e
        quello lo sa solo il resolver.
        """
        from app.core.planner.plans import validate_plan
        from app.core.layout import resolve_layout
        from app.core.resolver import resolve
        from app.core.structural import resolve_structural_traits
        from app.core.traits import resolve_traits
        from app.core.archetypes import ConceptResolutionPlan

        saved_resolution = ConceptResolutionPlan.from_dict(
            piano.get("concept_resolution") if isinstance(piano, dict) else None)
        if saved_resolution is not None:
            risultato.concept_resolution = saved_resolution
            if not self._validate_saved_concept(saved_resolution, risultato.report):
                return None

        piano = self._risolvi_concept(piano, risultato, opzioni,
                                      semantic_source=semantic_source)
        risultato.plan_json = piano

        grafo, _ = validate_plan(piano, self.catalog(), style=opzioni.style,
                                 report=risultato.report)
        risultato.plan = grafo
        if grafo is None:
            return None
        if risultato.concept_resolution is not None:
            grafo.concept_resolution = risultato.concept_resolution
        else:
            risultato.concept_resolution = grafo.concept_resolution
        if not self._validate_saved_concept(grafo.concept_resolution,
                                            risultato.report):
            return grafo
        self._adatta(grafo, risultato, opzioni)
        risultato.structural = resolve_structural_traits(
            grafo, self.catalog(), report=risultato.report)
        if not risultato.report.ok:
            return grafo
        risultato.resolved = resolve(grafo, self.catalog(), style=opzioni.style,
                                     budget=self._budget(opzioni),
                                     report=risultato.report)
        risultato.traits = resolve_traits(risultato.resolved, self.catalog(),
                                          report=risultato.report)
        risultato.layout = resolve_layout(risultato.resolved, self.catalog(),
                                          report=risultato.report)
        return grafo

    @staticmethod
    def _budget(opzioni: Options):
        """Il budget chiesto, o quello che questa macchina si puo' permettere.

        Il profilo hardware non e' una preferenza: e' un tetto. Chi passa un
        budget esplicito comanda; chi non ne passa nessuno prende quello del
        profilo invece di quello di riferimento, che su una macchina modesta
        vorrebbe dire costruire e poi accorgersene.
        """
        if opzioni.budget is not None:
            return opzioni.budget
        from app.core.hardware import current

        return current().budget()

    @staticmethod
    def _adatta(grafo, risultato: GenerationResult, opzioni: Options) -> None:
        """Il dettaglio e' una scelta: quello chiesto, o quello del piano.

        Il profilo hardware **non** lo tocca. Sarebbe un secondo meccanismo che
        fa il lavoro del budget, e con due tetti sulla stessa cosa non si sa
        mai quale dei due ha tagliato. La macchina impone un budget di
        triangoli; quante parti costruire lo dice il piano.
        """
        grafo.detail_level = opzioni.detail_level or grafo.detail_level

    def _costruisci(self, piano, risultato: GenerationResult,
                    opzioni: Options) -> None:
        """Effetti e geometria. Il piano puo' arrivare gia' risolto o no."""
        from app.build.assembler import build as assembla
        from app.build.validate import validate as controlla
        from app.core.effect import apply_effects
        from app.core.errors import Report
        from app.core.graph import CompositionGraph

        if risultato.report is None:
            risultato.report = Report()
        if risultato.resolved is None:
            if isinstance(piano, dict):
                self._verifica(piano, risultato, opzioni)
            elif isinstance(piano, CompositionGraph):
                risultato.plan = piano
                self._verifica_grafo(piano, risultato, opzioni)
        if risultato.resolved is None:
            return

        risultato.effects = apply_effects(risultato.resolved, self.catalog(),
                                          report=risultato.report)
        risultato.build = assembla(risultato.effects,
                                   budget=self._budget(opzioni),
                                   report=risultato.report)
        if opzioni.check:
            controlla(risultato.build,
                      style=self.catalog().style(risultato.plan.style
                                                 if risultato.plan else "low_poly"),
                      report=risultato.report)

    def _verifica_grafo(self, grafo, risultato: GenerationResult,
                         opzioni: Options) -> None:
        from app.core.layout import resolve_layout
        from app.core.resolver import resolve
        from app.core.structural import resolve_structural_traits
        from app.core.traits import resolve_traits

        self._adatta(grafo, risultato, opzioni)
        risultato.concept_resolution = getattr(grafo, "concept_resolution", None)
        if not self._validate_saved_concept(risultato.concept_resolution,
                                            risultato.report):
            return
        risultato.structural = resolve_structural_traits(
            grafo, self.catalog(), report=risultato.report)
        if not risultato.report.ok:
            return
        risultato.resolved = resolve(grafo, self.catalog(), style=opzioni.style,
                                     budget=self._budget(opzioni),
                                     report=risultato.report)
        risultato.traits = resolve_traits(risultato.resolved, self.catalog(),
                                          report=risultato.report)
        risultato.layout = resolve_layout(risultato.resolved, self.catalog(),
                                          report=risultato.report)

    def _validate_saved_concept(self, resolution, report) -> bool:
        if resolution is None or not resolution.selected_binding:
            return True
        binding = self.catalog().implementation_binding(resolution.selected_binding)
        if binding is None:
            report.add("SAVED_BINDING_MISSING",
                       "il binding salvato non e' installato: '%s'"
                       % resolution.selected_binding,
                       where="concept_resolution")
            return False
        if binding.implementation != resolution.selected_root_implementation:
            report.add("SAVED_BINDING_CHANGED",
                       "il binding salvato non indica piu' lo stesso root",
                       where=resolution.selected_binding)
            return False
        return True

    def _risolvi_concept(self, piano: dict, risultato: GenerationResult,
                         opzioni: Options, *, semantic_source: str = "local") -> dict:
        """Complete a semantic-only planner output with a backend-selected root."""
        if not isinstance(piano, dict) or not isinstance(piano.get("concept"), dict):
            return piano
        from copy import deepcopy
        from app.core.archetypes import MATCH_PLAN_ROOT, ConceptResolver

        concept = piano["concept"]
        requested = str(concept.get("requested") or risultato.prompt or "").strip()
        resolution = ConceptResolver(self.catalog(),
                                     index=self.component_index()).resolve(
            requested,
            archetypes=concept.get("archetypes") or (),
            profiles=concept.get("profiles") or (),
            adaptations=concept.get("adaptations") or (),
            semantic_source=semantic_source,
            style=opzioni.style)
        risultato.concept_resolution = resolution

        ha_radice = isinstance(piano.get("root"), dict) and piano["root"].get("ref")
        for diagnostic in resolution.diagnostics:
            severity = diagnostic.get("severity", "error")
            # Un concetto sbagliato non deve uccidere una radice valida: se il
            # piano ne porta una, la diagnosi resta ma scende ad avviso. Il
            # modello ha sbagliato una cosa, non tutto.
            if severity == "warning" or ha_radice:
                risultato.report.warn(diagnostic["code"], diagnostic["message"],
                                      where=diagnostic.get("where", ""))
            else:
                risultato.report.add(diagnostic["code"], diagnostic["message"],
                                     where=diagnostic.get("where", ""))

        # Due casi in cui la radice scritta nel piano vince sul concetto:
        # quando il concetto non si e' risolto, e quando si e' risolto **per
        # approssimazione**. Nel secondo il planner ha nominato un pezzo
        # preciso e il risolutore ha tirato a indovinare: fra una scelta e una
        # supposizione si tiene la scelta. Un concetto esatto invece comanda,
        # perche' li' non si sta indovinando niente.
        cede_alla_radice = ha_radice and (not resolution.selected_root_implementation
                                          or resolution.approximate)
        if cede_alla_radice:
            log.info("concept '%s' (%s): uso la radice del piano '%s'",
                     requested, resolution.match or "non risolto",
                     piano["root"].get("ref"))
            resolution.strategy.append("radice fornita dal piano")
            resolution.provenance["fallback"] = "plan_root"
            resolution.provenance["superseded_root_implementation"] = \
                resolution.selected_root_implementation
            resolution.selected_root_implementation = str(piano["root"]["ref"])
            resolution.match = MATCH_PLAN_ROOT
            # Nessun binding regge piu' questa scelta: tenerlo farebbe dire a
            # `_validate_saved_concept` che il binding «non indica piu' lo
            # stesso root», che e' vero e irrilevante — non e' stato un binding
            # a decidere.
            resolution.selected_binding = ""
            return {k: v for k, v in piano.items() if k != "concept"}
        if not resolution.selected_root_implementation:
            return piano

        completed = deepcopy(piano)
        root = dict(completed.get("root") or {})
        component = self.catalog().component(resolution.selected_root_implementation)
        root["id"] = root.get("id") or (component.name if component else "root")
        root["ref"] = resolution.selected_root_implementation
        params = dict(resolution.materialized_params)
        params.update(root.get("params") or {})
        if params:
            root["params"] = params
        completed["root"] = root
        completed["traits"] = self._merge_inferred_requests(
            resolution.materialized_traits, completed.get("traits") or {})
        completed["structural_traits"] = self._merge_inferred_requests(
            resolution.materialized_structural_traits,
            completed.get("structural_traits") or {}, structural=True)
        return completed

    @staticmethod
    def _merge_inferred_requests(defaults, explicit, structural: bool = False):
        explicit = list(explicit or []) if isinstance(explicit, list) else []
        keys = set()
        for item in explicit:
            if not isinstance(item, dict):
                continue
            target = item.get("target") if structural else ""
            target_key = repr(sorted(target.items())) if isinstance(target, dict) else repr(target)
            default_scope = "local" if structural else "subtree"
            keys.add((str(item.get("trait") or ""), str(item.get("on") or "root"),
                      str(item.get("scope") or default_scope), target_key))
        out = []
        for item in defaults or ():
            if not isinstance(item, dict):
                continue
            target = item.get("target") if structural else ""
            target_key = repr(sorted(target.items())) if isinstance(target, dict) else repr(target)
            default_scope = "local" if structural else "subtree"
            key = (str(item.get("trait") or ""), str(item.get("on") or "root"),
                   str(item.get("scope") or default_scope), target_key)
            if key not in keys:
                out.append(dict(item))
        out.extend(item for item in explicit if isinstance(item, dict))
        return out

    # ------------------------------------------------------------- stato #
    @property
    def current(self) -> Version | None:
        if 0 <= self.cursor < len(self.history):
            return self.history[self.cursor]
        return None

    @property
    def current_plan(self):
        """Il piano della versione corrente: un `CompositionGraph`."""
        v = self.current
        return v.plan if v else None

    @property
    def scene(self) -> Scene | None:
        v = self.current
        return v.scene if v else None

    @property
    def result(self) -> GenerationResult | None:
        v = self.current
        return v.result if v else None

    def can_undo(self) -> bool:
        return self.cursor > 0

    def can_redo(self) -> bool:
        return self.cursor < len(self.history) - 1

    def undo(self) -> Version | None:
        if self.can_undo():
            self.cursor -= 1
        return self.current

    def redo(self) -> Version | None:
        if self.can_redo():
            self.cursor += 1
        return self.current

    def goto(self, index: int) -> Version | None:
        if 0 <= index < len(self.history):
            self.cursor = index
        return self.current

    def _push(self, version: Version) -> Version:
        # una nuova azione dopo un undo taglia il ramo successivo
        self.history = self.history[: self.cursor + 1]
        self.history.append(version)
        self.cursor = len(self.history) - 1
        if self._autosave is not None:
            # Nessun timer: il momento buono per salvare e' subito dopo che
            # l'utente ha fatto qualcosa, ed e' l'unico momento in cui c'e'
            # qualcosa di nuovo da salvare.
            self._autosave.maybe_save()
        return version

    def restore(self, payload: dict) -> Version:
        """Rimette in cronologia una versione salvata, ricostruendola.

        Ricostruire e non rileggere e' il punto del formato: un progetto
        riaperto con un plugin aggiornato da' il modello **di adesso**, e se
        qualcosa non si incastra piu' lo si vede subito.
        """
        opzioni = Options.from_dict(payload.get("options"))
        risultato = self.build(payload.get("graph") or {}, opzioni)
        versione = Version(
            label=payload.get("label") or payload.get("prompt", "")[:48] or "modello",
            plan=risultato.plan, scene=risultato.scene(self.catalog()),
            message=payload.get("message", ""),
            seconds=float(payload.get("seconds", 0.0) or 0.0),
            prompt=payload.get("prompt", ""), options=opzioni.to_dict(),
            result=risultato)
        if risultato.plan is None:
            raise ValueError("piano non ricostruibile: %s"
                             % risultato.report.describe())
        return self._push(versione)

    # ---------------------------------------------------------- recupero #
    def start_autosave(self, interval: float | None = None):
        """Accende la copia di sicurezza periodica."""
        from app.core.recovery import INTERVAL, AutoSave

        self._autosave = AutoSave(self, interval=interval or INTERVAL)
        return self._autosave

    def stop_autosave(self, clean: bool = True) -> None:
        """Chiusura regolare: da qui in poi non c'e' niente da recuperare."""
        if self._autosave is not None:
            if clean:
                self._autosave.close()
            self._autosave = None

    # ---------------------------------------------------------- libreria #
    def save_to_library(self, name: str = "", tags=(), preview=None) -> AssetRecord:
        """Mette l'oggetto corrente nella libreria, piano compreso."""
        versione = self.current
        if versione is None or versione.scene is None:
            raise ValueError("nessun modello da salvare")
        return self.library.save(versione.scene, name=name, tags=tags,
                                 preview=preview, plan=versione.plan,
                                 prompt=versione.prompt,
                                 options=versione.options)

    def load_from_library(self, asset_id: str) -> Version:
        """Riporta un asset nella sessione come nuova versione, ancora modificabile."""
        record = self.library.get(asset_id)
        if record is None:
            raise KeyError("asset inesistente: %s" % asset_id)
        payload = self.library.load_plan(asset_id)
        versione = self.restore({**payload, "label": record.name,
                                 "message": "Caricato dalla libreria: %s"
                                            % record.name})
        log.info("asset caricato: %s | %s", asset_id,
                 versione.scene.summary() if versione.scene else "senza scena")
        return versione

    # ---------------------------------------------------------- progetto #
    def save_project(self, path, name: str = "", preview=None):
        """Salva l'intera cronologia in un file .my3d."""
        from app.core import project

        return project.save(self, path, name=name, preview=preview)

    def open_project(self, path):
        """Sostituisce la sessione con quella salvata nel progetto."""
        from app.core import project

        project.load(path, session=self)
        return self.current

    # ---------------------------------------------------------- risultato #
    def checks(self) -> list[Check]:
        s = self.scene
        return validate(s) if s else []

    def export(self, path: str | Path, textured: bool | None = None) -> Path:
        s = self.scene
        if s is None:
            raise ValueError("nessun modello da esportare")
        return export(s, path, textured=textured)

    def skeleton(self):
        """Scheletro del modello corrente: i giunti sono gli innesti veri."""
        from app.anim.skeleton import from_scene

        s = self.scene
        return from_scene(s) if s is not None else from_scene(None)

    def animations(self) -> list[str]:
        """Le animazioni che questo modello puo' davvero fare."""
        from app.anim.clip import default_clips

        skeleton = self.skeleton()
        return [c.name for c in default_clips(skeleton)] if skeleton.joints else []

    def export_animated(self, path: str | Path, clips: list[str] | None = None) -> Path:
        """Esporta un glTF con la gerarchia delle parti e le animazioni."""
        from app.anim.gltf import export_animated

        s = self.scene
        if s is None:
            raise ValueError("nessun modello da esportare")
        return export_animated(s, path, clips)
