"""Render dei casi d'oro: quello che esce da una **frase**.

I banchi (`render_benchmark.py`) partono da un piano scritto a mano e
verificano la geometria. Qui si parte da una frase e si passa dalla porta
unica, `Session.generate`: planner, registry, resolver, effetti, builder. Se
qualcosa nella catena si rompe, si vede in un'immagine invece che in un
`assert`.

Sono gli stessi cinque casi di `tests/test_golden.py`, letti da li': un render
che mostra qualcosa di diverso da cio' che i test verificano non servirebbe a
niente.

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
sys.path.insert(0, str(RADICE / "tests"))

from app.ai.provider import OfflineProvider              # noqa: E402
from app.core.planner.planner import MockPlanner         # noqa: E402
from app.core.session import Session                     # noqa: E402
from tools.render_benchmark import disegna               # noqa: E402

from test_golden import CASI, CASO_COMPLETO, PROMPT_COMPLETO   # noqa: E402
from test_scenari import COPIONI                         # noqa: E402

TITOLI = {
    "A": "Persona con testa di rana e gambe di spada",
    "B": "Casa con un pianeta enorme sopra",
    "C": "Albero con un nido e un uccello",
    "D": "Testa di drago, corpo di pesce, ali e cristalli",
    "E": "Il caso completo: braccia multiple, accessori annidati, due effetti",
}


def esporta(cartella: Path) -> list[Path]:
    cartella.mkdir(parents=True, exist_ok=True)
    copioni = dict(COPIONI)
    copioni[PROMPT_COMPLETO] = CASO_COMPLETO
    sessione = Session(provider=OfflineProvider(),
                       planner=MockPlanner(scripts=copioni))
    scritti = []

    for nome in sorted(CASI):
        prompt = CASI[nome][0]
        risultato = sessione.generate(prompt, remember=False)
        if risultato.build is None or not risultato.build.meshes():
            print("%-3s NIENTE GEOMETRIA: %s" % (nome, risultato.report.describe()))
            continue

        figura = plt.figure(figsize=(9.5, 4.6), dpi=130)
        for indice, (vista, elev, azim) in enumerate(
                (("davanti", 8, -88), ("di lato", 8, -8), ("tre quarti", 26, -58))):
            ax = figura.add_subplot(1, 3, indice + 1, projection="3d")
            disegna(ax, risultato.build, vista)
            ax.view_init(elev=elev, azim=azim)
        didascalia = "\n".join(textwrap.wrap("«%s»" % prompt, 88))
        figura.suptitle("%s. %s\n%s\n%d triangoli, %d pezzi, planner %s"
                        % (nome, TITOLI[nome], didascalia, risultato.triangles,
                           len(risultato.build.geometry()), risultato.planner),
                        fontsize=9)
        figura.tight_layout(rect=(0, 0, 1, 0.90))

        file = cartella / ("%s.png" % nome.lower())
        figura.savefig(file, facecolor="white")
        plt.close(figura)
        scritti.append(file)
        gravi = [d.code for d in risultato.diagnostics if d.fatal]
        print("%-3s %5d triangoli  %2d pezzi  %s"
              % (nome, risultato.triangles, len(risultato.build.geometry()),
                 "ok" if not gravi else "ERRORI: %s" % ", ".join(gravi)))
    return scritti


if __name__ == "__main__":
    destinazione = Path(sys.argv[1]) if len(sys.argv) > 1 \
        else RADICE / "output" / "scenari"
    for file in esporta(destinazione):
        print("scritto", file)
