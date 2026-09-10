"""Libreria di asset riutilizzabili.

Ogni asset e' una cartella autosufficiente:

    library/<id>/
        asset.json     metadati + il piano di composizione che lo ha prodotto
        model.glb      la mesh gia' cotta, per Blender, Unity, Unreal, web
        preview.png    anteprima per la griglia della UI

Conservare il *piano* oltre alla mesh e' la scelta che conta: ricaricando un
asset non si ottiene un blocco morto ma un modello ancora componibile, a cui si
puo' cambiare un pezzo, alzare il dettaglio o aggiungere un accessorio.

Il piano e' un `CompositionGraph` in JSON, la stessa forma che il planner
produce e che un progetto salva: una sola grammatica per l'intero sistema.

Il filesystem e' la fonte di verita': l'indice e' solo una cache che si
ricostruisce da solo. Cancellare una cartella a mano non rompe niente.
"""
from __future__ import annotations

import json
import re
import shutil
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import SETTINGS
from app.core.logging_setup import get
from app.core.scene import Scene

log = get("assets.library")

ASSET_FILE = "asset.json"
MODEL_FILE = "model.glb"
PREVIEW_FILE = "preview.png"

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_STOPWORDS = {
    "un", "uno", "una", "il", "lo", "la", "i", "gli", "le", "di", "da", "con",
    "per", "del", "della", "dei", "delle", "crea", "creare", "fai", "genera",
    "modello", "oggetto", "a", "e", "in", "su", "al", "the", "an", "of", "with",
    "create", "make", "generate", "model", "object",
}


def slugify(text: str, fallback: str = "asset") -> str:
    norm = unicodedata.normalize("NFKD", text.lower())
    norm = "".join(c for c in norm if not unicodedata.combining(c))
    slug = _SLUG_RE.sub("-", norm).strip("-")
    return (slug[:40] or fallback).strip("-")


def _words(text: str) -> list[str]:
    norm = unicodedata.normalize("NFKD", text.lower())
    norm = "".join(c for c in norm if not unicodedata.combining(c))
    return [w for w in _SLUG_RE.sub(" ", norm).split() if len(w) > 2 and w not in _STOPWORDS]


class AssetRecord(BaseModel):
    """Metadati di un asset salvato."""

    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    # Da che vocabolario viene la radice: `humanoid`, `architecture`, `nature`.
    # Non e' una tassonomia del mondo, e' il plugin che ha fornito il pezzo
    # principale — l'unica classificazione che il sistema conosce davvero.
    category: str = "altro"
    root_ref: str = ""              # il componente della radice, per esteso
    detail_level: int = 2
    style: str = "low_poly"
    tags: list[str] = Field(default_factory=list)
    prompt: str = ""
    seed: int = 0
    triangles: int = 0
    parts: int = 0
    dimensions: tuple[float, float, float] = (0.0, 0.0, 0.0)
    created: str = ""
    # Il piano, in JSON: `CompositionGraph.to_dict()`. Un dizionario e non un
    # oggetto tipizzato, perche' un asset deve poter essere riletto anche se il
    # piano contiene qualcosa che questa versione non conosce.
    plan: dict = Field(default_factory=dict)
    options: dict = Field(default_factory=dict)
    plugins: dict = Field(default_factory=dict)

    def summary(self) -> str:
        return "%d parti | %d triangoli | %.2f x %.2f x %.2f m" % (
            (self.parts, self.triangles) + self.dimensions)

    def strong_terms(self) -> list[str]:
        """Parole scelte dall'utente: pesano di piu' nella ricerca."""
        return _words(self.name + " " + self.prompt)

    def weak_terms(self) -> list[str]:
        """Sinonimi e classificazione: fanno trovare l'asset, ma senza dominare."""
        return _words(" ".join(self.tags) + " " + self.root_ref + " "
                      + self.category)

    def payload(self) -> dict:
        """Quello che serve a rimettere l'asset in una sessione."""
        return {"graph": dict(self.plan), "options": dict(self.options),
                "prompt": self.prompt, "label": self.name}


def auto_tags(plan=None, scene: Scene | None = None, prompt: str = "") -> list[str]:
    """Etichette derivate dal piano: rendono l'asset ritrovabile senza sforzo.

    Vengono da tre posti, e nessuno dei tre e' un elenco di categorie del
    mondo: i **riferimenti** usati nel piano (`humanoid:body` da' `humanoid` e
    `body`), le **etichette dei pezzi** costruiti, e le parole della richiesta.
    Un plugin nuovo porta con se' i propri tag senza che nessuno venga qui a
    scriverli.
    """
    tags: set[str] = set()
    for ref in _refs(plan):
        plugin, _, nome = ref.partition(":")
        tags.update({plugin, nome})
    if scene is not None:
        tags.update(t for node in scene.nodes for t in node.tags if len(t) > 3)
    tags.update(_words(prompt))
    return sorted(t for t in tags if t and len(t) > 2)


