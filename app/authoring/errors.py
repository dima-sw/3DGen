"""L'unico errore che l'authoring solleva, con un codice stabile.

Stessa forma di `DataPluginError`: un codice che i test possono asserire e un
messaggio che un umano puo' leggere. I codici del **formato dati** restano
quelli di `app/core/data_plugin.py` e non vengono tradotti: quando il
salvataggio produce un JSON che il loader rifiuta, chi legge deve vedere il
codice del loader, non un alias di authoring che nasconde dove sta il confine.
"""
from __future__ import annotations

# Il modello importato
MODEL_FORMAT = "AUTHORING_MODEL_FORMAT"          # non GLB/glTF
MODEL_INVALID = "AUTHORING_MODEL_INVALID"        # GLB illeggibile
MODEL_EMPTY = "AUTHORING_MODEL_EMPTY"            # nessun triangolo
FILE_MISSING = "AUTHORING_FILE_MISSING"

# Il progetto
NO_PROJECT = "AUTHORING_NO_PROJECT"
UNKNOWN_COMPONENT = "AUTHORING_UNKNOWN_COMPONENT"
UNKNOWN_OBJECT = "AUTHORING_UNKNOWN_OBJECT"
UNKNOWN_SOCKET = "AUTHORING_UNKNOWN_SOCKET"
UNKNOWN_PARAM = "AUTHORING_UNKNOWN_PARAM"
UNKNOWN_CHILD = "AUTHORING_UNKNOWN_CHILD"
DUPLICATE = "AUTHORING_DUPLICATE"
CYCLE = "AUTHORING_CYCLE"
NAME_INVALID = "AUTHORING_NAME_INVALID"
PATH_UNSAFE = "AUTHORING_PATH_UNSAFE"
PROJECT_INVALID = "AUTHORING_PROJECT_INVALID"
PARAM_STRATEGY = "AUTHORING_PARAM_STRATEGY"


class AuthoringError(ValueError):
    """Un codice stabile piu' un messaggio. Il chiamante decide la gravita'."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def fail(code: str, message: str):
    raise AuthoringError(code, message)
