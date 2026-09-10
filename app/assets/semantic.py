"""Ricerca semantica sulla libreria.

La ricerca testuale trova quello che e' stato scritto; questa deve trovare
quello che si intendeva. "un pneumatico da fuoristrada" deve arrivare alla jeep
anche se nessuno ha mai scritto la parola "pneumatico" in quell'asset.

Due strade, stessa interfaccia:

  - **locale**: TF-IDF sul corpus della libreria piu' un piccolo dizionario di
    sinonimi italiano/inglese. Nessuna rete, nessuna chiave, nessuna dipendenza
    nuova: e' il percorso predefinito e quello dei test.
  - **remota**: embedding veri da un endpoint gia' in catena, quando c'e'. Danno
    risultati migliori sulle parafrasi, ma non possono essere un requisito.

L'indice sta su disco accanto agli asset e si ricostruisce da solo quando la
libreria cambia: e' una cache, non una fonte di verita'.
"""
from __future__ import annotations

import json
import re
import unicodedata
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np

from app.core.logging_setup import get

log = get("assets.semantic")

INDEX_FILE = ".semantic-index.json"

# Ponti fra parole che descrivono la stessa cosa. Non e' un modello del
# linguaggio: e' un dizionario, e come tale va tenuto piccolo e onesto.
THESAURUS: dict[str, tuple[str, ...]] = {
    "pneumatico": ("gomma", "ruota", "tire", "wheel", "copertone"),
    "gomma": ("pneumatico", "ruota", "tire", "rubber"),
    "ruota": ("pneumatico", "gomma", "wheel", "tire", "cerchio"),
    "fuoristrada": ("offroad", "jeep", "suv", "4x4", "campagnola"),
    "jeep": ("fuoristrada", "offroad", "suv", "campagnola"),
    "auto": ("macchina", "vettura", "car", "automobile", "veicolo"),
    "macchina": ("auto", "vettura", "car", "veicolo"),
    "camion": ("truck", "autocarro", "tir"),
    "casa": ("abitazione", "edificio", "house", "villa", "dimora"),
    "edificio": ("casa", "palazzo", "building", "costruzione"),
    "albero": ("pianta", "tree", "arbusto", "fusto"),
    "pino": ("conifera", "abete", "albero", "sempreverde"),
    "spada": ("lama", "sword", "arma", "brando"),
    "arma": ("spada", "ascia", "mazza", "weapon", "lancia"),
    "sedia": ("seduta", "chair", "sgabello", "poltrona"),
    "tavolo": ("table", "scrivania", "tavolino", "banco"),
    "pesce": ("fish", "pesciolino", "acquatico"),
    "creatura": ("animale", "bestia", "mostro", "essere", "creature"),
    "animale": ("creatura", "bestia", "fauna", "animal"),
    "robot": ("androide", "automa", "meccanico", "droide"),
    "umanoide": ("persona", "umano", "figura", "antropomorfo"),
    "corazza": ("armatura", "piastra", "armor", "protezione"),
    "verde": ("militare", "oliva", "green"),
    "grande": ("grosso", "enorme", "maggiorato", "big"),
    "piccolo": ("mini", "compatto", "small", "ridotto"),
}

_SPLIT = re.compile(r"[^a-z0-9]+")
_STOP = {
    "un", "uno", "una", "il", "lo", "la", "i", "gli", "le", "di", "da", "con",
    "per", "del", "della", "dei", "delle", "che", "come", "crea", "creare",
    "fai", "genera", "modello", "oggetto", "the", "of", "with", "for", "and",
    "create", "make", "generate", "model", "object", "una", "and",
}


def tokenize(text: str) -> list[str]:
    norm = unicodedata.normalize("NFKD", (text or "").lower())
    norm = "".join(c for c in norm if not unicodedata.combining(c))
    return [w for w in _SPLIT.split(norm) if len(w) > 2 and w not in _STOP]