def _refs(plan) -> list[str]:
    """Tutti i riferimenti a componente di un piano, grafo o JSON che sia."""
    fuori: list[str] = []
    if plan is None:
        return fuori
    if hasattr(plan, "providers"):
        return sorted(set(plan.providers().values()))

    def scendi(nodo) -> None:
        if not isinstance(nodo, dict):
            return
        for chiave in ("ref", "swap"):
            if nodo.get(chiave):
                fuori.append(str(nodo[chiave]))
        for figlio in nodo.get("children") or ():
            scendi(figlio)

    scendi(plan.get("root") if isinstance(plan, dict) else None)
    return sorted(set(fuori))


def _radice(plan) -> str:
    """Il riferimento del componente radice di un piano. Vuoto se non c'e'."""
    if plan is None:
        return ""
    if hasattr(plan, "root_id"):
        return plan.resolved_ref(plan.root_id) if plan.root_id else ""
    radice = (plan or {}).get("root") if isinstance(plan, dict) else None
    if not isinstance(radice, dict):
        return ""
    return str(radice.get("swap") or radice.get("ref") or "")


class AssetLibrary:
    """Accesso alla cartella della libreria. Nessuno stato oltre alla cache."""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root) if root is not None else SETTINGS.library_dir
        self.root.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, tuple[float, AssetRecord]] = {}

    # ------------------------------------------------------------ percorsi #
    def path(self, asset_id: str) -> Path:
        return self.root / asset_id

    def model_path(self, asset_id: str) -> Path:
        return self.path(asset_id) / MODEL_FILE

    def preview_path(self, asset_id: str) -> Path:
        return self.path(asset_id) / PREVIEW_FILE

    def _new_id(self, name: str, categoria: str) -> str:
        base = "%s-%s" % (slugify(categoria, "asset"), slugify(name, "senza-nome"))
        # l'id contiene sempre un suffisso casuale, quindi non puo' coincidere
        # con un nome di dispositivo di Windows: resta valido come cartella
        return "%s-%s" % (base[:52], uuid.uuid4().hex[:6])

    # -------------------------------------------------------------- scrivi #
    def save(self, scene: Scene, name: str = "", tags: Iterable[str] = (),
             preview: Path | str | bytes | None = None, plan=None,
             prompt: str = "", options: dict | None = None,
             plugins: dict | None = None) -> AssetRecord:
        """Salva scena, piano e anteprima. Restituisce il record creato."""
        piano = plan if plan is not None else scene.plan
        radice = _radice(piano)
        label = (name or prompt or radice.partition(":")[2] or "modello").strip()[:60]
        categoria = radice.partition(":")[0] or "altro"
        asset_id = self._new_id(label, categoria)
        folder = self.path(asset_id)
        folder.mkdir(parents=True, exist_ok=True)

        record = AssetRecord(
            id=asset_id,
            name=label,
            category=categoria,
            root_ref=radice,
            detail_level=int(getattr(piano, "detail_level", 2) or 2),
            style=str(getattr(piano, "style", "low_poly") or "low_poly"),
            tags=sorted(set(auto_tags(piano, scene, prompt))
                        | {t.strip() for t in tags if t.strip()}),
            prompt=prompt,
            seed=int(getattr(piano, "seed", 0) or 0),
            triangles=scene.triangle_count,
            parts=len(scene.nodes),
            dimensions=scene.dimensions(),
            created=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            plan=piano.to_dict() if hasattr(piano, "to_dict") else dict(piano or {}),
            options=dict(options or {}),
            plugins=dict(plugins or {}),
        )

        try:
            from app.build.exporter import write_scene

            # texture piu' piccole: la libreria conserva molti asset
            write_scene(scene.to_trimesh_scene(texture_size=128),
                        folder / MODEL_FILE, "glb")
        except Exception as exc:  # la mesh cotta e' comoda, ma il piano basta
            log.warning("GLB non salvato per %s: %s", asset_id, exc)

        self._write_preview(folder / PREVIEW_FILE, preview, scene)
        (folder / ASSET_FILE).write_text(
            json.dumps(record.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")

        log.info("asset salvato: %s (%s)", asset_id, record.summary())
        self._cache.pop(asset_id, None)
        return record

    def _write_preview(self, target: Path, preview: Any, scene: Scene) -> None:
        try:
            if isinstance(preview, bytes):
                target.write_bytes(preview)
                return
            if preview is not None:
                src = Path(preview)
                if src.exists():
                    shutil.copyfile(src, target)
                    return
            from app.ui.offscreen import render      # solo se serve davvero

            render(scene, target, size=(480, 320))
        except Exception as exc:  # un asset senza anteprima resta valido
            log.warning("anteprima non generata: %s", exc)

    # ---------------------------------------------------------------- leggi #
    def _read(self, folder: Path) -> AssetRecord | None:
        meta = folder / ASSET_FILE
        if not meta.is_file():
            return None
        stamp = meta.stat().st_mtime
        cached = self._cache.get(folder.name)
        if cached and cached[0] == stamp:
            return cached[1]
        try:
            record = AssetRecord.model_validate_json(meta.read_text(encoding="utf-8"))
        except Exception as exc:
            log.warning("asset illeggibile in %s: %s", folder.name, exc)
            return None
        self._cache[folder.name] = (stamp, record)
        return record

    def all(self) -> list[AssetRecord]:
        records = [r for r in (self._read(d) for d in self.root.iterdir() if d.is_dir()) if r]
        records.sort(key=lambda r: r.created, reverse=True)
        return records

    def get(self, asset_id: str) -> AssetRecord | None:
        return self._read(self.path(asset_id))

    def search(self, query: str = "", category: str = "", limit: int | None = None) -> list[AssetRecord]:
        """Ricerca testuale sui tag e sui metadati. Punteggio semplice e prevedibile."""
        records = self.all()
        if category:
            records = [r for r in records if r.category == category]

        terms = _words(query)
        if not terms:
            return records[:limit] if limit else records

        scored: list[tuple[int, AssetRecord]] = []
        for record in records:
            strong, weak = record.strong_terms(), record.weak_terms()
            score = 0
            for term in terms:
                if term in strong:
                    score += 4
                elif term in weak:
                    score += 2
                elif any(h.startswith(term) for h in strong + weak):
                    score += 1
            if score:
                scored.append((score, record))
        # `records` arriva gia' dal piu' recente: l'ordinamento stabile per
        # punteggio conserva quell'ordine a parita' di rilevanza.
        scored.sort(key=lambda pair: -pair[0])
        result = [r for _, r in scored]
        return result[:limit] if limit else result

    # ------------------------------------------------------- ricerca semantica #
    def semantic_index(self, embedder=None, rebuild: bool = False):
        """Indice semantico, ricostruito solo quando la libreria e' cambiata."""
        from app.assets.semantic import INDEX_FILE, SemanticIndex

        records = self.all()
        path = self.root / INDEX_FILE
        if not rebuild:
            cached = SemanticIndex.load(path, embedder)
            if cached is not None and cached.is_current(records):
                return cached
        index = SemanticIndex(embedder=embedder) if embedder else SemanticIndex()
        index.build(records)
        index.save(path)
        return index

    def semantic_search(self, query: str, limit: int = 10, embedder=None,
                        threshold: float = 0.05) -> list[AssetRecord]:
        """Trova per significato, non per parole esatte.

        Se qualcosa va storto si ricade sulla ricerca testuale: un indice e' una
        comodita', non una condizione per poter cercare.
        """
        if not query.strip():
            return self.all()[:limit]
        try:
            index = self.semantic_index(embedder)
            hits = index.search(query, limit=limit, threshold=threshold)
        except Exception as exc:
            log.warning("ricerca semantica non disponibile (%s): uso il testo", exc)
            return self.search(query, limit=limit)

        by_id = {r.id: r for r in self.all()}
        found = [by_id[i] for i, _ in hits if i in by_id]
        if found:
            return found
        return self.search(query, limit=limit)

    def categories(self) -> list[str]:
        return sorted({r.category for r in self.all()})

    # -------------------------------------------------------------- carica #
    def load_plan(self, asset_id: str) -> dict:
        """Il piano di un asset, pronto per `Session.restore`.

        Torna un dizionario e non un grafo: chi lo rimette in una sessione lo
        fa passare dalla stessa validazione di qualunque piano che arriva da
        fuori, perche' un file sul disco e' esattamente questo — qualcosa che
        arriva da fuori.
        """
        record = self.get(asset_id)
        if record is None:
            raise KeyError("asset inesistente: %s" % asset_id)
        if not record.plan:
            raise ValueError("l'asset %s non ha un piano: e' solo una mesh"
                             % asset_id)
        return record.payload()

    def load_mesh(self, asset_id: str):
        import trimesh

        path = self.model_path(asset_id)
        if not path.is_file():
            raise FileNotFoundError("nessun GLB per %s" % asset_id)
        return trimesh.load(path)

    # ------------------------------------------------------------ cancella #
    def delete(self, asset_id: str) -> bool:
        folder = self.path(asset_id)
        if not folder.is_dir():
            return False
        shutil.rmtree(folder)
        self._cache.pop(asset_id, None)
        log.info("asset eliminato: %s", asset_id)
        return True

    def rename(self, asset_id: str, name: str) -> AssetRecord | None:
        record = self.get(asset_id)
        if record is None:
            return None
        record.name = name.strip()[:60] or record.name
        (self.path(asset_id) / ASSET_FILE).write_text(
            json.dumps(record.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")
        self._cache.pop(asset_id, None)
        return record
