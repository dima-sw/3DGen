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

from app.ai.provider import LLMProvider, make_provider
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
    resolved: Any = None
    effects: Any = None
    build: Any = None
    report: Any = None
    planner: str = ""
    repaired: bool = False
    seconds: float = 0.0
    options: Any = None

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
        if self.resolved is None:
            return []
        righe = []
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
        if self.build is not None:
            pezzi.append(self.build.describe())
        if self.report is not None and len(self.report):
            pezzi.append(self.report.describe())
        return "\n".join(pezzi)

    def to_dict(self) -> dict:
        return {"prompt": self.prompt, "planner": self.planner,
                "repaired": self.repaired, "seconds": round(self.seconds, 3),
                "plan": self.plan_json,
                "triangles": self.triangles,
                "explain": self.explain(), "changes": self.changes(),
                "skipped": self.skipped(),
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

    def vocabulary(self, style: str = ""):
        """Cio' che il planner puo' nominare. Cambia se cambiano i plugin."""
        from app.core.planner.vocabulary import build_vocabulary

        stile = style or "low_poly"
        if stile not in self._vocabolari:
            self._vocabolari[stile] = build_vocabulary(self.catalog(), style=stile)
        return self._vocabolari[stile]

    def _planner(self):
        if self.planner is None:
            from app.core.planner.planner import make_planner

            self.planner = make_planner(self.provider)
        return self.planner

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
        return Version(label=risultato.prompt.strip()[:48] or "modello",
                       plan=risultato.plan,
                       scene=risultato.scene(self.catalog()),
                       message="; ".join(risultato.explain()[:3]),
                       seconds=risultato.seconds, prompt=risultato.prompt,
                       options=opzioni.to_dict(), result=risultato)

    def _compose(self, prompt: str, opzioni: Options,
                 costruisci: bool) -> GenerationResult:
        from app.core.errors import Report
        from app.core.planner.planner import PlanRequest
        from app.core.planner.repair import repair_brief

        inizio = time.perf_counter()
        vocabolario = self.vocabulary(opzioni.style)
        planner = self._planner()
        richiesta = PlanRequest(prompt=prompt, vocabulary=vocabolario,
                                seed=opzioni.seed, style=opzioni.style,
                                detail_level=opzioni.detail_level)

        risposta = self._chiedi(planner, richiesta)
        risultato = GenerationResult(prompt=prompt, plan_json=risposta.plan,
                                     planner=risposta.source or planner.name,
                                     report=Report(), options=opzioni)
        for nota in risposta.notes:
            risultato.report.note("PLANNER_NOTE", nota)
        grafo = self._verifica(risposta.plan, risultato, opzioni)

        # La correzione, e una sola. Si tenta solo se c'e' qualcosa che una
        # riscrittura del piano puo' davvero cambiare: un budget esaurito non
        # si corregge cambiando dei nomi.
        rimedio = repair_brief(risultato.report)
        if opzioni.repair and not risultato.report.ok and rimedio.worth_retrying:
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
        except Exception as exc:                          # noqa: BLE001
            log.warning("il planner ha fallito (%s): passo a quello locale", exc)
            risposta = MockPlanner().plan(richiesta)
            risposta.source = "mock_fallback"
            risposta.notes.append("il planner remoto non ha risposto: %s" % exc)
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
        self._verifica(seconda.plan, candidato, opzioni)

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

    def _verifica(self, piano: dict, risultato: GenerationResult,
                  opzioni: Options):
        """Schema, grafo, registry, parametri; poi la risoluzione vera.

        La risoluzione **fa parte** della verifica: un piano puo' essere
        perfettamente formato e nominare due pezzi che non si incastrano, e
        quello lo sa solo il resolver.
        """
        from app.core.planner.plans import validate_plan
        from app.core.resolver import resolve

        grafo, _ = validate_plan(piano, self.catalog(), style=opzioni.style,
                                 report=risultato.report)
        risultato.plan = grafo
        if grafo is None:
            return None
        self._adatta(grafo, risultato, opzioni)
        risultato.resolved = resolve(grafo, self.catalog(), style=opzioni.style,
                                     budget=self._budget(opzioni),
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
        from app.core.resolver import resolve

        self._adatta(grafo, risultato, opzioni)
        risultato.resolved = resolve(grafo, self.catalog(), style=opzioni.style,
                                     budget=self._budget(opzioni),
                                     report=risultato.report)

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
