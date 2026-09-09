"""Render degli scenari: quello che esce da una **frase**.

I banchi (`render_benchmark.py`) partono da un piano scritto a mano e
verificano la geometria. Qui si parte da una frase e si passa dalla porta
unica, `Session.generate`: planner, registry, resolver, effetti, builder. Se
qualcosa nella catena si rompe, si vede in un'immagine invece che in un
`assert`.

Il planner e' quello finto, deterministico: due esecuzioni danno lo stesso
disegno, e non serve nessuna chiave di nessuna API per guardare cosa fa il
sistema.

    python tools/render_scenari.py [cartella]
"""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt        # noqa: E402

RADICE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RADICE))

from app.ai.provider import OfflineProvider              # noqa: E402
from app.core.planner.planner import MockPlanner         # noqa: E402
from app.core.session import Session                     # noqa: E402
from tools.render_benchmark import disegna               # noqa: E402

sys.path.insert(0, str(RADICE / "tests"))
from test_scenari import COPIONI                         # noqa: E402

SCENARI = {
    "1-persona-rana": (
        "Persona con testa di rana e gambe di spada, alta e magra",
        "una persona con la testa di rana e le gambe di spada, molto alta e magra"),
    "2-casa-pianeta": (
        "Casa con un pianeta enorme sopra",
        "una casa con un pianeta enorme sopra"),
    "3-albero-nido-uccello": (
        "Albero con un nido e un uccello",
        "un albero con un nido e un uccello sopra"),
    "4-robot-misto": (
        "Testa di drago, corpo di pesce, ali e cristalli",
        "un robot con testa di drago, corpo di pesce, ali e cristalli luminosi"),
    "5-traguardo-in-posa": (
        "Lo stesso, con le braccia lungo il corpo (effetto `final`)",
        "persona con testa di rana, corpo di pesce, gambe di spada, capelli con "
        "casco, piercing al naso, molto alta e magra, con le braccia lungo il corpo"),
    "5-traguardo": (
        "Il traguardo: cinque vocabolari in un modello",
        "persona con testa di rana, corpo di pesce, gambe di spada, capelli con "
        "casco, piercing al naso, molto alta e magra"),
}


def esporta(cartella: Path) -> list[Path]:
    cartella.mkdir(parents=True, exist_ok=True)
    sessione = Session(provider=OfflineProvider(),
                       planner=MockPlanner(scripts=COPIONI))
    scritti = []

    for nome, (titolo, prompt) in SCENARI.items():
        risultato = sessione.generate(prompt)
        if risultato.build is None or not risultato.build.meshes():
            print("%-22s NIENTE GEOMETRIA: %s" % (nome, risultato.report.describe()))
            continue

        figura = plt.figure(figsize=(9.5, 4.6), dpi=130)
        for indice, (vista, elev, azim) in enumerate(
                (("davanti", 8, -88), ("di lato", 8, -8), ("tre quarti", 26, -58))):
            ax = figura.add_subplot(1, 3, indice + 1, projection="3d")
            disegna(ax, risultato.build, vista)
            ax.view_init(elev=elev, azim=azim)
        didascalia = "\n".join(textwrap.wrap("«%s»" % prompt, 88))
        figura.suptitle("%s\n%s\n%d triangoli, %d pezzi, planner %s"
                        % (titolo, didascalia, risultato.triangles,
                           len(risultato.build.geometry()), risultato.planner),
                        fontsize=9)
        figura.tight_layout(rect=(0, 0, 1, 0.90))

        file = cartella / ("%s.png" % nome)
        figura.savefig(file, facecolor="white")
        plt.close(figura)
        scritti.append(file)
        gravi = [d.code for d in risultato.diagnostics if d.fatal]
        print("%-22s %5d triangoli  %2d pezzi  %s"
              % (nome, risultato.triangles, len(risultato.build.geometry()),
                 "ok" if not gravi else "ERRORI: %s" % ", ".join(gravi)))
    return scritti


if __name__ == "__main__":
    destinazione = Path(sys.argv[1]) if len(sys.argv) > 1 \
        else RADICE / "output" / "scenari"
    for file in esporta(destinazione):
        print("scritto", file)
