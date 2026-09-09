"""Scrittura di un glTF binario **animato**, composto a mano.

trimesh esporta glTF ma non scrive animazioni: non ha ne' `animations` ne'
`samplers` nel suo scrittore, e non esiste un parametro per aggiungerle. Le
alternative erano una dipendenza in piu' (`pygltflib`) o comporre il JSON qui.
Il formato e' documentato e la parte che serve e' piccola — nodi, accessori,
un'animazione di sole rotazioni — quindi si compone qui: nessuna dipendenza
nuova per una manciata di dizionari.

## La gerarchia

Ogni parte diventa un nodo posto nel proprio **pivot**, cioe' il socket a cui
e' attaccata; la mesh viene salvata in coordinate relative a quel pivot. Cosi'
una rotazione sul nodo ruota la parte attorno al suo giunto e trascina i figli,
che e' la definizione stessa di animazione a parti rigide. A riposo la somma
delle traslazioni lungo la catena ridA' esattamente la posa originale.
"""
from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from app.anim.clip import Clip
from app.anim.skeleton import Skeleton
from app.core.logging_setup import get

log = get("anim.gltf")

# costanti glTF usate qui
FLOAT = 5126
UNSIGNED_INT = 5125
ARRAY_BUFFER = 34962
ELEMENT_ARRAY_BUFFER = 34963
TRIANGLES = 4


class GltfError(ValueError):
    pass


@dataclass
class _Buffer:
    """Accumula i dati binari e genera bufferView e accessor coerenti."""

    blob: bytearray = field(default_factory=bytearray)
    views: list[dict] = field(default_factory=list)
    accessors: list[dict] = field(default_factory=list)

    def _view(self, data: bytes, target: int | None = None) -> int:
        # ogni vista parte a multiplo di 4: lo chiede la specifica
        while len(self.blob) % 4:
            self.blob.append(0)
        offset = len(self.blob)
        self.blob.extend(data)
        view = {"buffer": 0, "byteOffset": offset, "byteLength": len(data)}
        if target is not None:
            view["target"] = target
        self.views.append(view)
        return len(self.views) - 1

    def add(self, array: np.ndarray, kind: str, component: int,
            target: int | None = None, minmax: bool = False) -> int:
        dtype = np.float32 if component == FLOAT else np.uint32
        valori = np.ascontiguousarray(array, dtype=dtype)
        view = self._view(valori.tobytes(), target)
        piatto = valori.reshape(len(valori), -1) if valori.ndim > 1 else valori
        accessor = {
            "bufferView": view, "componentType": component,
            "count": int(len(valori)), "type": kind,
        }
        if minmax:
            accessor["min"] = [float(v) for v in np.atleast_1d(piatto.min(axis=0))]
            accessor["max"] = [float(v) for v in np.atleast_1d(piatto.max(axis=0))]
        self.accessors.append(accessor)
        return len(self.accessors) - 1


def _colour(hex_value: str) -> list[float]:
    h = (hex_value or "#9aa0a6").lstrip("#")
    if len(h) != 6:
        h = "9aa0a6"
    return [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)] + [1.0]


def _node_order(skeleton: Skeleton) -> list[str]:
    """Padri prima dei figli: un nodo non puo' citare un indice non ancora creato."""
    ordine: list[str] = []
    da_fare = [j.name for j in skeleton.joints if j.parent is None]
    while da_fare:
        nome = da_fare.pop(0)
        if nome in ordine:
            continue
        ordine.append(nome)
        da_fare.extend(j.name for j in skeleton.children(nome))
    # cicli o giunti irraggiungibili: si aggiungono in coda, meglio che perderli
    ordine += [j.name for j in skeleton.joints if j.name not in ordine]
    return ordine


def write(scene, skeleton: Skeleton, clips: list[Clip], path: str | Path) -> Path:
    """Scrive un `.glb` con la gerarchia delle parti e le animazioni.

    Le mesh della scena sono in coordinate mondo: qui vengono spostate nel
    sistema del proprio giunto, ed e' la catena delle traslazioni a rimetterle
    al loro posto.
    """
    destinazione = Path(path)
    if destinazione.suffix.lower() != ".glb":
        destinazione = destinazione.with_suffix(".glb")
    if not skeleton.joints:
        raise GltfError("scheletro vuoto: solo gli assemblaggi si possono animare")

    per_id = {n.id: n for n in scene.nodes}
    ordine = [n for n in _node_order(skeleton) if n in per_id or skeleton.get(n)]
    indice_di = {nome: i for i, nome in enumerate(ordine)}

    buffer = _Buffer()
    materiali: list[dict] = []
    indice_materiale: dict[str, int] = {}
    meshes: list[dict] = []
    nodi: list[dict] = []

    for nome in ordine:
        giunto = skeleton.get(nome)
        pivot = np.asarray(giunto.pivot, dtype=float)
        padre = skeleton.get(giunto.parent) if giunto.parent else None
        # traslazione locale: dal pivot del padre al proprio
        locale = pivot - (np.asarray(padre.pivot, dtype=float)
                          if padre is not None else np.zeros(3))

        nodo = {"name": nome, "translation": [float(v) for v in locale]}
        figli = [indice_di[c.name] for c in skeleton.children(nome)
                 if c.name in indice_di]
        if figli:
            nodo["children"] = figli

        origine = per_id.get(nome)
        if origine is not None and len(origine.mesh.faces):
            nodo["mesh"] = len(meshes)
            meshes.append(_mesh_entry(buffer, origine, pivot,
                                      materiali, indice_materiale))
        nodi.append(nodo)

    animazioni = [_animation(buffer, clip, indice_di) for clip in clips]
    animazioni = [a for a in animazioni if a["channels"]]

    documento = {
        "asset": {"version": "2.0", "generator": "3DGen"},
        "scene": 0,
        "scenes": [{"nodes": [indice_di[ordine[0]]] if ordine else []}],
        "nodes": nodi,
        "meshes": meshes,
        "materials": materiali or [{"pbrMetallicRoughness": {
            "baseColorFactor": _colour("#9aa0a6")}}],
        "bufferViews": buffer.views,
        "accessors": buffer.accessors,
        "buffers": [{"byteLength": len(buffer.blob)}],
    }
    if animazioni:
        documento["animations"] = animazioni

    _write_glb(documento, bytes(buffer.blob), destinazione)
    log.info("glTF animato: %s (%d nodi, %d animazioni)",
             destinazione, len(nodi), len(animazioni))
    return destinazione


