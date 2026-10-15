"""Le operazioni di authoring, come chiamate. La UI e' un cliente, non la via.

Questo e' il livello che la milestone chiede di esporre programmaticamente:
`create_authoring_project`, `import_model`, `create_component`, `set_parent`,
`add_socket`, `set_metadata`, `add_param`, `validate`, `save_plugin`,
`install_plugin`. Esistono tutte come metodi, nessuna richiede Qt, e un test
costruisce un plugin completo da un GLB senza aprire una finestra.

## Come fa a costruire prima di aver salvato

Una domanda vera, e la risposta decide il resto del modulo. Un draft non e' un
`Component`: non ha un `build`, non e' nel `Registry`, e il resolver non lo
vede. Si potrebbe simulare — chiamare `trimesh` e comporre a mano — ed e'
esattamente cio' che il punto 19 della milestone vieta, perche' la preview
mentirebbe appena qualcosa nella pipeline cambiasse.

Allora: **si emette il plugin in una cartella di lavoro e lo si installa in una
`Session` usa e getta**. Da quel momento la preview passa da Registry →
Resolver → Traits → Effects → Builder → Validation → Scene come qualunque
generazione, e cio' che si vede e' cio' che si salvera' — perche' e' lo stesso
JSON, letto dallo stesso loader.

Il costo e' una emissione piu' un caricamento di registry, e si paga solo
quando cambia **cio' che finirebbe nel plugin**: `AuthoringProject.fingerprint`
esclude selezione, pannello corrente e copertura, quindi muovere uno slider non
riscrive niente — i parametri viaggiano nel **piano**, non nel plugin.

## Il salvataggio vero non e' la cartella di lavoro

`save_plugin()` scrive dove l'utente ha detto; `_stage()` scrive in una
cartella temporanea che `close()` cancella. Sono due chiamate allo stesso
emettitore con due destinazioni, cosi' non esiste una seconda strada che
produce un formato diverso.
"""
from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.authoring import errors, gizmo
from app.authoring.emit import EmitResult, emit_plugin
from app.authoring.errors import AuthoringError
from app.authoring.inspect import LoadedModel, load_model
from app.authoring.lab import ComponentLab
from app.authoring.model import (CANDIDATE, COVERAGE, DRAFT_PREFIX, VARIANT_PREFIX,
                                 AuthoringProject, DraftChild, DraftComponent,
                                 DraftParam, DraftSocket, SceneObject, check_name)
from app.authoring.variant import VariantRecipe
from app.core.errors import ERROR, INFO, WARNING, Report

# Le quattro trasformazioni che un parametro dati puo' dichiarare. Lette dal
# loader, non riscritte: la UI deve offrire solo cio' che e' installato.
from app.core.data_plugin import TRANSFORMS
from app.core.frame import (FRAME_AMBIGUOUS, FRAME_CONVERTIBLE, FrameError,
                            compare, frame_from_dict)

# I ruoli semantici che la libreria installata dichiara davvero: si leggono dai
# componenti, non da un elenco nel core. Un plugin che inventa un ruolo nuovo
# lo vede comparire qui appena lo dichiara.
PROJECT_SUFFIX = ".3dgenproj"


@dataclass
class CapabilityView:
    """Una capability come l'editor la mostra: chi la fornisce, chi la accetta."""

    name: str
    description: str = ""
    providers: tuple[str, ...] = ()
    mounts: tuple[str, ...] = ()
    declared: bool = False

    @property
    def known(self) -> bool:
        """Qualcuno la conosce: dichiarata in un manifest, o usata da un pezzo."""
        return self.declared or bool(self.providers or self.mounts)

    def describe(self) -> str:
        return "%s | provides: %d | accepts: %d%s" % (
            self.name, len(self.providers), len(self.mounts),
            "" if self.declared else "  (non dichiarata in un manifest)")


@dataclass
class ValidationReport:
    """Il referto dell'authoring: le diagnostiche vere, per categoria.

    Non c'e' un validatore di authoring: ci sono i validatori del sistema —
    il loader dei plugin dati, `Registry.verify()`, il resolver, il contratto
    dei frame, `app/build/validate.py`, il retrieval — e questo oggetto li
    raccoglie in un posto con la loro gravita'.
    """

    report: Report = field(default_factory=Report)
    components: list[str] = field(default_factory=list)
    staged: Any = None

    @property
    def ok(self) -> bool:
        return self.report.ok

    def errors(self) -> list:
        return [d for d in self.report.sorted() if d.severity == ERROR]

    def warnings(self) -> list:
        return [d for d in self.report.sorted() if d.severity == WARNING]

    def notes(self) -> list:
        return [d for d in self.report.sorted() if d.severity == INFO]

    def by_category(self) -> dict[str, list]:
        return {ERROR: self.errors(), WARNING: self.warnings(), INFO: self.notes()}

    def codes(self) -> set[str]:
        return self.report.codes()

    def rows(self) -> list[dict]:
        """Per una tabella: una riga per diagnostica, gravita' inclusa."""
        return [{"severity": d.severity, "code": d.code, "where": d.where,
                 "message": d.message, "why": d.why,
                 "alternatives": list(d.alternatives)}
                for d in self.report.sorted()]

    def describe(self) -> str:
        return "%d errori, %d avvisi, %d note" % (len(self.errors()),
                                                  len(self.warnings()),
                                                  len(self.notes()))


@dataclass
class InstallResult:
    """L'esito di «installa e prova». Nessun riavvio, e il referto lo dice."""

    path: Path
    report: Report = field(default_factory=Report)
    installed: list[str] = field(default_factory=list)
    found: dict = field(default_factory=dict)
    index_invalidated: bool = False
    built: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.report.ok and bool(self.installed)

    def describe(self) -> str:
        trovati = sum(1 for v in self.found.values() if v)
        return ("%s | %d componenti installati | %d/%d trovabili | indice %s | %s"
                % (self.path, len(self.installed), trovati, len(self.found),
                   "invalidato" if self.index_invalidated else "invariato",
                   "ok" if self.ok else "con errori"))


