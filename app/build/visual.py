"""Misure deterministiche sull'aspetto di un modello.

La validazione semantica dice se le parti richieste ci sono; non dice se il
risultato si guarda. Un modello puo' avere corpo, testa, quattro zampe e una
coda ed essere comunque una patata con degli stuzzicadenti.

Qui ci sono le misure che distinguono le due cose, e sono **numeri calcolati,
non giudizi**: nessun modello di linguaggio viene interpellato per decidere se
una cosa e' bella. Si misurano fatti:

- quanto e' **articolata la silhouette** rispetto al suo guscio convesso: una
  creatura con appendici distinte riempie poco del proprio inviluppo, un blob lo
  riempie quasi tutto;
- quante **appendici si vedono davvero** dal di fuori, non quante esistono nel
  piano;
- se le proporzioni fra le parti stanno in un intervallo credibile;
- quanti triangoli servono, perche' "low poly" e' un requisito e non un caso.

Le silhouette si ricavano proiettando la mesh, non renderizzandola: niente
contesto grafico, niente driver, stesso risultato su qualunque macchina e nei
test automatici.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from app.core.logging_setup import get

log = get("build.visual")

# Griglia usata per le silhouette. Bassa apposta: si misura la sagoma, non il
# dettaglio, e una griglia fine renderebbe la misura sensibile al rumore.
GRID = 96


@dataclass
class VisualReport:
    """Che cosa si vede di questo modello, in numeri."""

    triangles: int = 0
    parts: int = 0
    solidity: dict[str, float] = field(default_factory=dict)   # per vista
    aspect: tuple[float, float, float] = (1.0, 1.0, 1.0)
    visible_parts: int = 0
    hidden_parts: list[str] = field(default_factory=list)
    largest_share: float = 0.0
    notes: list[str] = field(default_factory=list)

    @property
    def blobbiness(self) -> float:
        """Quanto il modello riempie il proprio guscio convesso, mediato sulle viste.

        Uno significa "e' il suo stesso inviluppo", cioe' una patata. Sotto lo
        0,75 c'e' qualcosa che sporge in modo riconoscibile.
        """
        return float(np.mean(list(self.solidity.values()))) if self.solidity else 1.0

    def describe(self) -> str:
        return ("%d triangoli, %d parti (%d visibili), riempimento %.2f, "
                "parte maggiore %.0f%%"
                % (self.triangles, self.parts, self.visible_parts,
                   self.blobbiness, self.largest_share * 100))


# --------------------------------------------------------------------------- #
# Silhouette
# --------------------------------------------------------------------------- #
VIEWS = {"front": (0, 1), "side": (2, 1), "top": (0, 2)}


def silhouette(points: np.ndarray, axes: tuple[int, int], grid: int = GRID,
               bounds: tuple[np.ndarray, np.ndarray] | None = None) -> np.ndarray:
    """Maschera della proiezione di una nuvola di punti su due assi.

    E' una proiezione, non un rendering: nessun contesto grafico, nessun driver,
    e lo stesso risultato su qualunque macchina — che e' cio' che serve per
    metterla in un test.
    """
    if len(points) == 0:
        return np.zeros((grid, grid), dtype=bool)
    piano = points[:, list(axes)]
    lo = piano.min(axis=0) if bounds is None else np.asarray(bounds[0])[list(axes)]
    hi = piano.max(axis=0) if bounds is None else np.asarray(bounds[1])[list(axes)]
    span = np.maximum(hi - lo, 1e-9)
    indici = np.clip(((piano - lo) / span * (grid - 1)).astype(int), 0, grid - 1)
    mask = np.zeros((grid, grid), dtype=bool)
    mask[indici[:, 0], indici[:, 1]] = True
    return mask


def _dense_points(mesh, target: int = GRID * GRID * 20) -> np.ndarray:
    """Punti sulla superficie, tanti da riempire la sagoma senza buchi.

    Campionare un numero fisso di punti per faccia non basta: un cubo ha dodici
    facce, e con tre punti ciascuna la sua sagoma risultava vuota. I punti si
    distribuiscono **in proporzione all'area**, cosi' una faccia grande ne
    riceve tanti quanti gliene servono per coprire la propria proiezione.
    """
    vertici = np.asarray(mesh.vertices, dtype=float)
    facce = np.asarray(mesh.faces)
    if len(facce) == 0:
        return vertici

    triangoli = vertici[facce]
    aree = np.linalg.norm(np.cross(triangoli[:, 1] - triangoli[:, 0],
                                   triangoli[:, 2] - triangoli[:, 0]), axis=1) * 0.5
    totale = float(aree.sum())
    if totale <= 0:
        return vertici

    rng = np.random.default_rng(0)
    scelte = rng.choice(len(facce), size=int(target), p=aree / totale)
    # coordinate baricentriche uniformi sul triangolo
    u = rng.random(int(target))
    v = rng.random(int(target))
    fuori = u + v > 1.0
    u[fuori], v[fuori] = 1.0 - u[fuori], 1.0 - v[fuori]
    scelti = triangoli[scelte]
    campioni = (scelti[:, 0] + u[:, None] * (scelti[:, 1] - scelti[:, 0])
                + v[:, None] * (scelti[:, 2] - scelti[:, 0]))
    return np.vstack([vertici, campioni])


def _solidity(mask: np.ndarray) -> float:
    """Frazione del guscio convesso della sagoma che la sagoma occupa davvero."""
    accesi = np.argwhere(mask)
    if len(accesi) < 3:
        return 1.0
    try:
        from scipy.spatial import ConvexHull, Delaunay

        scafo = ConvexHull(accesi.astype(float))
        triangolazione = Delaunay(accesi[scafo.vertices].astype(float))
    except Exception:
        return 1.0
    righe, colonne = np.mgrid[0:mask.shape[0], 0:mask.shape[1]]
    tutti = np.stack([righe.ravel(), colonne.ravel()], axis=1).astype(float)
    dentro = triangolazione.find_simplex(tutti) >= 0
    area_scafo = int(dentro.sum())
    return float(mask.sum() / area_scafo) if area_scafo else 1.0


# --------------------------------------------------------------------------- #
# Analisi
# --------------------------------------------------------------------------- #
def analyse(scene, min_share: float = 0.004) -> VisualReport:
    """Misura una scena. `min_share` e' quanto deve pesare una parte per dirsi visibile."""
    nodi = [n for n in scene.nodes if len(n.mesh.faces)]
    report = VisualReport(triangles=scene.triangle_count, parts=len(nodi))
    if not nodi:
        report.notes.append("scena vuota")
        return report

    fusa = scene.to_trimesh_scene(textured=False).to_geometry()
    punti = _dense_points(fusa)
    lo, hi = fusa.bounds
    for nome, assi in VIEWS.items():
        report.solidity[nome] = _solidity(silhouette(punti, assi, bounds=(lo, hi)))

    estensione = np.maximum(hi - lo, 1e-9)
    report.aspect = tuple(float(v) for v in estensione / estensione.max())

    # Quanto pesa ogni parte sulla superficie totale: una parte che vale meno
    # del mezzo percento c'e' nel piano ma non nel modello.
    aree = {}
    for nodo in nodi:
        try:
            aree[nodo.id] = float(nodo.mesh.area)
        except Exception:
            aree[nodo.id] = 0.0
    totale = sum(aree.values()) or 1.0
    quote = {k: v / totale for k, v in aree.items()}
    report.visible_parts = sum(1 for q in quote.values() if q >= min_share)
    report.hidden_parts = sorted(k for k, q in quote.items() if q < min_share)
    report.largest_share = max(quote.values())
    log.info("aspetto: %s", report.describe())
    return report


