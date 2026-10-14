"""Quattro deformazioni di forma: schiacciare, allungare, affusolare, torcere.

    squash      piu' basso e piu' largo
    elongate    piu' lungo e piu' stretto
    taper       la sezione si restringe verso un'estremita'
    twist       la sezione ruota man mano che si sale lungo un asse

Sono le quattro operazioni che `VISION-GAP.md` elencava come mancanti, e sono
contenuto, non architettura: nessuna riga del core e' stata cambiata per
aggiungerle. Stanno in questo plugin come `bend` sta in `deformazioni.py`.

## Perche' non sono gli effetti di proporzione che esistono gia'

`lanky` e `chunky` sono dello stadio `proportion`: cambiano i **parametri** di
cio' che verra' costruito, quindi funzionano solo su un componente che sappia
ricostruirsi — e lo fanno meglio, perche' una gamba piu' lunga e' una gamba
piu' lunga e non una gamba stirata. Questi quattro sono dello stadio `local`:
muovono i **vertici** di cio' che e' stato costruito. E' la stessa distinzione
che `app/core/effect.py` dichiara in testa, ed e' la ragione per cui non sono
doppioni: una mesh importata ha un solo stato e non si puo' rigenerare, quindi
l'unico modo di farla variare e' muoverle i punti.

## Perche' sono mappe di punti

Perche' `EffectSpec.deform` e' una funzione `punti -> punti` e il builder la
usa **sia** sui vertici **sia** sui socket: geometria e innesti non possono
desincronizzarsi, non per disciplina ma per costruzione. Vale per tutti e
quattro, ed e' la ragione per cui nessuno di loro dichiara `apply`.

## Perche' tutto si normalizza fra 0 e 1

Stessa ragione di `bend`: la posizione lungo l'asse diventa `t` fra 0 e 1
**prima** di diventare un angolo o un fattore. Cosi' la stessa intensita' da'
la stessa forma su una figura di sei metri e su una di sessanta centimetri. Un
angolo per metro sarebbe un effetto diverso su ogni modello.

## Low poly

Nessuno dei quattro aggiunge un vertice, una faccia o una suddivisione: il
conteggio dei triangoli dopo e' quello di prima. `taper` e `twist` non sono
affini — il fattore dipende da `t` — ma le facce restano piane perche' sono
triangoli, e tre punti sono sempre complanari. Non c'e' niente da smussare.
"""
import math

import numpy as np

from app.core.params import ENUM, FLOAT, RATIO, ParamSpec
from app.core.vocabulary import (PRESERVE_SOCKETS, RECOVERABLE, SCOPE_GROUP,
                                 SCOPE_PART, SCOPE_ROLE, SCOPE_SUBTREE,
                                 STAGE_LOCAL, EffectSpec)

ASSI = {"X": 0, "Y": 1, "Z": 2}

# Gli stessi ambiti di `bend`, e `model` non c'e' per la stessa ragione: una
# deformazione dello stadio `local` si applica **pezzo per pezzo**, con il
# riferimento del pezzo, quindi «tutto il modello» non e' una misura che possa
# usare. Lo stadio che ha i limiti del modello e' `global`, e li' vive
# `perspective_exaggeration`. Dichiarare `model` qui farebbe schiacciare ogni
# parte attorno alla propria base, che non e' cio' che la richiesta direbbe.
AMBITI = (SCOPE_PART, SCOPE_SUBTREE, SCOPE_GROUP, SCOPE_ROLE)


def _asse(ctx, nome: str, predefinito: str) -> int:
    return ASSI.get(str(ctx.get(nome, predefinito)).upper(), ASSI[predefinito])


def _estremi(punti: np.ndarray, asse: int, ctx) -> tuple[float, float]:
    """Da dove a dove si misura lungo un asse: i limiti del modello se ci sono.

    Identico a `deformazioni.py` e per la stessa ragione: un effetto che colpisce
    il modello intero deve misurare il modello, non il pezzo che sta toccando in
    quel momento. Duplicato invece che importato perche' i moduli di un plugin
    si caricano per percorso e non formano un pacchetto — come `posa.py`.
    """
    limiti = getattr(ctx, "bounds", None)
    if limiti is not None:
        return float(limiti[0][asse]), float(limiti[1][asse])
    colonna = punti[:, asse]
    return float(colonna.min()), float(colonna.max())


