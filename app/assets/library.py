"""Libreria di asset riutilizzabili.

Ogni asset e' una cartella autosufficiente:

    library/<id>/
        asset.json     metadati + il GenerationPlan che lo ha prodotto
        model.glb      la mesh gia' cotta, per Blender, Unity, Unreal, web
        preview.png    anteprima per la griglia della UI

Conservare il *piano* oltre alla mesh e' la scelta che conta: ricaricando un
asset non si ottiene un blocco morto ma un modello ancora parametrico, che si
puo' modificare a voce e da cui si possono generare altre varianti.

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
from app.core.spec import GenerationPlan

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
    category: str = "altro"
    template: str = ""
    density: float = 1.0
    tags: list[str] = Field(default_factory=list)
    prompt: str = ""
    seed: int = 0
    triangles: int = 0
    parts: int = 0
    dimensions: tuple[float, float, float] = (0.0, 0.0, 0.0)
    created: str = ""
    plan: GenerationPlan | None = None

    def summary(self) -> str:
        return "%d parti | %d triangoli | %.2f x %.2f x %.2f m" % (
            (self.parts, self.triangles) + self.dimensions)

    def strong_terms(self) -> list[str]:
        """Parole scelte dall'utente: pesano di piu' nella ricerca."""
        return _words(self.name + " " + self.prompt)

    def weak_terms(self) -> list[str]:
        """Sinonimi e classificazione: fanno trovare l'asset, ma senza dominare."""
        return _words(" ".join(self.tags) + " " + self.template + " "
                      + self.category)


def auto_tags(plan: GenerationPlan, scene: Scene | None = None) -> list[str]:
    """Etichette derivate dal piano: rendono l'asset ritrovabile senza sforzo."""
    from app.geometry.templates import TEMPLATES, load_all

    load_all()
    tags: set[str] = {plan.template}
    tmpl = TEMPLATES.get(plan.template)
    if tmpl is not None:
        tags.add(tmpl.category)
        # I sinonimi che il template usa per farsi riconoscere dal planner
        # servono anche qui: senza, "albero" non troverebbe un asset salvato
        # come "pino". E' ricerca testuale, non semantica: quella e' la voce 2.
        tags.update(tmpl.keywords)

    for key, value in plan.params.items():
        if isinstance(value, bool):
            if value and key.startswith("has_"):
                tags.add(key[4:])
        elif isinstance(value, str):
            tags.add(value)

    tags.update(_words(plan.prompt))
    if scene is not None:
        tags.update(t for node in scene.nodes for t in node.tags if len(t) > 3)
    return sorted(t for t in tags if t)


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

    def _new_id(self, name: str, template: str) -> str:
        base = "%s-%s" % (slugify(template, "asset"), slugify(name, "senza-nome"))
        # l'id contiene sempre un suffisso casuale, quindi non puo' coincidere
        # con un nome di dispositivo di Windows: resta valido come cartella
        return "%s-%s" % (base[:52], uuid.uuid4().hex[:6])

    # -------------------------------------------------------------- scrivi #
    def save(self, scene: Scene, name: str = "", tags: Iterable[str] = (),
             preview: Path | str | bytes | None = None) -> AssetRecord:
        """Salva scena, piano e anteprima. Restituisce il record creato."""
        plan = scene.plan
        label = (name or plan.object_type or plan.template).strip()[:60]
        asset_id = self._new_id(label, plan.template)
        folder = self.path(asset_id)
        folder.mkdir(parents=True, exist_ok=True)

        from app.geometry.templates import TEMPLATES, load_all

        load_all()
        tmpl = TEMPLATES.get(plan.template)
        record = AssetRecord(
            id=asset_id,
            name=label,
            category=tmpl.category if tmpl else "altro",
            template=plan.template,
            density=plan.density,
            tags=sorted(set(auto_tags(plan, scene)) | {t.strip() for t in tags if t.strip()}),
            prompt=plan.prompt,
            seed=plan.seed,
            triangles=scene.triangle_count,
            parts=len(scene.nodes),
            dimensions=scene.dimensions(),
            created=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            plan=plan,
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
    def load_plan(self, asset_id: str) -> GenerationPlan:
        record = self.get(asset_id)
        if record is None:
            raise KeyError("asset inesistente: %s" % asset_id)
        if record.plan is None:
            raise ValueError("l'asset %s non ha un piano: e' solo una mesh" % asset_id)
        return record.plan.model_copy(deep=True)

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
