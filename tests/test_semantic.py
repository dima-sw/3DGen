"""Ricerca semantica: trovare cio' che si intendeva, non cio' che si e' scritto."""
from __future__ import annotations

import json

import numpy as np
import pytest

from app.ai.provider import OfflineProvider
from app.assets.library import AssetLibrary
from app.assets.semantic import (
    INDEX_FILE, Embedder, RemoteEmbedder, SemanticIndex, TfidfEmbedder,
    expand, tokenize,
)
from app.core.session import Session

OFFLINE = OfflineProvider()

CORPUS = [
    ("una jeep militare verde con ruote grandi", "Fuoristrada militare"),
    ("una casa a due piani con portico", "Villetta"),
    ("un pino alto 9 metri", "Conifera"),
    ("una spada medievale a due mani", "Lama antica"),
    ("una sedia da ufficio", "Poltroncina"),
    ("un tavolo rotondo di legno", "Tavolo tondo"),
]


@pytest.fixture()
def library(tmp_path):
    lib = AssetLibrary(tmp_path / "lib")
    session = Session(provider=OFFLINE, library=lib)
    for prompt, name in CORPUS:
        session.generate_legacy(prompt)
        session.save_to_library(name)
    return lib


# --------------------------------------------------------------------------- #
# Tokenizzazione e sinonimi
# --------------------------------------------------------------------------- #
def test_tokenizer_drops_noise_words():
    tokens = tokenize("Crea una Jeep militare con le ruote grandi")
    assert "jeep" in tokens and "militare" in tokens and "ruote" in tokens
    assert "una" not in tokens and "crea" not in tokens


def test_tokenizer_ignores_accents_and_case():
    assert tokenize("Città") == tokenize("citta") == ["citta"]


def test_synonyms_are_added_with_less_weight():
    bag = expand(["pneumatico"])
    assert bag["pneumatico"] == 1.0
    assert 0.0 < bag["gomma"] < 1.0, "un sinonimo non deve pesare come la parola detta"


# --------------------------------------------------------------------------- #
# TF-IDF
# --------------------------------------------------------------------------- #
def test_embeddings_are_normalised():
    embedder = TfidfEmbedder()
    embedder.fit(["una jeep verde", "una casa grande", "un pino alto"])
    vectors = embedder.embed(["una jeep", "una casa"])
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-9)


def test_rare_words_weigh_more_than_common_ones():
    embedder = TfidfEmbedder()
    embedder.fit(["jeep verde", "jeep rossa", "jeep nera", "spada antica"])
    idf = embedder.idf
    assert idf[embedder.vocabulary["spada"]] > idf[embedder.vocabulary["jeep"]]


def test_empty_corpus_does_not_crash():
    embedder = TfidfEmbedder()
    embedder.fit([])
    assert embedder.embed(["qualcosa"]).shape[0] == 1


# --------------------------------------------------------------------------- #
# Il criterio di accettazione
# --------------------------------------------------------------------------- #
def test_finds_by_meaning_not_by_words(library):
    """Il criterio del TODO: 'un pneumatico da fuoristrada' trova la jeep."""
    hits = library.semantic_search("un pneumatico da fuoristrada", limit=2)
    assert hits and hits[0].name == "Fuoristrada militare"


@pytest.mark.parametrize("query,expected", [
    ("una vettura", "Fuoristrada militare"),
    ("un arbusto sempreverde", "Conifera"),
    ("un'arma da taglio", "Lama antica"),
    ("abitazione", "Villetta"),
    ("una seduta", "Poltroncina"),
])
def test_paraphrases_reach_the_right_asset(library, query, expected):
    hits = library.semantic_search(query, limit=2)
    assert hits and expected in [h.name for h in hits], \
        "%r -> %s" % (query, [h.name for h in hits])


def test_unrelated_query_returns_nothing(library):
    assert library.semantic_search("sottomarino nucleare a propulsione", limit=3) == []