def _normalizzato(punti: np.ndarray, asse: int, ctx) -> np.ndarray:
    minimo, massimo = _estremi(punti, asse, ctx)
    if massimo - minimo < 1e-9:
        return np.zeros(len(punti))
    return np.clip((punti[:, asse] - minimo) / (massimo - minimo), 0.0, 1.0)


def _centro(punti: np.ndarray, asse: int, ctx) -> float:
    minimo, massimo = _estremi(punti, asse, ctx)
    return (minimo + massimo) * 0.5


def _scala(punti: np.ndarray, ctx, asse: int, lungo: float,
           attorno: float) -> np.ndarray:
    """Scala lungo un asse e nella sezione, lasciando la base dov'e'.

    La base e non il centro: una cosa schiacciata resta appoggiata dove stava,
    e una allungata cresce verso l'alto invece di sprofondare. La sezione
    invece si scala attorno al proprio centro, perche' non ha un "sotto".
    """
    fuori = np.array(punti, dtype=float, copy=True)
    base, _ = _estremi(fuori, asse, ctx)
    fuori[:, asse] = base + (fuori[:, asse] - base) * lungo
    for altro in (0, 1, 2):
        if altro == asse:
            continue
        centro = _centro(punti, altro, ctx)
        fuori[:, altro] = centro + (fuori[:, altro] - centro) * attorno
    return fuori


# --------------------------------------------------------------------------- #
# squash / elongate
# --------------------------------------------------------------------------- #
def schiaccia(punti: np.ndarray, ctx) -> np.ndarray:
    """Piu' basso lungo un asse, piu' largo negli altri due."""
    if len(punti) == 0:
        return punti
    quanto = float(ctx.amount)
    return _scala(punti, ctx, _asse(ctx, "axis", "Y"),
                  1.0 - quanto * 0.60, 1.0 + quanto * 0.45)


SQUASH = EffectSpec(
    id="squash",
    description="schiaccia lungo un asse e allarga negli altri due",
    stage=STAGE_LOCAL, scopes=AMBITI,
    amount=ParamSpec(0.5, RATIO, min=0.0, max=1.0,
                     description="quanto schiacciare: 0 niente, 1 il massimo"),
    params={"axis": ParamSpec("Y", ENUM, choices=("X", "Y", "Z"),
                              description="l'asse che si accorcia")},
    deform=schiaccia, socket_policy=PRESERVE_SOCKETS, on_failure=RECOVERABLE,
    conflicts=frozenset({"elongate"}),
    tags=frozenset({"deformazione", "forma"}),
)


def allunga(punti: np.ndarray, ctx) -> np.ndarray:
    """Piu' lungo lungo un asse, piu' stretto negli altri due."""
    if len(punti) == 0:
        return punti
    quanto = float(ctx.amount)
    return _scala(punti, ctx, _asse(ctx, "axis", "Y"),
                  1.0 + quanto * 0.80, 1.0 - quanto * 0.30)


ELONGATE = EffectSpec(
    id="elongate",
    description="allunga lungo un asse e assottiglia negli altri due",
    stage=STAGE_LOCAL, scopes=AMBITI,
    amount=ParamSpec(0.5, RATIO, min=0.0, max=1.0,
                     description="quanto allungare: 0 niente, 1 il massimo"),
    params={"axis": ParamSpec("Y", ENUM, choices=("X", "Y", "Z"),
                              description="l'asse che si allunga")},
    deform=allunga, socket_policy=PRESERVE_SOCKETS, on_failure=RECOVERABLE,
    conflicts=frozenset({"squash"}),
    tags=frozenset({"deformazione", "forma"}),
)


