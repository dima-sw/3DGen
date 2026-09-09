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

## Due strade, per ora

`generate`, `plan` e `build` sono la strada nuova, e restituiscono un
`GenerationResult`. `generate_legacy` e cio' che le gira intorno — libreria,
progetti, animazione, varianti — sono la strada storica, quella dei template e
del campo implicito, che regge ancora l'interfaccia. Convivono con nomi diversi
apposta: finche' non e' migrato tutto, si deve poter vedere da ogni chiamata
quale delle due si sta usando.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.ai.planner import edit_plan, generate_plan, revariate
from app.assets.library import AssetLibrary, AssetRecord
from app.ai.provider import LLMProvider, make_provider
from app.build.builder import build_scene
from app.build.exporter import Check, export, validate
from app.core.logging_setup import get
from app.core.scene import Scene
from app.core.planner.planner import MockPlanner
from app.core.spec import GenerationPlan

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


@dataclass
class GenerationResult:
    """Che cosa e' stato chiesto, che cosa e' stato scelto, che cosa e' uscito.

    Tutti gli strati restano accessibili — piano, risolto, effetti, geometria —
    perche' senza il primo non si capisce il secondo e senza il secondo non si
    capisce il terzo. E' la stessa regola che vale fra `graph` e `resolved`.
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

    def scene(self):
        """La geometria come scena trimesh, un nodo per componente."""
        return self.build.scene() if self.build is not None else None

    def mesh(self):
        return self.build.combined() if self.build is not None else None

    # ---------------------------------------------------------- spiegazione #
    def explain(self) -> list[str]:
        """Perche' il modello e\' venuto cosi\'.

        Una riga per scelta importante, in un italiano che si puo\' mostrare:
        quale componente e\' stato usato, per quale capability, e se ha preso il
        posto di qualcos\'altro. Serve a chi guarda un modello e non capisce da
        dove venga un pezzo — e servira\' con migliaia di plugin installati.
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
                if collegamento.capability else "si attacca a '%s'" % collegamento.parent_socket
            riga = "'%s' scelto per '%s': %s (%s)" % (
                nodo.ref, nodo.id, motivo, collegamento.how)
            if nodo.substituted:
                riga += ", al posto di '%s'" % nodo.swapped_from
            righe.append(riga)
        return righe

    def changes(self) -> list[str]:
        """Cosa e\' cambiato rispetto a cio\' che i componenti direbbero da soli."""
        if self.resolved is None:
            return []
        from app.core.graph import FROM_DEFAULT

        righe = []
        for nodo in self.resolved.walk():
            for nome in sorted(nodo.sources):
                voce = nodo.sources[nome]
                if voce.source == FROM_DEFAULT and not voce.modified:
                    continue
                righe.append("%s.%s %s" % (nodo.id, nome, voce.describe()))
        return righe

    def skipped(self) -> list[str]:
        """Cosa non e\' entrato nel modello, e resta da spiegare."""
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
    label: str
    plan: GenerationPlan
    scene: Scene
    message: str
    seconds: float


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
        risultato = GenerationResult(planner="nessuno")
        self._costruisci(plan, risultato, opzioni)
        risultato.seconds = time.perf_counter() - inizio
        return risultato

    def generate(self, prompt: str, options: Options | None = None) -> GenerationResult:
        """Il giro completo: frase, piano, risoluzione, effetti, geometria.

        E' l'unica porta. La UI, la riga di comando e un test passano di qui, e
        quello che ne esce e' sempre lo stesso oggetto: il modello, con accanto
        tutto cio' che serve a spiegarlo.
        """
        return self._compose(prompt, options or Options(), costruisci=True)

    # ------------------------------------------------------------- interno #
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
                                     report=Report())
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
            risposta.notes.append("il planner remoto non ha risposto: %s" % exc)
            return risposta

    def _correggi(self, planner, richiesta, risposta, rimedio, primo: GenerationResult,
                  opzioni: Options) -> GenerationResult:
        """Il secondo e ultimo tentativo.

        Se anche questo non regge si tiene il **migliore dei due**: un piano con
        tre problemi non e' migliorato da una correzione che ne lascia cinque, e
        preferire sempre l'ultimo vorrebbe dire che una correzione puo' solo
        peggiorare le cose senza che nessuno se ne accorga.
        """
        from dataclasses import replace

        from app.core.errors import Report

        seconda = self._chiedi(planner, replace(
            richiesta, previous=risposta.plan, feedback=rimedio.to_text(),
            diagnostics=tuple(rimedio.to_dict())))
        candidato = GenerationResult(prompt=primo.prompt, plan_json=seconda.plan,
                                     planner=seconda.source or planner.name,
                                     repaired=True, report=Report())
        self._verifica(seconda.plan, candidato, opzioni)
        if len(candidato.report.errors()) >= len(primo.report.errors()):
            primo.report.note("REPAIR_NOT_BETTER",
                              "la correzione non ha migliorato il piano",
                              why="%d problemi prima, %d dopo"
                                  % (len(primo.report.errors()),
                                     len(candidato.report.errors())))
            return primo
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
        if opzioni.detail_level:
            grafo.detail_level = opzioni.detail_level
        risultato.resolved = resolve(grafo, self.catalog(), style=opzioni.style,
                                     budget=opzioni.budget,
                                     report=risultato.report)
        return grafo

    def _costruisci(self, piano, risultato: GenerationResult,
                    opzioni: Options) -> None:
        """Effetti e geometria. Il piano puo' arrivare gia' risolto o no."""
        from app.core.effect import apply_effects
        from app.build.assembler import build as assembla
        from app.build.validate import validate as controlla
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
        risultato.build = assembla(risultato.effects, budget=opzioni.budget,
                                   report=risultato.report)
        if opzioni.check:
            controlla(risultato.build,
                      style=self.catalog().style(risultato.plan.style
                                                 if risultato.plan else "low_poly"),
                      report=risultato.report)

    def _verifica_grafo(self, grafo, risultato: GenerationResult,
                        opzioni: Options) -> None:
        from app.core.resolver import resolve

        if opzioni.detail_level:
            grafo.detail_level = opzioni.detail_level
        risultato.resolved = resolve(grafo, self.catalog(), style=opzioni.style,
                                     budget=opzioni.budget,
                                     report=risultato.report)

    # ------------------------------------------------------------- stato #
    @property
    def current(self) -> Version | None:
        if 0 <= self.cursor < len(self.history):
            return self.history[self.cursor]
        return None

    @property
    def current_plan(self) -> GenerationPlan | None:
        """Il `GenerationPlan` della versione corrente, sulla strada storica.

        Si chiamava `plan`, e ha lasciato il nome al metodo che fa un piano di
        composizione a partire da una frase. Sono due cose diverse: questo e'
        lo stato di una sessione, quello e' un passo della pipeline.
        """
        v = self.current
        return v.plan if v else None

    @property
    def scene(self) -> Scene | None:
        v = self.current
        return v.scene if v else None

    def can_undo(self) -> bool:
        return self.cursor > 0

    def can_redo(self) -> bool:
        return self.cursor < len(self.history) - 1

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

    # ------------------------------------------------- pipeline storica #
    def generate_legacy(self, prompt: str, seed: int | None = None) -> Version:
        """La generazione dei template e del campo implicito.

        Si chiama cosi' perche' deve vedersi. E' la strada da cui si viene:
        `GenerationPlan`, template, strategie, `Scene` — ed e' ancora l'unica
        che regge la libreria, i progetti, le varianti e l'animazione. La
        strada nuova e' `generate`, e restituisce un `GenerationResult`.
        """
        t0 = time.perf_counter()
        plan, message = generate_plan(prompt, self.provider, seed)
        scene = build_scene(plan)
        dt = time.perf_counter() - t0
        log.info("generazione completata in %.2fs | %s", dt, scene.summary())
        return self._push(Version(label=prompt.strip()[:48] or plan.template,
                                  plan=plan, scene=scene, message=message, seconds=dt))

    def generate_from_image(self, image, prompt: str = "", seed: int | None = None,
                            front=None) -> Version:
        """Genera partendo da un'immagine di riferimento.

        L'immagine non diventa mai geometria: fornisce una descrizione (se c'e'
        un modello vision) e delle misure (sempre). Il resto della pipeline e'
        identico, cosi' il risultato resta modificabile, variabile ed
        esportabile come qualunque altro.
        """
        from app.ai import reference

        t0 = time.perf_counter()
        text, hints = reference.prompt_from_image(image, prompt, self.provider,
                                                  front=front)
        plan, message = generate_plan(text, self.provider, seed)
        plan.prompt = text
        reference.apply_hints(plan, hints)
        scene = build_scene(plan)
        dt = time.perf_counter() - t0
        log.info("generazione da immagine in %.2fs | %s", dt, scene.summary())
        label = (prompt.strip() or text)[:48]
        return self._push(Version(label=label, plan=plan, scene=scene,
                                  message="%s | riferimento: %s"
                                          % (message, hints.describe()),
                                  seconds=dt))

    def modify(self, prompt: str) -> Version:
        if self.current_plan is None:
            return self.generate_legacy(prompt)
        t0 = time.perf_counter()
        plan, message = edit_plan(prompt, self.current_plan, self.provider)
        scene = build_scene(plan)
        dt = time.perf_counter() - t0
        log.info("modifica completata in %.2fs | %s", dt, scene.summary())
        return self._push(Version(label=prompt.strip()[:48] or "modifica",
                                  plan=plan, scene=scene, message=message, seconds=dt))

    def revariate(self, seed: int | None = None) -> Version:
        """Altra variante dello stesso oggetto: nessuna chiamata all'LLM."""
        if self.current_plan is None:
            raise ValueError("nessun modello da variare")
        t0 = time.perf_counter()
        plan, message = revariate(self.current_plan, seed)
        scene = build_scene(plan)
        dt = time.perf_counter() - t0
        log.info("variante in %.2fs | %s", dt, scene.summary())
        base = self.current.label if self.current else "variante"
        base = base.split(" [var")[0]
        return self._push(Version(label="%s [var %d]" % (base, plan.seed % 10000),
                                  plan=plan, scene=scene, message=message, seconds=dt))

    def rebuild(self) -> Version | None:
        """Ricostruisce la scena dal piano corrente (dopo un cambio manuale)."""
        v = self.current
        if v is None:
            return None
        v.scene = build_scene(v.plan)
        return v

    # ---------------------------------------------------------- libreria #
    def save_to_library(self, name: str = "", tags=(), preview=None) -> AssetRecord:
        """Mette l'oggetto corrente nella libreria, piano compreso."""
        scene = self.scene
        if scene is None:
            raise ValueError("nessun modello da salvare")
        return self.library.save(scene, name=name, tags=tags, preview=preview)

    def load_from_library(self, asset_id: str) -> Version:
        """Riporta un asset nella sessione come nuova versione, ancora modificabile."""
        record = self.library.get(asset_id)
        if record is None:
            raise KeyError("asset inesistente: %s" % asset_id)
        t0 = time.perf_counter()
        plan = self.library.load_plan(asset_id)
        scene = build_scene(plan)
        dt = time.perf_counter() - t0
        log.info("asset caricato: %s | %s", asset_id, scene.summary())
        return self._push(Version(label=record.name, plan=plan, scene=scene,
                                  message="Caricato dalla libreria: %s" % record.name,
                                  seconds=dt))

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
        """Scheletro del modello corrente, vuoto se non viene da un assemblaggio."""
        from app.anim.skeleton import from_scene

        s = self.scene
        return from_scene(s) if s is not None else from_scene(None)

    def animations(self) -> list[str]:
        """Le animazioni che questo modello puo' davvero fare."""
        from app.anim.clip import default_clips

        skeleton = self.skeleton()
        return [c.name for c in default_clips(skeleton)] if skeleton.joints else []

    def export_animated(self, path: str | Path, clips: list[str] | None = None) -> Path:
        """Esporta un glTF con la gerarchia delle parti e le animazioni.

        Solo per gli assemblaggi: un modello da template non ha un grafo di
        parti, quindi non ha giunti da animare.
        """
        from app.anim.gltf import export_animated

        s = self.scene
        if s is None:
            raise ValueError("nessun modello da esportare")
        return export_animated(s, path, clips)
