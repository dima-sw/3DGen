"""Render dei banchi di prova: si guarda cosa esce, non solo se i test passano.

Ombreggiatura piatta, nessuna texture, nessun antialiasing sulle facce: e'
esattamente il modo in cui un modello low poly va guardato. Se una silhouette
non si legge cosi', non si legge nemmeno in un motore di gioco.

    python tools/render_benchmark.py [cartella]
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt        # noqa: E402
import numpy as np                     # noqa: E402
from mpl_toolkits.mplot3d.art3d import Poly3DCollection   # noqa: E402

RADICE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RADICE))

from app.build.assembler import build              # noqa: E402
from app.build.validate import validate            # noqa: E402
from app.core.capability import Requirement        # noqa: E402
from app.core.effect import apply_effects          # noqa: E402
from app.core.graph import CompositionGraph        # noqa: E402
from app.core.registry import load                 # noqa: E402
from app.core.resolver import resolve              # noqa: E402

# Tinte piatte per materiale: nel cartoon low poly il colore e' del materiale,
# non di una texture.
COLORI = {
    "skin": (0.93, 0.76, 0.62), "hair": (0.35, 0.22, 0.16),
    "eye": (0.12, 0.12, 0.14), "mouth": (0.62, 0.28, 0.28),
    "scale": (0.42, 0.62, 0.48), "metal": (0.66, 0.68, 0.72),
    "glass": (0.55, 0.72, 0.82), "masonry": (0.80, 0.74, 0.64),
    "tile": (0.58, 0.34, 0.28), "wood": (0.52, 0.36, 0.22),
    "rock": (0.45, 0.44, 0.42), "default": (0.70, 0.70, 0.72),
    "leaf": (0.32, 0.55, 0.30), "straw": (0.78, 0.66, 0.38),
    "feather": (0.72, 0.55, 0.34), "membrane": (0.62, 0.45, 0.52),
    "crystal": (0.48, 0.78, 0.86),
}

LUCE = np.array([0.4, 0.8, 0.45])
LUCE = LUCE / np.linalg.norm(LUCE)


def chiedi(capability: str = "", **kwargs) -> Requirement:
    return Requirement(capability=capability, **kwargs)


ALTO, BASSO = frozenset({"alto"}), frozenset({"basso"})


def figura(height: float = 1.8, detail_level: int = 3) -> CompositionGraph:
    g = CompositionGraph(detail_level=detail_level)
    g.set_root("corpo", "humanoid:body", height=height)
    g.add_child("torso", "humanoid:torso", "corpo", requirement=chiedi("core_mount"))
    g.add_child("collo", "humanoid:neck", "torso", requirement=chiedi("head_mount"),
                insert=0.3)
    g.add_child("testa", "humanoid:head", "collo", requirement=chiedi("head_mount"),
                insert=0.25)
    for nome, lato in (("braccio_l", "l"), ("braccio_r", "r")):
        g.add_child(nome, "humanoid:arm", "torso", insert=1.15,
                    requirement=chiedi("limb_mount", side=lato, tags=ALTO))
    for nome, lato in (("gamba_l", "l"), ("gamba_r", "r")):
        g.add_child(nome, "humanoid:leg", "torso", insert=0.9,
                    requirement=chiedi("limb_mount", side=lato, tags=BASSO))
    return g


def mostro() -> CompositionGraph:
    g = figura(1.8, detail_level=3)
    g.swap("testa", "creature:frog_head")
    g.swap("torso", "fish:fish_body")
    for gamba in ("gamba_l", "gamba_r"):
        g.swap(gamba, "weapon:sword", scale_mode="fit_replaced")
    g.attach("capelli", "humanoid:hair", "testa", requirement=chiedi("hair_mount"),
             scale_mode="socket", insert=0.45)
    g.attach("casco", "accessories:helmet", "capelli",
             requirement=chiedi("gear_mount"), scale_mode="socket", insert=0.3)
    g.attach("visiera", "accessories:visor", "casco",
             requirement=chiedi("visor_mount"), scale_mode="socket")
    g.attach("piercing", "accessories:piercing", "testa",
             requirement=chiedi("anchor"), scale_mode="socket")
    g.attach("ala", "fish:fin", "torso", scale_mode="socket",
             requirement=chiedi("gear_mount"))
    return g


def casa_su_pianeta(raggio: float = 12.0) -> CompositionGraph:
    g = CompositionGraph(detail_level=3)
    g.set_root("casa", "architecture:house", width=6.0, height=4.5, depth=5.0)
    g.add_child("pianeta", "space:planet", "casa", requirement=chiedi("surface"),
                radius=raggio, insert=0.0)
    return g


BANCHI = {
    "1-umanoide": ("Umanoide, livello 3", figura),
    "2-casa-pianeta": ("Casa su un pianeta", casa_su_pianeta),
    "3-mostro": ("Rana + pesce + spade + casco", mostro),
}


def disegna(ax, risultato, titolo: str) -> None:
    """Ombreggiatura piatta: una tinta per faccia, come la vede un motore."""
    facce, colori = [], []
    for costruito in risultato.geometry():
        mesh = costruito.mesh
        base = np.array(COLORI.get(costruito.material, COLORI["default"]))
        # il modello ha +Y in alto, matplotlib vuole +Z: si scambia qui, nella
        # vista, senza toccare il modello
        vertici = np.asarray(mesh.vertices)[:, [0, 2, 1]]
        triangoli = vertici[np.asarray(mesh.faces)]
        normali = np.asarray(mesh.face_normals)[:, [0, 2, 1]]
        luce = np.clip(normali @ LUCE, 0.0, 1.0)
        for triangolo, intensita in zip(triangoli, luce):
            facce.append(triangolo)
            colori.append(np.clip(base * (0.42 + 0.58 * intensita), 0, 1))

    collezione = Poly3DCollection(facce, facecolors=colori, edgecolors=(0, 0, 0, 0.22),
                                  linewidths=0.25)
    ax.add_collection3d(collezione)

    limiti = risultato.bounds[:, [0, 2, 1]]
    centro = limiti.mean(axis=0)
    raggio = float(np.max(limiti[1] - limiti[0])) * 0.52
    for imposta, valore in ((ax.set_xlim, centro[0]), (ax.set_ylim, centro[1]),
                            (ax.set_zlim, centro[2])):
        imposta(valore - raggio, valore + raggio)
    if titolo:
        ax.set_title(titolo, fontsize=9)
    ax.set_axis_off()
    ax.set_box_aspect((1, 1, 1))


def esporta(cartella: Path) -> list[Path]:
    cartella.mkdir(parents=True, exist_ok=True)
    registry = load([RADICE / "app" / "plugins"])
    registry.freeze()
    stile = registry.style("low_poly")
    scritti = []

    for nome, (titolo, piano) in BANCHI.items():
        grafo = piano()
        risultato = build(apply_effects(resolve(grafo, registry), registry))
        validate(risultato, style=stile)

        figura_mpl = plt.figure(figsize=(9.5, 4.4), dpi=130)
        viste = (("davanti", 8, -88), ("di lato", 8, -8), ("tre quarti", 26, -58))
        for indice, (nome_vista, elev, azim) in enumerate(viste):
            ax = figura_mpl.add_subplot(1, 3, indice + 1, projection="3d")
            disegna(ax, risultato, nome_vista)
            ax.view_init(elev=elev, azim=azim)
        figura_mpl.suptitle("%s  —  %d triangoli, %d pezzi"
                            % (titolo, risultato.triangles,
                               len(risultato.geometry())), fontsize=11)
        figura_mpl.tight_layout()

        file = cartella / ("%s.png" % nome)
        figura_mpl.savefig(file, facecolor="white")
        plt.close(figura_mpl)
        scritti.append(file)
        print("%-16s %5d triangoli  %2d pezzi  %s"
              % (nome, risultato.triangles, len(risultato.geometry()),
                 "ok" if risultato.report.ok else "CON ERRORI"))
    return scritti


if __name__ == "__main__":
    destinazione = Path(sys.argv[1]) if len(sys.argv) > 1 \
        else RADICE / "output" / "benchmark"
    for file in esporta(destinazione):
        print("scritto", file)
