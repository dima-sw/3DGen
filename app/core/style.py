"""Lo stile del prodotto, in un posto solo.

3DGen fa **una cosa sola**: cartoon low-poly. Non e' una delle quattro opzioni,
e' il linguaggio geometrico del software. Avere quattro stili che si facevano
concorrenza voleva dire quattro tarature da tenere allineate, quattro rami in
ogni generatore, e nessuno dei quattro fatto davvero bene.

Qui c'e' tutto cio' che quella scelta comporta, raccolto: quanti triangoli,
quanto fitta la griglia, quanto arrotondare, quanto si puo' esagerare, quali
proporzioni sono ammesse. Chi deve sapere "come deve venire" chiede qui, e non
tiene numeri propri sparsi nel codice.

## Densita' non e' stile

Resta un solo grado di liberta' numerico, `density`: quanto fitta viene la
superficie. Serve ai livelli di dettaglio (un LOD lontano e' lo stesso oggetto
piu' rado) e all'hardware modesto. **Non cambia lo stile**: un modello a
densita' 0,5 e' lo stesso modello, con meno triangoli. Non diventa "blocky".

## Cartoon vuol dire esagerare

Un umanoide cartoon ha la testa grande, le mani grandi e le gambe corte. Non e'
un errore di proporzione da correggere: e' il mestiere. Per questo gli
intervalli che i validatori usano stanno **qui** e non dentro il validatore:
altrimenti i controlli anatomici combatterebbero la direzione artistica e la
riporterebbero verso il realismo, cioe' farebbero esattamente il danno che
devono impedire.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.core.logging_setup import get

log = get("core.style")


@dataclass(frozen=True)
class Style:
    """Tutto cio' che decide come viene fatto un modello."""

    name: str

    # --- superfici implicite (SDF -> marching cubes -> decimazione) ------- #
    resolution: int              # celle sul lato lungo, a densita' 1
    smoothing: int               # iterazioni di Taubin: poche, il low poly le odia
    triangle_budget: int         # triangoli del corpo fuso, a densita' 1

    # --- solidi a primitive (template parametrici) ----------------------- #
    sections: int                # segmenti dei solidi di rivoluzione
    subdivisions: int            # suddivisioni delle icosfere
    rounding: float              # moltiplicatore degli arrotondamenti

    # --- composizione ---------------------------------------------------- #
    blend_ratio: float           # fusione max, in frazione dello spessore della parte

    # --- proporzioni ammesse, per tag della parte ------------------------ #
    # Sono i limiti che i validatori usano. Larghi: devono fermare l'assurdo,
    # non lo stile.
    proportions: dict[str, tuple[float, float]] = field(default_factory=dict)

    # --- esagerazione cartoon, per ruolo --------------------------------- #
    exaggeration: dict[str, float] = field(default_factory=dict)

    # --- materiali -------------------------------------------------------- #
    flat_materials: bool = True  # tinte piatte: le texture non servono al cartoon

    def emphasis(self, ruolo: str) -> float:
        """Quanto ingrandire (o rimpicciolire) un ruolo, per lo stile."""
        return float(self.exaggeration.get(ruolo, 1.0))


# --------------------------------------------------------------------------- #
# L'unico stile
# --------------------------------------------------------------------------- #
CARTOON = Style(
    name="cartoon low-poly",
    resolution=56,
    smoothing=1,
    triangle_budget=3200,
    sections=7,
    subdivisions=1,
    rounding=0.70,
    blend_ratio=0.30,
    proportions={
        # (minimo, massimo) rispetto al riferimento: il corpo per gli arti,
        # l'arto per le estremita'. Piu' larghi dell'anatomia, di proposito.
        "hand":      (0.20, 1.30),
        "foot":      (0.25, 1.60),
        "extremity": (0.20, 1.60),
        "eye":       (0.02, 0.45),
        "horn":      (0.03, 0.80),
        "fin":       (0.05, 1.40),
        "wing":      (0.18, 2.60),
        "tail":      (0.10, 2.20),
        "tentacle":  (0.12, 2.20),
        "arm":       (0.08, 1.40),
        "leg":       (0.08, 1.30),
        "neck":      (0.03, 0.60),
        "head":      (0.10, 1.15),
        "limb":      (0.05, 1.60),
    },
    exaggeration={
        # Il volto e le estremita' crescono, gli arti si accorciano: e' la
        # firma del cartoon, ed e' una scelta, non una svista.
        "head": 1.28,
        "eye": 1.45,
        "hand": 1.30,
        "foot": 1.25,
        "limb_length": 0.90,
        "torso_width": 1.08,
    },
)

_CURRENT: Style = CARTOON


def current() -> Style:
    """Lo stile in uso. Oggi ce n'e' uno; la funzione resta perche' i plugin
    porteranno **etichette** di stile, che sono un'altra cosa."""
    return _CURRENT


# --------------------------------------------------------------------------- #
# Densita'
# --------------------------------------------------------------------------- #
# Limiti di sicurezza: sotto il primo non si riconosce piu' niente, sopra il
# secondo si paga soltanto.
DENSITY_LIMITS = (0.30, 2.40)


def clamp_density(value: float) -> float:
    basso, alto = DENSITY_LIMITS
    try:
        return float(min(max(float(value), basso), alto))
    except (TypeError, ValueError):
        return 1.0


def resolution_for(density: float = 1.0) -> int:
    """Celle della griglia sul lato lungo, per questa densita'."""
    return int(max(round(current().resolution * clamp_density(density)), 16))


def budget_for(density: float = 1.0) -> int:
    """Triangoli concessi al corpo.

    La densita' entra **al quadrato** perche' i triangoli stanno su una
    superficie: dimezzare la risoluzione lineare ne toglie tre quarti.
    """
    return int(max(current().triangle_budget * clamp_density(density) ** 2, 200))


def sections_for(density: float = 1.0, base: int | None = None) -> int:
    """Segmenti di un solido di rivoluzione, per i template a primitive."""
    riferimento = current().sections if base is None else base
    return int(max(round(riferimento * clamp_density(density)), 4))


def smoothing_for(density: float = 1.0) -> int:
    """Iterazioni di lisciatura. Poche sempre: il low poly vive di spigoli."""
    return int(max(min(round(current().smoothing * clamp_density(density)), 3), 0))


def subdivisions_for(density: float = 1.0) -> int:
    return int(max(min(round(current().subdivisions * clamp_density(density)), 3), 0))


def rounding_for(radius: float, density: float = 1.0) -> float:
    """Arrotondamento di uno spigolo. Nel cartoon si smussa, non si sfuma."""
    return float(radius) * current().rounding
