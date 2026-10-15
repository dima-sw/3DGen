"""Dal progetto di authoring al plugin dati. Nessun formato nuovo, nessun Python.

Quello che esce e' esattamente la struttura di V4/V5:

    my_plugin/
    ├ plugin.json          type: "data", e le sole chiavi che un manifest dati ammette
    ├ components/*.json    la traduzione dei modelli esistenti in JSON
    ├ meshes/*.glb         soltanto la geometria che serve, con le trasformazioni
    └ materials/*.json     `MaterialSpec` dichiarati

## Tre decisioni, e il perche'

**Un file per componente, chiamato come il componente.** Il nome e' gia'
vincolato (`check_name`: minuscole, cifre, `_`, `-`), quindi non puo' diventare
un percorso. Il JSON punta alla mesh in modo **relativo** (`../meshes/x.glb`),
come i fixture di V4: un plugin copiato altrove continua a funzionare, ed e'
anche la ragione per cui `PluginInfo.fingerprint` usa percorsi relativi.

**Si esporta solo la geometria necessaria.** Un componente ricavato da tre nodi
di un GLB da ottanta porta tre nodi, non ottanta nascosti. Le trasformazioni
dei nodi sono bakeate nei vertici all'import (`inspect.load_model`), quindi la
copia e' nella posizione in cui l'autore l'ha vista.

**Niente campi dell'editor.** `coverage`, `notes`, `selection`, `hidden`,
`objects`, `mesh_source` non compaiono nel JSON: il plugin e' una libreria, non
uno stato di lavoro. Un test li cerca e non li trova.

## Confinamento

Tutto si scrive sotto `destination/plugin_id` e niente altrove. I nomi passano
da `check_name`, la destinazione viene risolta, e un nome di componente o di
materiale che tentasse di uscire e' rifiutato prima di aprire un file. E' la
stessa politica di `safe_path` dal lato della scrittura.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.authoring import errors
from app.authoring.errors import AuthoringError
from app.authoring.inspect import export_glb
from app.authoring.model import AuthoringProject, DraftComponent, check_name

# Le chiavi che un manifest dati ammette. **[V7]** si leggono da dove vive il
# formato (`app/core/data_plugin.py`) invece di essere ricopiate: emettere una
# chiave in piu' farebbe rifiutare il plugin con INVALID_MANIFEST, e quel
# rifiuto va evitato leggendo l'elenco vero, non tenendone una copia.
from app.core.data_plugin import DATA_MANIFEST_KEYS as MANIFEST_KEYS


@dataclass
class EmitResult:
    """Dove e' stato scritto, e cosa."""

    path: Path
    components: list[str] = field(default_factory=list)
    meshes: list[str] = field(default_factory=list)
    materials: list[str] = field(default_factory=list)
    manifest: dict = field(default_factory=dict)

    @property
    def files(self) -> list[str]:
        return ["plugin.json", *self.components, *self.meshes, *self.materials]

    def describe(self) -> str:
        return "%s: %d componenti, %d mesh, %d materiali" % (
            self.path, len(self.components), len(self.meshes), len(self.materials))


def _confined(root: Path, relative: str) -> Path:
    """Un file dentro la cartella del plugin, o un errore. Mai fuori."""
    target = (root / relative).resolve()
    if not target.is_relative_to(root.resolve()):
        raise AuthoringError(errors.PATH_UNSAFE,
                             "il salvataggio uscirebbe dalla cartella del "
                             "plugin: %r" % relative)
    return target


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")


def component_data(project: AuthoringProject, draft: DraftComponent,
                   *, mesh_relative: str = "") -> dict:
    """La definizione JSON di un componente. Solo chiavi del formato V4/V5."""
    data: dict[str, Any] = {"id": draft.component_id(project.plugin_id)}
    if draft.description:
        data["description"] = draft.description
    if mesh_relative:
        data["mesh"] = mesh_relative
    for key in ("role", "material"):
        value = getattr(draft, key)
        if value:
            data[key] = value
    for key in ("tags", "provides", "styles", "requires"):
        value = getattr(draft, key)
        if value:
            data[key] = list(value)
    if draft.mounts:
        data["mounts"] = [dict(m) for m in draft.mounts]
    if draft.sockets:
        data["sockets"] = [s.to_data() for s in draft.sockets]
    if draft.params:
        data["params"] = {p.name: p.to_data() for p in draft.params}
    if draft.children:
        data["children"] = [
            child.to_data(project.resolve_ref(child),
                          params=project.resolve_params(child))
            for child in draft.children]
    if draft.layout_regions:
        data["layout_regions"] = [dict(r) for r in draft.layout_regions]
    if draft.frame:
        data["frame"] = dict(draft.frame)
    return data


