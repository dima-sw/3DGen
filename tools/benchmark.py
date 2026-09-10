"""Quanto costa una generazione, passo per passo.

    python tools/benchmark.py [ripetizioni]

Non e' un profiler e non serve a ottimizzare: serve ad avere una **linea di
partenza**. Senza un numero scritto da qualche parte, "e' diventato lento" e'
un'impressione; con questo, e' una differenza.

Si misurano i cinque passi separatamente, perche' quando uno peggiora bisogna
sapere quale. Il planner e' quello finto: misurare la rete vorrebbe dire
misurare la rete.
"""
from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RADICE))
sys.path.insert(0, str(RADICE / "tests"))

from app.ai.provider import OfflineProvider              # noqa: E402
from app.build.assembler import build                    # noqa: E402
from app.build.validate import validate                  # noqa: E402
from app.core.effect import apply_effects                # noqa: E402
from app.core.planner.planner import MockPlanner, PlanRequest   # noqa: E402
from app.core.planner.plans import validate_plan         # noqa: E402
from app.core.planner.vocabulary import build_vocabulary  # noqa: E402
from app.core.registry import load                       # noqa: E402
from app.core.resolver import resolve                    # noqa: E402
from app.core.session import Session                     # noqa: E402

CASI = {
    "casa e pianeta": "una casa con un pianeta enorme sopra",
    "albero e nido": "un albero con un nido e un uccello sopra",
    "figura": "una persona molto alta e magra",
}


def cronometra(quante: int, fai) -> tuple[float, float]:
    """Mediana e massimo, in millisecondi. La mediana perche' una misura
    isolata su una macchina qualunque non vuol dire niente."""
    tempi = []
    for _ in range(quante):
        inizio = time.perf_counter()
        fai()
        tempi.append((time.perf_counter() - inizio) * 1000.0)
    return statistics.median(tempi), max(tempi)


def misura(ripetizioni: int = 5) -> dict:
    sessione = Session(provider=OfflineProvider(), planner=MockPlanner())
    registro = sessione.catalog()

    fuori: dict[str, tuple[float, float]] = {}
    fuori["caricamento plugin"] = cronometra(
        max(2, ripetizioni // 2), lambda: load([RADICE / "app" / "plugins"]).freeze())
    fuori["vocabolario"] = cronometra(
        ripetizioni, lambda: build_vocabulary(registro))

    vocabolario = sessione.vocabulary()
    planner = MockPlanner()
    for nome, prompt in CASI.items():
        richiesta = PlanRequest(prompt=prompt, vocabulary=vocabolario)
        piano = planner.plan(richiesta).plan
        grafo, _ = validate_plan(piano, registro)
        risolto = resolve(grafo, registro)
        effetti = apply_effects(risolto, registro)
        costruito = build(effetti)

        fuori["%s: planner" % nome] = cronometra(
            ripetizioni, lambda r=richiesta: planner.plan(r))
        fuori["%s: validazione" % nome] = cronometra(
            ripetizioni, lambda p=piano: validate_plan(p, registro))
        fuori["%s: resolver" % nome] = cronometra(
            ripetizioni, lambda g=grafo: resolve(g, registro))
        fuori["%s: effetti" % nome] = cronometra(
            ripetizioni, lambda r=risolto: apply_effects(r, registro))
        fuori["%s: builder" % nome] = cronometra(
            ripetizioni, lambda e=effetti: build(e))
        fuori["%s: qualita'" % nome] = cronometra(
            ripetizioni, lambda c=costruito: validate(c))
        fuori["%s: TOTALE" % nome] = cronometra(
            ripetizioni, lambda p=prompt: sessione.generate(p, remember=False))
    return fuori


def main(ripetizioni: int = 5) -> int:
    misure = misura(ripetizioni)
    print("%-28s %10s %10s" % ("passo", "mediana", "peggiore"))
    print("-" * 50)
    for nome, (mediana, massimo) in misure.items():
        if nome.endswith("TOTALE"):
            print("-" * 50)
        print("%-28s %8.1f ms %8.1f ms" % (nome, mediana, massimo))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 5))
