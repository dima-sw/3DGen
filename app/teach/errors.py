"""L'unico errore che il livello Teach solleva, con un codice stabile.

Stessa forma di `AuthoringError` e di `DataPluginError`: un codice che i test
possono asserire e un messaggio che un umano puo' leggere. E la stessa regola
sul confine — **i codici degli altri livelli non si traducono**. Quando una
risposta importata produce un JSON che il loader dei plugin dati rifiuta, chi
legge vede `DATA_SCHEMA_INVALID`, non un alias `TEACH_*` che nasconde dove sta
il confine; quando l'authoring rifiuta un nome, vede `AUTHORING_NAME_INVALID`.
"""
from __future__ import annotations

# Il progetto
NO_PROJECT = "TEACH_NO_PROJECT"
PROJECT_INVALID = "TEACH_PROJECT_INVALID"
FILE_MISSING = "TEACH_FILE_MISSING"

# La gerarchia importata
RESPONSE_INVALID = "TEACH_RESPONSE_INVALID"       # non e' JSON, o non e' un oggetto
SCHEMA_INVALID = "TEACH_SCHEMA_INVALID"           # JSON valido, forma sbagliata
HIERARCHY_TOO_DEEP = "TEACH_HIERARCHY_TOO_DEEP"
HIERARCHY_TOO_LARGE = "TEACH_HIERARCHY_TOO_LARGE"
DUPLICATE_NODE = "TEACH_DUPLICATE_NODE"
UNKNOWN_NODE = "TEACH_UNKNOWN_NODE"
NO_HIERARCHY = "TEACH_NO_HIERARCHY"

# Le decisioni
UNKNOWN_CANDIDATE = "TEACH_UNKNOWN_CANDIDATE"
UNKNOWN_COMPONENT = "TEACH_UNKNOWN_COMPONENT"
NO_SOLUTION = "TEACH_NO_SOLUTION"
COVERAGE_INVALID = "TEACH_COVERAGE_INVALID"

# Lo staging e la fiducia
ENVELOPE_INVALID = "TEACH_ENVELOPE_INVALID"
PATH_UNSAFE = "TEACH_PATH_UNSAFE"
FILE_TOO_LARGE = "TEACH_FILE_TOO_LARGE"
EXTENSION_REFUSED = "TEACH_EXTENSION_REFUSED"
TRUST_REQUIRED = "TEACH_TRUST_REQUIRED"
UNKNOWN_ARTIFACT = "TEACH_UNKNOWN_ARTIFACT"
ASSET_MISSING = "TEACH_ASSET_MISSING"

# Il provider
NO_PROVIDER = "TEACH_NO_PROVIDER"          # non configurato, o non disponibile
PROVIDER_FAILED = "TEACH_PROVIDER_FAILED"  # c'era, e non ha risposto

# Il completamento
NOT_LEARNED = "TEACH_NOT_LEARNED"


class TeachError(ValueError):
    """Un codice stabile piu' un messaggio. Il chiamante decide la gravita'."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def fail(code: str, message: str):
    raise TeachError(code, message)