def manifest_data(project: AuthoringProject, components: list[str],
                  materials: list[str]) -> dict:
    """Il `plugin.json`, con `type: "data"` e nient'altro di eseguibile."""
    synonyms = {str(word).strip().lower(): sorted({str(v).strip().lower()
                                                   for v in values if str(v).strip()})
                for word, values in project.synonyms.items() if str(word).strip()}
    # Le parole che un componente dichiara di avere come sinonimi diventano
    # ponti nel manifest: e' li' che `Registry.synonyms()` le legge, ed e'
    # dati, non codice (regola 11 di PROJECT-INDEX).
    for draft in project.components:
        for word in draft.synonyms:
            key = str(word).strip().lower()
            if not key:
                continue
            existing = set(synonyms.get(key, ()))
            existing.add(draft.name)
            synonyms[key] = sorted(existing)
    data: dict[str, Any] = {"id": project.plugin_id, "version": project.version,
                            "type": "data",
                            "components": components, "materials": materials}
    for key in ("name", "description", "author", "license"):
        value = getattr(project, key)
        if value:
            data[key] = value
    if project.tags:
        data["tags"] = sorted(project.tags)
    if project.frame:
        data["frame"] = dict(project.frame)
    if synonyms:
        data["synonyms"] = synonyms
    unknown = set(data) - set(MANIFEST_KEYS)
    if unknown:                                    # difensivo, non raggiungibile
        raise AuthoringError(errors.PROJECT_INVALID,
                             "il manifest avrebbe chiavi non ammesse: %s"
                             % ", ".join(sorted(unknown)))
    return data


def emit_plugin(project: AuthoringProject, destination, *, models=None,
                clean: bool = True) -> EmitResult:
    """Scrive il plugin dati. `models` sono i `LoadedModel` per l'estrazione.

    `clean` riscrive da zero le tre sottocartelle che questo emettitore
    possiede, perche' un componente rinominato lascerebbe altrimenti il suo
    vecchio JSON nel manifest di nessuno — e un plugin con un file orfano e' un
    plugin che un domani si ricarica diverso.
    """
    root = (Path(destination) / project.plugin_id).resolve()
    if clean:
        for folder in ("components", "meshes", "materials"):
            path = root / folder
            if path.is_dir():
                shutil.rmtree(path)
    root.mkdir(parents=True, exist_ok=True)

    models = dict(models or {})
    components: list[str] = []
    meshes: list[str] = []
    materials: list[str] = []

    for draft in project.components:
        name = check_name(draft.name, "nome del componente")
        mesh_relative = ""
        if draft.mesh_source:
            source = Path(draft.mesh_source)
            if not source.is_file():
                raise AuthoringError(errors.FILE_MISSING,
                                     "la mesh dichiarata da '%s' non c'e': %s"
                                     % (name, source))
            target = _confined(root, "meshes/%s.glb" % name)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            mesh_relative = "../meshes/%s.glb" % name
            meshes.append("meshes/%s.glb" % name)
        elif draft.objects:
            mesh = _extract(draft, models)
            target = _confined(root, "meshes/%s.glb" % name)
            export_glb(mesh, target)
            mesh_relative = "../meshes/%s.glb" % name
            meshes.append("meshes/%s.glb" % name)
        relative = "components/%s.json" % name
        _write_json(_confined(root, relative),
                    component_data(project, draft, mesh_relative=mesh_relative))
        components.append(relative)

    for material in project.materials:
        name = check_name(material.get("name", ""), "nome del materiale")
        relative = "materials/%s.json" % name
        _write_json(_confined(root, relative), dict(material, name=name))
        materials.append(relative)

    manifest = manifest_data(project, components, materials)
    _write_json(root / "plugin.json", manifest)
    return EmitResult(path=root, components=components, meshes=meshes,
                      materials=materials, manifest=manifest)


def _extract(draft: DraftComponent, models: dict):
    """La geometria dei soli oggetti del draft, da tutti i modelli aperti."""
    pieces = []
    for model in models.values():
        mesh = model.extract(draft.objects)
        if mesh is not None:
            pieces.append(mesh)
    if not pieces:
        raise AuthoringError(errors.UNKNOWN_OBJECT,
                             "il componente '%s' nomina oggetti che non sono in "
                             "nessun modello aperto: %s"
                             % (draft.name, ", ".join(draft.objects)))
    if len(pieces) == 1:
        return pieces[0]
    import trimesh

    vertices, faces = trimesh.util.append_faces([p.vertices for p in pieces],
                                                [p.faces for p in pieces])
    return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
