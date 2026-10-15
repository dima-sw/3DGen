"""Teach 3DGen, come chiamate. La finestra e' un cliente, non la via.

Stessa regola di V6 (regola 28 di `PROJECT-INDEX`): ogni operazione esiste come
metodo, niente qui importa Qt, e un test insegna un concetto intero senza
aprire una finestra. V6 l'ha fatto perche' «un domani che decompone un concetto
con un modello deve poter costruire un plugin senza pilotare widget»: questo e'
quel domani, e la strada c'era.

## Che cosa questo livello possiede, e che cosa riusa

Possiede quattro cose e nient'altro: il **processo** (`TeachProject`), le
**evidenze** di copertura (`coverage.py`), la **specifica** tecnica
(`spec.py`) e i **prompt** (`prompts.py`). Tutto il resto e' riuso:

    retrieval        `Session.component_index()` - l'indice di V1
    costruzione      `Session.build` - la pipeline vera, mai una simulazione
    laboratorio      `ComponentLab` di V6, su qualunque componente installato
    variant          `VariantRecipe` di V6, che e' cio' che fa diventare verde
                     un giallo senza duplicare geometria
    emissione        `AuthoringService` di V6 scrive il composite della radice:
                     un secondo emettitore di plugin dati sarebbe un secondo
                     formato che divergera'
    installazione    `Session.reload_plugins()` di V6
    validazione      il loader dei plugin dati, `Registry.verify()`, il
                     resolver, il quality gate, il retrieval

## L'AI propone, l'utente decide, e il codice lo rende vero

Nessun metodo che importa una risposta di un modello scrive `VALIDATED`. Una
raccomandazione diventa `SuitabilityRecord`; i parametri suggeriti diventano
valori da provare nel laboratorio; la copertura cambia soltanto in
`accept_candidate`, `save_variant`, `accept_artifact` e `set_coverage` — quattro
metodi che un utente (o una validazione deterministica) chiama. §14 e §43.

## Niente lavoro in background

§36 lo vieta e il livello non ne ha: ogni passo e' una chiamata che ritorna. Il
ciclo e' `next_node()` + `advance()`, e chi lo guida — la finestra, un test, un
tool — decide quando fare il passo successivo.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.authoring.lab import ComponentLab
from app.authoring.model import check_name
from app.authoring.variant import VariantRecipe
from app.core.errors import ERROR, INFO, WARNING, Report
from app.teach import coverage as cov
from app.teach import errors, prompts, staging
from app.teach.errors import TeachError
from app.teach.knowledge import TeachKnowledge
from app.teach.model import (BACKENDS, BY_DETERMINISTIC, BY_USER, CANDIDATE,
                             COMPOSITE, COVERAGE, FROM_GENERATED, FROM_LIBRARY,
                             FROM_VARIANT, LEARNED, LEARNING, MISSING, PROXY,
                             SUITABILITY, VALIDATED, ArtifactRecord, Attempt,
                             Exchange, Solution, SuitabilityRecord, TeachNode,
                             TeachProject, build_tree, slug)
from app.teach.schema import SCHEMAS
from app.teach.spec import (build_queue, build_spec, next_buildable,
                            recommend_backend)

# Le specie di scambio. Gli stessi nomi di `SCHEMAS`, piu' i due che non hanno
# uno schema perche' la risposta non e' JSON (la riparazione lo ha).
DECOMPOSITION = "decomposition"
REFINEMENT = "refinement"
SUITABILITY_KIND = "suitability"
DEEP = "deep"
VISUAL = "visual"
IMPLEMENTATION = "implementation"
REPAIR = "repair"

MANUAL = "manual"
PROVIDER = "provider"

MAX_REPAIRS = 1          # §34: una riparazione per tentativo, nessun ciclo


@dataclass
class PromptBundle:
    """Un prompt pronto: da copiare, o da mandare a un provider. Lo stesso.

    §5 chiede che le due modalita' non divergano, e il modo di garantirlo e'
    che siano **lo stesso oggetto**: `text` e' cio' che l'utente copia,
    `system`/`user`/`schema` e' cio' che un provider riceve, e nessuno dei due
    e' derivato dall'altro per approssimazione.
    """

    kind: str
    node: str = ""
    system: str = ""
    user: str = ""
    schema: dict = field(default_factory=dict)

    @property
    def text(self) -> str:
        return prompts.render(self.system, self.user)

    @property
    def characters(self) -> int:
        return len(self.text)

    def describe(self) -> str:
        return "%s%s | %d caratteri" % (self.kind,
                                        (" " + self.node) if self.node else "",
                                        self.characters)


@dataclass
class TeachReport:
    """Il referto di un passo: diagnostiche vere, per gravita'."""

    report: Report = field(default_factory=Report)
    detail: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.report.ok

    def errors(self) -> list:
        return [d for d in self.report.sorted() if d.severity == ERROR]

    def warnings(self) -> list:
        return [d for d in self.report.sorted() if d.severity == WARNING]

    def notes(self) -> list:
        return [d for d in self.report.sorted() if d.severity == INFO]

    def by_category(self) -> dict:
        return {ERROR: self.errors(), WARNING: self.warnings(), INFO: self.notes()}

    def rows(self) -> list[dict]:
        return [{"severity": d.severity, "code": d.code, "where": d.where,
                 "message": d.message, "why": d.why,
                 "alternatives": list(d.alternatives)}
                for d in self.report.sorted()]

    def describe(self) -> str:
        return "%d errori, %d avvisi, %d note" % (len(self.errors()),
                                                  len(self.warnings()),
                                                  len(self.notes()))


@dataclass
class CompletionReport:
    """Perche' un concetto e' (o non e') `LEARNED`. §37, voce per voce."""

    mandatory_validated: bool = False
    counts_satisfied: bool = False
    root_installed: bool = False
    root_builds: bool = False
    root_retrievable: bool = False
    validation_ok: bool = False
    missing: tuple[str, ...] = ()
    triangles: int = 0
    root_component: str = ""
    report: Report = field(default_factory=Report)

    @property
    def learned(self) -> bool:
        return all((self.mandatory_validated, self.counts_satisfied,
                    self.root_installed, self.root_builds,
                    self.root_retrievable, self.validation_ok))

    def rows(self) -> list[tuple[str, bool]]:
        return [("ogni mandatory rilevante e' VALIDATED", self.mandatory_validated),
                ("i count sono soddisfatti nel composite", self.counts_satisfied),
                ("il composite della radice e' installato", self.root_installed),
                ("il composite della radice costruisce", self.root_builds),
                ("la radice e' trovabile dal retrieval", self.root_retrievable),
                ("la validazione e' ok", self.validation_ok)]

    def describe(self) -> str:
        righe = ["%s %s" % ("si" if ok else "no", what) for what, ok in self.rows()]
        if self.missing:
            righe.append("mancano: %s" % ", ".join(self.missing))
        righe.append("-> %s" % (LEARNED if self.learned else LEARNING))
        return "\n".join(righe)