# --------------------------------------------------------------------------- #
# taper
# --------------------------------------------------------------------------- #
def affusola(punti: np.ndarray, ctx) -> np.ndarray:
    """Restringe la sezione verso un'estremita'.

    Il fattore dipende da dove si e' lungo l'asse, quindi la deformazione non
    e' affine: e' esattamente cio' che distingue un affusolamento da una scala.
    Quale delle due estremita' si restringe lo dice un parametro, perche' una
    coda si assottiglia verso la punta e un tronco verso l'alto, ma un piede si
    assottiglia verso il tallone — e l'effetto non sa cosa sta guardando.
    """
    if len(punti) == 0:
        return punti
    asse = _asse(ctx, "axis", "Y")
    t = _normalizzato(punti, asse, ctx)
    if str(ctx.get("end", "tip")).lower() == "base":
        t = 1.0 - t
    fattori = 1.0 - float(ctx.amount) * 0.80 * t
    fuori = np.array(punti, dtype=float, copy=True)
    for altro in (0, 1, 2):
        if altro == asse:
            continue
        centro = _centro(punti, altro, ctx)
        fuori[:, altro] = centro + (fuori[:, altro] - centro) * fattori
    return fuori


TAPER = EffectSpec(
    id="taper",
    description="restringe la sezione verso un'estremita': da cono a cilindro",
    stage=STAGE_LOCAL, scopes=AMBITI,
    amount=ParamSpec(0.5, RATIO, min=0.0, max=1.0,
                     description="quanto restringere all'estremita' scelta"),
    params={"axis": ParamSpec("Y", ENUM, choices=("X", "Y", "Z"),
                              description="l'asse lungo cui si affusola"),
            "end": ParamSpec("tip", ENUM, choices=("tip", "base"),
                             description="quale estremita' si restringe")},
    deform=affusola, socket_policy=PRESERVE_SOCKETS, on_failure=RECOVERABLE,
    tags=frozenset({"deformazione", "forma"}),
)


# --------------------------------------------------------------------------- #
# twist
# --------------------------------------------------------------------------- #
def torci(punti: np.ndarray, ctx) -> np.ndarray:
    """Ruota la sezione di un angolo che cresce lungo l'asse.

    L'angolo totale e' dichiarato in gradi e si distribuisce su `t`: alla base
    niente, all'altra estremita' tutto. La rotazione e' attorno alla **linea
    centrale** della sezione, non attorno all'origine, perche' un pezzo che non
    e' centrato altrimenti si allontanerebbe invece di torcersi.
    """
    if len(punti) == 0:
        return punti
    asse = _asse(ctx, "axis", "Y")
    t = _normalizzato(punti, asse, ctx)
    angoli = math.radians(float(ctx.get("angle", 90.0)) * float(ctx.amount)) * t
    primo, secondo = [i for i in (0, 1, 2) if i != asse]
    centro_primo = _centro(punti, primo, ctx)
    centro_secondo = _centro(punti, secondo, ctx)
    fuori = np.array(punti, dtype=float, copy=True)
    a = fuori[:, primo] - centro_primo
    b = fuori[:, secondo] - centro_secondo
    fuori[:, primo] = centro_primo + a * np.cos(angoli) - b * np.sin(angoli)
    fuori[:, secondo] = centro_secondo + a * np.sin(angoli) + b * np.cos(angoli)
    return fuori


TWIST = EffectSpec(
    id="twist",
    description="torce la sezione man mano che si sale lungo un asse",
    stage=STAGE_LOCAL, scopes=AMBITI,
    amount=ParamSpec(1.0, RATIO, min=0.0, max=1.0,
                     description="quanta parte dell'angolo applicare"),
    params={"axis": ParamSpec("Y", ENUM, choices=("X", "Y", "Z"),
                              description="l'asse attorno a cui si torce"),
            "angle": ParamSpec(90.0, FLOAT, min=-360.0, max=360.0,
                               description="l'angolo totale in gradi, con il segno")},
    deform=torci, socket_policy=PRESERVE_SOCKETS, on_failure=RECOVERABLE,
    tags=frozenset({"deformazione", "forma"}),
)
