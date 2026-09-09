"""Riconoscere un oggetto dalla sua sagoma, confrontandola con il catalogo.

Serve a una domanda sola: **senza modello vision, come si fa a sapere che nella
foto c'e' un'automobile?** La risposta non e' un classificatore addestrato — non
ce n'e' uno gratis e locale — ma un confronto con cio' che sappiamo gia'
costruire. Ogni template procedurale viene generato ai valori predefiniti,
proiettato di lato e ridotto a un **profilo di larghezze**: quanto e' largo
l'oggetto a ventiquattro altezze diverse.

Un'auto e' larga in basso e stretta nell'abitacolo; un albero e' l'opposto; un
tavolo e' largo sopra e sottile sotto. Confrontando il profilo della foto con
quelli del catalogo si sceglie il candidato piu' vicino.

E' un recupero per forma, non un riconoscimento semantico: sa dire "somiglia a
un veicolo", non "e' una Fiat Panda". Quando la somiglianza non e' netta lo
dichiara e non decide, perche' una scelta sbagliata sarebbe peggio di nessuna
scelta: il testo dell'utente e il modello vision hanno sempre la precedenza.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.core.logging_setup import get

log = get("ai.shape")

BANDS = 24              # altezze a cui si misura la larghezza
COLUMNS = 96            # risoluzione orizzontale della rasterizzazione
# Sotto questo scarto fra il primo e il secondo candidato la scelta non e'
# netta: meglio non decidere che decidere male.
MARGIN = 0.06


@dataclass
class ShapeMatch:
    template: str
    distance: float
    confident: bool
    runner_up: str = ""

    def describe(self) -> str:
        if not self.confident:
            return "nessuna forma riconosciuta con sicurezza (%s?)" % self.template
        return "somiglia a '%s' (scarto %.3f)" % (self.template, self.distance)


# --------------------------------------------------------------------------- #
# Profili
# --------------------------------------------------------------------------- #
def profile_from_mask(mask: np.ndarray, bands: int = BANDS) -> np.ndarray:
    """Larghezze relative a `bands` altezze, dal basso verso l'alto.

    Normalizzate sulla larghezza massima: resta la forma, non la scala.
    """
    rows = np.flatnonzero(mask.any(axis=1))
    cols = np.flatnonzero(mask.any(axis=0))
    if len(rows) == 0 or len(cols) == 0:
        return np.zeros(bands)
    box = mask[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1]
    widths = box.sum(axis=1).astype(float)
    # dall'alto verso il basso nell'immagine: si rovescia, il basso viene prima
    widths = widths[::-1]
    bordi = np.linspace(0, len(widths), bands + 1)
    fasce = np.array([widths[int(bordi[i]):max(int(bordi[i + 1]),
                                               int(bordi[i]) + 1)].mean()
                      for i in range(bands)])
    massimo = fasce.max()
    return fasce / massimo if massimo > 0 else fasce


def rasterize_side(mesh, bands: int = BANDS, columns: int = COLUMNS) -> np.ndarray:
    """Sagoma laterale di una mesh, senza rasterizzatori esterni.

    Si proietta lungo l'asse orizzontale piu' corto — cioe' si guarda l'oggetto
    dal suo lato lungo, come farebbe chi lo fotografa — e si riempie una
    scanline per fascia: ogni triangolo tagliato da una riga contribuisce un
    intervallo, e l'unione degli intervalli e' la larghezza a quell'altezza.
    """
    vertices = np.asarray(mesh.vertices, dtype=float)
    faces = np.asarray(mesh.faces, dtype=int)
    if len(faces) == 0:
        return np.zeros((bands, columns), dtype=bool)

    estensione = vertices.max(axis=0) - vertices.min(axis=0)
    orizzontali = [0, 2]                       # Y e' l'asse verticale
    lungo = orizzontali[int(np.argmax(estensione[orizzontali]))]
    piatto = np.stack([vertices[:, lungo], vertices[:, 1]], axis=1)

    lo, hi = piatto.min(axis=0), piatto.max(axis=0)
    span = np.maximum(hi - lo, 1e-9)
    normalizzato = (piatto - lo) / span
    triangoli = normalizzato[faces]            # (n, 3, 2)

    mask = np.zeros((bands, columns), dtype=bool)
    for indice in range(bands):
        y = (indice + 0.5) / bands
        differenze = np.zeros(columns + 1, dtype=np.int32)
        inizio, fine = _crossings(triangoli, y)
        if len(inizio) == 0:
            continue
        a = np.clip((inizio * columns).astype(int), 0, columns - 1)
        b = np.clip((fine * columns).astype(int) + 1, 1, columns)
        np.add.at(differenze, a, 1)
        np.add.at(differenze, b, -1)
        mask[bands - 1 - indice] = np.cumsum(differenze[:-1]) > 0
    return mask


def _crossings(triangoli: np.ndarray, y: float) -> tuple[np.ndarray, np.ndarray]:
    """Intervallo [x_min, x_max] in cui ogni triangolo interseca la retta y."""
    sopra = triangoli[:, :, 1] >= y
    # un triangolo interessa la riga solo se ha vertici da entrambe le parti
    tocca = sopra.any(axis=1) & (~sopra).any(axis=1)
    if not tocca.any():
        return np.empty(0), np.empty(0)
    t = triangoli[tocca]

    xs = []
    for i, j in ((0, 1), (1, 2), (2, 0)):
        p, q = t[:, i], t[:, j]
        dy = q[:, 1] - p[:, 1]
        # dy == 0: lato orizzontale, non produce un attraversamento utile
        sicuro = np.where(np.abs(dy) < 1e-12, 1.0, dy)
        alfa = (y - p[:, 1]) / sicuro
        valido = (np.abs(dy) >= 1e-12) & (alfa >= 0.0) & (alfa <= 1.0)
        x = p[:, 0] + alfa * (q[:, 0] - p[:, 0])
        xs.append(np.where(valido, x, np.nan))

    incroci = np.stack(xs, axis=1)
    with np.errstate(invalid="ignore"):
        minimi = np.nanmin(incroci, axis=1)
        massimi = np.nanmax(incroci, axis=1)
    buoni = ~np.isnan(minimi)
    return minimi[buoni], massimi[buoni]


# --------------------------------------------------------------------------- #
# Catalogo
# --------------------------------------------------------------------------- #
_CATALOG: dict[str, tuple[np.ndarray, float]] | None = None


def catalog() -> dict[str, tuple[np.ndarray, float]]:
    """Profilo e proporzione di ogni template, ai valori predefiniti.

    Costruire tutti i template costa due decimi di secondo in tutto, quindi si
    calcola una volta per processo e si tiene in memoria: nessun file di cache
    da invalidare quando un template cambia.
    """
    global _CATALOG
    if _CATALOG is not None:
        return _CATALOG

    from app.build.builder import build_scene
    from app.core.spec import GenerationPlan
    from app.geometry.templates import TEMPLATES, load_all

    load_all()
    _CATALOG = {}
    for name, template in TEMPLATES.items():
        if name == "primitive":
            continue                    # un cubo somiglia a tutto: non aiuta
        try:
            scene = build_scene(GenerationPlan(template=name,
                                               params=template.defaults()))
            mesh = scene.to_trimesh_scene(textured=False).to_geometry()
            mask = rasterize_side(mesh)
            lo, hi = mesh.bounds
            dimensioni = hi - lo
            orizzontale = float(max(dimensioni[0], dimensioni[2]))
            aspetto = orizzontale / max(float(dimensioni[1]), 1e-6)
            _CATALOG[name] = (profile_from_mask(mask), aspetto)
        except Exception as exc:        # un template rotto non blocca gli altri
            log.warning("profilo di '%s' non calcolato: %s", name, exc)
    return _CATALOG


# Quanto pesa la proporzione rispetto al profilo. Tarato su sette casi noti
# (foto di auto, auto sintetica, albero, tavolo, sedia, umanoide, casa): fra
# 0.25 e 0.70 li classifica tutti giusti, e il margine sul caso piu' debole
# cresce da 0.06 a 0.20. Si prende il mezzo dell'intervallo verificato — piu'
# in alto la misura degenererebbe nel classificare per sole proporzioni.
ASPECT_WEIGHT = 0.45


def distance(profilo: np.ndarray, aspetto: float,
             riferimento: np.ndarray, aspetto_riferimento: float) -> float:
    """Quanto due sagome sono diverse: forma piu' proporzione.

    La proporzione entra in scala logaritmica, cosi' "il doppio piu' lungo" pesa
    quanto "la meta' piu' corto". Sui dati veri si e' rivelata piu' capace di
    distinguere del profilo stesso: un'auto e un masso possono avere profili
    simili, proporzioni no.
    """
    forma = float(np.abs(profilo - riferimento).mean())
    proporzione = abs(np.log(max(aspetto, 1e-6) / max(aspetto_riferimento, 1e-6)))
    return forma + ASPECT_WEIGHT * min(proporzione, 2.0)


def match(mask: np.ndarray, aspect: float) -> ShapeMatch | None:
    """Il template del catalogo la cui sagoma somiglia di piu' a questa."""
    profilo = profile_from_mask(mask)
    voci = catalog()
    if not voci:
        return None

    classifica = sorted(
        ((distance(p, a, profilo, aspect), nome) for nome, (p, a) in voci.items()))
    migliore, nome = classifica[0]
    secondo = classifica[1][1] if len(classifica) > 1 else ""
    scarto = (classifica[1][0] - migliore) if len(classifica) > 1 else 1.0
    esito = ShapeMatch(template=nome, distance=migliore,
                       confident=scarto >= MARGIN, runner_up=secondo)
    log.info("sagoma: %s (secondo '%s', scarto %.3f)", esito.describe(), secondo, scarto)
    return esito