# --------------------------------------------------------------------------- #
# Indice: cache che si ricostruisce da sola
# --------------------------------------------------------------------------- #
def test_index_is_written_to_disk(library):
    library.semantic_index()
    assert (library.root / INDEX_FILE).is_file()


def test_index_is_reused_when_nothing_changed(library):
    first = library.semantic_index()
    second = library.semantic_index()
    assert second.fingerprint == first.fingerprint
    assert second.ids == first.ids


def test_index_rebuilds_when_an_asset_is_added(library):
    before = library.semantic_index().fingerprint
    session = Session(provider=OFFLINE, library=library)
    session.generate_legacy("un camion da cantiere")
    session.save_to_library("Camion")
    assert library.semantic_index().fingerprint != before
    assert any(h.name == "Camion" for h in library.semantic_search("autocarro", limit=3))


def test_saved_index_can_answer_without_refitting(library):
    """Senza vocabolario e idf salvati i vettori sarebbero inservibili."""
    library.semantic_index()
    reloaded = SemanticIndex.load(library.root / INDEX_FILE)
    assert reloaded is not None
    hits = reloaded.search("un pneumatico da fuoristrada", limit=1)
    assert hits and hits[0][1] > 0.05


def test_corrupted_index_is_rebuilt(library):
    library.semantic_index()
    (library.root / INDEX_FILE).write_text("{ rotto", encoding="utf-8")
    assert SemanticIndex.load(library.root / INDEX_FILE) is None
    hits = library.semantic_search("un pneumatico da fuoristrada")
    assert hits, "la ricerca deve funzionare lo stesso"


def test_index_of_another_engine_is_discarded(library):
    library.semantic_index()
    path = library.root / INDEX_FILE
    data = json.loads(path.read_text(encoding="utf-8"))
    data["embedder"] = "remote"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert SemanticIndex.load(path) is None


# --------------------------------------------------------------------------- #
# Embedder remoto: interfaccia pronta, nessun servizio richiesto
# --------------------------------------------------------------------------- #
class FakeRemote(Embedder):
    """Sostituisce un servizio esterno nei test: stesso contratto."""

    name = "remote"

    def __init__(self, mapping: dict[str, list[float]]) -> None:
        self.mapping = mapping
        self.calls = 0

    def fit(self, documents):
        return None

    def embed(self, texts):
        self.calls += 1
        vectors = []
        for text in texts:
            vector = np.zeros(3)
            for key, value in self.mapping.items():
                if key in text.lower():
                    vector += np.asarray(value, dtype=float)
            vectors.append(vector if vector.any() else np.array([1e-6, 0, 0]))
        matrix = np.asarray(vectors)
        return matrix / np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-9)

    @property
    def signature(self):
        return "fake"


def test_index_works_with_any_embedder(library):
    fake = FakeRemote({"jeep": [1, 0, 0], "casa": [0, 1, 0], "pino": [0, 0, 1],
                       "fuoristrada": [1, 0, 0], "villetta": [0, 1, 0],
                       "conifera": [0, 0, 1]})
    index = library.semantic_index(embedder=fake, rebuild=True)
    hits = index.search("jeep", limit=1)
    assert hits and fake.calls >= 2


def test_remote_embedder_reports_a_failure():
    embedder = RemoteEmbedder("http://127.0.0.1:9/embeddings", "chiave", "modello", timeout=1)
    with pytest.raises(Exception):
        embedder.embed(["prova"])


def test_search_falls_back_to_text_when_the_index_fails(library, monkeypatch):
    """Regola 9 applicata alla ricerca: un indice rotto non impedisce di cercare."""
    def boom(*args, **kwargs):
        raise RuntimeError("indice non disponibile")

    monkeypatch.setattr(AssetLibrary, "semantic_index", boom)
    hits = library.semantic_search("jeep", limit=3)
    assert hits and any("Fuoristrada" in h.name for h in hits)
