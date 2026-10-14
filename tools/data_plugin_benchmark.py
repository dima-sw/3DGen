"""Quanto costa un componente mesh-backed, confrontato con uno procedurale.

    python tools/data_plugin_benchmark.py [ripetizioni] [--json FILE]

Non serve a dimostrare che l'import di un GLB e' veloce: serve a dimostrare che
**non costa in modo sproporzionato**. Le tre colonne sono lo stesso albero di
composizione (una radice e un figlio) costruito tre volte:

    procedurale    due componenti del plugin `humanoid`
    mesh-backed    due componenti dichiarati in dati, geometria da GLB
    misto          radice procedurale, figlio mesh-backed

I passi misurati sono quelli che la milestone chiede: scoperta dei plugin,
caricamento del GLB, build, indice semantico e generazione locale completa. Il
planner e' quello finto: misurare la rete vorrebbe dire misurare la rete.

Il plugin dati viene scritto in una cartella temporanea dalle stesse fixture
dei test, quindi il numero si riproduce senza asset versionati.
"""
from __future__ import annotations

import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RADICE))
sys.path.insert(0, str(RADICE / "tests"))

from app.ai.provider import OfflineProvider                      # noqa: E402
from app.core.component import BuildContext                      # noqa: E402
from app.core.data_plugin import load_component                  # noqa: E402
from app.core.planner.planner import MockPlanner                 # noqa: E402
from app.core.planner.retrieval import build_index               # noqa: E402
from app.core.registry import load                               # noqa: E402
from app.core.session import Options, Session                    # noqa: E402

PLUGIN = RADICE / "app" / "plugins"

# radice, figlio, e il percorso su cui il figlio si posa quando la radice
# dichiara la propria parte da se' (`on`, come in un piano qualunque).
CASI = {
    "procedurale": ("humanoid:body", "humanoid:head", "torso"),
    "mesh-backed": ("mesh_fixture:body", "mesh_fixture:head", ""),
    "misto": ("humanoid:body", "mesh_fixture:head", "torso"),
}


def cronometra(quante: int, fai) -> tuple[float, float]:
    """Mediana e massimo in millisecondi. La mediana, perche' una misura sola
    su una macchina qualunque non vuol dire niente."""
    tempi = []
    for _ in range(quante):
        inizio = time.perf_counter()
        fai()
        tempi.append((time.perf_counter() - inizio) * 1000.0)
    return statistics.median(tempi), max(tempi)


def piano(radice: str, figlio: str, dove: str = "") -> dict:
    figlio_voce = {"id": "part", "ref": figlio, "insert": 0.0,
                   "at": {"capability": "head_mount"}}
    if dove:
        figlio_voce["on"] = dove
    return {"version": "1.3", "style": "low_poly", "detail_level": 2, "seed": 7,
            "root": {"id": "subject", "ref": radice, "children": [figlio_voce]}}


def misura(cartella: Path, ripetizioni: int = 5) -> dict:
    from data_plugin_fixtures import write_knight_plugin

    dati = write_knight_plugin(cartella)
    fuori: dict[str, tuple[float, float]] = {}

    poche = max(2, ripetizioni // 2)
    fuori["scoperta: solo codice (22 plugin)"] = cronometra(
        poche, lambda: load([PLUGIN]).freeze())
    fuori["scoperta: codice + dati (23 plugin)"] = cronometra(
        poche, lambda: load([PLUGIN, dati]).freeze())
    fuori["scoperta: il solo plugin dati"] = cronometra(
        poche, lambda: load([dati]).freeze())
    fuori["caricamento GLB: 1 componente"] = cronometra(
        ripetizioni, lambda: load_component(dati / "components/head.json", dati))

    solo_codice = load([PLUGIN]).freeze()
    registro = load([PLUGIN, dati]).freeze()
    sessione = Session(registry=registro, provider=OfflineProvider(),
                       planner=MockPlanner())
    fuori["indice semantico: %d componenti" % len(solo_codice.components())] =         cronometra(poche, lambda: build_index(solo_codice))
    fuori["indice semantico: %d (+ dati)" % len(registro.components())] =         cronometra(poche, lambda: build_index(registro))

    for nome, (radice, figlio, dove) in CASI.items():
        istruzioni = piano(radice, figlio, dove)
        risultato = sessione.build(istruzioni)
        if not risultato.ok or not risultato.report.ok:
            raise RuntimeError("%s: %s" % (nome, risultato.report.describe()))
        componente = registro.component(figlio)
        # i valori risolti, non i default: un componente procedurale non ha
        # l'obbligo di avere un default per ogni parametro.
        valori = dict(risultato.resolved.node("part").values)
        fuori["%s: build del figlio" % nome] = cronometra(
            ripetizioni, lambda c=componente, v=valori: c.build(dict(v), BuildContext()))
        fuori["%s: TOTALE locale" % nome] = cronometra(
            ripetizioni, lambda p=istruzioni: sessione.build(p, Options(repair=False)))
        fuori["%s: triangoli" % nome] = (float(risultato.triangles),
                                          float(risultato.triangles))
    return fuori


def main(ripetizioni: int = 5, destinazione: str = "") -> int:
    with tempfile.TemporaryDirectory() as temporanea:
        misure = misura(Path(temporanea), ripetizioni)

    print("%-38s %11s %11s" % ("passo", "mediana", "peggiore"))
    print("-" * 62)
    for nome, (mediana, massimo) in misure.items():
        if nome.endswith("triangoli"):
            print("%-38s %11d %11s" % (nome, int(mediana), "-"))
            continue
        if nome.endswith("TOTALE locale"):
            print("-" * 62)
        print("%-38s %8.2f ms %8.2f ms" % (nome, mediana, massimo))

    if destinazione:
        percorso = Path(destinazione)
        percorso.parent.mkdir(parents=True, exist_ok=True)
        percorso.write_text(json.dumps(
            {nome: {"median_ms": mediana, "worst_ms": massimo}
             for nome, (mediana, massimo) in misure.items()}, indent=2),
            encoding="utf-8")
        print("\nscritto: %s" % percorso)
    return 0


if __name__ == "__main__":
    argomenti = [a for a in sys.argv[1:] if a != "--json"]
    quante = int(argomenti[0]) if argomenti and argomenti[0].isdigit() else 5
    file = next((a for a in argomenti if not a.isdigit()), "")
    raise SystemExit(main(quante, file))
