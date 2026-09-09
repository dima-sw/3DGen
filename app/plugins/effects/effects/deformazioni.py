"""Tre effetti, uno per ciascun modo di cambiare un modello.

    lanky                       proporzione   cambia **cosa** si costruisce
    bend                        locale        cambia i vertici di una parte
    perspective_exaggeration    globale       cambia i vertici del modello

Nessuno dei tre sa che cosa sta deformando. `lanky` non cerca gambe: cerca
parametri che qualcuno ha dichiarato essere lunghezze e spessori. Il risultato
e' che allunga un umanoide, un tavolo e un cristallo con lo stesso codice — e
se un giorno arriva un plugin di cose che oggi non esistono, funziona anche li'.

## Perche' sono mappe di punti e non trasformazioni di mesh

Perche' un pezzo non ha solo vertici: ha anche i socket dove si attaccano i
figli. Piegare la mesh e lasciare i socket dov'erano fa attaccare le dita in
mezzo all'aria, e non se ne accorge nessuno finche' non si guarda il modello.
Dichiarando una funzione `punti -> punti`, il builder muove le due cose con la
stessa identica mappa: la coerenza non e' una convenzione da rispettare, e'
impossibile romperla.

## Perche' la curvatura e' un angolo totale e non radianti al metro

Perche' altrimenti la stessa piega su un modello alto sei metri sarebbe tre
volte piu' forte. La posizione lungo l'asse si normalizza fra 0 e 1 **prima**
di diventare un angolo: la forma resta la stessa a qualunque scala. E' un
errore che questo progetto ha gia' fatto una volta, e i giunti si staccavano.
"""
import math

import numpy as np

from app.core.params import ENUM, FLOAT, RATIO, ParamSpec
from app.core.vocabulary import (PRESERVE_SOCKETS, RECOVERABLE, SCOPE_GROUP,
                                 SCOPE_MODEL, SCOPE_PART, SCOPE_ROLE,
                                 SCOPE_SUBTREE, STAGE_GLOBAL, STAGE_LOCAL,
                                 STAGE_PROPORTION, EffectSpec, ParamRule)

ASSI = {"X": 0, "Y": 1, "Z": 2}


def _asse(ctx, nome: str, predefinito: str) -> int:
    return ASSI.get(str(ctx.get(nome, predefinito)).upper(), ASSI[predefinito])


def _estremi(punti: np.ndarray, asse: int, ctx) -> tuple[float, float]:
    """Da dove a dove si misura la posizione lungo un asse.

    Se il contesto porta i limiti del **modello** si usano quelli: un'esagerazione
    prospettica calcolata sui limiti di una mano deformerebbe la mano invece del
    corpo. Altrimenti valgono i limiti di cio' che si sta deformando.
    """
    limiti = getattr(ctx, "bounds", None)
    if limiti is not None:
        return float(limiti[0][asse]), float(limiti[1][asse])
    colonna = punti[:, asse]
    return float(colonna.min()), float(colonna.max())


def _normalizzato(punti: np.ndarray, asse: int, ctx) -> np.ndarray:
    """La posizione lungo un asse, portata fra 0 e 1.

    E' il passaggio che rende la deformazione indipendente dalla scala: senza,
    la stessa intensita' darebbe effetti diversi su modelli di taglia diversa.
    """
    minimo, massimo = _estremi(punti, asse, ctx)
    if massimo - minimo < 1e-9:
        return np.zeros(len(punti))
    return np.clip((punti[:, asse] - minimo) / (massimo - minimo), 0.0, 1.0)


# --------------------------------------------------------------------------- #
# Proporzione: cambia i parametri, non i vertici
# --------------------------------------------------------------------------- #
LANKY = EffectSpec(
    id="lanky",
    description="allunga e assottiglia: tutto piu' lungo e piu' magro",
    stage=STAGE_PROPORTION,
    scopes=(SCOPE_MODEL, SCOPE_SUBTREE, SCOPE_PART, SCOPE_GROUP, SCOPE_ROLE),
    amount=ParamSpec(0.6, RATIO, min=0.0, max=1.0,
                     description="quanto spingere: 0 niente, 1 il massimo"),
    changes=(
        ParamRule(semantic_role="length", expression="value * (1 + amount * 0.45)"),
        ParamRule(semantic_role="girth", expression="value * (1 - amount * 0.30)"),
    ),
    conflicts=frozenset({"chunky"}),
    tags=frozenset({"proporzione"}),
)