class TeachService:
    """Insegnare un concetto a 3DGen, un passo per chiamata."""

    def __init__(self, session=None, project: TeachProject | None = None, *,
                 knowledge: TeachKnowledge | None = None,
                 staging_root=None) -> None:
        from app.core.session import Session

        self.session = session if session is not None else Session()
        self.project = project
        self.knowledge = knowledge if knowledge is not None else TeachKnowledge()
        self._staging_root = Path(staging_root) if staging_root else None
        self._owned_staging = staging_root is None
        self._artifacts: dict[str, staging.StagedArtifact] = {}
        self._labs: dict[str, ComponentLab] = {}
        self._project_path: Path | None = None

    # --------------------------------------------------------- il progetto #
    def create_project(self, concept: str, *, description: str = "",
                       style: str = "low_poly", style_target: str = "",
                       detail_target: int = 2, destination: str = "",
                       plugin_id: str = "") -> TeachProject:
        """Un progetto nuovo. Non tocca niente di installato."""
        self.project = TeachProject(concept=concept, description=description,
                                    style=style, style_target=style_target,
                                    detail_target=detail_target,
                                    destination=destination,
                                    plugin_id=plugin_id or slug(concept, "concept"))
        self._artifacts = {}
        self._labs = {}
        self.record_fingerprints()
        return self.project

    def save_project(self, path=None) -> Path:
        project = self._project()
        target = Path(path) if path else self._project_path
        if target is None:
            target = Path(project.destination or Path(tempfile.gettempdir())) / (
                slug(project.concept, "concept"))
        for key, artifact in self._artifacts.items():
            project.artifacts[key] = artifact.record()
        saved = project.save(target)
        self._project_path = saved
        return saved

    def load_project(self, path) -> TeachProject:
        """Riapre un progetto. Gli artefatti in staging si ritrovano dal disco.

        §44 chiede che dopo una riapertura ci siano ancora gerarchia, stati,
        candidati, implementazioni scelte, ricette, prompt, risposte,
        validazione e artefatti generati. I primi otto stanno nel file; il nono
        sta nelle cartelle che il file nomina, e un artefatto la cui cartella e'
        sparita resta nel progetto come **record** con `available = False`,
        invece di diventare un'eccezione.
        """
        self.project = TeachProject.load(path)
        self._project_path = Path(path)
        self._artifacts = {}
        self._labs = {}
        for key, record in self.project.artifacts.items():
            rebuilt = self._artifact_from_record(record)
            if rebuilt is not None:
                self._artifacts[key] = rebuilt
        return self.project

    def _artifact_from_record(self, record: ArtifactRecord):
        if not record.available:
            return None
        container = Path(record.path)
        plugin = container / (record.plugin_id or "")
        files = []
        for relative in record.files:
            source = plugin / relative
            if source.is_file():
                files.append(staging.StagedFile(
                    path=relative, content=source.read_text(encoding="utf-8-sig")))
        if not files:
            return None
        return staging.StagedArtifact(
            id=record.id, node=record.node, kind=record.kind,
            container=container, path=plugin, plugin_id=record.plugin_id,
            component_id=self._component_id_of(record),
            files=tuple(files),
            inspections=tuple(staging.inspect_python(plugin / f.path)
                              for f in files if f.python),
            notes=record.notes, trusted=record.trusted)

    def _component_id_of(self, record: ArtifactRecord) -> str:
        node = self.project.node(record.node) if self.project else None
        if node is None:
            return ""
        spec = self.spec(node.id)
        return spec.component_id

    def record_fingerprints(self) -> dict:
        """L'identita' dei plugin adesso: `id -> version#fingerprint` (§45).

        Non si duplicano i plugin nel progetto: si registra la loro identita',
        con gli stessi meccanismi di V4, cosi' un componente usato durante il
        Teach che poi cambia si puo' **rilevare**.
        """
        project = self._project()
        registry = self.session.catalog()
        project.fingerprints = {
            info.id: "%s#%s" % (info.version, info.fingerprint or "")
            for info in registry.plugins()}
        return dict(project.fingerprints)

    def changed_components(self) -> list[dict]:
        """I componenti usati nel Teach i cui plugin non sono piu' gli stessi."""
        project = self._project()
        registry = self.session.catalog()
        out: list[dict] = []
        for node in project.nodes():
            state = project.state(node.id)
            if state.solution is None:
                continue
            plugin = state.solution.ref.partition(":")[0]
            if project.owns(state.solution.ref):
                continue
            before = project.fingerprints.get(plugin)
            info = registry.plugin(plugin)
            if info is None:
                out.append({"node": node.id, "ref": state.solution.ref,
                            "plugin": plugin, "was": before or "",
                            "now": "", "change": "PLUGIN_MISSING"})
                continue
            now = "%s#%s" % (info.version, info.fingerprint or "")
            if before is not None and before != now:
                change = ("PLUGIN_VERSION_CHANGED"
                          if before.partition("#")[0] != info.version
                          else "PLUGIN_CONTENT_CHANGED")
                out.append({"node": node.id, "ref": state.solution.ref,
                            "plugin": plugin, "was": before, "now": now,
                            "change": change})
        return out

    # -------------------------------------------------- i due passi dell'AI #
    def decomposition_prompt(self) -> PromptBundle:
        """Pass 1 (§4): solo ontologia. Il prompt e' identico nelle due modalita'."""
        project = self._project()
        system, user = prompts.decomposition_prompt(
            project.concept, style_target=project.style_target,
            detail_target=project.detail_target, description=project.description)
        bundle = PromptBundle(kind=DECOMPOSITION, system=system, user=user,
                              schema=SCHEMAS[DECOMPOSITION])
        project.add_exchange(Exchange(kind=DECOMPOSITION, prompt=bundle.text))
        return bundle

    def import_decomposition(self, raw) -> TeachReport:
        """Valida e importa la gerarchia. **Non esegue niente** (§6)."""
        return self._import_hierarchy(raw, kind=DECOMPOSITION)

    def refinement_prompt(self) -> PromptBundle:
        """Pass 2 (§7): la stessa domanda, con la prima risposta davanti."""
        project = self._project()
        if project.root is None:
            raise TeachError(errors.NO_HIERARCHY,
                             "non c'e' una gerarchia da raffinare: importa "
                             "prima la decomposizione")
        system, user = prompts.refinement_prompt(project)
        bundle = PromptBundle(kind=REFINEMENT, system=system, user=user,
                              schema=SCHEMAS[REFINEMENT])
        project.add_exchange(Exchange(kind=REFINEMENT, prompt=bundle.text))
        return bundle

    def import_refinement(self, raw) -> TeachReport:
        """Importa il raffinamento. L'utente puo' saltarlo: §7 lo dice."""
        return self._import_hierarchy(raw, kind=REFINEMENT)

    def _import_hierarchy(self, raw, *, kind: str) -> TeachReport:
        project = self._project()
        data = self._as_json(raw)
        allowed = {"concept", "description", "root", "changes"}
        unknown = set(data) - allowed
        if unknown:
            raise TeachError(errors.SCHEMA_INVALID,
                             "campi non ammessi nella risposta: %s"
                             % ", ".join(sorted(unknown)))
        root = data.get("root")
        if isinstance(root, (list, tuple)):
            raise TeachError(errors.SCHEMA_INVALID,
                             "'root' e' una lista: una decomposizione ha una "
                             "radice sola")
        if not isinstance(root, dict):
            raise TeachError(errors.SCHEMA_INVALID,
                             "'root' deve essere l'oggetto della radice")
        concept = str(data.get("concept", "")).strip() or project.concept
        tree = build_tree(root, concept=slug(concept, "concept"))

        out = TeachReport()
        previous = {n.id: project.state(n.id) for n in project.nodes()}
        project.root = tree
        project.description = (str(data.get("description", "")).strip()
                               or project.description)
        # Gli stati sopravvivono per **id**, e gli id sono percorsi derivati dai
        # nomi: un nodo che il raffinamento non ha toccato conserva la sua
        # decisione, uno rinominato o spostato riparte. E' il prezzo dichiarato
        # di avere un'identita' leggibile, e il referto lo dice invece di
        # perdere una scelta in silenzio.
        kept, lost = {}, []
        for node in project.nodes():
            state = previous.get(node.id)
            if state is not None:
                kept[node.id] = state
        for node_id, state in previous.items():
            if node_id not in kept and (state.solution is not None
                                        or state.locked):
                lost.append(node_id)
        project.states = kept
        for node_id in sorted(lost):
            out.report.warn("TEACH_DECISION_LOST",
                            "il nodo %r non esiste piu' dopo l'import: la sua "
                            "decisione e' stata lasciata cadere" % node_id,
                            where=node_id,
                            why="gli id dei nodi sono percorsi derivati dai "
                                "nomi, quindi un rinominato e' un nodo nuovo")
        changes = [str(c) for c in data.get("changes", ()) or ()]
        exchange = project.exchange_of(kind)
        if exchange is not None:
            exchange.response = self._as_text(raw)
            exchange.accepted = True
        project.passes[kind] = {"nodes": len(project.nodes()),
                                "changes": changes}
        out.detail = {"nodes": len(project.nodes()),
                      "mandatory": sum(1 for n in project.nodes() if n.mandatory),
                      "optional": sum(1 for n in project.nodes()
                                      if not n.mandatory),
                      "changes": changes, "kept": sorted(kept), "lost": lost}
        out.report.note("TEACH_HIERARCHY_IMPORTED",
                        "%d nodi importati (%d mandatory)"
                        % (len(project.nodes()),
                           sum(1 for n in project.nodes() if n.mandatory)),
                        where=project.concept)
        return out

    # --------------------------------------------------------- il provider #
    def ask(self, bundle: PromptBundle, *, provider=None,
            temperature: float = 0.2) -> str:
        """Manda il prompt al provider configurato. Lo **stesso** prompt (§5).

        Non c'e' un secondo sistema di provider e non ne viene aggiunto uno
        (§5): si usa quello che la `Session` ha, cioe' `LLMProvider`, con il
        suo `complete_json` e il suo schema. Un provider non disponibile e' un
        errore con un codice, non un ripiego silenzioso.
        """
        chosen = provider if provider is not None else self.session.provider
        if chosen is None or not chosen.available():
            raise TeachError(errors.NO_PROVIDER,
                             "nessun provider configurato e disponibile: usa la "
                             "modalita' esterna (copia il prompt, incolla la "
                             "risposta)")
        inizio = time.perf_counter()
        chosen.set_phase("teach")
        try:
            data = chosen.complete_json(bundle.system, bundle.user,
                                        temperature=temperature,
                                        schema=bundle.schema or None)
        except Exception as exc:                           # noqa: BLE001
            # Un fornitore che non risponde e' un errore con un codice, non un
            # ripiego silenzioso: `OfflineProvider` si dichiara disponibile e
            # poi alza, perche' per il **planner** «offline» vuol dire regole
            # locali — e per Teach non esiste un Teach a regole locali.
            raise TeachError(errors.PROVIDER_FAILED,
                             "il provider %r non ha risposto: %s. Usa la "
                             "modalita' esterna: copia il prompt, incolla la "
                             "risposta"
                             % (getattr(chosen, "name", "?"), exc)) from exc
        text = json.dumps(data, sort_keys=True)
        project = self._project()
        exchange = project.exchange_of(bundle.kind, bundle.node)
        if exchange is not None:
            exchange.mode = PROVIDER
            exchange.provider = str(getattr(chosen, "name", "")
                                    or getattr(chosen, "key", ""))
            exchange.seconds = time.perf_counter() - inizio
            exchange.response = text
        return text

    # ---------------------------------------------------------- copertura #
    def analyse(self) -> cov.CoverageReport:
        """Ricalcola la copertura di tutta la gerarchia. §9, §35."""
        project = self._project()
        if project.root is None:
            raise TeachError(errors.NO_HIERARCHY,
                             "non c'e' una gerarchia da analizzare")
        return cov.analyse(project, self.session.catalog(),
                           self.session.component_index(),
                           knowledge=self.knowledge)

    def tree(self) -> list[dict]:
        return self._project().tree()

    def exchanges(self) -> list[dict]:
        """Gli scambi con un modello, come righe. §44 vuole che si rileggano."""
        return [{"kind": e.kind, "node": e.node, "mode": e.mode,
                 "provider": e.provider, "accepted": e.accepted,
                 "characters": len(e.prompt), "seconds": round(e.seconds, 4),
                 "prompt": e.prompt, "response": e.response}
                for e in self._project().exchanges]

    def recipes(self) -> list:
        """Le variant salvate in questo progetto (§18)."""
        project = self._project()
        return [project.recipes[k] for k in sorted(project.recipes)]

    def tree_text(self) -> str:
        return cov.tree_text(self._project())

    def progress(self):
        return self._project().progress()

    def summary(self) -> dict:
        return cov.summary(self._project())

    def candidates(self, node_id: str) -> list:
        """I candidati di un nodo, con le loro evidenze (§12)."""
        return list(cov.ensure_state(self._project(), node_id).candidates)

    def node_detail(self, node_id: str) -> dict:
        """Tutto cio' che si sa di un nodo. E' la vista del pannello di §40."""
        project = self._project()
        node = project.require_node(node_id)
        state = project.state(node_id)
        backend, order, reason = recommend_backend(project, node)
        return {
            "id": node.id, "name": node.name, "role": node.role,
            "mandatory": node.mandatory, "count": node.count,
            "importance": node.importance, "detail_level": node.detail_level,
            "description": node.description, "depth": node.depth,
            "relevant": project.relevant(node),
            "coverage": state.coverage, "locked": state.locked,
            "solution": None if state.solution is None else state.solution.to_dict(),
            "candidates": [c.to_dict() for c in state.candidates],
            "suitability": [r.to_dict() for r in state.suitability],
            "attempts": [a.to_dict() for a in state.attempts],
            "backend": backend, "backend_candidates": list(order),
            "backend_reason": reason, "asset": state.asset,
            "children": [c.id for c in node.children],
            "artifacts": [k for k, a in project.artifacts.items()
                          if a.node == node.id]}

    # ------------------------------------------------------- i candidati #
    def dossier(self, node_id: str, component_id: str = "") -> str:
        """Il dossier di §13. Metadata, non codice: la modalita' economica."""
        project = self._project()
        chosen = component_id or self._best(node_id)
        return prompts.candidate_dossier(project, node_id, chosen,
                                         self.session.catalog(),
                                         session=self.session)

    def suitability_prompt(self, node_id: str, component_id: str = "") -> PromptBundle:
        """«Validate with AI» (§14): una raccomandazione, non una decisione."""
        project = self._project()
        chosen = component_id or self._best(node_id)
        system, user = prompts.suitability_prompt(project, node_id, chosen,
                                                  self.session.catalog(),
                                                  session=self.session)
        bundle = PromptBundle(kind=SUITABILITY_KIND, node=node_id, system=system,
                              user=user, schema=SCHEMAS[SUITABILITY_KIND])
        project.add_exchange(Exchange(kind=SUITABILITY_KIND, node=node_id,
                                      prompt=bundle.text))
        return bundle

    def deep_validation_prompt(self, node_id: str, component_id: str = "", *,
                               limit: int = prompts.DEEP_LIMIT) -> PromptBundle:
        """Il secondo livello (§15): il codice o il JSON, con un tetto."""
        project = self._project()
        chosen = component_id or self._best(node_id)
        system, user = prompts.deep_validation_prompt(
            project, node_id, chosen, self.session.catalog(),
            session=self.session, limit=limit)
        bundle = PromptBundle(kind=DEEP, node=node_id, system=system, user=user,
                              schema=SCHEMAS[SUITABILITY_KIND])
        project.add_exchange(Exchange(kind=DEEP, node=node_id, prompt=bundle.text))
        return bundle

    def import_suitability(self, node_id: str, raw, *, component_id: str = "",
                           deep: bool = False) -> SuitabilityRecord:
        """Importa la raccomandazione. **Non** cambia la copertura (§14).

        Nemmeno con `status: SUITABLE` e confidenza 1.0: un modello non puo'
        scrivere `VALIDATED`, e un test lo verifica proprio su quel caso.
        `NOT_SUITABLE` non rifiuta nemmeno — toglie la raccomandazione, e chi
        decide e' `reject_candidate`.
        """
        project = self._project()
        state = cov.ensure_state(project, node_id)
        chosen = component_id or self._best(node_id)
        data = self._as_json(raw)
        unknown = set(data) - {"status", "confidence", "reason",
                               "suggested_params"}
        if unknown:
            raise TeachError(errors.SCHEMA_INVALID,
                             "campi non ammessi nella risposta: %s"
                             % ", ".join(sorted(unknown)))
        status = str(data.get("status", "")).strip()
        if status not in SUITABILITY:
            raise TeachError(errors.SCHEMA_INVALID,
                             "status %r non ammesso (attesi: %s)"
                             % (status, ", ".join(SUITABILITY)))
        suggested = dict(data.get("suggested_params", {}) or {})
        component = self.session.catalog().component(chosen)
        clean: dict[str, float] = {}
        for name, value in suggested.items():
            if component is None or name not in component.params:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            clean[str(name)] = float(value)
        record = SuitabilityRecord(component_id=chosen, status=status,
                                   confidence=data.get("confidence", 0.0),
                                   reason=str(data.get("reason", "")),
                                   suggested_params=clean, deep=bool(deep))
        state.suitability = state.suitability + (record,)
        exchange = project.exchange_of(DEEP if deep else SUITABILITY_KIND, node_id)
        if exchange is not None:
            exchange.response = self._as_text(raw)
            exchange.accepted = True
        return record

    def visual_validation_prompt(self, node_id: str, component_id: str = "", *,
                                 variants=None, out_dir=None) -> PromptBundle:
        """«Generate Visual Validation Prompt» (§17): render piu' domanda.

        3DGen rende le immagini con l'offscreen che ha gia' — predefinito,
        suggerimento dell'AI, e un paio di variazioni dentro gli intervalli
        dichiarati — e scrive la domanda. Nessuna API vision nuova: le immagini
        le porta l'utente dove vuole.
        """
        project = self._project()
        chosen = component_id or self._best(node_id)
        shown = list(variants or self.render_variants(node_id, chosen,
                                                      out_dir=out_dir))
        system, user = prompts.visual_validation_prompt(
            project, node_id, chosen, shown, registry=self.session.catalog())
        bundle = PromptBundle(kind=VISUAL, node=node_id, system=system,
                              user=user, schema=SCHEMAS[VISUAL])
        project.add_exchange(Exchange(kind=VISUAL, node=node_id,
                                      prompt=bundle.text))
        return bundle

    def render_variants(self, node_id: str, component_id: str = "", *,
                        out_dir=None, count: int = 2) -> list[dict]:
        """Qualche configurazione del candidato, resa su file. Per §17.

        Il predefinito, il suggerimento dell'AI se c'e', e `count`
        randomizzazioni **dentro gli intervalli dichiarati** — `randomize` di
        V6, che non inventa un intervallo a un parametro che non ne ha.
        """
        project = self._project()
        node = project.require_node(node_id)
        chosen = component_id or self._best(node_id)
        lab = self.lab(node_id, chosen)
        folder = Path(out_dir) if out_dir else self._staging() / "renders"
        folder.mkdir(parents=True, exist_ok=True)
        shown: list[dict] = []
        plans = [("A", dict(lab.defaults()))]
        record = project.state(node_id).record_for(chosen)
        if record is not None and record.suggested_params:
            merged = dict(lab.defaults())
            merged.update(record.suggested_params)
            plans.append(("B", merged))
        for index in range(int(count)):
            lab.reset()
            built = lab.randomize(seed=index + 1)
            plans.append((chr(ord("B") + 1 + index), dict(built.values)))
        for label, values in plans:
            lab.reset()
            built = lab.build(values, detail_level=node.detail_level, check=False,
                              remember=False)
            image = ""
            scene = None if built.result is None else built.result.scene()
            if scene is not None and scene.nodes:
                image = str(self._render(scene, folder / ("%s_%s.png" % (
                    slug(node.name, "part"), label))))
            shown.append({"label": label, "params": values, "image": image,
                          "triangles": built.triangles})
        return shown

    def _render(self, scene, target: Path) -> Path:
        """Un'immagine con l'offscreen che c'e'. Se non c'e', nessuna immagine."""
        try:
            from app.ui.offscreen import render_scene
        except Exception:                                  # noqa: BLE001
            return Path("")
        try:
            render_scene(scene, str(target))
        except Exception:                                  # noqa: BLE001
            return Path("")
        return target if target.is_file() else Path("")

    def import_visual(self, node_id: str, raw) -> dict:
        """Importa il giudizio visivo. Resta una raccomandazione (§17)."""
        project = self._project()
        cov.ensure_state(project, node_id)
        data = self._as_json(raw)
        unknown = set(data) - {"best", "verdicts"}
        if unknown:
            raise TeachError(errors.SCHEMA_INVALID,
                             "campi non ammessi nella risposta: %s"
                             % ", ".join(sorted(unknown)))
        verdicts = data.get("verdicts")
        if not isinstance(verdicts, list) or not verdicts:
            raise TeachError(errors.SCHEMA_INVALID,
                             "'verdicts' deve essere una lista non vuota")
        rows = []
        for item in verdicts:
            if not isinstance(item, dict):
                raise TeachError(errors.SCHEMA_INVALID,
                                 "un verdetto e' un oggetto JSON")
            status = str(item.get("status", ""))
            if status not in SUITABILITY:
                raise TeachError(errors.SCHEMA_INVALID,
                                 "status %r non ammesso" % status)
            rows.append({"variant": str(item.get("variant", "")),
                         "status": status,
                         "reason": str(item.get("reason", ""))})
        exchange = project.exchange_of(VISUAL, node_id)
        if exchange is not None:
            exchange.response = self._as_text(raw)
            exchange.accepted = True
        return {"best": str(data.get("best", "")), "verdicts": rows}

    # ----------------------------------------------------- il laboratorio #
    def lab(self, node_id: str, component_id: str = "") -> ComponentLab:
        """«Open in Component Lab» (§16). Il laboratorio di V6, non un secondo.

        Nessun secondo editor di parametri: `ComponentLab` funziona su
        qualunque componente installato, procedurale o mesh-backed, e passa
        dalla pipeline vera.
        """
        project = self._project()
        node = project.require_node(node_id)
        chosen = component_id or self._best(node_id)
        key = "%s|%s" % (node_id, chosen)
        lab = self._labs.get(key)
        if lab is None:
            lab = ComponentLab(self.session, chosen, style=project.style,
                               detail_level=node.detail_level)
            self._labs[key] = lab
        return lab

    def apply_suggestion(self, node_id: str, component_id: str = ""):
        """«Apply AI Suggestion»: i parametri suggeriti, dentro i loro intervalli.

        I valori arrivano da una raccomandazione, quindi non si fidano: ciascuno
        passa da `ParamSpec.coerce`, che e' cio' che il resto del sistema usa
        per un valore che arriva da fuori. Un parametro che non esiste non
        viene inventato.
        """
        project = self._project()
        chosen = component_id or self._best(node_id)
        record = project.state(node_id).record_for(chosen)
        if record is None or not record.suggested_params:
            raise TeachError(errors.NO_SOLUTION,
                             "nessun parametro suggerito per %s su %s"
                             % (chosen, node_id))
        lab = self.lab(node_id, chosen)
        values = {}
        for name, value in record.suggested_params.items():
            spec = lab.component.params.get(name)
            if spec is None:
                continue
            values[name] = spec.coerce(value)
        return lab.build(values)

    def save_variant(self, node_id: str, name: str, *, component_id: str = "",
                     description: str = "", validate: bool = True) -> VariantRecipe:
        """«Save Variant» (§18): giallo -> verde, senza duplicare la geometria.

        Riusa `VariantRecipe` di V6: base piu' parametri, nessuna mesh. Il nodo
        passa a `VALIDATED` e **punta alla ricetta** — questa e' la proprieta'
        che la milestone chiama fondamentale, perche' vuol dire che 3DGen puo'
        imparare conoscenza nuova senza creare geometria nuova.
        """
        project = self._project()
        node = project.require_node(node_id)
        chosen = component_id or self._best(node_id)
        lab = self.lab(node_id, chosen)
        recipe = lab.save_variant(check_name(name, "nome della variant"),
                                  description=description, coverage=CANDIDATE)
        if validate:
            built = self.session.build(recipe.to_plan())
            if built is None or not built.ok:
                raise TeachError(errors.NO_SOLUTION,
                                 "la configurazione salvata non costruisce: %s"
                                 % ("nessun risultato" if built is None
                                    else built.report.describe()))
        recipe.promote()
        project.recipes[recipe.name] = recipe
        state = project.state(node_id)
        state.solution = Solution(ref=chosen, recipe=recipe.name,
                                  params=dict(recipe.params),
                                  origin=FROM_VARIANT,
                                  decided_by=BY_USER if not validate
                                  else BY_DETERMINISTIC,
                                  note="variant confermata su %s" % node.id)
        state.coverage = VALIDATED
        state.locked = False
        return recipe

    # ------------------------------------------------------- le decisioni #
    def choose_candidate(self, node_id: str, component_id: str) -> None:
        """Scegli un candidato diverso (§12). Non lo valida: lo mette davanti."""
        project = self._project()
        state = cov.ensure_state(project, node_id)
        if self.session.catalog().component(component_id) is None:
            raise TeachError(errors.UNKNOWN_COMPONENT,
                             "nessun componente installato con id %r"
                             % component_id)
        found = state.candidate(component_id)
        if found is None:
            # Un componente che le evidenze non avevano proposto resta
            # scegliibile: §43 chiede che l'utente possa scegliere **un altro**
            # componente, non uno fra quelli che gli abbiamo offerto. Le
            # evidenze si calcolano comunque, cosi' il dossier resta onesto su
            # cio' che quel pezzo ha e non ha - anche quando non basterebbero a
            # proporlo.
            from app.teach.model import Candidate, Evidence

            node = project.require_node(node_id)
            component = self.session.catalog().component(component_id)
            evidence = cov.evidence_for(
                project, node, component, registry=self.session.catalog(),
                score=0.0, hosts=frozenset(), host_names="il padre",
                subjects=frozenset(), knowledge=self.knowledge,
                style=project.style)
            evidence += (Evidence("user", "scelto a mano da chi costruisce",
                                  0.0),)
            found = Candidate(component_id=component_id, verdict=PROXY,
                              evidence=evidence,
                              reason="scelto a mano da chi costruisce")
        state.candidates = (found,) + tuple(c for c in state.candidates
                                            if c.component_id != component_id)
        return None

    def accept_candidate(self, node_id: str, component_id: str = "", *,
                         params=None, decided_by: str = BY_USER) -> Solution:
        """«This Works»: il nodo diventa `VALIDATED`. Lo decide chi chiama."""
        project = self._project()
        node = project.require_node(node_id)
        chosen = component_id or self._best(node_id)
        if self.session.catalog().component(chosen) is None:
            raise TeachError(errors.UNKNOWN_COMPONENT,
                             "nessun componente installato con id %r" % chosen)
        state = project.state(node_id)
        solution = Solution(ref=chosen, params=dict(params or {}),
                            origin=FROM_GENERATED if project.owns(chosen)
                            else FROM_LIBRARY,
                            decided_by=decided_by,
                            note="accettato per %s" % node.id)
        state.solution = solution
        state.coverage = VALIDATED
        state.locked = False
        return solution

    def reject_candidate(self, node_id: str, component_id: str = "") -> str:
        """«Reject Candidate»: via dall'elenco, e la copertura si rilegge.

        Se dopo il rifiuto non resta nessun candidato, il nodo e' `MISSING` e
        serve conoscenza nuova: e' il percorso di §20 per un proxy che non
        bastava.
        """
        project = self._project()
        state = cov.ensure_state(project, node_id)
        chosen = component_id or self._best(node_id)
        state.candidates = tuple(c for c in state.candidates
                                 if c.component_id != chosen)
        state.suitability = tuple(r for r in state.suitability
                                  if r.component_id != chosen)
        if state.solution is not None and state.solution.ref == chosen:
            state.solution = None
        best = state.best
        state.coverage = best.verdict if best is not None else MISSING
        state.locked = True
        return state.coverage

    def set_coverage(self, node_id: str, value: str) -> str:
        """Forza uno stato (§43). Resta fino a quando qualcuno lo cambia.

        `locked` e' cio' che lo rende vero: un ricalcolo aggiorna i candidati e
        non sovrascrive una decisione. Forzare `VALIDATED` senza una soluzione
        e' rifiutato — uno stato verde senza niente dietro e' la bugia che §41
        vieta.
        """
        project = self._project()
        state = cov.ensure_state(project, node_id)
        if value not in COVERAGE:
            raise TeachError(errors.COVERAGE_INVALID,
                             "copertura %r non ammessa (attese: %s)"
                             % (value, ", ".join(COVERAGE)))
        if value == VALIDATED and state.solution is None:
            raise TeachError(errors.NO_SOLUTION,
                             "VALIDATED senza una soluzione non significa "
                             "niente: scegli un candidato, salva una variant, "
                             "o accetta un componente generato")
        if value != VALIDATED:
            state.solution = None
        state.coverage = value
        state.locked = True
        return state.coverage

    def set_backend(self, node_id: str, backend: str) -> str:
        """La scelta dell'utente sul backend (§23). Vince sulla raccomandazione."""
        project = self._project()
        state = cov.ensure_state(project, node_id)
        if backend not in BACKENDS:
            raise TeachError(errors.PROJECT_INVALID,
                             "backend %r non ammesso (attesi: %s)"
                             % (backend, ", ".join(BACKENDS)))
        state.backend = backend
        return backend

    def supply_asset(self, node_id: str, path) -> str:
        """Un GLB per questo nodo (§26). 3DGen non lo inventa: glielo si da'."""
        project = self._project()
        cov.ensure_state(project, node_id)
        source = Path(path)
        if not source.is_file():
            raise TeachError(errors.ASSET_MISSING, "asset assente: %s" % source)
        project.state(node_id).asset = str(source)
        return str(source)

    # ------------------------------------------------- modifica l'ontologia #
    def set_node(self, node_id: str, **fields) -> TeachNode:
        """Cambia un nodo: mandatory, count, importanza, livello, ruolo, nome.

        §43 chiede di poter modificare la gerarchia, il mandatory e il count.
        Il nome si cambia e **l'id non**: l'id e' identita', e rinominarlo
        porterebbe via le decisioni appese a quel nodo. Il nome che si vede e'
        quello nuovo, il percorso resta.
        """
        project = self._project()
        node = project.require_node(node_id)
        allowed = {"name", "role", "mandatory", "count", "importance",
                   "detail_level", "description"}
        unknown = set(fields) - allowed
        if unknown:
            raise TeachError(errors.PROJECT_INVALID,
                             "campi non modificabili: %s"
                             % ", ".join(sorted(unknown)))
        if "count" in fields:
            count = int(fields["count"])
            if count <= 0:
                raise TeachError(errors.SCHEMA_INVALID,
                                 "count deve essere almeno 1")
        for key, value in fields.items():
            setattr(node, key, value)
        node.__post_init__()
        return node

    def add_node(self, parent_id: str, name: str, **fields) -> TeachNode:
        """Aggiunge un nodo a mano (§43). Stesse regole di forma dell'import."""
        project = self._project()
        parent = project.require_node(parent_id)
        taken = {n.id for n in project.nodes()}
        base = "%s.%s" % (parent.id, slug(name, "part"))
        node_id, ordinal = base, 1
        while node_id in taken:
            ordinal += 1
            node_id = "%s_%d" % (base, ordinal)
        node = TeachNode(id=node_id, name=str(name),
                         role=str(fields.get("role", "")),
                         mandatory=bool(fields.get("mandatory", True)),
                         count=int(fields.get("count", 1)),
                         importance=float(fields.get("importance", 0.5)),
                         detail_level=int(fields.get("detail_level",
                                                     parent.detail_level + 1)),
                         description=str(fields.get("description", "")))
        parent.children = parent.children + (node,)
        return node

    def remove_node(self, node_id: str) -> int:
        """Toglie un nodo e la sua discendenza, con i loro stati."""
        project = self._project()
        node = project.require_node(node_id)
        if project.root is not None and project.root.id == node_id:
            raise TeachError(errors.PROJECT_INVALID,
                             "la radice non si toglie: e' il concetto")
        gone = [n.id for n in node.walk()]
        parent = project.parent_of(node_id)
        if parent is not None:
            parent.children = tuple(c for c in parent.children if c.id != node_id)
        for key in gone:
            project.states.pop(key, None)
        return len(gone)

    # ------------------------------------------------------------ la coda #
    def queue(self) -> list[TeachNode]:
        """I mandatory da costruire, dai dettagli verso la radice (§21)."""
        return build_queue(self._project())

    def queue_text(self) -> str:
        from app.teach.spec import queue_text

        return queue_text(self._project())

    def next_node(self) -> TeachNode | None:
        """Il prossimo nodo affrontabile. `None` quando non ne resta nessuno."""
        return next_buildable(self._project())

    def spec(self, node_id: str, *, measure: bool = True):
        """La specifica tecnica (§22). La decide 3DGen, non l'AI."""
        return build_spec(self._project(), node_id, self.session.catalog(),
                          session=self.session if measure else None)

    def implementation_prompt(self, node_id: str, *, backend: str = "",
                              measure: bool = True) -> PromptBundle:
        """«Generate Implementation Prompt» (§24-§27): un contratto completo."""
        project = self._project()
        spec = self.spec(node_id, measure=measure)
        chosen = backend or spec.backend
        if chosen != spec.backend:
            self.set_backend(node_id, chosen)
            spec = self.spec(node_id, measure=measure)
        system, user = prompts.implementation_prompt(spec, self.session.catalog(),
                                                     backend=chosen)
        bundle = PromptBundle(kind=IMPLEMENTATION, node=node_id, system=system,
                              user=user, schema=SCHEMAS[IMPLEMENTATION])
        project.add_exchange(Exchange(kind=IMPLEMENTATION, node=node_id,
                                      prompt=bundle.text))
        return bundle

    # ----------------------------------------------------------- staging #
    def _staging(self) -> Path:
        if self._staging_root is None:
            self._staging_root = Path(tempfile.mkdtemp(prefix="3dgen-teach-"))
        self._staging_root.mkdir(parents=True, exist_ok=True)
        return self._staging_root

    def import_implementation(self, node_id: str, raw, *,
                              artifact_id: str = "") -> staging.StagedArtifact:
        """Mette la risposta in staging. **Mai** nella libreria installata (§29).

        Per un artefatto di dati questo e' tutto cio' che serve prima di
        validarlo: non c'e' niente da eseguire. Per un artefatto di **codice**
        qui finisce il percorso automatico: i file sono su disco, ispezionati, e
        `trusted` e' falso.
        """
        project = self._project()
        node = project.require_node(node_id)
        state = project.state(node_id)
        spec = self.spec(node_id)
        files, notes = staging.parse_envelope(raw)
        index = len(state.attempts) + 1
        key = artifact_id or "%s_%d" % (slug(node.name, "part"), index)
        artifact = staging.stage(self._staging(), files, artifact_id=key,
                                 node=node_id, expect_plugin=spec.plugin_id,
                                 component_id=spec.component_id,
                                 asset=state.asset or None, notes=notes)
        self._artifacts[key] = artifact
        project.artifacts[key] = artifact.record()
        state.attempts = state.attempts + (
            Attempt(index=index, node=node_id, backend=spec.backend,
                    artifact=key, notes=notes),)
        exchange = project.exchange_of(IMPLEMENTATION, node_id)
        if exchange is not None:
            exchange.response = self._as_text(raw)
            exchange.accepted = True
        return artifact

    def artifact(self, artifact_id: str) -> staging.StagedArtifact:
        found = self._artifacts.get(artifact_id)
        if found is None:
            raise TeachError(errors.UNKNOWN_ARTIFACT,
                             "nessun artefatto in staging con id %r"
                             % artifact_id)
        return found

    def artifacts(self) -> list[staging.StagedArtifact]:
        return [self._artifacts[k] for k in sorted(self._artifacts)]

    def inspect_artifact(self, artifact_id: str) -> dict:
        """Cio' che si deve vedere **prima** di concedere fiducia (§30, §31).

        File, sorgente, import, dimensione, manifest, API richieste, avvisi. E
        `security` dice la verita' su che cosa valgono: sono controlli statici,
        non una garanzia, e la parola «sandbox» non compare perche' non ce n'e'
        una.
        """
        artifact = self.artifact(artifact_id)
        return {
            "id": artifact.id, "node": artifact.node, "kind": artifact.kind,
            "plugin": artifact.plugin_id, "component": artifact.component_id,
            "path": str(artifact.container), "code": artifact.code,
            "trusted": artifact.trusted, "total_size": artifact.total_size,
            "manifest": artifact.manifest(),
            "files": [{"path": f.path, "size": f.size, "python": f.python,
                       "content": f.content} for f in artifact.files],
            "inspections": [{"path": i.path, "syntax_ok": i.syntax_ok,
                             "error": i.error, "imports": list(i.imports),
                             "flagged_imports": list(i.flagged_imports),
                             "flagged_calls": list(i.flagged_calls),
                             "unexpected_api": list(i.unexpected_api),
                             "size": i.size,
                             "builds_component": i.builds_component,
                             "warnings": list(i.warnings)}
                            for i in artifact.inspections],
            "warnings": list(artifact.warnings),
            "security": ("controlli statici: dicono quali moduli e quali "
                         "chiamate il testo nomina, non che cosa il codice "
                         "fara'. Non c'e' nessuna sandbox, e il codice va "
                         "letto."),
        }

    def trust_artifact(self, artifact_id: str) -> staging.StagedArtifact:
        """«Trust and Test»: il gesto esplicito di §30. Lo fa una persona."""
        artifact = self.artifact(artifact_id)
        artifact.trusted = True
        project = self._project()
        record = project.artifacts.get(artifact_id)
        if record is not None:
            record.trusted = True
        return artifact

    def validate_artifact(self, artifact_id: str, *, isolate: bool = False,
                          timeout: float = staging.RUN_TIMEOUT) -> staging.StagedValidation:
        """Carica, costruisce, misura, cerca. Con i validatori che ci sono (§32).

        Per un artefatto di codice **alza** se non e' fidato: caricare vuol dire
        importare. Per un artefatto di dati non serve fiducia, perche' non c'e'
        niente da eseguire.
        """
        project = self._project()
        artifact = self.artifact(artifact_id)
        node = project.node(artifact.node)
        out = staging.validate_artifact(
            artifact, base_paths=self.session.plugin_paths or (),
            component_id=artifact.component_id, style=project.style,
            detail_level=node.detail_level if node is not None else 2,
            isolate=isolate, timeout=timeout)
        state = project.state(artifact.node) if node is not None else None
        if state is not None and state.attempts:
            last = state.attempts[-1]
            state.attempts = state.attempts[:-1] + (
                Attempt(index=last.index, node=last.node, backend=last.backend,
                        artifact=last.artifact, ok=out.ok,
                        codes=tuple(sorted(out.codes())), notes=last.notes,
                        repaired_from=last.repaired_from),)
        return out

    def artifact_lab(self, artifact_id: str) -> ComponentLab:
        """Il Component Lab sull'artefatto, per guardarlo prima di accettarlo (§33).

        Si costruisce una sessione usa e getta sulla cartella di staging: il
        laboratorio e' quello di V6, e il componente e' installato per davvero
        — in una sessione che non e' quella del progetto.
        """
        from app.core.session import Session

        project = self._project()
        artifact = self.artifact(artifact_id)
        if artifact.code and not artifact.trusted:
            raise TeachError(errors.TRUST_REQUIRED,
                             "l'artefatto %s contiene Python e non e' fidato: "
                             "il laboratorio lo importerebbe" % artifact_id)
        session = Session(provider=self.session.provider,
                          plugin_paths=tuple([*(self.session.plugin_paths or ()),
                                              str(artifact.container)]))
        node = project.node(artifact.node)
        return ComponentLab(session, artifact.component_id, style=project.style,
                            detail_level=node.detail_level if node else 2)

    def accept_artifact(self, artifact_id: str, *,
                        build: bool = True) -> staging.StagedValidation:
        """«Accept» (§33, §35): installa, reindicizza, ricalcola la copertura.

        L'ultima parte e' quella che la milestone chiama fondamentale:
        installare un componente puo' rendere verdi o gialli **altri** nodi, e
        la coda cambia da sola. Per questo `analyse()` gira qui dentro.
        """
        project = self._project()
        artifact = self.artifact(artifact_id)
        node = project.require_node(artifact.node)
        # Prima si copia dove la libreria vive, poi si registra **quella**
        # cartella. L'ordine conta: registrare lo staging e poi la destinazione
        # darebbe lo stesso plugin da due percorsi, e il registry lo scarta.
        destination = self._install_dir(artifact)
        container = artifact.container
        if destination is not None:
            shutil.copytree(artifact.path, destination, dirs_exist_ok=True)
            container = destination.parent
        out = staging.install(artifact, self.session, build=build,
                              style=project.style,
                              detail_level=node.detail_level,
                              container=container)
        if not out.ok and build:
            return out
        state = project.state(artifact.node)
        state.solution = Solution(ref=artifact.component_id,
                                  origin=FROM_GENERATED,
                                  decided_by=BY_USER,
                                  note="generato e accettato (%s)" % artifact.id)
        state.coverage = VALIDATED
        state.locked = False
        record = project.artifacts.get(artifact_id)
        if record is not None:
            record.accepted = True
        self.analyse()
        return out

    def reject_artifact(self, artifact_id: str, *, discard: bool = False) -> str:
        """«Reject» (§33): il nodo resta `MISSING`, il tentativo resta scritto."""
        project = self._project()
        artifact = self.artifact(artifact_id)
        state = project.state(artifact.node)
        if state.solution is not None and \
                state.solution.ref == artifact.component_id:
            state.solution = None
        state.coverage = MISSING
        record = project.artifacts.get(artifact_id)
        if record is not None:
            record.accepted = False
        if discard:
            staging.discard(artifact)
            self._artifacts.pop(artifact_id, None)
            project.artifacts.pop(artifact_id, None)
        return state.coverage

    def repair_prompt(self, artifact_id: str) -> PromptBundle:
        """«Generate Repair Prompt» (§34): specifica, file, diagnostiche vere.

        Una riparazione per tentativo, e la cronologia resta nel progetto. Non
        c'e' un ciclo: chi chiama decide se farne un'altra, e `MAX_REPAIRS` dice
        quante ne offre la UI.
        """
        project = self._project()
        artifact = self.artifact(artifact_id)
        node = project.require_node(artifact.node)
        spec = self.spec(node.id)
        out = staging.validate_artifact(
            artifact, base_paths=self.session.plugin_paths or (),
            component_id=artifact.component_id, style=project.style,
            detail_level=node.detail_level) if not artifact.code or \
            artifact.trusted else None
        rows = []
        if out is not None:
            rows = [{"severity": d.severity, "code": d.code,
                     "message": d.message, "why": d.why, "where": d.where}
                    for d in out.report.sorted()]
        if not rows:
            rows = [{"severity": "warning", "code": w.split(":")[0],
                     "message": w, "why": "", "where": artifact.id}
                    for w in artifact.warnings]
        state = project.state(node.id)
        attempt = len(state.attempts)
        system, user = prompts.repair_prompt(
            spec, self.session.catalog(),
            files=[f.to_dict() for f in artifact.files], diagnostics=rows,
            attempt=attempt)
        bundle = PromptBundle(kind=REPAIR, node=node.id, system=system,
                              user=user, schema=SCHEMAS[IMPLEMENTATION])
        project.add_exchange(Exchange(kind=REPAIR, node=node.id,
                                      prompt=bundle.text))
        return bundle

    def import_repair(self, node_id: str, raw, *,
                      repaired_from: int = -1) -> staging.StagedArtifact:
        """La riparazione e' un tentativo nuovo, non una sovrascrittura."""
        project = self._project()
        state = cov.ensure_state(project, node_id)
        previous = len(state.attempts)
        artifact = self.import_implementation(node_id, raw)
        if state.attempts:
            last = state.attempts[-1]
            state.attempts = state.attempts[:-1] + (
                Attempt(index=last.index, node=last.node, backend=last.backend,
                        artifact=last.artifact, ok=last.ok, codes=last.codes,
                        notes=last.notes,
                        repaired_from=(repaired_from if repaired_from >= 0
                                       else previous)),)
        return artifact

    def _install_dir(self, artifact) -> Path | None:
        """Dove un artefatto accettato va a vivere. `None` senza destinazione.

        Senza una destinazione dichiarata l'artefatto resta dove e', e la
        sessione lo tiene installato dallo staging: va bene per un test e per
        una prova, e non va bene per una libreria — per questo chi vuole
        conservarlo dichiara `destination`.
        """
        project = self._project()
        if not project.destination:
            return None
        return Path(project.destination) / artifact.plugin_id

    # ------------------------------------------------- la radice composite #
    @staticmethod
    def _composite_socket(index: int, total: int) -> dict:
        """Dove mettere l'innesto numero `index` di `total`, su un composite.

        Un composite non ha geometria, quindi non c'e' una superficie su cui
        posare un socket: la disposizione e' una **convenzione**, e questa e'
        dichiarata invece di essere casuale. Gli innesti si distribuiscono su
        una circonferenza nel piano XZ, guardando verso l'esterno, con una
        quota che sale: cosi' i figli non finiscono tutti nello stesso punto, e
        il referto geometrico parla di una composizione e non di un ammasso.

        Chi vuole una disposizione migliore la ottiene in due modi che
        esistono: le `LayoutRegion` dichiarate dal composite, o un socket
        spostato a mano nell'authoring. Questa e' la posizione di partenza.
        """
        import math

        count = max(1, int(total))
        angle = 2.0 * math.pi * (index % count) / count
        radius = 0.55
        height = 0.0 if count < 2 else (
            -0.3 + 0.6 * (index % count) / float(count - 1))
        position = (radius * math.cos(angle), height, radius * math.sin(angle))
        direction = (math.cos(angle), 0.0, math.sin(angle))
        return {"position": position, "direction": direction,
                "up": (0.0, 1.0, 0.0)}

    def emit_composite(self, node_id: str = "", *,
                       install: bool = True) -> dict:
        """Scrive il composite di un nodo, e lo installa (§27, §38).

        Lo scrive **3DGen**, non un modello, e il motivo e' che non c'e' niente
        da decidere: i componenti, i requirement, i parametri e i conteggi
        stanno nella specifica. E lo scrive con `AuthoringService` di V6, non
        con un emettitore nuovo: un secondo produttore di plugin dati sarebbe un
        secondo formato che divergera' (regola 29 di `PROJECT-INDEX` dal lato
        della scrittura).

        Un figlio con `count: N` diventa **N archi** sullo stesso componente,
        ciascuno con il suo socket: e' cosi' che due occhi sono due occhi.

        La radice dichiara una capability con il nome del concetto. Non e'
        conoscenza di dominio nel core - e' una stringa che arriva dal progetto
        dell'utente, come `fox_stylized` dichiara `animal` nel proprio
        manifest - ed e' cio' che rende il concetto un **soggetto intero** per
        `subject_capabilities()`: fornita da qualcuno, accettata da nessuno.
        Senza, la degradazione semantica di V2 non potrebbe mai sceglierlo.
        """
        from app.authoring import AuthoringService

        project = self._project()
        node = project.require_node(node_id or (project.root.id
                                                if project.root else ""))
        is_root = project.root is not None and node.id == project.root.id
        spec = self.spec(node.id, measure=False)
        wanted = [c for c in node.children
                  if project.relevant(c) and (c.mandatory
                                              or project.state(c.id).coverage
                                              == VALIDATED)]
        satisfied = [c for c in wanted
                     if project.state(c.id).coverage == VALIDATED]
        if len(satisfied) != len(wanted) or not wanted:
            raise TeachError(errors.NO_SOLUTION,
                             "il composite di %s ha ancora %d figli non "
                             "validati su %d" % (node.id,
                                                 len(wanted) - len(satisfied),
                                                 len(wanted)))
        plugin_id = spec.plugin_id
        destination = Path(project.destination) if project.destination \
            else self._staging() / "composite"
        concept_word = slug(project.concept, "concept")
        provides = [concept_word] if is_root else list(spec.provides)
        service = AuthoringService(session=self.session)
        try:
            service.create_authoring_project(
                plugin_id, name=project.concept,
                description=("%s: a composite learned by Teach 3DGen"
                             % project.concept),
                destination=str(destination))
            name = check_name(slug(node.name, "concept"), "nome del componente")
            draft = service.create_component(
                name, from_selection=False, role=node.role or "",
                description=(node.description
                             or ("a %s, composed of its validated parts"
                                 % node.name)),
                provides=provides,
                tags=sorted({concept_word, name}),
                synonyms=[concept_word])
            # Un composite nasce senza innesti: il resolver direbbe `NO_MOUNTS`
            # e i figli non si attaccherebbero. `add_mount` crea socket e
            # `Mount` insieme, che e' la risposta di V6 §4 allo stesso problema.
            instances = [(child, i) for child in wanted
                         for i in range(child.count)]
            for position, (child, instance) in enumerate(instances):
                state = project.state(child.id)
                solution = state.solution
                component = self.session.catalog().component(solution.ref)
                provided = sorted({c.name for c in component.provides}) \
                    if component is not None else []
                capability = provided[0] if provided else ""
                if not capability:
                    raise TeachError(errors.NO_SOLUTION,
                                     "%s non fornisce nessuna capability, "
                                     "quindi nessun composite lo puo' montare: "
                                     "scegli per %s un candidato che fornisca "
                                     "qualcosa, oppure genera il componente"
                                     % (solution.ref, child.id))
                socket = ("%s_%d" % (slug(child.name, "child"), instance + 1)
                          if child.count > 1 else slug(child.name, "child"))
                place = self._composite_socket(position, len(instances))
                service.add_mount(draft.key, capability, socket=socket,
                                  radius=0.12, **place)
                service.set_parent(solution.ref, draft.key, child_id=socket,
                                   level=child.detail_level,
                                   requirement={"capability": capability},
                                   params=dict(solution.params))
            if not is_root and spec.provides:
                # L'innesto con cui il composite si attacca a chi lo contiene.
                # Non e' un `Mount` - quello e' cio' che si **accetta** - e' il
                # proprio `own_socket`, che il resolver usa dall'altro lato.
                service.add_socket(draft.key, "base", position=(0.0, 0.0, 0.0),
                                   direction=(0.0, -1.0, 0.0), up=(0.0, 0.0, 1.0),
                                   radius=0.2)
            if spec.frame:
                service.set_frame("", **{k: v for k, v in spec.frame.items()})
            report = service.validate()
            component_id = "%s:%s" % (plugin_id, name)
            out: dict[str, Any] = {"component": component_id,
                                   "plugin": plugin_id,
                                   "children": len(instances),
                                   "validation": report.describe(),
                                   "codes": sorted(report.codes()),
                                   "ok": report.ok}
            if install:
                installed = service.install_plugin()
                out["path"] = str(installed.path)
                out["installed"] = list(installed.installed)
                out["ok"] = bool(installed.ok)
                out["codes"] = sorted(installed.report.codes())
                state = project.state(node.id)
                state.solution = Solution(ref=component_id,
                                          origin=FROM_GENERATED,
                                          decided_by=BY_DETERMINISTIC,
                                          note="composite emesso da 3DGen")
                state.coverage = VALIDATED
                state.locked = False
                if is_root:
                    project.root_component = component_id
            else:
                out["path"] = str(service.save_plugin())
            return out
        finally:
            service.close()

    # ----------------------------------------------------- completamento #
    def completion_report(self) -> CompletionReport:
        """Perche' il concetto e' (o non e') `LEARNED`. §37, voce per voce."""
        project = self._project()
        out = CompletionReport(root_component=project.root_component)
        missing = project.mandatory_missing()
        out.missing = tuple(n.id for n in missing)
        out.mandatory_validated = not missing
        registry = self.session.catalog()
        root_id = project.root_component
        component = registry.component(root_id) if root_id else None
        out.root_installed = component is not None
        if component is None:
            out.report.add("TEACH_ROOT_NOT_INSTALLED",
                           "il composite della radice non e' installato",
                           why="emettilo con emit_composite() quando tutti i "
                               "mandatory sono validati")
        else:
            from app.core.session import Options

            plan = {"version": "1.3", "style": project.style,
                    "detail_level": project.detail_target, "seed": 0,
                    "root": {"id": "subject", "ref": root_id}}
            result = self.session.build(plan, Options(style=project.style,
                                                      detail_level=project.detail_target,
                                                      check=True))
            if result is not None:
                out.triangles = int(result.triangles)
                out.root_builds = bool(result.ok)
                out.validation_ok = bool(result.ok)
                if result.report is not None and not result.report.ok:
                    out.report.extend(result.report)
            hits = {c.id for c in self.session.shortlist(project.concept,
                                                         project.style).components}
            out.root_retrievable = root_id in hits
            if not out.root_retrievable:
                out.report.warn("TEACH_ROOT_NOT_RETRIEVABLE",
                                "una ricerca per %r non trova %r"
                                % (project.concept, root_id),
                                why="il documento semantico nasce dai metadati "
                                    "dichiarati: descrizione, ruolo, tag, "
                                    "sinonimi del manifest")
            # I count: ogni figlio mandatory con `count: N` deve comparire N
            # volte fra i figli dichiarati del composite, non una.
            declared: dict[str, int] = {}
            if component.children is not None:
                from app.core.component import BuildContext

                try:
                    values = {k: s.default for k, s in component.params.items()
                              if not s.derived}
                    for attachment in component.children(
                            values, BuildContext(style=project.style,
                                                 detail_level=project.detail_target)):
                        declared[attachment.component] = declared.get(
                            attachment.component, 0) + 1
                except Exception:                          # noqa: BLE001
                    declared = {}
            satisfied = True
            if project.root is not None:
                for child in project.root.children:
                    if not child.mandatory or not project.relevant(child):
                        continue
                    state = project.state(child.id)
                    if state.solution is None:
                        satisfied = False
                        continue
                    if declared.get(state.solution.ref, 0) < child.count:
                        satisfied = False
                        out.report.add("TEACH_COUNT_NOT_SATISFIED",
                                       "%s chiede %d istanze di %s e il "
                                       "composite ne dichiara %d"
                                       % (child.id, child.count,
                                          state.solution.ref,
                                          declared.get(state.solution.ref, 0)),
                                       where=child.id)
            out.counts_satisfied = satisfied
        return out

    def finish(self) -> CompletionReport:
        """Dichiara il concetto `LEARNED`, se lo e'. §37.

        Non e' un interruttore: la condizione si **misura**, e un concetto che
        non la soddisfa resta `LEARNING` con il referto che dice quale voce
        manca. Gli optional non bloccano.
        """
        project = self._project()
        out = self.completion_report()
        project.completion = LEARNED if out.learned else LEARNING
        if out.learned:
            self.knowledge.merge(project)
        return out

    def export_knowledge(self, path=None) -> Path:
        """Scrive le validazioni nello store riusabile (§19, §39)."""
        project = self._project()
        self.knowledge.merge(project)
        return self.knowledge.save(path)

    # ------------------------------------------------------------- il ciclo #
    def advance(self) -> dict:
        """Un passo del ciclo di §36. Dice che cosa fare, non lo fa.

        Non c'e' niente in background e non c'e' nessun ciclo autonomo: questa
        chiamata guarda lo stato e restituisce la **prossima mossa possibile**,
        con il nodo su cui farla. Chi guida — una finestra, un test, un tool —
        decide se farla.
        """
        project = self._project()
        if project.root is None:
            return {"action": "import_decomposition",
                    "why": "non c'e' ancora una gerarchia"}
        missing = project.mandatory_missing()
        if not missing:
            if not project.root_component:
                return {"action": "emit_composite", "node": project.root.id,
                        "why": "tutti i mandatory sono validati"}
            return {"action": "finish", "why": "il composite c'e'"}
        node = next_buildable(project)
        if node is None:
            return {"action": "choose", "why": "nessun nodo e' affrontabile "
                                               "adesso: scegli un candidato o "
                                               "cambia un backend"}
        state = project.state(node.id)
        if state.coverage in (CANDIDATE, PROXY) and state.candidates:
            return {"action": "validate_candidate", "node": node.id,
                    "candidate": state.candidates[0].component_id,
                    "coverage": state.coverage,
                    "why": "c'e' un candidato da verificare"}
        backend, _, reason = recommend_backend(project, node)
        if backend == COMPOSITE:
            return {"action": "emit_composite", "node": node.id, "why": reason}
        return {"action": "generate", "node": node.id, "backend": backend,
                "why": reason}

    # ----------------------------------------------------------- interno #
    def _project(self) -> TeachProject:
        if self.project is None:
            raise TeachError(errors.NO_PROJECT,
                             "nessun progetto Teach aperto: chiama "
                             "create_project() o load_project()")
        return self.project

    def _best(self, node_id: str) -> str:
        state = cov.ensure_state(self._project(), node_id)
        if state.solution is not None and state.solution.ref:
            return state.solution.ref
        best = state.best
        if best is None:
            raise TeachError(errors.UNKNOWN_CANDIDATE,
                             "il nodo %r non ha candidati: serve conoscenza "
                             "nuova" % node_id)
        return best.component_id

    @staticmethod
    def _as_json(raw) -> dict:
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8", errors="replace")
        if isinstance(raw, dict):
            return dict(raw)
        text = str(raw or "").strip()
        if text.startswith("```"):
            text = "\n".join(l for l in text.splitlines()
                             if not l.strip().startswith("```")).strip()
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise TeachError(errors.RESPONSE_INVALID,
                             "la risposta non e' JSON valido: %s" % exc) from exc
        if not isinstance(data, dict):
            raise TeachError(errors.RESPONSE_INVALID,
                             "la risposta deve essere un oggetto JSON")
        return data

    @staticmethod
    def _as_text(raw) -> str:
        if isinstance(raw, dict):
            return json.dumps(raw, sort_keys=True)
        if isinstance(raw, (bytes, bytearray)):
            return raw.decode("utf-8", errors="replace")
        return str(raw or "")

    def close(self) -> None:
        """Butta la cartella di staging, se e' nostra. Il progetto resta."""
        if self._owned_staging and self._staging_root is not None:
            shutil.rmtree(self._staging_root, ignore_errors=True)
            self._staging_root = None
        self._labs = {}

    def __enter__(self) -> "TeachService":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
