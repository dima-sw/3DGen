"""Importare un GLB per guardarlo, non per convertirlo.

Due vincoli dichiarati prima della prima riga, entrambi presi da
`VISION-GAP.md` §5.3 e da V4:

1. **Niente inferenza.** Importare non significa indovinare parti, socket o
   parametri. Questo modulo elenca cio' che il file dichiara — nodi,
   triangoli, limiti, trasformazione, tinta — e si ferma. Riconoscere le parti
   con un modello e' una feature separata e successiva.
2. **Niente esecuzione, e niente file fuori dalla cartella del modello.** Un
   `.gltf` puo' nominare risorse esterne: passano dallo stesso lettore
   confinato di `app/core/data_plugin.py`, con la cartella del modello come
   radice. `trimesh` riceve byte e un dizionario, mai un resolver di
   filesystem o di rete.

## Perche' riusa i privati di `data_plugin`

Che cosa sia un glTF 2.0 valido, e che cosa sia una `uri` ammissibile, e'
deciso in **un** posto: `app/core/data_plugin.py`. Scrivere qui un secondo
parser vorrebbe dire due idee di validita' che divergono alla prima
divergenza, e il formato che si salva e' quello che il loader rilegge. Si
importano quindi i suoi helper invece di copiarli — e quando il loader
diventera' piu' severo, l'import lo diventera' insieme.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import trimesh

from app.authoring import errors
from app.authoring.errors import AuthoringError
from app.authoring.model import SceneObject, SourceModel
# Una sola idea di glTF valido, una sola idea di risorsa confinata.
from app.core.data_plugin import (DataPluginError, _face_colors, _gltf_document,
                                  _resources)

SUFFIXES = (".glb", ".gltf")


def _hex(colors) -> str:
    """La tinta rappresentativa di una mesh: la media dei colori, se ci sono."""
    if colors is None or len(colors) == 0:
        return ""
    mean = np.asarray(colors, dtype=float).reshape(-1, np.asarray(colors).shape[-1])
    rgb = np.clip(mean[:, :3].mean(axis=0), 0, 255).astype(int)
    return "#%02x%02x%02x" % tuple(int(v) for v in rgb)


@dataclass
class LoadedModel:
    """Il file importato: cio' che si guarda, piu' la geometria per nodo.

    La geometria sta qui e non nel progetto serializzato: un `.3dgenproj` non
    contiene mesh, come un `.my3d` non contiene mesh. Riaprendo un progetto i
    modelli si reimportano dai loro percorsi, e se un file non c'e' piu' lo si
    dice invece di inventarlo.
    """

    source: SourceModel
    meshes: dict[str, trimesh.Trimesh] = field(default_factory=dict)

    @property
    def path(self) -> str:
        return self.source.path

    def object(self, key: str) -> SceneObject | None:
        return self.source.object(key)

    def extract(self, keys) -> trimesh.Trimesh | None:
        """Soltanto la geometria che serve, con le trasformazioni gia' bakeate.

        Le trasformazioni dei nodi sono applicate ai vertici al momento
        dell'import, quindi estrarre due nodi e concatenarli conserva le loro
        posizioni relative: e' la stessa politica che `data_plugin._load_mesh`
        usa per un GLB multi-nodo, e per la stessa ragione — si concatenano
        vertici e facce a mano, cosi' nessun materiale predefinito viene
        inventato per i pezzi che non ne hanno uno.
        """
        wanted = [k for k in keys if k in self.meshes]
        if not wanted:
            return None
        meshes = [self.meshes[k] for k in wanted]
        if len(meshes) == 1:
            return meshes[0].copy()
        vertices, faces = trimesh.util.append_faces([m.vertices for m in meshes],
                                                    [m.faces for m in meshes])
        merged = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
        if any(getattr(m.visual, "defined", False) for m in meshes):
            fallback = np.array([154, 160, 166, 255], dtype=np.uint8)
            stacked = []
            for mesh in meshes:
                colors = _face_colors(mesh)
                stacked.append(colors if colors is not None
                               else np.tile(fallback, (len(mesh.faces), 1)))
            merged.visual.face_colors = np.vstack(stacked)
        return merged


def load_model(path, *, prefix: str = "") -> LoadedModel:
    """Legge un GLB/glTF e ne elenca i nodi di geometria.

    `prefix` entra nelle chiavi degli oggetti: due file con lo stesso nome di
    nodo devono restare distinguibili dentro lo stesso progetto, e una chiave
    che dipende dall'ordine di importazione non sarebbe un'identita'.
    """
    source = Path(path)
    suffix = source.suffix.lower()
    if suffix not in SUFFIXES:
        raise AuthoringError(errors.MODEL_FORMAT,
                             "formato non supportato: %s (GLB/glTF soltanto; "
                             "FBX, USD e .blend non sono previsti)" % (suffix or "?"))
    if not source.is_file():
        raise AuthoringError(errors.FILE_MISSING, "modello assente: %s" % source)

    root = source.parent.resolve()
    try:
        raw = source.read_bytes()
        document = _gltf_document(raw, suffix, str(source))
        resources, _ = _resources(document, source.resolve(), root)
        scene = trimesh.load(io.BytesIO(raw), file_type=suffix[1:],
                             resolver=resources, force="scene", process=False,
                             allow_remote=False)
    except DataPluginError:
        raise
    except Exception as exc:                       # noqa: BLE001 - isolamento
        raise AuthoringError(errors.MODEL_INVALID,
                             "modello GLB/glTF non valido in %s: %s"
                             % (source, exc)) from exc

    stem = prefix or source.stem
    objects: list[SceneObject] = []
    meshes: dict[str, trimesh.Trimesh] = {}
    for node in sorted(scene.graph.nodes_geometry):
        transform, geometry_name = scene.graph[node]
        geometry = scene.geometry[geometry_name]
        if not isinstance(geometry, trimesh.Trimesh):
            raise AuthoringError(errors.MODEL_INVALID,
                                 "il modello contiene geometria non triangolare: %s"
                                 % node)
        if len(geometry.vertices) == 0 or len(geometry.faces) == 0:
            continue
        mesh = geometry.copy()
        colors = _face_colors(mesh)
        mesh.apply_transform(transform)
        key = "%s/%s" % (stem, node)
        meshes[key] = mesh
        low, high = mesh.bounds
        objects.append(SceneObject(
            key=key, name=str(node), triangles=int(len(mesh.faces)),
            bounds=(tuple(float(v) for v in low), tuple(float(v) for v in high)),
            transform=tuple(float(v) for v in np.asarray(transform).ravel()),
            color=_hex(colors), source=str(source)))
    if not objects:
        raise AuthoringError(errors.MODEL_EMPTY,
                             "il modello non contiene triangoli: %s" % source)
    return LoadedModel(source=SourceModel(path=str(source), objects=objects),
                       meshes=meshes)


def export_glb(mesh: trimesh.Trimesh, destination) -> Path:
    """Scrive un GLB valido. Nessun esportatore nuovo: quello di trimesh.

    Si passa da `export(file_type="glb")` e si scrivono i byte, cosi' il file
    che il plugin dichiara e' lo stesso che `data_plugin._load_mesh`
    rileggerebbe — ed e' quello che il test di round-trip verifica.
    """
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    raw = trimesh.Scene(mesh).export(file_type="glb")
    target.write_bytes(raw if isinstance(raw, bytes) else bytes(raw))
    return target
