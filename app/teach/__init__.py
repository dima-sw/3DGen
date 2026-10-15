"""Teach 3DGen: insegnare un concetto alla libreria, non rigenerarlo ogni volta.

La differenza che questa milestone introduce sta in una frase. L'utente non
chiede «genera un drago»: insegna a 3DGen **che cosa serve per costruire
draghi**. Una volta imparato il concetto, una generazione normale usa la
libreria, e l'AI non serve piu'.

    "dragon"
      -> un modello decompone il concetto in parti           (ontologia)
      -> 3DGen normalizza e raffina la gerarchia
      -> la libreria installata viene confrontata con essa   (copertura)
      -> i gialli si validano, i blu si adattano, i rossi si generano
      -> ogni risultato si valida e si installa, dal basso verso l'alto
      -> tutti i mandatory verdi -> si costruisce il composite della radice
      -> concetto = LEARNED

## Che cosa c'e' dentro, e che cosa e' riuso

    TeachProject      il **processo**: gerarchia, copertura, decisioni,
                      ricette, prompt, risposte, tentativi, completamento.
                      Serializzabile in `.teach3d`, che non e' `.my3d`
    coverage.py       le evidenze che distinguono VALIDATED/CANDIDATE/PROXY/
                      MISSING. Nessun secondo motore di ricerca: i candidati
                      arrivano dal `SemanticIndex` di V1
    spec.py           la specifica tecnica di un componente mancante, decisa da
                      3DGen prima di chiedere niente a nessuno, piu' la coda
                      dependency-aware
    prompts.py        i prompt, identici nelle due modalita' (esterna e con un
                      provider configurato)
    contracts.py      le API di 3DGen, **generate** leggendo 3DGen
    staging.py        dove finisce cio' che un modello scrive, e la fiducia che
                      il Python generato non ha per predefinito
    knowledge.py      la memoria delle validazioni, fuori da `Component`
    TeachService      tutte le operazioni come chiamate. Nessun Qt, qui dentro

Tutto il resto e' riuso dichiarato: `ComponentLab` e `VariantRecipe` di V6,
`AuthoringService` per emettere il composite, `Session.reload_plugins` per
installare, e i validatori di V4/V5/V6 per giudicare.
"""
from __future__ import annotations

from app.teach.coverage import CoverageReport, analyse, summary, tree_text
from app.teach.errors import TeachError
from app.teach.knowledge import KnowledgeRecord, TeachKnowledge
from app.teach.model import (BACKENDS, CANDIDATE, COMPOSITE, COVERAGE, DATA_MESH,
                             LEARNED, LEARNING, MISSING, PROCEDURAL, PROXY,
                             SUITABILITY, VALIDATED, ArtifactRecord, Attempt,
                             Candidate, Evidence, Exchange, NodeState, Progress,
                             Solution, SuitabilityRecord, TeachNode,
                             TeachProject, build_tree)
from app.teach.service import (CompletionReport, PromptBundle, TeachReport,
                               TeachService)
from app.teach.spec import ComponentSpec, build_queue, build_spec, next_buildable
from app.teach.staging import (PythonInspection, StagedArtifact, StagedFile,
                               StagedValidation)

__all__ = [
    "ArtifactRecord", "Attempt", "BACKENDS", "CANDIDATE", "COMPOSITE",
    "COVERAGE", "Candidate", "CompletionReport", "ComponentSpec",
    "CoverageReport", "DATA_MESH", "Evidence", "Exchange", "KnowledgeRecord",
    "LEARNED", "LEARNING", "MISSING", "NodeState", "PROCEDURAL", "PROXY",
    "Progress", "PromptBundle", "PythonInspection", "SUITABILITY", "Solution",
    "StagedArtifact", "StagedFile", "StagedValidation", "SuitabilityRecord",
    "TeachError", "TeachKnowledge", "TeachNode", "TeachProject", "TeachReport",
    "TeachService", "VALIDATED", "analyse", "build_queue", "build_spec",
    "build_tree", "next_buildable", "summary", "tree_text",
]
