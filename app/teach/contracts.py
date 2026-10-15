"""Il contratto di 3DGen, scritto leggendo 3DGen. Non una copia a mano.

Un prompt di implementazione deve dire a un modello **quali API esistono** -
§25 chiede «solo le API necessarie» - e la tentazione e' scrivere quel testo a
mano una volta. E' la cosa sbagliata: diventerebbe falso al primo campo
aggiunto a `Component`, e un prompt falso produce codice che non si carica, che
e' il modo peggiore di scoprire un errore di documentazione.

Quindi tutto cio' che segue si **genera**: i campi arrivano da
`dataclasses.fields`, le firme da `inspect.signature`, le chiavi del formato
dati dalle costanti che il loader fa valere (`app/core/data_plugin.py`), i tipi
di parametro dalle costanti di `app/core/params.py`. Se qualcuno aggiunge un
campo a `Piece`, il prompt lo dice il giorno dopo senza che nessuno lo
aggiorni - e un test confronta il testo generato con i campi veri, cosi' una
divergenza fallisce invece di passare.

Che cosa **non** c'e': il core. Un modello che implementa un componente non
deve conoscere il resolver, il builder, la pipeline degli effetti o la
sessione, e non deve poterli modificare (§25). Qui ci sono i tipi che un
plugin **costruisce**, piu' il kernel poligonale che un plugin puo' chiamare.
"""
from __future__ import annotations

import dataclasses
import inspect
from typing import Any

from app.core.capability import Capability, Mount, Requirement
from app.core.component import Attachment, BuildContext, Component, Piece
from app.core.data_plugin import (CHILD_KEYS, COMPONENT_KEYS, DATA_MANIFEST_KEYS,
                                  EFFECT_KEYS, PARAM_KEYS, SOCKET_KEYS, TRANSFORMS)
from app.core.layout import LayoutRegion
from app.core.params import TYPES, ParamSpec
from app.core.socket import Socket

# Le chiavi che un manifest di **codice** usa per nominare file Python. Lette
# dal punto che le scorre (`Registry._read_manifest`), non inventate qui.
CODE_SOURCE_KEYS = ("components", "effects", "styles", "materials", "traits",
                    "archetypes", "profiles", "bindings")

# I tipi che un plugin costruisce. Non il core: un componente nuovo non deve
# conoscere il resolver, e non deve poterlo cambiare.
BUILT = (Component, Piece, Socket, ParamSpec, Attachment, Capability, Mount,
         Requirement, BuildContext, LayoutRegion)

# Le funzioni del kernel poligonale che un plugin puo' chiamare. L'elenco e'
# quello di `PROJECT-INDEX` §6, e le firme si leggono.
KERNEL = ("ring", "sweep", "profile_sweep", "grow", "block", "faces_per_normal")


def _type_name(annotation: Any) -> str:
    if annotation is None or annotation is dataclasses.MISSING:
        return ""
    text = str(annotation)
    for prefix in ("<class '", "typing.", "app.core."):
        text = text.replace(prefix, "")
    return text.replace("'>", "").strip()


def _default(field: dataclasses.Field) -> str:
    if field.default is not dataclasses.MISSING:
        return "" if field.default is None else repr(field.default)
    if field.default_factory is not dataclasses.MISSING:   # type: ignore[misc]
        try:
            return repr(field.default_factory())           # type: ignore[misc]
        except Exception:                                  # noqa: BLE001
            return "<factory>"
    return "obbligatorio"


def dataclass_text(cls) -> str:
    """Una dataclass come un contratto: campi, tipi, valori predefiniti."""
    righe = ["%s - %s" % (cls.__name__,
                          (cls.__doc__ or "").strip().splitlines()[0]
                          if cls.__doc__ else "")]
    for field in dataclasses.fields(cls):
        if field.name.startswith("_"):
            continue
        righe.append("    %-16s %-28s %s" % (field.name, _type_name(field.type),
                                             _default(field)))
    return "\n".join(righe)


def kernel_text() -> str:
    """Le firme del kernel poligonale, lette con `inspect`."""
    from app.geometry import kernel

    righe = ["app/geometry/kernel.py - l'unico costruttore di geometria "
             "procedurale installato"]
    for name in KERNEL:
        function = getattr(kernel, name, None)
        if function is None:
            continue
        doc = (function.__doc__ or "").strip().splitlines()
        righe.append("    %s%s" % (name, inspect.signature(function)))
        if doc:
            righe.append("        %s" % doc[0].strip())
    return "\n".join(righe)


def param_types_text() -> str:
    return "tipi di ParamSpec ammessi: %s" % ", ".join(TYPES)


