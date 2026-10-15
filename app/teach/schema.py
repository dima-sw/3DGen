"""Gli schemi delle quattro domande che Teach fa a un modello. La forma, non il senso.

Stessa divisione di `app/core/planner/schema.py`, e per la stessa ragione:

    schema.py      un nodo ha un nome, `count` e' un intero, `status` e' una
                   delle quattro parole                           <- questo file
    model.py       la gerarchia non e' troppo profonda, gli id non si
                   ripetono, `count` sta in 1..64
    coverage.py    `creature:eye` esiste davvero ed e' compatibile
    staging.py     questi file si possono scrivere, questo Python non e' fidato

Uno schema JSON puo' dire che `component` e' una stringa; non puo' dire quali
stringhe esistono, perche' dipendono dai plugin installati. Per questo **nessuno
schema qui elenca un id**, e per questo la validazione vera non e' qui.

A che cosa servono allora: a far rispondere della forma giusta i fornitori che
sanno vincolare l'uscita (`LLMProvider.structured`), e a essere la definizione
controllabile di che cosa Teach accetta. Gli stessi oggetti vanno in entrambe
le modalita' di §5 — esterna e con un provider configurato — perche' il prompt
e lo schema devono essere identici nelle due.

`additionalProperties: false` ovunque, deliberatamente: regola 22 di
`PROJECT-INDEX` applicata a una risposta di un modello. Un campo che non
capiamo e' un contratto che divergera', e qui costerebbe un'ontologia letta al
contrario.
"""
from __future__ import annotations

SCHEMA_VERSION = "1.0"

# --------------------------------------------------------------------------- #
# 1. Decomposizione e raffinamento (§4, §7)
# --------------------------------------------------------------------------- #
# La ricorsione dice "un nodo ha nodi dentro" e nient'altro: il tetto di
# profondita' e il numero massimo di nodi sono decisioni di chi valida
# (`app/teach/model.py:MAX_DEPTH`), non della forma.
_NODE: dict = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "minLength": 1, "maxLength": 48,
                 "description": "il nome della parte, al singolare"},
        "role": {"type": "string", "maxLength": 48,
                 "description": "il ruolo semantico della parte: che cosa e'"},
        "mandatory": {"type": "boolean",
                      "description": "senza questa parte l'oggetto non e' se stesso"},
        "count": {"type": "integer", "minimum": 1, "maximum": 64,
                  "description": "quante istanze identiche; non duplicare il nodo"},
        "importance": {"type": "number", "minimum": 0.0, "maximum": 1.0,
                       "description": "quanto conta per riconoscere l'oggetto"},
        "detail_level": {"type": "integer", "minimum": 1, "maximum": 5,
                         "description": "da quale livello di dettaglio serve"},
        "description": {"type": "string", "maxLength": 400},
        "children": {"type": "array", "maxItems": 24, "items": {"$ref": "#/$defs/node"}},
    },
    "required": ["name", "mandatory"],
    "additionalProperties": False,
}

DECOMPOSITION_SCHEMA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://3dgen.local/schemas/teach-decomposition/1.0",
    "title": "Decomposizione concettuale di un oggetto",
    "type": "object",
    "properties": {
        "concept": {"type": "string", "minLength": 1, "maxLength": 64},
        "description": {"type": "string", "maxLength": 600},
        "root": {"$ref": "#/$defs/node"},
    },
    "required": ["concept", "root"],
    "additionalProperties": False,
    "$defs": {"node": _NODE},
}

# Il raffinamento restituisce la **stessa** forma: e' la seconda risposta alla
# stessa domanda, non una domanda diversa. Un campo libero in piu' per dire che
# cosa ha cambiato, perche' una revisione muta non si puo' rivedere.
REFINEMENT_SCHEMA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://3dgen.local/schemas/teach-refinement/1.0",
    "title": "Gerarchia raffinata in componenti riutilizzabili",
    "type": "object",
    "properties": {
        "concept": {"type": "string", "minLength": 1, "maxLength": 64},
        "description": {"type": "string", "maxLength": 600},
        "root": {"$ref": "#/$defs/node"},
        "changes": {"type": "array", "maxItems": 40,
                    "items": {"type": "string", "maxLength": 200},
                    "description": "che cosa e' stato cambiato rispetto al pass 1"},
    },
    "required": ["concept", "root"],
    "additionalProperties": False,
    "$defs": {"node": _NODE},
}

