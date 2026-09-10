"""Lo schema di un piano: la **forma**, non il significato.

    schema      un piano ha una radice, i figli sono un elenco, `amount` e' un
                numero                                           <- questo file
    plans.py    `humanoid:body` esiste davvero, `width` e' un parametro di
                quel componente, `lanky` e' un effetto installato

La divisione conta. Uno schema JSON puo' dire che `ref` e' una stringa; non
puo' dire quali stringhe esistono, perche' quelle dipendono dai plugin
installati e cambiano fra due macchine. Se provasse a dirlo, ogni plugin nuovo
richiederebbe di rigenerare lo schema, e uno schema rigenerato non e' piu' un
contratto: e' una fotografia.

Per questo lo schema qui e' **indipendente dai plugin** e non elenca nessun id.
I riferimenti li verifica il registry, dove vivono.

## A che cosa serve davvero

A due cose, e nessuna delle due e' la validazione principale:

1. **Structured output.** Un fornitore che sa vincolare la risposta a uno
   schema JSON restituisce un piano gia' della forma giusta, e si risparmia un
   giro di correzione speso su una parentesi.
2. **Documentazione eseguibile.** E' la definizione di che cosa sia un piano,
   in una forma che si puo' controllare invece di leggere.

La validazione vera resta in `plans.py`, perche' un piano storto non deve dare
"non conforme allo schema" ma "'creature:dragon_head' non si attacca a
'architecture:window': al suo posto puoi usare humanoid:head". Uno schema non
sa dire la seconda frase.

## Versione

`SCHEMA_VERSION` cambia quando cambia la **forma** di un piano, non quando
cambiano i plugin. Un piano dichiara la propria versione in `version`, e chi lo
legge sa che cosa aspettarsi.
"""
from __future__ import annotations

SCHEMA_VERSION = "1.0"
SCHEMA_ID = "https://3dgen.local/schemas/composition-plan/1.0"

# Un nodo si riferisce a se stesso: un piano e' un albero di profondita'
# qualunque, e la ricorsione dello schema dice esattamente questo. Il tetto di
# profondita' non sta qui — e' una decisione di chi valida, non della forma.
_NODO = {
    "type": "object",
    "properties": {
        "id": {"type": "string", "minLength": 1, "maxLength": 64,
               "description": "nome unico nel piano; se manca viene costruito"},
        "ref": {"type": "string", "minLength": 1,
                "description": "'plugin:componente', oppure una capability"},
        "swap": {"type": "string", "minLength": 1,
                 "description": "sostituisce cio' da cui il nodo viene costruito"},
        "at": {
            "type": "object",
            "description": "dove si attacca, sul componente che lo contiene",
            "properties": {
                "capability": {"type": "string"},
                "socket": {"type": "string"},
                "side": {"type": "string", "enum": ["l", "r", "", "top",
                                                    "bottom", "front", "back"]},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "additionalProperties": False,
        },
        "on": {"type": "string",
               "description": "percorso di una parte gia' prevista: 'testa/naso'"},
        "params": {
            "type": "object",
            "description": "parametri del componente; i nomi li dichiara il componente",
            "additionalProperties": {"type": ["number", "string", "boolean"]},
        },
        "effects": {"type": "array", "items": {"$ref": "#/$defs/effetto"}},
        "optional": {"type": "boolean"},
        "on_request": {"type": "boolean"},
        "level": {"type": "integer", "minimum": 1, "maximum": 5},
        "scale_mode": {"type": "string",
                       "enum": ["none", "socket", "fit_replaced"]},
        "insert": {"type": "number", "minimum": 0.0, "maximum": 2.0},
        "roll": {"type": "number", "minimum": -360.0, "maximum": 360.0},
        "tags": {"type": "array", "items": {"type": "string"}},
        "children": {"type": "array", "items": {"$ref": "#/$defs/nodo"}},
    },
    "anyOf": [{"required": ["ref"]}, {"required": ["swap"]}],
    "additionalProperties": False,
}

_EFFETTO = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "minLength": 1,
                 "description": "id dell'effetto, fra quelli del vocabolario"},
        "scope": {"type": "string",
                  "description": "model | part:id | subtree:id | group:tag | role:x"},
        "amount": {"type": "number"},
        "target": {"type": "string"},
    },
    "required": ["type"],
    # I parametri di un effetto sono dichiarati dall'effetto stesso: qui non si
    # possono elencare senza sapere quali plugin sono installati.
    "additionalProperties": {"type": ["number", "string", "boolean"]},
}

PLAN_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": SCHEMA_ID,
    "title": "Piano di composizione 3DGen",
    "description": "Che cosa costruire: componenti, come si attaccano, "
                   "che parametri hanno, che effetti subiscono.",
    "type": "object",
    "properties": {
        "version": {"type": "string"},
        "style": {"type": "string", "description": "id di uno stile installato"},
        "detail_level": {"type": "integer", "minimum": 1, "maximum": 5},
        "seed": {"type": "integer", "minimum": 0},
        "root": {"$ref": "#/$defs/nodo"},
    },
    "required": ["root"],
    "additionalProperties": False,
    "$defs": {"nodo": _NODO, "effetto": _EFFETTO},
}


def plan_schema() -> dict:
    """Una copia dello schema. Copia, perche' un dizionario condiviso e'
    un dizionario che qualcuno prima o poi modifica."""
    import copy

    return copy.deepcopy(PLAN_SCHEMA)


def describe() -> str:
    """Lo schema in due righe, per chi legge un prompt e non un JSON."""
    return ("un oggetto con 'root'; ogni nodo ha 'ref' (o 'swap'), "
            "facoltativi 'id', 'at', 'params', 'effects', 'children', 'on'")