def python_contract() -> str:
    """Il contratto di un plugin di **codice**: `Component -> Piece`, e nulla piu'."""
    blocchi = [
        "CONTRATTO DI UN COMPONENTE DI CODICE",
        "",
        "Un plugin di codice e' una cartella con un `plugin.json` che nomina "
        "moduli Python.",
        "Il registry importa quei moduli e raccoglie gli oggetti di livello "
        "modulo: un",
        "`Component` assegnato a una variabile del modulo viene registrato. "
        "Non esiste",
        "una funzione di registrazione da chiamare, non esiste un decoratore, "
        "e il core",
        "non va modificato: la sola cosa da scrivere e' il modulo.",
        "",
        "Il manifest nomina i moduli sotto queste chiavi: %s."
        % ", ".join(CODE_SOURCE_KEYS),
        "L'`id` di un `Component` e' **non qualificato** (`piece`, non "
        "`plugin:piece`):",
        "il registry lo qualifica con l'id del plugin.",
        "",
        "I TIPI CHE SI COSTRUISCONO",
        "",
    ]
    blocchi.extend(dataclass_text(cls) for cls in BUILT)
    blocchi.extend(["", param_types_text(), "", kernel_text(), "",
                    "`build(values, ctx)` riceve i valori dei parametri e un "
                    "`BuildContext`, e",
                    "restituisce un `Piece`. `children(values, ctx)` - "
                    "facoltativa - restituisce",
                    "una lista di `Attachment`. Nessuna delle due deve "
                    "leggere file, aprire",
                    "socket di rete, importare moduli del core oltre a quelli "
                    "elencati qui, o",
                    "dipendere dallo stato globale: lo stesso ingresso deve "
                    "dare la stessa",
                    "geometria, sempre."])
    return "\n".join(blocchi)


def data_contract() -> str:
    """Il contratto di un plugin **dati**: JSON accanto a un GLB, nessun Python."""
    return "\n".join([
        "CONTRATTO DI UN PLUGIN DATI",
        "",
        "Nessun Python. Un `plugin.json` con `type: \"data\"`, uno o piu' file "
        "JSON di",
        "componente, e i GLB a cui si riferiscono. Niente di questa cartella "
        "viene",
        "importato o eseguito: un `.py` qui dentro non verrebbe nemmeno aperto.",
        "",
        "plugin.json - chiavi ammesse (ogni altra chiave fa rifiutare il "
        "plugin):",
        "    %s" % ", ".join(DATA_MANIFEST_KEYS),
        "",
        "componente - chiavi ammesse:",
        "    %s" % ", ".join(COMPONENT_KEYS),
        "",
        "`mesh` e' il percorso del GLB, **relativo al file del componente** "
        "(tipicamente",
        "`../meshes/<nome>.glb`), e non puo' uscire dalla cartella del plugin. "
        "`mesh` e'",
        "facoltativo: senza mesh il componente e' un **composite** e la "
        "geometria la",
        "portano i `children` - allora i children sono obbligatori e nessun "
        "parametro",
        "puo' dichiarare `transform`.",
        "",
        "socket - chiavi ammesse: %s" % ", ".join(SOCKET_KEYS),
        "    `direction` e `up` devono essere non nulli e non paralleli; "
        "`radius` > 0.",
        "",
        "params - chiavi ammesse: %s" % ", ".join(PARAM_KEYS),
        "    Un parametro dichiara **esattamente una** strategia:",
        "      transform: %s  (solo valori positivi: una scala negativa "
        "specchierebbe"
        % "/".join(TRANSFORMS),
        "                 la mesh)",
        "      effect:    { %s }  - nomina un effetto installato e uno dei "
        "suoi knob"
        % ", ".join(EFFECT_KEYS),
        "                 **numerici**; il valore puo' essere negativo, "
        "perche' il verso",
        "                 di una piega e' un segno",
        "    Nessun'altra chiave e' ammessa: un parametro dati non puo' "
        "nominare un",
        "    callable, un modulo, un'espressione o una matrice.",
        "",
        "children - chiavi ammesse: %s" % ", ".join(CHILD_KEYS),
        "    `params` di un child accetta solo letterali: numeri, stringhe, "
        "booleani,",
        "    liste di numeri.",
        "",
        "`frame` dichiara `growth_axis`, `front`, `up` con assi nominati "
        "(+X/-X/+Y/-Y/+Z/-Z).",
        "Dichiararlo e' facoltativo, e un frame non dichiarato non si confronta "
        "con nessuno.",
    ])


def composite_contract() -> str:
    """Il contratto di un composite dichiarativo: la forma normale di un concetto."""
    return "\n".join([
        "CONTRATTO DI UN COMPOSITE DATI",
        "",
        "Un composite e' un componente dati **senza** `mesh`: non ha geometria "
        "propria, e",
        "i suoi `children` la portano. E' la forma normale di un concetto "
        "complesso - un",
        "oggetto intero e' quasi sempre una composizione, non una mesh unica.",
        "",
        "Due regole lo rendono non ambiguo:",
        "    senza `mesh` i `children` sono obbligatori",
        "    senza `mesh` nessun parametro puo' dichiarare `transform`",
        "        (un `effect` con ambito `subtree` resta ammesso: deforma i "
        "figli)",
        "",
        "Un composite nasce senza innesti, quindi il resolver direbbe "
        "`NO_MOUNTS` e i",
        "figli non si attaccherebbero: deve dichiarare i `sockets` **e** i "
        "`mounts` che",
        "li usano. Un `mount` su un socket che non esiste non monta niente, e "
        "un socket",
        "senza `mount` non viene mai scelto.",
        "",
        "Un figlio nomina un componente **installato** (`plugin:nome`) e il "
        "`requirement`",
        "con cui si attacca. I `params` del figlio incorporano una "
        "configurazione: e' il",
        "modo in cui una variant confermata entra in un composite senza "
        "duplicare la mesh.",
    ])


CONTRACTS = {"procedural_python": python_contract, "data_mesh": data_contract,
             "composite": composite_contract}


def contract_for(backend: str) -> str:
    builder = CONTRACTS.get(backend)
    return builder() if builder is not None else ""