def _mesh_entry(buffer: _Buffer, node, pivot: np.ndarray,
                materiali: list[dict], indice_materiale: dict[str, int]) -> dict:
    mesh = node.mesh
    vertici = np.asarray(mesh.vertices, dtype=float) - pivot
    posizione = buffer.add(vertici, "VEC3", FLOAT, ARRAY_BUFFER, minmax=True)
    indici = buffer.add(np.asarray(mesh.faces).reshape(-1), "SCALAR",
                        UNSIGNED_INT, ELEMENT_ARRAY_BUFFER)
    attributi = {"POSITION": posizione}
    try:
        normali = np.asarray(mesh.vertex_normals, dtype=float)
        if normali.shape == vertici.shape:
            attributi["NORMAL"] = buffer.add(normali, "VEC3", FLOAT, ARRAY_BUFFER)
    except Exception:               # una mesh degenere non ha normali: pazienza
        pass

    material = node.material
    chiave = "%s|%s" % (material.name, material.base_color)
    if chiave not in indice_materiale:
        indice_materiale[chiave] = len(materiali)
        materiali.append({
            "name": material.name or "materiale",
            "pbrMetallicRoughness": {
                "baseColorFactor": _colour(material.base_color),
                "metallicFactor": float(material.metallic),
                "roughnessFactor": float(material.roughness),
            },
        })
    return {"name": node.name,
            "primitives": [{"attributes": attributi, "indices": indici,
                            "material": indice_materiale[chiave],
                            "mode": TRIANGLES}]}


def _animation(buffer: _Buffer, clip: Clip, indice_di: dict[str, int]) -> dict:
    samplers: list[dict] = []
    channels: list[dict] = []
    for canale in clip.channels:
        if canale.joint not in indice_di:
            continue
        tempo = buffer.add(np.asarray(canale.times, dtype=float), "SCALAR",
                           FLOAT, minmax=True)
        valori = buffer.add(np.asarray(canale.rotations, dtype=float), "VEC4", FLOAT)
        samplers.append({"input": tempo, "output": valori, "interpolation": "LINEAR"})
        channels.append({"sampler": len(samplers) - 1,
                         "target": {"node": indice_di[canale.joint],
                                    "path": "rotation"}})
    return {"name": clip.name, "samplers": samplers, "channels": channels}


def _write_glb(documento: dict, binario: bytes, path: Path) -> None:
    """Contenitore GLB: intestazione, blocco JSON, blocco binario.

    Entrambi i blocchi vanno riempiti a multiplo di 4 — il JSON con spazi, il
    binario con zeri — o i lettori piu' severi rifiutano il file.
    """
    testo = json.dumps(documento, separators=(",", ":")).encode("utf-8")
    testo += b" " * ((4 - len(testo) % 4) % 4)
    dati = binario + b"\x00" * ((4 - len(binario) % 4) % 4)

    lunghezza = 12 + 8 + len(testo) + (8 + len(dati) if dati else 0)
    with open(path, "wb") as file:
        file.write(struct.pack("<III", 0x46546C67, 2, lunghezza))
        file.write(struct.pack("<II", len(testo), 0x4E4F534A))
        file.write(testo)
        if dati:
            file.write(struct.pack("<II", len(dati), 0x004E4942))
            file.write(dati)


def export_animated(scene, path: str | Path, clips: list[str] | None = None) -> Path:
    """Da una scena a un glTF animato, scegliendo le animazioni sensate."""
    from app.anim import clip as clip_module
    from app.anim import skeleton as skeleton_module

    skeleton = skeleton_module.from_scene(scene)
    if not skeleton.joints:
        raise GltfError("questa scena non ha un grafo di parti: "
                        "solo gli assemblaggi hanno uno scheletro")
    scelte = ([clip_module.make(nome, skeleton) for nome in clips]
              if clips else clip_module.default_clips(skeleton))
    return write(scene, skeleton, [c for c in scelte if c.channels], path)