# --------------------------------------------------------------------------- #
# 2. Idoneita' di un candidato (§14)
# --------------------------------------------------------------------------- #
# `suggested_params` e' un oggetto di soli numeri: un parametro di un
# componente e' un numero, e ammettere una stringa qui vorrebbe dire ammettere
# che un modello nomini un'espressione. E' la politica di V5 §1, applicata a
# una risposta invece che a un file.
SUITABILITY_SCHEMA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://3dgen.local/schemas/teach-suitability/1.0",
    "title": "Idoneita' di un componente installato per una parte richiesta",
    "type": "object",
    "properties": {
        "status": {"enum": ["SUITABLE", "SUITABLE_WITH_PARAMETERS",
                            "NEEDS_VISUAL_CHECK", "NOT_SUITABLE"]},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "reason": {"type": "string", "maxLength": 600},
        "suggested_params": {
            "type": "object",
            "additionalProperties": {"type": "number"},
            "description": "solo parametri dichiarati dal componente, solo numeri"},
    },
    "required": ["status", "confidence", "reason"],
    "additionalProperties": False,
}

# --------------------------------------------------------------------------- #
# 3. Implementazione (§28)
# --------------------------------------------------------------------------- #
# L'inviluppo. Percorsi relativi, niente traversal, niente percorsi assoluti,
# dimensioni limitate, estensioni ammesse: lo schema dice la **forma**, e
# `app/teach/staging.py` fa valere tutto il resto — perche' uno schema non sa
# dire "questo percorso uscirebbe dalla cartella".
IMPLEMENTATION_SCHEMA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://3dgen.local/schemas/teach-implementation/1.0",
    "title": "I file di un plugin, come un modello li consegna",
    "type": "object",
    "properties": {
        "files": {
            "type": "array", "minItems": 1, "maxItems": 24,
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "minLength": 1, "maxLength": 160,
                             "description": "relativo alla radice del plugin"},
                    "content": {"type": "string", "maxLength": 200000},
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        },
        "notes": {"type": "string", "maxLength": 2000},
    },
    "required": ["files"],
    "additionalProperties": False,
}

# --------------------------------------------------------------------------- #
# 4. Validazione visiva (§17)
# --------------------------------------------------------------------------- #
# Non serve una API vision nuova: l'utente porta i render e il testo a un
# modello che le immagini le sa guardare, e torna con questo. Il verdetto resta
# dell'utente, come per l'idoneita'.
VISUAL_SCHEMA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://3dgen.local/schemas/teach-visual/1.0",
    "title": "Giudizio su alcune varianti rese di un candidato",
    "type": "object",
    "properties": {
        "best": {"type": "string", "maxLength": 32,
                 "description": "l'etichetta della variante migliore"},
        "verdicts": {
            "type": "array", "minItems": 1, "maxItems": 12,
            "items": {
                "type": "object",
                "properties": {
                    "variant": {"type": "string", "minLength": 1, "maxLength": 32},
                    "status": {"enum": ["SUITABLE", "SUITABLE_WITH_PARAMETERS",
                                        "NEEDS_VISUAL_CHECK", "NOT_SUITABLE"]},
                    "reason": {"type": "string", "maxLength": 400},
                },
                "required": ["variant", "status"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["verdicts"],
    "additionalProperties": False,
}

SCHEMAS = {
    "decomposition": DECOMPOSITION_SCHEMA,
    "refinement": REFINEMENT_SCHEMA,
    "suitability": SUITABILITY_SCHEMA,
    "implementation": IMPLEMENTATION_SCHEMA,
    "visual": VISUAL_SCHEMA,
}