def expand(tokens: Sequence[str], weight: float = 0.55) -> dict[str, float]:
    """Aggiunge i sinonimi con peso ridotto: aiutano senza dominare."""
    bag: dict[str, float] = {}
    for token in tokens:
        bag[token] = bag.get(token, 0.0) + 1.0
        for synonym in THESAURUS.get(token, ()):
            bag[synonym] = bag.get(synonym, 0.0) + weight
    return bag


# --------------------------------------------------------------------------- #
# Interfaccia
# --------------------------------------------------------------------------- #
class Embedder(ABC):
    """Trasforma testo in vettori confrontabili."""

    name = "abstract"

    @abstractmethod
    def fit(self, documents: Sequence[str]) -> None:
        """Prepara l'embedder sul corpus (per TF-IDF serve, per gli altri no)."""

    @abstractmethod
    def embed(self, texts: Sequence[str]) -> np.ndarray:
        """Matrice (n, dim) gia' normalizzata."""

    @property
    @abstractmethod
    def signature(self) -> str:
        """Identifica il modello: se cambia, l'indice va ricostruito."""

    def state(self) -> dict:
        """Cio' che serve per interrogare l'indice senza rifare il fit."""
        return {}

    def restore(self, state: dict) -> bool:
        """Ripristina lo stato salvato. False se non e' utilizzabile."""
        return True