class AuthoringService:
    """Tutto cio' che si puo' fare a un progetto di authoring, come metodi."""

    def __init__(self, session=None, project: AuthoringProject | None = None) -> None:
        from app.core.session import Session

        self.session = session if session is not None else Session()
        self.project = project
        self.models: dict[str, LoadedModel] = {}
        self._stage_dir: Path | None = None
        self._staged_session = None
        self._staged_fingerprint = ""
        self._staged_emit: EmitResult | None = None

    # --------------------------------------------------------- il progetto #
    def create_authoring_project(self, plugin_id: str = "my_plugin", *,
                                 version: str = "1.0.0", name: str = "",
                                 description: str = "", author: str = "",
                                 license: str = "", tags=(),
                                 destination: str = "") -> AuthoringProject:
        """Un progetto nuovo. Non tocca niente di installato."""
        self.project = AuthoringProject(
            plugin_id=check_name(plugin_id, "plugin_id"), version=str(version),
            name=name or plugin_id.replace("_", " "), description=description,
            author=author, license=license, tags=tuple(tags),
            destination=str(destination))
        self.models = {}
        self._invalidate()
        return self.project

    def save_project(self, path=None) -> Path:
        """Serializza il lavoro in corso. Nessuna mesh dentro: solo percorsi."""
        project = self._project()
        target = Path(path) if path else Path(project.destination or ".") / (
            project.plugin_id + PROJECT_SUFFIX)
        if target.suffix != PROJECT_SUFFIX:
            target = target.with_suffix(PROJECT_SUFFIX)
        return project.save(target)

    def load_project(self, path) -> AuthoringProject:
        """Riprende un lavoro. I modelli si reimportano dai loro percorsi.

        Un file che non c'e' piu' diventa un avviso e non un'eccezione: il
        progetto resta apribile, e chi legge sa quale sorgente e' sparita —
        la stessa politica di `Session.missing_plugins`.
        """
        self.project = AuthoringProject.load(path)
        self.models = {}
        self.reopen_models()
        self._invalidate()
        return self.project

    def reopen_models(self) -> Report:
        """Reimporta le sorgenti di un progetto appena caricato."""
        project = self._project()
        report = Report()
        for source in project.sources:
            try:
                model = load_model(source.path, prefix=Path(source.path).stem)
            except AuthoringError as exc:
                report.warn(exc.code, "sorgente non riaperta: %s" % exc.message,
                            where=source.path,
                            why="il progetto resta apribile; i componenti che "
                                "nominano i suoi oggetti non si potranno salvare")
                continue
            self.models[source.path] = model
        return report

    # ------------------------------------------------------------- import #
    def import_model(self, path) -> Any:
        """Importa un GLB/glTF e ne elenca i nodi. Nessuna inferenza.

        Il file resta dov'e' e non viene modificato: l'authoring guarda la
        geometria, non la riscrive (punto 6 della milestone).
        """
        project = self._project()
        source_path = str(Path(path))
        stem = Path(source_path).stem
        taken = {Path(s.path).stem for s in project.sources}
        prefix, index = stem, 2
        while prefix in taken and source_path not in {s.path for s in project.sources}:
            prefix, index = "%s_%d" % (stem, index), index + 1
        model = load_model(source_path, prefix=prefix)
        project.sources = [s for s in project.sources if s.path != model.path]
        project.sources.append(model.source)
        self.models[model.path] = model
        self._invalidate()
        return model.source

    def scene_objects(self) -> list[SceneObject]:
        """Tutti i nodi di geometria importati, di ogni sorgente."""
        return self._project().objects()

    def object_info(self, key: str) -> dict:
        """Nome, triangoli, limiti, trasformazione, tinta, visibilita'."""
        obj = self._object(key)
        owner = self._project().owner_of(key)
        return {"key": obj.key, "name": obj.name, "source": obj.source,
                "triangles": obj.triangles, "bounds": obj.bounds,
                "extents": obj.extents, "center": obj.center,
                "transform": list(obj.transform), "color": obj.color,
                "visible": key not in self._project().hidden,
                "component": owner.key if owner else ""}

    # ---------------------------------------------------------- selezione #
    def select(self, keys, *, add: bool = False) -> tuple[str, ...]:
        project = self._project()
        wanted = [keys] if isinstance(keys, str) else list(keys)
        for key in wanted:
            self._object(key)
        current = list(project.selection) if add else []
        for key in wanted:
            if key not in current:
                current.append(key)
        project.selection = tuple(current)
        return project.selection

    def select_all(self) -> tuple[str, ...]:
        project = self._project()
        project.selection = tuple(o.key for o in project.objects())
        return project.selection

    def clear_selection(self) -> tuple[str, ...]:
        self._project().selection = ()
        return ()

    def selection(self) -> list[SceneObject]:
        project = self._project()
        return [o for o in project.objects() if o.key in project.selection]

    def hide(self, keys) -> tuple[str, ...]:
        project = self._project()
        wanted = [keys] if isinstance(keys, str) else list(keys)
        hidden = list(project.hidden)
        for key in wanted:
            self._object(key)
            if key not in hidden:
                hidden.append(key)
        project.hidden = tuple(hidden)
        return project.hidden

    def show(self, keys) -> tuple[str, ...]:
        project = self._project()
        wanted = {keys} if isinstance(keys, str) else set(keys)
        project.hidden = tuple(k for k in project.hidden if k not in wanted)
        return project.hidden

    def isolate(self, keys=None) -> tuple[str, ...]:
        """Mostra solo questi (o la selezione), nasconde tutto il resto."""
        project = self._project()
        wanted = set(project.selection if keys is None
                     else ({keys} if isinstance(keys, str) else set(keys)))
        project.hidden = tuple(o.key for o in project.objects() if o.key not in wanted)
        return project.hidden

    def show_all(self) -> tuple[str, ...]:
        self._project().hidden = ()
        return ()

    def visible_objects(self) -> list[SceneObject]:
        project = self._project()
        return [o for o in project.objects() if o.key not in project.hidden]

    # --------------------------------------------------------- componenti #
    def create_component(self, name: str, *, objects=None, from_selection: bool = True,
                         role: str = "", description: str = "", tags=(),
                         provides=(), mounts=None, styles=(), requires=(),
                         material: str = "", frame=None, synonyms=(),
                         coverage: str = CANDIDATE,
                         mesh_source: str = "") -> DraftComponent:
        """Un componente dai nodi selezionati, oppure un composite senza mesh.

        `objects=()` esplicito (o nessuna selezione con `from_selection=False`)
        da' un componente **senza geometria propria**: il root che contiene
        corpo, testa, spada e scudo. E' il caso che V6 ha dovuto aprire nel
        loader, e il caso normale per un concetto complesso.
        """
        project = self._project()
        local = check_name(name, "nome del componente")
        if project.component_by_name(local) is not None:
            raise AuthoringError(errors.DUPLICATE,
                                 "esiste gia' un componente chiamato %r" % local)
        if objects is None:
            chosen = tuple(project.selection) if from_selection else ()
        else:
            chosen = tuple([objects] if isinstance(objects, str) else objects)
        for key in chosen:
            self._object(key)
            owner = project.owner_of(key)
            if owner is not None:
                raise AuthoringError(errors.DUPLICATE,
                                     "l'oggetto %r appartiene gia' a '%s'"
                                     % (key, owner.name))
        if chosen and mesh_source:
            raise AuthoringError(errors.PROJECT_INVALID,
                                 "un componente prende la geometria dagli oggetti "
                                 "selezionati **oppure** da un GLB esistente")
        draft = DraftComponent(
            key=self._fresh_key(local), name=local, description=description,
            role=role, material=material, tags=tuple(tags), provides=tuple(provides),
            styles=tuple(styles), requires=tuple(requires), synonyms=tuple(synonyms),
            mounts=[dict(m) for m in (mounts or [])], objects=chosen,
            mesh_source=str(mesh_source),
            frame=dict(frame or {}),
            coverage=coverage if coverage in COVERAGE else CANDIDATE)
        project.components.append(draft)
        project.current = draft.key
        self._invalidate()
        return draft

    def remove_component(self, key: str) -> None:
        """Toglie un componente e gli archi che lo nominavano."""
        project = self._project()
        draft = self._draft(key)
        project.components = [c for c in project.components if c.key != key]
        ref = DRAFT_PREFIX + key
        for component in project.components:
            component.children = [c for c in component.children if c.ref != ref]
        if project.current == key:
            project.current = project.components[0].key if project.components else ""
        del draft
        self._invalidate()

    def set_current(self, key: str) -> DraftComponent:
        draft = self._draft(key)
        self._project().current = key
        return draft

    def current(self) -> DraftComponent | None:
        project = self._project()
        return project.component(project.current) if project.current else None

    def set_metadata(self, key: str, **fields) -> DraftComponent:
        """Ruolo, tag, descrizione, sinonimi, copertura, materiale, requisiti.

        I nomi dei campi sono quelli del draft, che sono quelli del formato
        dati, che sono quelli di `Component`. Un campo sconosciuto e' un errore
        e non un'opzione ignorata: la stessa politica del loader (regola 22).
        """
        draft = self._draft(key)
        allowed = {"description", "role", "material", "tags", "provides", "styles",
                   "requires", "synonyms", "mounts", "coverage", "notes",
                   "layout_regions", "name"}
        unknown = set(fields) - allowed
        if unknown:
            raise AuthoringError(errors.PROJECT_INVALID,
                                 "campi di metadata non supportati: %s"
                                 % ", ".join(sorted(unknown)))
        for field_name, value in fields.items():
            if field_name == "name":
                local = check_name(value, "nome del componente")
                other = self._project().component_by_name(local)
                if other is not None and other.key != draft.key:
                    raise AuthoringError(errors.DUPLICATE,
                                         "esiste gia' un componente %r" % local)
                draft.name = local
            elif field_name == "coverage":
                if value not in COVERAGE:
                    raise AuthoringError(errors.PROJECT_INVALID,
                                         "copertura attesa fra %s, non %r"
                                         % (", ".join(COVERAGE), value))
                draft.coverage = value
            elif field_name in ("tags", "provides", "styles", "requires", "synonyms"):
                setattr(draft, field_name, tuple(str(v) for v in value))
            elif field_name in ("mounts", "layout_regions"):
                setattr(draft, field_name, [dict(v) for v in value])
            else:
                setattr(draft, field_name, str(value))
        self._invalidate()
        return draft

    def set_objects(self, key: str, objects) -> DraftComponent:
        """Riassegna la geometria di un componente agli oggetti indicati."""
        project = self._project()
        draft = self._draft(key)
        chosen = tuple([objects] if isinstance(objects, str) else objects)
        for object_key in chosen:
            self._object(object_key)
            owner = project.owner_of(object_key)
            if owner is not None and owner.key != key:
                raise AuthoringError(errors.DUPLICATE,
                                     "l'oggetto %r appartiene a '%s'"
                                     % (object_key, owner.name))
        draft.objects = chosen
        if chosen:
            draft.mesh_source = ""
        self._invalidate()
        return draft

    # ---------------------------------------------------------- gerarchia #
    def set_parent(self, child: str, parent: str, *, child_id: str = "",
                   **options) -> DraftChild:
        """Aggancia un componente (o una variant, o un installato) a un padre.

        `child` e' un riferimento nelle tre forme che `DraftChild.ref` ammette:
        la chiave di un draft, `variant:<nome>`, oppure l'id di un componente
        **installato** — che e' il punto 7 della milestone: una gerarchia puo'
        mescolare un corpo di drago importato con `creature:eye` e
        `fantasy:wing` esistenti.
        """
        project = self._project()
        host = self._draft(parent)
        ref = self._reference(child)
        if ref == DRAFT_PREFIX + host.key:
            raise AuthoringError(errors.CYCLE,
                                 "un componente non puo' contenere se stesso")
        identifier = child_id or self._child_id(host, ref)
        if host.child(identifier) is not None:
            raise AuthoringError(errors.DUPLICATE,
                                 "'%s' ha gia' un figlio con id %r"
                                 % (host.name, identifier))
        edge = DraftChild(id=identifier, ref=ref)
        self._apply_child_options(edge, options)
        host.children.append(edge)
        if self._cycle(project):
            host.children.remove(edge)
            raise AuthoringError(errors.CYCLE,
                                 "l'aggancio creerebbe un ciclo nella gerarchia")
        self._invalidate()
        return edge

    def unparent(self, parent: str, child_id: str) -> None:
        host = self._draft(parent)
        edge = host.child(child_id)
        if edge is None:
            raise AuthoringError(errors.UNKNOWN_CHILD,
                                 "'%s' non ha un figlio %r" % (host.name, child_id))
        host.children.remove(edge)
        self._invalidate()

    def remove_from_hierarchy(self, key: str) -> int:
        """Stacca un componente da tutti i padri. Il componente resta."""
        project = self._project()
        self._draft(key)
        ref = DRAFT_PREFIX + key
        removed = 0
        for component in project.components:
            before = len(component.children)
            component.children = [c for c in component.children if c.ref != ref]
            removed += before - len(component.children)
        self._invalidate()
        return removed

    def reorder(self, parent: str, child_id: str, index: int) -> list[str]:
        """L'ordine dei figli e' dichiarato, quindi va poter essere cambiato."""
        host = self._draft(parent)
        edge = host.child(child_id)
        if edge is None:
            raise AuthoringError(errors.UNKNOWN_CHILD,
                                 "'%s' non ha un figlio %r" % (host.name, child_id))
        host.children.remove(edge)
        position = max(0, min(int(index), len(host.children)))
        host.children.insert(position, edge)
        self._invalidate()
        return [c.id for c in host.children]

    def set_child_options(self, parent: str, child_id: str, **options) -> DraftChild:
        """Livello, opzionale, on_request, replaces, scale_mode, insert, roll."""
        host = self._draft(parent)
        edge = host.child(child_id)
        if edge is None:
            raise AuthoringError(errors.UNKNOWN_CHILD,
                                 "'%s' non ha un figlio %r" % (host.name, child_id))
        self._apply_child_options(edge, options)
        self._invalidate()
        return edge

    def duplicate_reference(self, parent: str, child_id: str, *,
                            new_id: str = "") -> DraftChild:
        """Lo stesso componente, montato una seconda volta. Due occhi, due ali."""
        host = self._draft(parent)
        edge = host.child(child_id)
        if edge is None:
            raise AuthoringError(errors.UNKNOWN_CHILD,
                                 "'%s' non ha un figlio %r" % (host.name, child_id))
        copy = DraftChild(**{**edge.to_dict(), "id": new_id or
                             self._child_id(host, edge.ref)})
        host.children.append(copy)
        self._invalidate()
        return copy

    def hierarchy(self, key: str = "") -> list[dict]:
        """La gerarchia come righe annidate: quello che un tree editor disegna."""
        project = self._project()
        roots = [self._draft(key)] if key else project.roots()
        rows: list[dict] = []

        def walk(draft: DraftComponent, depth: int, edge: DraftChild | None,
                 seen: tuple[str, ...]) -> None:
            rows.append({"key": draft.key, "name": draft.name, "depth": depth,
                         "id": edge.id if edge else draft.key,
                         "ref": edge.ref if edge else "",
                         "level": edge.level if edge else 1,
                         "optional": bool(edge.optional) if edge else False,
                         "on_request": bool(edge.on_request) if edge else False,
                         "composite": draft.composite,
                         "coverage": draft.coverage,
                         "installed": False})
            for child in draft.children:
                if child.draft_key:
                    target = project.component(child.draft_key)
                    if target is None or child.draft_key in seen:
                        continue
                    walk(target, depth + 1, child, seen + (draft.key,))
                else:
                    rows.append({"key": "", "name": project.resolve_ref(child),
                                 "depth": depth + 1, "id": child.id,
                                 "ref": child.ref, "level": child.level,
                                 "optional": bool(child.optional),
                                 "on_request": bool(child.on_request),
                                 "composite": False, "coverage": "",
                                 "installed": True})

        for root in roots:
            walk(root, 0, None, ())
        return rows

    # ------------------------------------------------------------- socket #
    def add_socket(self, key: str, name: str, *, position=(0.0, 0.0, 0.0),
                   direction=(0.0, 1.0, 0.0), up=(0.0, 0.0, 1.0),
                   radius: float = 0.1, capabilities=(), side: str = "",
                   tags=()) -> DraftSocket:
        """Un innesto nuovo. Diventa un `Socket`, mai un MeshSocket."""
        draft = self._draft(key)
        socket_name = str(name).strip()
        if not socket_name:
            raise AuthoringError(errors.NAME_INVALID, "il socket vuole un nome")
        if draft.socket(socket_name) is not None:
            raise AuthoringError(errors.DUPLICATE,
                                 "'%s' ha gia' un socket %r" % (draft.name, socket_name))
        socket = DraftSocket(name=socket_name, position=tuple(float(v) for v in position),
                             direction=tuple(float(v) for v in direction),
                             up=tuple(float(v) for v in up), radius=float(radius),
                             capabilities=tuple(str(c) for c in capabilities),
                             side=str(side), tags=tuple(str(t) for t in tags))
        # Degenere subito, invece che al caricamento: chi sta disegnando un
        # innesto deve sapere adesso che direction e up sono paralleli.
        socket.check()
        draft.sockets.append(socket)
        self._invalidate()
        return socket

    def add_mount(self, key: str, capability: str, *, socket: str = "",
                  position=(0.0, 0.0, 0.0), direction=(0.0, 1.0, 0.0),
                  up=(0.0, 0.0, 1.0), radius: float = 0.1, side: str = "",
                  tags=(), capacity: int = 1,
                  description: str = "") -> dict:
        """Un posto dove qualcosa si monta: il socket **e** il `Mount`, insieme.

        Esistono separati nel modello e per buone ragioni — un socket e'
        geometria, un mount e' contratto — ma dichiararne uno senza l'altro e'
        l'errore che si fa sempre: un `Mount` su un socket che non c'e' non
        monta niente, e un socket senza `Mount` non viene mai scelto dal
        resolver. Un composite appena creato ha questo problema per
        costruzione, perche' non ha socket: senza un innesto il resolver dice
        `NO_MOUNTS` e i figli non si attaccano.

        Se il socket esiste gia' lo si riusa aggiungendogli la capability,
        invece di crearne un secondo nello stesso punto.
        """
        draft = self._draft(key)
        socket_name = str(socket or capability)
        existing = draft.socket(socket_name)
        if existing is None:
            self.add_socket(key, socket_name, position=position, direction=direction,
                            up=up, radius=radius, capabilities=[str(capability)],
                            side=side, tags=tags)
        elif capability not in existing.capabilities:
            self.update_socket(key, socket_name,
                               capabilities=(*existing.capabilities, str(capability)))
        mount: dict[str, Any] = {"capability": str(capability),
                                 "socket_id": socket_name}
        if side:
            mount["side"] = str(side)
        if tags:
            mount["tags"] = [str(t) for t in tags]
        if int(capacity) != 1:
            mount["capacity"] = int(capacity)
        if description:
            mount["description"] = str(description)
        mounts = [m for m in draft.mounts
                  if not (m.get("capability") == mount["capability"]
                          and m.get("socket_id") == socket_name)]
        mounts.append(mount)
        draft.mounts = mounts
        self._invalidate()
        return mount

    def update_socket(self, key: str, name: str, **fields) -> DraftSocket:
        draft = self._draft(key)
        socket = draft.socket(name)
        if socket is None:
            raise AuthoringError(errors.UNKNOWN_SOCKET,
                                 "'%s' non ha un socket %r" % (draft.name, name))
        allowed = {"name", "position", "direction", "up", "radius", "capabilities",
                   "side", "tags"}
        unknown = set(fields) - allowed
        if unknown:
            raise AuthoringError(errors.PROJECT_INVALID,
                                 "campi di socket non supportati: %s"
                                 % ", ".join(sorted(unknown)))
        # Si prova la modifica su una copia e si tiene solo se regge: un
        # aggiornamento rifiutato non deve lasciare il socket a meta'.
        from dataclasses import replace

        changes: dict[str, Any] = {}
        for field_name, value in fields.items():
            if field_name in ("position", "direction", "up"):
                changes[field_name] = tuple(float(v) for v in value)
            elif field_name == "radius":
                changes[field_name] = float(value)
            elif field_name in ("capabilities", "tags"):
                changes[field_name] = tuple(str(v) for v in value)
            else:
                changes[field_name] = str(value)
        replace(socket, **changes).check()
        for field_name, value in changes.items():
            setattr(socket, field_name, value)
        self._invalidate()
        return socket

    def remove_socket(self, key: str, name: str) -> None:
        draft = self._draft(key)
        socket = draft.socket(name)
        if socket is None:
            raise AuthoringError(errors.UNKNOWN_SOCKET,
                                 "'%s' non ha un socket %r" % (draft.name, name))
        draft.sockets.remove(socket)
        self._invalidate()

    # -------------------------------------------------------- snap helpers #
    def component_bounds(self, key: str):
        """I limiti della geometria che appartiene a questo componente.

        Senza geometria propria non ci sono limiti da misurare, e la risposta
        e' `None` invece di una scatola unitaria inventata.
        """
        draft = self._draft(key)
        project = self._project()
        boxes = [project.object(k).bounds for k in draft.objects
                 if project.object(k) is not None]
        if not boxes:
            return None
        lows = [b[0] for b in boxes]
        highs = [b[1] for b in boxes]
        return (tuple(min(v[i] for v in lows) for i in range(3)),
                tuple(max(v[i] for v in highs) for i in range(3)))

    def snap_socket_to_center(self, key: str, name: str, *,
                              object_key: str = "") -> DraftSocket:
        """Al centro del componente, o di un oggetto preciso."""
        bounds = (self._object(object_key).bounds if object_key
                  else self.component_bounds(key))
        if bounds is None:
            raise AuthoringError(errors.UNKNOWN_OBJECT,
                                 "niente geometria da misurare per '%s'" % key)
        return self.update_socket(key, name, position=gizmo.snap_to_center(bounds))

    def snap_socket_to_face(self, key: str, name: str, axis: str, *,
                            object_key: str = "") -> DraftSocket:
        """Al centro della faccia del bounding box che guarda questo asse."""
        bounds = (self._object(object_key).bounds if object_key
                  else self.component_bounds(key))
        if bounds is None:
            raise AuthoringError(errors.UNKNOWN_OBJECT,
                                 "niente geometria da misurare per '%s'" % key)
        return self.update_socket(key, name, position=gizmo.snap_to_face(bounds, axis))

    def snap_socket_to_extreme(self, key: str, name: str, axis: str, *,
                               object_key: str = "") -> DraftSocket:
        """Al minimo o al massimo lungo un asse."""
        bounds = (self._object(object_key).bounds if object_key
                  else self.component_bounds(key))
        if bounds is None:
            raise AuthoringError(errors.UNKNOWN_OBJECT,
                                 "niente geometria da misurare per '%s'" % key)
        return self.update_socket(key, name,
                                  position=gizmo.snap_to_extreme(bounds, axis))

    def align_socket_direction(self, key: str, name: str, axis: str) -> DraftSocket:
        """Allinea `direction` a uno dei sei assi. `up` resta ortogonale."""
        draft = self._draft(key)
        socket = draft.socket(name)
        if socket is None:
            raise AuthoringError(errors.UNKNOWN_SOCKET,
                                 "'%s' non ha un socket %r" % (draft.name, name))
        direction = gizmo.axis_vector(axis)
        from app.core.socket import orthogonal_up

        up = orthogonal_up(direction, socket.up)
        return self.update_socket(key, name,
                                  direction=tuple(float(v) for v in direction),
                                  up=tuple(float(v) for v in up))

    def align_socket_up(self, key: str, name: str, axis: str) -> DraftSocket:
        """Allinea l'`up` a un asse, tenendo la direzione che c'e'."""
        draft = self._draft(key)
        socket = draft.socket(name)
        if socket is None:
            raise AuthoringError(errors.UNKNOWN_SOCKET,
                                 "'%s' non ha un socket %r" % (draft.name, name))
        return self.update_socket(key, name,
                                  up=tuple(float(v) for v in gizmo.axis_vector(axis)))

    def mirror_socket(self, key: str, name: str, *, axis: str = "+X",
                      new_name: str = "") -> DraftSocket:
        """La coppia L/R in una chiamata, con il lato invertito se c'era."""
        draft = self._draft(key)
        socket = draft.socket(name)
        if socket is None:
            raise AuthoringError(errors.UNKNOWN_SOCKET,
                                 "'%s' non ha un socket %r" % (draft.name, name))
        position, direction, up = gizmo.mirror(socket.position, socket.direction,
                                               socket.up, axis)
        side = gizmo.MIRROR_SIDES.get(socket.side, socket.side)
        return self.add_socket(key, new_name or gizmo.mirror_name(name),
                               position=position, direction=direction, up=up,
                               radius=socket.radius,
                               capabilities=socket.capabilities, side=side,
                               tags=socket.tags)

    def socket_gizmo(self, key: str, name: str = ""):
        """I nodi di gizmo per uno o per tutti i socket del componente."""
        draft = self._draft(key)
        sockets = ([draft.socket(name)] if name else list(draft.sockets))
        if name and sockets[0] is None:
            raise AuthoringError(errors.UNKNOWN_SOCKET,
                                 "'%s' non ha un socket %r" % (draft.name, name))
        nodes = []
        for socket in sockets:
            nodes.extend(gizmo.socket_gizmo(socket.to_socket()))
        return nodes

    # ----------------------------------------------------------- capability #
    def capabilities(self) -> list[CapabilityView]:
        """Tutte le capability conosciute, con chi le fornisce e chi le accetta.

        Legge il registry installato: l'utente sceglie da un elenco invece di
        ricordare una stringa. Le capability che i draft dichiarano ci sono
        anche quando nessuno le conosce ancora — e' lecito inventarne una, ed e'
        dati, non codice — e `declared` dice la differenza.
        """
        registry = self.session.catalog()
        names = set(registry.capabilities())
        project = self.project
        if project is not None:
            for draft in project.components:
                names |= set(draft.provides)
                names |= {str(m.get("capability", "")) for m in draft.mounts}
                for socket in draft.sockets:
                    names |= set(socket.capabilities)
        views = []
        for name in sorted(n for n in names if n):
            info = registry.capability(name)
            views.append(CapabilityView(name=name, description=info.description,
                                        providers=info.providers, mounts=info.mounts,
                                        declared=info.known))
        return views

    def search_capabilities(self, text: str) -> list[CapabilityView]:
        needle = str(text or "").strip().lower()
        views = self.capabilities()
        if not needle:
            return views
        return [v for v in views
                if needle in v.name.lower() or needle in v.description.lower()]

    # --------------------------------------------------------------- params #
    def param_strategies(self) -> dict:
        """Le strategie **realmente** disponibili: nessuna opzione inventata.

        `transform` e' l'elenco chiuso del loader. Gli effetti sono quelli
        installati, con i loro knob numerici e i loro ambiti dichiarati: un
        knob `enum` non compare, perche' un parametro dati pilota solo numeri
        (debito dichiarato di V5).
        """
        registry = self.session.catalog()
        effects = []
        for effect in registry.effects():
            knobs = ["amount"] if effect.amount is not None else []
            knobs += [name for name, spec in sorted(effect.params.items())
                      if spec.type in ("float", "ratio", "int") and not spec.choices]
            if not knobs:
                continue
            effects.append({"type": effect.id, "stage": effect.stage,
                            "description": effect.description,
                            "knobs": knobs,
                            "scopes": list(effect.scopes) or ["part"]})
        return {"transforms": list(TRANSFORMS), "effects": effects}

    def semantic_roles(self) -> list[str]:
        """I ruoli semantici che la libreria installata dichiara davvero."""
        registry = self.session.catalog()
        roles = set()
        for component in registry.components():
            for spec in component.params.values():
                role = getattr(spec, "semantic_role", "")
                if role:
                    roles.add(role)
        for rule in registry.trait_rules():
            roles |= {p.semantic_role for p in rule.patches if p.semantic_role}
            roles |= set(rule.match.param_roles)
        return sorted(r for r in roles if r)

    def add_param(self, key: str, name: str, *, type: str = "float",
                  default: float = 1.0, min: float | None = None,
                  max: float | None = None, semantic_role: str = "",
                  description: str = "", unit: str = "", transform: str = "",
                  effect: dict | None = None) -> DraftParam:
        """Un parametro con la sua strategia. `transform` **oppure** `effect`.

        Non si rifiuta subito un parametro a meta': scrivere il nome e poi
        scegliere la strategia e' come si lavora. `validate()` lo segnala, e il
        loader lo rifiuterebbe — quindi non si puo' salvarlo per sbaglio.
        """
        draft = self._draft(key)
        param_name = str(name).strip()
        if not param_name:
            raise AuthoringError(errors.NAME_INVALID, "il parametro vuole un nome")
        if draft.param(param_name) is not None:
            raise AuthoringError(errors.DUPLICATE,
                                 "'%s' ha gia' un parametro %r"
                                 % (draft.name, param_name))
        if transform and effect:
            raise AuthoringError(errors.PARAM_STRATEGY,
                                 "il parametro %r dichiara transform **e** effect: "
                                 "non c'e' un ordine fra una scala e una "
                                 "deformazione che non sia arbitrario" % param_name)
        if transform and transform not in TRANSFORMS:
            raise AuthoringError(errors.PARAM_STRATEGY,
                                 "transform atteso fra %s, non %r"
                                 % ("/".join(TRANSFORMS), transform))
        if effect is not None:
            effect = self._effect_binding(effect, param_name)
        param = DraftParam(name=param_name, type=str(type), default=float(default),
                           min=None if min is None else float(min),
                           max=None if max is None else float(max),
                           semantic_role=str(semantic_role),
                           description=str(description), unit=str(unit),
                           transform=str(transform), effect=effect)
        draft.params.append(param)
        self._invalidate()
        return param

    def update_param(self, key: str, name: str, **fields) -> DraftParam:
        draft = self._draft(key)
        param = draft.param(name)
        if param is None:
            raise AuthoringError(errors.UNKNOWN_PARAM,
                                 "'%s' non ha un parametro %r" % (draft.name, name))
        allowed = {"name", "type", "default", "min", "max", "semantic_role",
                   "description", "unit", "transform", "effect"}
        unknown = set(fields) - allowed
        if unknown:
            raise AuthoringError(errors.PROJECT_INVALID,
                                 "campi di parametro non supportati: %s"
                                 % ", ".join(sorted(unknown)))
        if fields.get("transform") and fields.get("effect"):
            raise AuthoringError(errors.PARAM_STRATEGY,
                                 "transform e effect si escludono")
        for field_name, value in fields.items():
            if field_name in ("default",):
                param.default = float(value)
            elif field_name in ("min", "max"):
                setattr(param, field_name, None if value is None else float(value))
            elif field_name == "effect":
                param.effect = (None if value is None
                                else self._effect_binding(value, param.name))
                if param.effect is not None:
                    param.transform = ""
            elif field_name == "transform":
                text = str(value)
                if text and text not in TRANSFORMS:
                    raise AuthoringError(errors.PARAM_STRATEGY,
                                         "transform atteso fra %s, non %r"
                                         % ("/".join(TRANSFORMS), value))
                param.transform = text
                if text:
                    param.effect = None
            else:
                setattr(param, field_name, str(value))
        self._invalidate()
        return param

    def remove_param(self, key: str, name: str) -> None:
        draft = self._draft(key)
        param = draft.param(name)
        if param is None:
            raise AuthoringError(errors.UNKNOWN_PARAM,
                                 "'%s' non ha un parametro %r" % (draft.name, name))
        draft.params.remove(param)
        self._invalidate()

    # ----------------------------------------------------------- materiali #
    def add_material(self, name: str, *, base_color: str = "#9aa0a6",
                     roughness: float = 0.6, metallic: float = 0.0,
                     opacity: float = 1.0, description: str = "") -> dict:
        """Un `MaterialSpec` con i cinque campi che esistono. Nessun editor PBR."""
        from app.core.material import MaterialSpec

        project = self._project()
        material_name = check_name(name, "nome del materiale")
        if any(m.get("name") == material_name for m in project.materials):
            raise AuthoringError(errors.DUPLICATE,
                                 "esiste gia' un materiale %r" % material_name)
        spec = MaterialSpec(name=material_name, base_color=base_color,
                            roughness=roughness, metallic=metallic,
                            opacity=opacity, description=description)
        data = spec.model_dump()
        project.materials.append(data)
        self._invalidate()
        return data

    def assign_material(self, key: str, name: str) -> DraftComponent:
        """Il materiale nominato vince sui colori importati (politica di V4)."""
        return self.set_metadata(key, material=str(name))

    def material_preview(self, key: str) -> dict:
        """Tinta importata, materiale scelto, e quello che si vedrebbe.

        Tre righe perche' le decisioni sono tre, e la politica di V4 le ordina:
        il materiale nominato vince, altrimenti valgono i colori della mesh,
        altrimenti il ripiego.
        """
        draft = self._draft(key)
        project = self._project()
        registry = self.session.catalog()
        imported = [project.object(k).color for k in draft.objects
                    if project.object(k) is not None and project.object(k).color]
        declared = {m.get("name"): m for m in project.materials}
        chosen = draft.material
        if chosen and chosen in declared:
            spec = declared[chosen]
            effective = {"name": chosen, "base_color": spec.get("base_color", ""),
                          "source": "progetto"}
        elif chosen and registry.knows_material(chosen):
            material = registry.material(chosen)
            effective = {"name": chosen, "base_color": material.base_color,
                          "source": "installato"}
        elif imported:
            effective = {"name": "", "base_color": imported[0], "source": "importato"}
        else:
            material = registry.material("default")
            effective = {"name": "default", "base_color": material.base_color,
                          "source": "ripiego"}
        return {"imported": imported, "declared": chosen, "effective": effective,
                "available": sorted(set(declared) | {m.name for m in registry.materials()})}

    # -------------------------------------------------------------- frame #
    def set_frame(self, key: str = "", *, growth_axis: str | None = None,
                  front: str | None = None, up: str | None = None) -> dict:
        """La terna di un componente, o quella del plugin con `key=""`.

        Una convenzione appartiene all'autore del plugin, per questo la terna
        del manifest e' la predefinita di tutti i suoi componenti (V5 §7). Un
        asse illeggibile e' rifiutato adesso, non al caricamento.
        """
        project = self._project()
        target = project.frame if not key else self._draft(key).frame
        data = dict(target)
        for name, value in (("growth_axis", growth_axis), ("front", front),
                            ("up", up)):
            if value is None:
                continue
            if value == "":
                data.pop(name, None)
            else:
                data[name] = str(value)
        try:
            frame_from_dict(data)
        except FrameError as exc:
            raise AuthoringError(errors.PROJECT_INVALID, str(exc)) from exc
        if key:
            self._draft(key).frame = data
        else:
            project.frame = data
        self._invalidate()
        return data

    def frame_of(self, key: str):
        """La terna effettiva: quella del componente, o quella del plugin."""
        project = self._project()
        draft = self._draft(key)
        return frame_from_dict(draft.frame or project.frame)

    def frame_report(self) -> list[dict]:
        """`compare()` su ogni arco della gerarchia. Non converte niente.

        Gli esiti sono i quattro di `app/core/frame.py`, con le stesse parole
        che il resolver usera' sul modello vero: `compatible`, `convertible`
        (e allora la mossa e' una sola, e viene nominata), `ambiguous`,
        `undeclared`. V6 non corregge: dice.
        """
        project = self._project()
        registry = self.session.catalog()
        rows: list[dict] = []
        for draft in project.components:
            parent_frame = self.frame_of(draft.key)
            for child in draft.children:
                if child.draft_key:
                    child_frame = self.frame_of(child.draft_key)
                    name = child.draft_key
                else:
                    installed = registry.component(project.resolve_ref(child))
                    if installed is None:
                        continue
                    from app.core.frame import frame_of as frame_of_component

                    child_frame = frame_of_component(installed)
                    name = installed.id
                comparison = compare(parent_frame, child_frame)
                move = comparison.move(scope="subtree:%s" % child.id)
                rows.append({"parent": draft.key, "child": name, "edge": child.id,
                             "result": comparison.result,
                             "describe": comparison.describe(),
                             "move": move})
        return rows

    def verify_frame(self, key: str) -> Report:
        """`verify_frame` sulla geometria vera, non sui numeri dichiarati.

        E' l'helper di authoring che esisteva (`app/core/authoring.py`): dice
        se la parte cresce dove ha dichiarato di crescere, se il socket `base`
        guarda all'indietro, se tutti i socket hanno un verso. Diagnostica,
        mai correzione — come in V4.
        """
        from app.core.authoring import verify_frame as check
        from app.core.component import Piece

        draft = self._draft(key)
        frame = self.frame_of(key)
        report = Report()
        if not frame.growth_axis:
            report.note("FRAME_UNDECLARED",
                        "'%s' non dichiara un growth_axis" % draft.name,
                        where=draft.name,
                        why="un frame non dichiarato non si confronta con nessuno: "
                            "e' il limite dichiarato del contratto")
            return report
        mesh = None
        for model in self.models.values():
            mesh = model.extract(draft.objects)
            if mesh is not None:
                break
        piece = Piece(mesh=mesh,
                      sockets={s.name: s.to_socket() for s in draft.sockets})
        return check(piece, frame.growth_axis, name=draft.name, report=report)

    # ----------------------------------------------------- semantic preview #
    def search_components(self, query: str, limit: int = 8) -> list[tuple[str, float]]:
        """L'indice semantico vero, non una ricerca dell'editor.

        E' il `SemanticIndex` di V1 attraverso `Session.component_index()`:
        quello che l'autore vede qui e' quello che il planner vedrebbe, ed e' il
        motivo per cui esiste (punto 12 della milestone).
        """
        return self.session.component_index().search(str(query), limit=int(limit))

    def search_staged(self, query: str, limit: int = 8) -> list[tuple[str, float]]:
        """La stessa ricerca, ma sulla libreria **piu'** i draft di adesso.

        Risponde alla domanda che l'autore si fa davvero: «se scrivo *dragon
        eye*, il mio componente verra' trovato?». Per rispondere bisogna che il
        componente esista in un indice, quindi si usa la sessione di lavoro.
        """
        session = self._stage()
        return session.component_index().search(str(query), limit=int(limit))

    def planner_preview(self, key: str) -> str:
        """Che cosa il planner vedra' di questo componente. Il testo reso.

        Regola 16 di `PROJECT-INDEX`: cio' che non e' nel testo reso non esiste
        per il modello. Quindi qui non si mostra un riassunto scritto da noi, si
        mostra `ComponentEntry.to_text()` — la stessa funzione che produce il
        vocabolario di produzione.
        """
        project = self._project()
        draft = self._draft(key)
        session = self._stage()
        component = session.catalog().component(draft.component_id(project.plugin_id))
        if component is None:
            return ""
        from app.core.planner.vocabulary import _componente

        return _componente(component).to_text()

    def detail_preview(self, key: str, level: int) -> list[str]:
        """Quali nodi esistono davvero a questo livello di dettaglio.

        Misurato con una build vera, perche' un composite espande figli di
        figli e l'elenco degli `Attachment` dichiarati non lo dice. E non e' il
        LOD di una mesh: qui crescono i nodi.
        """
        built = self.build_component(key, detail_level=int(level), check=False)
        resolved = getattr(built, "resolved", None)
        return [] if resolved is None else [n.path for n in resolved.walk()]

    # ------------------------------------------------- build e validazione #
    def plan_for(self, key: str, *, params=None, detail_level: int = 2,
                 traits=(), effects=(), style: str = "low_poly",
                 node_id: str = "subject") -> dict:
        """Il piano che costruisce questo componente. Un piano normale."""
        project = self._project()
        draft = self._draft(key)
        root: dict[str, Any] = {"id": node_id,
                                "ref": draft.component_id(project.plugin_id)}
        if params:
            root["params"] = dict(params)
        if effects:
            root["effects"] = [dict(e) for e in effects]
        plan: dict[str, Any] = {"version": "1.3", "style": style,
                                "detail_level": int(detail_level), "seed": 0,
                                "root": root}
        if traits:
            plan["traits"] = [dict(t) for t in traits]
        return plan

    def build_component(self, key: str, *, params=None, detail_level: int = 2,
                        traits=(), effects=(), style: str = "low_poly",
                        check: bool = True):
        """Dalla pipeline vera: Registry → Resolver → Traits → Effects → Builder.

        Niente `trimesh` chiamato a mano per simulare il risultato: si installa
        il plugin in una sessione di lavoro e si costruisce come sempre. Vedi la
        testata del file.
        """
        from app.core.session import Options

        session = self._stage()
        plan = self.plan_for(key, params=params, detail_level=detail_level,
                             traits=traits, effects=effects, style=style)
        return session.build(plan, Options(style=style, detail_level=int(detail_level),
                                           check=check))

    def preview_scene(self, key: str, *, params=None, detail_level: int = 2,
                      sockets: bool = True, frame: bool = False, **kwargs):
        """La scena del componente, con i gizmo come geometria in piu'.

        I nodi di gizmo portano il tag `gizmo` e non sono il modello: non
        entrano nei triangoli di `GenerationResult` e non vengono esportati.
        """
        draft = self._draft(key)
        result = self.build_component(key, params=params, detail_level=detail_level,
                                      check=False, **kwargs)
        scene = result.scene()
        chosen = [s.to_socket() for s in draft.sockets] if sockets else []
        return gizmo.preview_scene(scene, sockets=chosen,
                                   frame=self.frame_of(key) if frame else None)

    def lab(self, component_id: str, **kwargs) -> ComponentLab:
        """Il Component Lab su un componente installato."""
        return ComponentLab(self.session, component_id, **kwargs)

    def draft_lab(self, key: str, **kwargs) -> ComponentLab:
        """Il Component Lab su un componente **in lavorazione**.

        Stessa classe e stessa pipeline: il laboratorio non sa se il componente
        viene dalla libreria dell'utente o dalla cartella di lavoro, perche' in
        entrambi i casi e' un `Component` installato in una `Session`.
        """
        project = self._project()
        draft = self._draft(key)
        return ComponentLab(self._stage(), draft.component_id(project.plugin_id),
                            **kwargs)

    def validate(self, *, detail_level: int = 3) -> ValidationReport:
        """Tutti i validatori veri, in un referto con tre gravita'.

        L'ordine segue il flusso: prima cio' che impedisce di scrivere il JSON,
        poi cio' che il **loader** dice del JSON scritto, poi cio' che il
        **registry** dice del plugin installato (dipendenze, materiali, legami
        parametro→effetto), poi cio' che la **pipeline** dice del modello
        costruito (socket, capability, frame, geometria, budget, stile), poi
        cio' che il **retrieval** dice della sua trovabilita'.

        Non c'e' un validatore di authoring, e le diagnostiche dei frame
        arrivano dal resolver come su qualunque generazione — e' il contratto
        di V5, e si applica a ogni collegamento. `frame_report()` resta la
        vista del pannello Frame, e la si usa qui **solo** come ripiego quando
        nessuna build e' arrivata a risolvere: un errore a monte non deve far
        scomparire gli esiti dei frame dal referto.
        """
        project = self._project()
        report = Report()
        self._check_project(project, report)
        staged = None
        session = None
        try:
            session = self._stage()
            staged = self._staged_emit
        except (AuthoringError, ValueError) as exc:
            report.add(getattr(exc, "code", "AUTHORING_EMIT_FAILED"),
                       "il plugin non si e' potuto scrivere: %s" % exc,
                       where=project.plugin_id)
        resolved_any = False
        if session is not None:
            registry = session.catalog()
            report.extend(registry.report)
            for draft in project.components:
                component_id = draft.component_id(project.plugin_id)
                if registry.component(component_id) is None:
                    report.add("AUTHORING_NOT_INSTALLED",
                               "'%s' non e' stato installato dal plugin scritto"
                               % component_id, where=draft.name,
                               why="le diagnostiche del registry dicono perche'")
                    continue
                self._check_retrieval(session, draft, component_id, report)
            for root in project.roots():
                built = self.build_component(root.key, check=True,
                                             detail_level=int(detail_level))
                resolved_any = resolved_any or getattr(built, "resolved", None) is not None
                if built.report is not None:
                    for entry in built.report.sorted():
                        report.entries.append(entry)
        if not resolved_any:
            self._check_frames(report)
        return ValidationReport(report=report,
                                components=list(project.component_ids()),
                                staged=staged)

    # ------------------------------------------------------ salva/installa #
    def save_plugin(self, destination=None) -> Path:
        """Scrive il plugin dati V4/V5. Nessun Python, nessun formato parallelo."""
        project = self._project()
        target = Path(destination) if destination else Path(project.destination or ".")
        result = emit_plugin(project, target, models=self.models)
        project.destination = str(target)
        return result.path

    def install_plugin(self, destination=None, *, build: bool = True) -> InstallResult:
        """Salva, ricarica il registry, verifica, costruisce. Senza riavviare.

        Quattro cose vanno misurate e non assunte, perche' sono le quattro che
        la milestone chiede:

            installato      i componenti sono nel registry
            indice          il `SemanticIndex` si e' accorto del cambiamento
            trovabile       una ricerca per il nome del componente lo trova
            costruibile     almeno la radice passa dalla pipeline vera
        """
        project = self._project()
        path = self.save_plugin(destination)
        previous = self.session.component_index()
        report = Report()
        report.extend(self.session.reload_plugins(path.parent))
        registry = self.session.catalog()
        installed = [c for c in project.component_ids()
                     if registry.component(c) is not None]
        for component_id in project.component_ids():
            if component_id not in installed:
                report.add("AUTHORING_NOT_INSTALLED",
                           "'%s' non risulta installato" % component_id,
                           where=str(path))
        index_invalidated = not previous.is_current(registry)
        index = self.session.component_index()
        found = {}
        for draft in project.components:
            component_id = draft.component_id(project.plugin_id)
            hits = {i for i, _ in index.search(draft.name.replace("_", " "), limit=12)}
            found[component_id] = component_id in hits
            if component_id in installed and not found[component_id]:
                report.warn("AUTHORING_NOT_RETRIEVABLE",
                            "'%s' e' installato ma non lo trova una ricerca per %r"
                            % (component_id, draft.name), where=draft.name,
                            why="il documento semantico nasce dai metadati "
                                "dichiarati: descrizione, ruolo e tag")
        built = {}
        if build:
            from app.core.session import Options

            for root in project.roots():
                plan = self.plan_for(root.key)
                result = self.session.build(plan, Options(check=True))
                built[root.key] = {"ok": bool(result.ok),
                                   "triangles": int(result.triangles)}
                if result.report is not None and not result.report.ok:
                    for entry in result.report.errors():
                        report.entries.append(entry)
        self._invalidate()
        return InstallResult(path=path, report=report, installed=installed,
                             found=found, index_invalidated=index_invalidated,
                             built=built)

    # ------------------------------------------------------ plugin esistente #
    def open_data_plugin(self, path) -> AuthoringProject:
        """Riapre un plugin dati gia' creato, senza introdurre metadati editor-only.

        Si ricostruisce cio' che il JSON dice, e **soltanto** quello: id,
        metadati, socket, parametri, children, frame, materiali, sinonimi. Due
        cose non tornano, e sono dichiarate invece di essere inventate:

            la selezione    la mesh di un componente salvato e' gia' un file
                            per componente, quindi «quali nodi del GLB
                            originale erano questi» non e' scritto da nessuna
                            parte. Il draft tiene il GLB come `mesh_source` e
                            al salvataggio lo copia **byte per byte**: niente
                            riestrazione, niente perdita.
            la copertura    e' un giudizio di chi costruiva, non un dato della
                            libreria, e il plugin non la contiene per scelta
                            (vedi `app/authoring/model.py`).

        Non si tocca nessun plugin di codice: un manifest senza `type: "data"`
        viene rifiutato qui, perche' modificare Python automaticamente e' un
        percorso diverso con una fiducia diversa.
        """
        import json

        from app.core.registry import MANIFEST

        folder = Path(path)
        manifest_path = folder / MANIFEST
        if not manifest_path.is_file():
            raise AuthoringError(errors.FILE_MISSING,
                                 "manca %s in %s" % (MANIFEST, folder))
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            raise AuthoringError(errors.PROJECT_INVALID,
                                 "manifest illeggibile: %s" % exc) from exc
        if manifest.get("type") != "data":
            raise AuthoringError(errors.PROJECT_INVALID,
                                 "si aprono solo plugin dati: %r dichiara type=%r. "
                                 "Un plugin di codice si modifica a mano."
                                 % (manifest.get("id"), manifest.get("type", "code")))
        project = AuthoringProject(
            plugin_id=str(manifest.get("id", folder.name)),
            version=str(manifest.get("version", "1.0.0")),
            name=str(manifest.get("name", "")),
            description=str(manifest.get("description", "")),
            author=str(manifest.get("author", "")),
            license=str(manifest.get("license", "")),
            tags=tuple(manifest.get("tags", ()) or ()),
            frame=dict(manifest.get("frame", {}) or {}),
            synonyms={str(k): tuple(v if isinstance(v, list) else [v])
                      for k, v in (manifest.get("synonyms") or {}).items()},
            destination=str(folder.parent))
        for relative in manifest.get("materials", []) or []:
            data = json.loads((folder / relative).read_text(encoding="utf-8-sig"))
            project.materials.append(dict(data))
        for relative in manifest.get("components", []) or []:
            definition_path = folder / relative
            data = json.loads(definition_path.read_text(encoding="utf-8-sig"))
            project.components.append(
                self._draft_from_data(data, definition_path, project.plugin_id))
        # I riferimenti interni tornano a essere archi fra draft.
        local = {c.component_id(project.plugin_id): c.key for c in project.components}
        for draft in project.components:
            for child in draft.children:
                if child.ref in local:
                    child.ref = DRAFT_PREFIX + local[child.ref]
        self.project = project
        self.models = {}
        self._invalidate()
        return project

    # ----------------------------------------------------------- variants #
    def save_variant(self, recipe: VariantRecipe) -> VariantRecipe:
        """Tiene una ricetta nel progetto. Nessuna mesh duplicata."""
        project = self._project()
        project.variants = [v for v in project.variants if v.name != recipe.name]
        project.variants.append(recipe)
        self._invalidate()
        return recipe

    def variants(self) -> list[VariantRecipe]:
        return list(self._project().variants)

    def build_variant(self, name: str, *, check: bool = True):
        """Costruisce una variant come piano normale, sulla libreria installata."""
        from app.core.session import Options

        recipe = self._project().variant(name)
        if recipe is None:
            raise AuthoringError(errors.UNKNOWN_COMPONENT,
                                 "nessuna variant chiamata %r" % name)
        plan = recipe.to_plan()
        return self.session.build(plan, Options(style=recipe.style,
                                                 detail_level=recipe.detail_level,
                                                 check=check))

    # ------------------------------------------------------------- chiusura #
    def close(self) -> None:
        """Butta la cartella di lavoro. Il plugin salvato non e' li'."""
        if self._stage_dir is not None and self._stage_dir.is_dir():
            shutil.rmtree(self._stage_dir, ignore_errors=True)
        self._stage_dir = None
        self._staged_session = None
        self._staged_fingerprint = ""
        self._staged_emit = None

    def __enter__(self) -> "AuthoringService":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # --------------------------------------------------------------- interni #
    def _project(self) -> AuthoringProject:
        if self.project is None:
            raise AuthoringError(errors.NO_PROJECT,
                                 "nessun progetto di authoring aperto: chiama "
                                 "create_authoring_project() o load_project()")
        return self.project

    def _draft(self, key: str) -> DraftComponent:
        project = self._project()
        draft = project.component(key) or project.component_by_name(str(key))
        if draft is None:
            raise AuthoringError(errors.UNKNOWN_COMPONENT,
                                 "nessun componente in lavorazione con chiave %r"
                                 % key)
        return draft

    def _object(self, key: str) -> SceneObject:
        obj = self._project().object(key)
        if obj is None:
            raise AuthoringError(errors.UNKNOWN_OBJECT,
                                 "nessun oggetto importato con chiave %r" % key)
        return obj

    def _fresh_key(self, name: str) -> str:
        project = self._project()
        taken = {c.key for c in project.components}
        key, index = name, 2
        while key in taken:
            key, index = "%s_%d" % (name, index), index + 1
        return key

    def _reference(self, child: str) -> str:
        """Normalizza un riferimento nelle tre forme ammesse, verificandolo."""
        project = self._project()
        text = str(child)
        if text.startswith(DRAFT_PREFIX):
            self._draft(text[len(DRAFT_PREFIX):])
            return text
        if text.startswith(VARIANT_PREFIX):
            name = text[len(VARIANT_PREFIX):]
            if project.variant(name) is None:
                raise AuthoringError(errors.UNKNOWN_COMPONENT,
                                     "nessuna variant chiamata %r" % name)
            return text
        if project.component(text) is not None:
            return DRAFT_PREFIX + text
        if project.variant(text) is not None:
            return VARIANT_PREFIX + text
        if self.session.catalog().component(text) is None:
            raise AuthoringError(errors.UNKNOWN_COMPONENT,
                                 "%r non e' un draft, non e' una variant e non e' "
                                 "un componente installato" % text)
        return text

    @staticmethod
    def _child_id(host: DraftComponent, ref: str) -> str:
        base = ref.split(":")[-1].replace(DRAFT_PREFIX, "") or "child"
        taken = {c.id for c in host.children}
        if base not in taken:
            return base
        index = 2
        while "%s_%d" % (base, index) in taken:
            index += 1
        return "%s_%d" % (base, index)

    @staticmethod
    def _apply_child_options(edge: DraftChild, options: dict) -> None:
        from app.core.socket import SCALE_MODES

        allowed = {"level", "optional", "on_request", "replaces", "replaces_parent",
                   "on", "own_socket", "scale_mode", "insert", "roll",
                   "requirement", "params", "material", "tags"}
        unknown = set(options) - allowed
        if unknown:
            raise AuthoringError(errors.PROJECT_INVALID,
                                 "opzioni di aggancio non supportate: %s"
                                 % ", ".join(sorted(unknown)))
        for name, value in options.items():
            if name == "level":
                edge.level = int(value)
            elif name in ("optional", "on_request", "replaces_parent"):
                setattr(edge, name, bool(value))
            elif name in ("insert", "roll"):
                setattr(edge, name, None if value is None else float(value))
            elif name == "requirement":
                edge.requirement = None if value is None else dict(value)
            elif name == "params":
                edge.params = dict(value)
            elif name == "tags":
                edge.tags = tuple(str(v) for v in value)
            elif name == "scale_mode":
                if str(value) not in SCALE_MODES:
                    raise AuthoringError(errors.PROJECT_INVALID,
                                         "scale_mode atteso fra %s, non %r"
                                         % ("/".join(SCALE_MODES), value))
                edge.scale_mode = str(value)
            else:
                setattr(edge, name, str(value))

    @staticmethod
    def _cycle(project: AuthoringProject) -> bool:
        """Un ciclo nella gerarchia dei draft. Si cerca prima di accettarlo."""
        edges = {c.key: [child.draft_key for child in c.children if child.draft_key]
                 for c in project.components}
        state: dict[str, int] = {}

        def visit(key: str) -> bool:
            if state.get(key) == 1:
                return True
            if state.get(key) == 2:
                return False
            state[key] = 1
            for target in edges.get(key, ()):
                if target in edges and visit(target):
                    return True
            state[key] = 2
            return False

        return any(visit(key) for key in edges)

    def _effect_binding(self, value, param: str) -> dict:
        """Un legame parametro → effetto, verificato contro cio' che e' installato.

        Le chiavi sono le quattro di `ParamEffect` e nient'altro: un plugin
        dati non puo' nemmeno **nominare** un callable, un modulo, una
        espressione o una matrice (V5 §1), e l'editor non deve essere la strada
        per aggirarlo. L'effetto, il knob e l'ambito devono esistere adesso: il
        `Registry` li verificherebbe comunque, ma dirlo qui evita di salvare un
        plugin che si rifiuta da solo.
        """
        if not isinstance(value, dict):
            raise AuthoringError(errors.PARAM_STRATEGY,
                                 "effect deve essere un oggetto con type, "
                                 "parameter, scope, neutral")
        unknown = set(value) - {"type", "parameter", "scope", "neutral"}
        if unknown:
            raise AuthoringError(errors.PARAM_STRATEGY,
                                 "effect: chiavi non ammesse: %s"
                                 % ", ".join(sorted(unknown)))
        effect_id = str(value.get("type", ""))
        effect = self.session.catalog().effect(effect_id)
        if effect is None:
            raise AuthoringError(errors.PARAM_STRATEGY,
                                 "l'effetto %r non e' installato" % effect_id)
        knob = str(value.get("parameter", "amount"))
        if knob != "amount" and knob not in effect.params:
            raise AuthoringError(errors.PARAM_STRATEGY,
                                 "l'effetto %s non dichiara il knob %r (ha %s)"
                                 % (effect_id, knob,
                                    ", ".join(sorted(effect.params)) or "solo amount"))
        scope = str(value.get("scope", "part"))
        if not effect.fits_scope(scope):
            raise AuthoringError(errors.PARAM_STRATEGY,
                                 "l'effetto %s non dichiara l'ambito %r (ha %s)"
                                 % (effect_id, scope, ", ".join(effect.scopes)))
        data = {"type": effect_id, "parameter": knob, "scope": scope}
        if value.get("neutral") is not None:
            data["neutral"] = float(value["neutral"])
        del param
        return data

    def _invalidate(self) -> None:
        """La cartella di lavoro non e' piu' quella giusta. Si riemette dopo."""
        self._staged_fingerprint = ""

    def _stage(self):
        """La sessione di lavoro: il plugin emesso e installato per davvero.

        Si riemette solo quando l'impronta di cio' che finirebbe nel plugin e'
        cambiata. Muovere uno slider non la cambia — i parametri viaggiano nel
        piano — quindi il laboratorio dei parametri non paga un caricamento di
        registry a ogni passo.
        """
        from app.core.session import Session

        project = self._project()
        fingerprint = project.fingerprint()
        if self._staged_session is not None and fingerprint == self._staged_fingerprint:
            return self._staged_session
        if self._stage_dir is None:
            self._stage_dir = Path(tempfile.mkdtemp(prefix="3dgen-authoring-"))
        for child in self._stage_dir.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
        self._staged_emit = emit_plugin(project, self._stage_dir, models=self.models)
        session = Session(provider=self.session.provider,
                          plugin_paths=tuple([*(self.session.plugin_paths or ()),
                                              str(self._stage_dir)]))
        if not session.plugin_paths or len(session.plugin_paths) == 1:
            from app.core.session import PLUGIN

            session.plugin_paths = (str(PLUGIN), str(self._stage_dir))
        session.catalog()
        self._staged_session = session
        self._staged_fingerprint = fingerprint
        return session

    # ----------------------------------------------------------- controlli #
    def _check_project(self, project: AuthoringProject, report: Report) -> None:
        """Cio' che si vede senza scrivere niente: nomi, riferimenti, strategie."""
        if not project.components:
            report.warn("AUTHORING_EMPTY_PROJECT",
                        "il progetto non dichiara nessun componente",
                        where=project.plugin_id)
        names: dict[str, str] = {}
        for draft in project.components:
            if draft.name in names:
                report.add("AUTHORING_DUPLICATE_NAME",
                           "due componenti si chiamano '%s'" % draft.name,
                           where=draft.key)
            names[draft.name] = draft.key
            if draft.composite and not draft.children:
                report.add("AUTHORING_EMPTY_COMPONENT",
                           "'%s' non ha ne' geometria ne' figli" % draft.name,
                           where=draft.name,
                           why="un composite esiste per contenere: senza figli "
                               "il loader lo rifiuterebbe")
            if not draft.description:
                report.note("AUTHORING_NO_DESCRIPTION",
                            "'%s' non ha una descrizione" % draft.name,
                            where=draft.name,
                            why="la descrizione e' il documento che il retrieval "
                                "indicizza: senza, il componente e' trovabile solo "
                                "per id, ruolo e tag")
            for param in draft.params:
                if param.strategy == "none":
                    report.add("AUTHORING_PARAM_STRATEGY",
                               "il parametro '%s.%s' non dichiara una strategia"
                               % (draft.name, param.name), where=draft.name,
                               why="transform (una scala) oppure effect (un "
                                   "effetto installato): il loader rifiuta "
                                   "entrambi e nessuno dei due")
                elif param.strategy == "both":
                    report.add("AUTHORING_PARAM_STRATEGY",
                               "il parametro '%s.%s' dichiara transform **e** effect"
                               % (draft.name, param.name), where=draft.name)
                elif param.strategy == "transform" and draft.composite:
                    report.add("AUTHORING_PARAM_STRATEGY",
                               "'%s.%s' scala una mesh che non c'e'"
                               % (draft.name, param.name), where=draft.name,
                               why="un componente senza mesh non ha niente da "
                                   "scalare: serve un effect")
            socket_names = {s.name for s in draft.sockets}
            for mount in draft.mounts:
                socket_id = str(mount.get("socket_id", ""))
                if socket_id and socket_id not in socket_names:
                    report.add("AUTHORING_MOUNT_WITHOUT_SOCKET",
                               "'%s' espone un innesto su un socket che non ha: %r"
                               % (draft.name, socket_id), where=draft.name,
                               alternatives=sorted(socket_names)[:6])
            for child in draft.children:
                try:
                    reference = project.resolve_ref(child)
                except AuthoringError as exc:
                    report.add(exc.code, exc.message, where=draft.name)
                    continue
                # Un riferimento e' buono se e' un componente di questo
                # progetto (lo sara' appena si salva) oppure uno installato.
                local_ids = set(project.component_ids())
                if (not child.draft_key and reference not in local_ids
                        and self.session.catalog().component(reference) is None):
                    report.add("AUTHORING_REF_NOT_FOUND",
                               "l'arco '%s' di '%s' punta a %r, che non e' ne' un "
                               "componente di questo progetto ne' uno installato"
                               % (child.id, draft.name, reference), where=draft.name)
                if child.variant_name:
                    recipe = project.variant(child.variant_name)
                    if recipe is not None and not recipe.embeddable:
                        report.warn("AUTHORING_VARIANT_NOT_EMBEDDABLE",
                                    "la variant '%s' porta %s che un Attachment non "
                                    "trasporta" % (recipe.name,
                                                   " e ".join(recipe.lost_in_attachment())),
                                    where=draft.name,
                                    why="trait ed effetti sono cose del piano; i "
                                        "parametri si incorporano, loro no")
        for draft in project.components:
            for capability in draft.provides:
                info = self.session.catalog().capability(capability)
                if not info.known and capability not in {
                        str(m.get("capability", "")) for c in project.components
                        for m in c.mounts}:
                    report.note("AUTHORING_NEW_CAPABILITY",
                                "'%s' fornisce una capability che nessuno accetta "
                                "ancora: %r" % (draft.name, capability),
                                where=draft.name,
                                why="dichiararne una nuova e' lecito ed e' dati; "
                                    "finche' nessuno la accetta, nessun pezzo ci "
                                    "si monta")

    def _check_retrieval(self, session, draft: DraftComponent, component_id: str,
                         report: Report) -> None:
        """Il componente e' trovabile con le parole che lo descrivono?"""
        words = draft.name.replace("_", " ")
        hits = {i for i, _ in session.component_index().search(words, limit=12)}
        if component_id not in hits:
            report.warn("AUTHORING_NOT_RETRIEVABLE",
                        "'%s' non viene trovato cercando %r" % (component_id, words),
                        where=draft.name,
                        why="il documento semantico nasce dai metadati dichiarati: "
                            "descrizione, ruolo, tag, capability")

    def _check_frames(self, report: Report) -> None:
        """Gli esiti del contratto dei frame sugli archi della gerarchia."""
        for row in self.frame_report():
            if row["result"] == FRAME_CONVERTIBLE:
                move = row.get("move") or {}
                report.warn("FRAME_CONVERTIBLE", row["describe"],
                            where="%s/%s" % (row["parent"], row["edge"]),
                            alternatives=["fx:rotate axis=%s angle=%s"
                                          % (move.get("params", {}).get("axis", "?"),
                                             move.get("params", {}).get("angle", "?"))])
            elif row["result"] == FRAME_AMBIGUOUS:
                report.warn("FRAME_AMBIGUOUS", row["describe"],
                            where="%s/%s" % (row["parent"], row["edge"]),
                            why="una terna incompleta non determina la rotazione: "
                                "dichiarare up e front sul componente")

    def _draft_from_data(self, data: dict, definition_path: Path,
                         plugin_id: str) -> DraftComponent:
        """Un draft da una definizione JSON. Nessun campo inventato."""
        component_id = str(data.get("id", ""))
        name = component_id.partition(":")[2] or component_id
        mesh_source = ""
        if data.get("mesh"):
            candidate = (definition_path.parent / str(data["mesh"])).resolve()
            mesh_source = str(candidate)
        params = []
        for param_name, spec in (data.get("params") or {}).items():
            params.append(DraftParam.from_dict(dict(spec, name=param_name)))
        children = []
        for child in data.get("children") or []:
            children.append(DraftChild(
                id=str(child.get("id", "")), ref=str(child.get("component", "")),
                level=int(child.get("level", 2)),
                optional=bool(child.get("optional", False)),
                on_request=bool(child.get("on_request", False)),
                replaces=str(child.get("replaces", "")),
                replaces_parent=bool(child.get("replaces_parent", False)),
                on=str(child.get("on", "")),
                own_socket=str(child.get("own_socket", "base")),
                scale_mode=str(child.get("scale_mode", "none")),
                insert=None if child.get("insert") is None else float(child["insert"]),
                roll=None if child.get("roll") is None else float(child["roll"]),
                requirement=dict(child["requirement"]) if child.get("requirement") else None,
                params=dict(child.get("params", {})),
                material=str(child.get("material", "")),
                tags=tuple(child.get("tags", ()) or ())))
        return DraftComponent(
            key=name, name=name, description=str(data.get("description", "")),
            role=str(data.get("role", "")), material=str(data.get("material", "")),
            tags=tuple(data.get("tags", ()) or ()),
            provides=tuple(str(p) if isinstance(p, str) else str(p.get("name", ""))
                           for p in data.get("provides", ()) or ()),
            styles=tuple(data.get("styles", ()) or ()),
            requires=tuple(data.get("requires", ()) or ()),
            mounts=[dict(m) if isinstance(m, dict) else {"capability": str(m)}
                    for m in data.get("mounts", ()) or ()],
            mesh_source=mesh_source,
            sockets=[DraftSocket.from_dict(s) for s in data.get("sockets", ()) or ()],
            params=params, children=children,
            layout_regions=[dict(r) for r in data.get("layout_regions", ()) or ()],
            frame=dict(data.get("frame", {}) or {}))