# Dichiarato per avere un conflitto vero da verificare: e' l'opposto esatto.
CHUNKY = EffectSpec(
    id="chunky",
    description="accorcia e ingrossa: l'opposto di lanky",
    stage=STAGE_PROPORTION,
    scopes=(SCOPE_MODEL, SCOPE_SUBTREE, SCOPE_PART, SCOPE_GROUP, SCOPE_ROLE),
    amount=ParamSpec(0.6, RATIO, min=0.0, max=1.0),
    changes=(
        ParamRule(semantic_role="length", expression="value * (1 - amount * 0.30)"),
        ParamRule(semantic_role="girth", expression="value * (1 + amount * 0.45)"),
    ),
    conflicts=frozenset({"lanky"}),
    tags=frozenset({"proporzione"}),
)


# --------------------------------------------------------------------------- #
# Deformazione locale: i punti di una parte
# --------------------------------------------------------------------------- #
def piega(punti: np.ndarray, ctx) -> np.ndarray:
    """Curva una parte lungo il suo asse di crescita.

    Ogni punto ruota di un angolo proporzionale a quanto e' avanti lungo
    l'asse: alla base niente, alla punta la curvatura piena. L'angolo totale
    dipende solo da `amount`, mai dalla lunghezza.
    """
    if len(punti) == 0:
        return punti
    lungo = _asse(ctx, "along", "X")
    attorno = _asse(ctx, "axis", "Z")
    if lungo == attorno:
        return punti

    fuori = np.array(punti, dtype=float, copy=True)
    t = _normalizzato(fuori, lungo, ctx)
    angoli = float(ctx.amount) * (math.pi * 0.5) * t

    altro = [i for i in (0, 1, 2) if i not in (lungo, attorno)][0]
    a = fuori[:, lungo].copy()
    b = fuori[:, altro].copy()
    fuori[:, lungo] = a * np.cos(angoli) - b * np.sin(angoli)
    fuori[:, altro] = a * np.sin(angoli) + b * np.cos(angoli)
    return fuori


BEND = EffectSpec(
    id="bend",
    description="curva una parte lungo il suo asse di crescita",
    stage=STAGE_LOCAL,
    scopes=(SCOPE_PART, SCOPE_SUBTREE, SCOPE_GROUP, SCOPE_ROLE),
    amount=ParamSpec(0.4, FLOAT, min=-1.0, max=1.0,
                     description="verso e quantita' della curva"),
    params={"axis": ParamSpec("Z", ENUM, choices=("X", "Y", "Z"),
                              description="attorno a quale asse si curva"),
            "along": ParamSpec("X", ENUM, choices=("X", "Y", "Z"),
                               description="l'asse di crescita della parte")},
    deform=piega,
    socket_policy=PRESERVE_SOCKETS,
    on_failure=RECOVERABLE,
    tags=frozenset({"deformazione"}),
)


# --------------------------------------------------------------------------- #
# Deformazione globale: i punti del modello
# --------------------------------------------------------------------------- #
def esagera_prospettiva(punti: np.ndarray, ctx) -> np.ndarray:
    """Ingrandisce cio' che e' vicino e rimpicciolisce cio' che e' lontano.

    E' l'esagerazione che i disegnatori usano per far sembrare un pugno enorme
    e la spalla piccola. Qui e' una scala della sezione lungo un asse, non una
    proiezione: la geometria resta geometria.
    """
    if len(punti) == 0:
        return punti
    profondita = _asse(ctx, "axis", "X")
    fuori = np.array(punti, dtype=float, copy=True)
    t = _normalizzato(fuori, profondita, ctx)

    forza = float(ctx.amount) * 0.6
    fattori = 1.0 + forza - 2.0 * forza * t          # da 1+forza a 1-forza
    for asse in (0, 1, 2):
        if asse == profondita:
            continue
        minimo, massimo = _estremi(fuori, asse, ctx)
        centro = (minimo + massimo) * 0.5
        fuori[:, asse] = centro + (fuori[:, asse] - centro) * fattori
    return fuori


PERSPECTIVE_EXAGGERATION = EffectSpec(
    id="perspective_exaggeration",
    description="esagera la profondita': grande davanti, piccolo dietro",
    stage=STAGE_GLOBAL,
    scopes=(SCOPE_MODEL,),
    amount=ParamSpec(0.5, RATIO, min=0.0, max=1.0),
    params={"axis": ParamSpec("X", ENUM, choices=("X", "Y", "Z"),
                              description="l'asse della profondita'")},
    deform=esagera_prospettiva,
    socket_policy=PRESERVE_SOCKETS,
    on_failure=RECOVERABLE,
    tags=frozenset({"deformazione", "prospettiva"}),
)