def _normalise(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.maximum(norms, 1e-9)


class TfidfEmbedder(Embedder):
    """TF-IDF con espansione dei sinonimi. Locale, deterministico, senza rete."""

    name = "tfidf"

    def __init__(self, synonym_weight: float = 0.55) -> None:
        self.vocabulary: dict[str, int] = {}
        self.idf: np.ndarray = np.zeros(0)
        self.synonym_weight = synonym_weight

    def fit(self, documents: Sequence[str]) -> None:
        bags = [expand(tokenize(d), self.synonym_weight) for d in documents]
        vocabulary: dict[str, int] = {}
        for bag in bags:
            for term in bag:
                vocabulary.setdefault(term, len(vocabulary))
        self.vocabulary = vocabulary

        n = max(len(documents), 1)
        counts = np.zeros(len(vocabulary))
        for bag in bags:
            for term in bag:
                counts[vocabulary[term]] += 1.0
        # smoothing: un termine presente ovunque non deve valere zero
        self.idf = np.log((1.0 + n) / (1.0 + counts)) + 1.0

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        if not self.vocabulary:
            return np.zeros((len(texts), 1))
        matrix = np.zeros((len(texts), len(self.vocabulary)))
        for row, text in enumerate(texts):
            for term, weight in expand(tokenize(text), self.synonym_weight).items():
                index = self.vocabulary.get(term)
                if index is not None:
                    matrix[row, index] = weight * self.idf[index]
        return _normalise(matrix)

    @property
    def signature(self) -> str:
        return "tfidf-%d" % len(self.vocabulary)

    def state(self) -> dict:
        # senza vocabolario e idf i vettori salvati sarebbero inservibili:
        # non si potrebbe proiettare una nuova interrogazione nello stesso spazio
        return {"vocabulary": self.vocabulary, "idf": self.idf.tolist(),
                "synonym_weight": self.synonym_weight}

    def restore(self, state: dict) -> bool:
        try:
            self.vocabulary = {str(k): int(v) for k, v in state["vocabulary"].items()}
            self.idf = np.asarray(state["idf"], dtype=float)
            self.synonym_weight = float(state.get("synonym_weight", 0.55))
        except Exception:
            return False
        return len(self.idf) == len(self.vocabulary)


class RemoteEmbedder(Embedder):
    """Embedding da un endpoint compatibile OpenAI, quando ce n'e' uno.

    Non e' un requisito: se la chiamata fallisce l'indice ricade sul TF-IDF.
    """

    name = "remote"

    def __init__(self, endpoint: str, api_key: str, model: str, timeout: int = 30) -> None:
        self.endpoint = endpoint
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def fit(self, documents: Sequence[str]) -> None:
        return None                      # niente da apprendere

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        import requests

        response = requests.post(
            self.endpoint,
            headers={"Authorization": "Bearer %s" % self.api_key,
                     "Content-Type": "application/json"},
            json={"model": self.model, "input": list(texts)},
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise RuntimeError("embedding rifiutati (%d): %s"
                               % (response.status_code, response.text[:160]))
        payload = response.json()
        vectors = [item["embedding"] for item in payload["data"]]
        return _normalise(np.asarray(vectors, dtype=float))

    @property
    def signature(self) -> str:
        return "remote-%s" % self.model


# --------------------------------------------------------------------------- #
# Indice
# --------------------------------------------------------------------------- #
@dataclass
class SemanticIndex:
    """Vettori degli asset, con persistenza e ricostruzione automatica."""

    embedder: Embedder = field(default_factory=TfidfEmbedder)
    ids: list[str] = field(default_factory=list)
    vectors: np.ndarray = field(default_factory=lambda: np.zeros((0, 1)))
    fingerprint: str = ""

    # ------------------------------------------------------------ costruzione #
    @staticmethod
    def document_for(record) -> str:
        """Il testo che descrive un asset. Il nome pesa doppio: e' la scelta
        dell'utente, non una classificazione automatica."""
        return " ".join([record.name, record.name, record.prompt,
                         record.root_ref.replace(":", " "), record.category,
                         " ".join(record.tags)])

    @staticmethod
    def fingerprint_of(records: Sequence) -> str:
        return "|".join(sorted("%s:%s" % (r.id, r.created) for r in records))

    def build(self, records: Sequence) -> "SemanticIndex":
        documents = [self.document_for(r) for r in records]
        self.embedder.fit(documents)
        self.ids = [r.id for r in records]
        self.vectors = (self.embedder.embed(documents) if documents
                        else np.zeros((0, 1)))
        self.fingerprint = self.fingerprint_of(records)
        log.info("indice semantico: %d asset, %s", len(self.ids), self.embedder.signature)
        return self

    def is_current(self, records: Sequence) -> bool:
        return bool(self.ids) and self.fingerprint == self.fingerprint_of(records)

    # ---------------------------------------------------------------- ricerca #
    def search(self, query: str, limit: int = 10,
               threshold: float = 0.05) -> list[tuple[str, float]]:
        if not self.ids or not query.strip():
            return []
        vector = self.embedder.embed([query])[0]
        scores = self.vectors @ vector
        order = np.argsort(-scores)
        out: list[tuple[str, float]] = []
        for index in order[:limit]:
            score = float(scores[index])
            if score < threshold:
                break
            out.append((self.ids[index], score))
        return out

    # ------------------------------------------------------------ persistenza #
    def save(self, path: Path) -> None:
        try:
            Path(path).write_text(json.dumps({
                "embedder": self.embedder.name,
                "signature": self.embedder.signature,
                "fingerprint": self.fingerprint,
                "ids": self.ids,
                "vectors": np.round(self.vectors, 5).tolist(),
                "state": self.embedder.state(),
            }), encoding="utf-8")
        except Exception as exc:      # l'indice e' una cache: non deve bloccare
            log.warning("indice non salvato: %s", exc)

    @classmethod
    def load(cls, path: Path, embedder: Embedder | None = None) -> "SemanticIndex | None":
        source = Path(path)
        if not source.is_file():
            return None
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
            engine = embedder or TfidfEmbedder()
            if engine.name != data.get("embedder"):
                return None            # indice di un altro motore: da rifare
            if not engine.restore(data.get("state") or {}):
                return None
            index = cls(embedder=engine)
            index.ids = list(data["ids"])
            index.vectors = np.asarray(data["vectors"], dtype=float)
            index.fingerprint = data.get("fingerprint", "")
            return index if len(index.ids) == len(index.vectors) else None
        except Exception as exc:
            log.warning("indice illeggibile, lo ricostruisco: %s", exc)
            return None
