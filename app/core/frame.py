"""La convenzione d'asse, promossa da annotazione a contratto verificabile.

Fino a V4 un componente poteva dichiarare `growth_axis`, `front` e `up`, e
quelle tre stringhe servivano a una **diagnostica di authoring**
(`app/core/authoring.py:verify_frame`): guardavano la geometria di un pezzo e
dicevano se cresceva dove aveva dichiarato di crescere. Nessuno le confrontava
fra due componenti, e il risultato era il drago del `VISION-GAP`: un corpo di
pesce, una testa di drago e due ali di tre plugin diversi si montavano per
capability senza che nulla notasse che i tre asset non concordavano su che cosa
fosse "davanti".

## Che cosa confronta questo modulo, e che cosa no

Tre assi, due significati diversi, ed e' la distinzione che rende il contratto
usabile invece che rumoroso:

    growth_axis   **locale**: da dove la parte si estende, partendo dalla sua
                  base. Un arto che cresce +X su un torso che cresce +Y non e'
                  un'incoerenza, e' la convenzione di `authoring.py`. Il socket
                  del padre porta `direction` e `up`, e il placement engine usa
                  quelli: la rotazione di un figlio rispetto al padre e' gia'
                  decisa, e qui non si tocca.

    up / front    **del soggetto**: quale asse locale guarda in alto e quale in
                  avanti quando il componente sta dritto. Queste due il socket
                  **non** le concilia: il frame di innesto allinea `direction`
                  con `-direction`, non la nozione di "in alto" di due autori
                  diversi. Se un plugin costruisce con il davanti verso +Z e un
                  altro verso -Z, i due pezzi si montano senza un errore e il
                  risultato guarda dalla parte sbagliata.

Quindi: `compare()` guarda **solo** `up` e `front`. `growth_axis` resta la
diagnostica geometrica che era, e continua a vivere in `verify_frame`.

## Quattro esiti, e nessuna correzione

    compatible    i due concordano su cio' che entrambi dichiarano
    convertible   non concordano, ma entrambi dichiarano una terna completa:
                  allora la rotazione che porta l'uno sull'altro e' **una
                  sola**, e si puo' nominare
    ambiguous     non concordano e uno dei due e' incompleto: la rotazione non
                  e' determinata, e indovinarla sarebbe inventare
    undeclared    non c'e' niente da confrontare

`undeclared` non e' un difetto: e' il limite dichiarato del contratto. Un
orientamento assurdo si rileva **quando i metadata lo permettono**, e per i 22
plugin che non dichiarano niente il sistema non sa e dice di non sapere.

## Perche' non converte

Perche' applicare la rotazione vorrebbe dire decidere la posa di un figlio
contro il socket che il padre ha dichiarato, cioe' un secondo sistema di
placement accanto a quello che c'e'. La rotazione si **calcola** e si **nomina**
— `rotation_to()` da' asse e gradi, e `move()` scrive la richiesta di effetto
che la applicherebbe con `fx:rotate`, che e' installato — e chi legge la
diagnostica decide. E' la stessa scelta di V3.5 per i brief di riparazione:
dire la mossa, non farla.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from app.core.authoring import ASSI

# Gli esiti di un confronto. Sono quattro perche' "non lo so" e "non si puo'
# sapere" sono risposte diverse da "va bene" e da "va girato".
FRAME_COMPATIBLE = "compatible"
FRAME_CONVERTIBLE = "convertible"
FRAME_AMBIGUOUS = "ambiguous"
FRAME_UNDECLARED = "undeclared"

COMPARISONS = (FRAME_COMPATIBLE, FRAME_CONVERTIBLE, FRAME_AMBIGUOUS,
               FRAME_UNDECLARED)

# Le due politiche del progetto. Non c'e' una terza che converte: vedi sopra.
POLICY_DIAGNOSE = "diagnose"      # avviso, il modello si costruisce
POLICY_STRICT = "strict"          # errore: una chimera disorientata non passa

POLICIES = (POLICY_DIAGNOSE, POLICY_STRICT)

# Gli assi che il confronto guarda, in ordine di importanza: `up` decide se una
# cosa sta in piedi, `front` decide se guarda avanti.
SUBJECT_AXES = ("up", "front")


class FrameError(ValueError):
    """Una terna che non si puo' leggere. Il chiamante decide la gravita'."""


@dataclass(frozen=True)
class FrameSpec:
    """La terna dichiarata da un componente. Tre stringhe, nessuna matrice.

    I nomi sono quelli di `authoring.ASSI` (`+X`, `-X`, `+Y`, ...): un autore
    scrive un asse, non un quaternione, perche' cio' che sta dichiarando e' una
    convenzione e non una posa.
    """

    growth_axis: str = ""
    front: str = ""
    up: str = ""

    def __post_init__(self) -> None:
        for name in ("growth_axis", "front", "up"):
            value = str(getattr(self, name) or "")
            if value and value not in ASSI:
                raise FrameError("frame.%s: asse atteso fra %s, non %r"
                                 % (name, ", ".join(sorted(ASSI)), value))
            object.__setattr__(self, name, value)
        if self.front and self.up and abs(float(self.vector("front")
                                                @ self.vector("up"))) > 1e-9:
            raise FrameError("frame.front e frame.up devono essere ortogonali: "
                             "%s e %s non lo sono" % (self.front, self.up))

    # --------------------------------------------------------------- lettura #
    @property
    def declared(self) -> tuple[str, ...]:
        """Quali dei tre assi questo frame nomina davvero."""
        return tuple(n for n in ("growth_axis", "front", "up") if getattr(self, n))

    @property
    def complete(self) -> bool:
        """Basta a determinare una rotazione? Serve la coppia `up` + `front`.

        Due assi ortogonali fissano la terza colonna per prodotto vettoriale:
        `growth_axis` non aggiunge gradi di liberta' e non ne toglie.
        """
        return bool(self.front and self.up)

    @property
    def empty(self) -> bool:
        return not self.declared

    def vector(self, name: str) -> np.ndarray:
        axis = getattr(self, name, "")
        if not axis:
            raise FrameError("frame.%s non e' dichiarato" % name)
        return ASSI[axis].copy()

    def basis(self) -> np.ndarray:
        """La terna ortonormale destrorsa (right, up, front) come colonne.

        Esiste solo per un frame completo: senza `front` la rotazione attorno a
        `up` resta libera, e una matrice inventata mentirebbe sul fatto che
        manca un'informazione.
        """
        if not self.complete:
            raise FrameError("frame incompleto: serve up e front, dichiarati %s"
                             % (", ".join(self.declared) or "nessuno"))
        up = self.vector("up")
        front = self.vector("front")
        right = np.cross(up, front)
        return np.column_stack([right, up, front])

    def to_dict(self) -> dict[str, str]:
        return {n: getattr(self, n) for n in self.declared}

    def describe(self) -> str:
        if self.empty:
            return "frame non dichiarato"
        return ", ".join("%s %s" % (n, getattr(self, n)) for n in self.declared)

    # ------------------------------------------------------------- confronto #
    def rotation_to(self, other: "FrameSpec") -> np.ndarray:
        """La matrice che porta questo frame su quello dell'altro.

        Entrambi completi, quindi la risposta e' unica: `other.basis() @
        self.basis().T`. Due terne ortonormali destrorse hanno una sola
        rotazione che mappa l'una sull'altra, e per questo "convertibile" e'
        una categoria utile e non un'opinione.
        """
        return other.basis() @ self.basis().T

    def axis_and_angle_to(self, other: "FrameSpec") -> tuple[str, float]:
        """La stessa rotazione, detta come `fx:rotate` la chiede: asse e gradi.

        L'asse e' quello cartesiano piu' vicino, perche' `fx:rotate` accetta X,
        Y o Z: se la rotazione non e' attorno a uno di quei tre l'angolo
        riportato e' comunque l'angolo totale, e chi legge sa che la mossa
        suggerita e' un'approssimazione. Si sceglie in modo deterministico.
        """
        matrix = self.rotation_to(other)
        cosine = float(np.clip((np.trace(matrix) - 1.0) * 0.5, -1.0, 1.0))
        angle = float(np.degrees(np.arccos(cosine)))
        vector = np.array([matrix[2, 1] - matrix[1, 2],
                           matrix[0, 2] - matrix[2, 0],
                           matrix[1, 0] - matrix[0, 1]])
        norm = float(np.linalg.norm(vector))
        if norm < 1e-9:
            if angle < 1e-6:
                return "Y", 0.0
            # mezzo giro: l'asse e' l'autovettore di autovalore +1, e per una
            # matrice simmetrica lo si legge dalla diagonale senza decomporre
            diagonal = np.diag(matrix)
            index = int(np.argmax(diagonal))
            return "XYZ"[index], 180.0
        index = int(np.argmax(np.abs(vector)))
        sign = 1.0 if vector[index] >= 0 else -1.0
        return "XYZ"[index], angle * sign

    def move(self, other: "FrameSpec", *, scope: str = "") -> dict[str, Any]:
        """La richiesta di effetto che applicherebbe la conversione.

        Non la applica nessuno: e' il testo di una mossa, nella forma che il
        piano accetta, cosi' che chi legge la diagnostica possa copiarla.
        """
        axis, angle = self.axis_and_angle_to(other)
        return {"type": "fx:rotate", "scope": scope or "subtree",
                "params": {"axis": axis, "angle": round(angle, 3)}, "amount": 1.0}


EMPTY_FRAME = FrameSpec()


@dataclass(frozen=True)
class FrameComparison:
    """L'esito di un confronto, con il perche' e la mossa quando c'e'."""

    result: str
    parent: FrameSpec = EMPTY_FRAME
    child: FrameSpec = EMPTY_FRAME
    compared: tuple[str, ...] = ()        # gli assi che entrambi dichiarano
    disagreeing: tuple[str, ...] = ()     # quelli su cui non concordano

    @property
    def ok(self) -> bool:
        """Niente da dire: concordano, o non c'e' nulla da confrontare."""
        return self.result in (FRAME_COMPATIBLE, FRAME_UNDECLARED)

    @property
    def detectable(self) -> bool:
        """I metadata permettono di accorgersene."""
        return self.result in (FRAME_CONVERTIBLE, FRAME_AMBIGUOUS)

    def rotation(self) -> np.ndarray | None:
        if self.result != FRAME_CONVERTIBLE:
            return None
        return self.child.rotation_to(self.parent)

    def move(self, scope: str = "") -> dict[str, Any] | None:
        if self.result != FRAME_CONVERTIBLE:
            return None
        return self.child.move(self.parent, scope=scope)

    def describe(self) -> str:
        if self.result == FRAME_UNDECLARED:
            return "frame non confrontabile: %s / %s" % (
                self.parent.describe(), self.child.describe())
        if self.result == FRAME_COMPATIBLE:
            return "frame compatibili su %s" % ", ".join(self.compared)
        axes = ", ".join("%s: %s contro %s"
                         % (n, getattr(self.parent, n), getattr(self.child, n))
                         for n in self.disagreeing)
        if self.result == FRAME_CONVERTIBLE:
            axis, angle = self.child.axis_and_angle_to(self.parent)
            return ("frame convertibile (%s): %.1f gradi attorno a %s"
                    % (axes, angle, axis))
        return "frame ambiguo (%s): terna incompleta, rotazione indeterminata" % axes


def frame_from_dict(value: Any) -> FrameSpec:
    """Una terna da un dizionario di dati. Solleva `FrameError` se non si legge."""
    if value is None or value == {}:
        return EMPTY_FRAME
    if isinstance(value, FrameSpec):
        return value
    if not isinstance(value, dict):
        raise FrameError("frame deve essere un oggetto con growth_axis/front/up")
    unknown = set(value) - {"growth_axis", "front", "up"}
    if unknown:
        raise FrameError("frame: campi non supportati: %s" % ", ".join(sorted(unknown)))
    for name, axis in value.items():
        if not isinstance(axis, str):
            raise FrameError("frame.%s deve essere una stringa" % name)
    return FrameSpec(**value)


def frame_of(component: Any) -> FrameSpec:
    """Il frame di un componente, o quello vuoto. Mai `None` da gestire."""
    declared = getattr(component, "frame", None)
    if isinstance(declared, FrameSpec):
        return declared
    if isinstance(declared, dict):
        try:
            return frame_from_dict(declared)
        except FrameError:
            return EMPTY_FRAME
    return EMPTY_FRAME


def compare(parent: Any, child: Any) -> FrameComparison:
    """Due componenti (o due `FrameSpec`) si montano con lo stesso sopra?

    Guarda `up` e `front`, mai `growth_axis`: la ragione sta in testa al file.
    """
    a = parent if isinstance(parent, FrameSpec) else frame_of(parent)
    b = child if isinstance(child, FrameSpec) else frame_of(child)
    compared = tuple(n for n in SUBJECT_AXES if getattr(a, n) and getattr(b, n))
    if not compared:
        return FrameComparison(FRAME_UNDECLARED, parent=a, child=b)
    disagreeing = tuple(n for n in compared if getattr(a, n) != getattr(b, n))
    if not disagreeing:
        return FrameComparison(FRAME_COMPATIBLE, parent=a, child=b,
                               compared=compared)
    result = FRAME_CONVERTIBLE if (a.complete and b.complete) else FRAME_AMBIGUOUS
    return FrameComparison(result, parent=a, child=b, compared=compared,
                           disagreeing=disagreeing)