# --------------------------------------------------------------------------- #
# Criteri
# --------------------------------------------------------------------------- #
@dataclass
class VisualCriteria:
    """Cosa si pretende dall'aspetto di una categoria di modello.

    Sono soglie larghe: servono a intercettare la regressione — il giorno in cui
    una modifica riporta il pesce a essere un panino — non a imporre uno stile.
    """

    max_blobbiness: float = 0.86
    min_visible_parts: int = 3
    max_largest_share: float = 0.92
    triangle_range: tuple[int, int] = (250, 30_000)
    min_elongation: float = 1.0

    def check(self, report: VisualReport) -> list[str]:
        """Elenco dei difetti trovati. Vuoto significa che va bene."""
        difetti: list[str] = []
        if report.blobbiness > self.max_blobbiness:
            difetti.append("riempie il %.0f%% del proprio inviluppo: e' un blob"
                           % (report.blobbiness * 100))
        if report.visible_parts < self.min_visible_parts:
            difetti.append("solo %d parti si vedono davvero (ne servono %d)"
                           % (report.visible_parts, self.min_visible_parts))
        if report.largest_share > self.max_largest_share:
            difetti.append("una parte sola vale il %.0f%% della superficie"
                           % (report.largest_share * 100))
        basso, alto = self.triangle_range
        if not basso <= report.triangles <= alto:
            difetti.append("%d triangoli, fuori dall'intervallo %d-%d"
                           % (report.triangles, basso, alto))
        allungamento = 1.0 / max(min(report.aspect), 1e-6)
        if allungamento < self.min_elongation:
            difetti.append("proporzioni troppo cubiche (%.2f)" % allungamento)
        return difetti


def report_for(scene, criteria: VisualCriteria | None = None) -> tuple[VisualReport, list[str]]:
    report = analyse(scene)
    return report, (criteria or VisualCriteria()).check(report)
