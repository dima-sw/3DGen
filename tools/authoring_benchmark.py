"""Quanto costano le operazioni di authoring, e quali sembrano interattive.

    python tools/authoring_benchmark.py [ripetizioni] [--json FILE]

Il target della milestone non e' «veloce», e' **interattivo**: muovere uno
slider deve sembrare immediato, salvare un plugin puo' costare. Quindi le
righe sono divise in due gruppi, e il secondo ha il permesso di essere lento.

Quello che si misura, e perche' quel passo e' quello:

    import GLB              leggere e ispezionare un file d'artista
    preview rebuild         una build completa dalla pipeline vera
    slider update           **la riga che conta**: un parametro che cambia non
                            riscrive il plugin, perche' i parametri viaggiano
                            nel piano e non nel JSON (`fingerprint` esclude lo
                            stato dell'editor)
    staging a freddo        la prima emissione piu' il caricamento del registry:
                            e' il prezzo di far passare la preview dalla
                            pipeline vera invece di simularla
    validation              loader + registry + resolver + build + retrieval
    save plugin             scrivere JSON e GLB sul disco
    install (reload)        il registry rifatto, senza riavviare
    semantic reindex        l'indice che si accorge dei componenti nuovi

Il cavaliere di prova e' quello dei test (`tests/authoring_fixtures.py`): un
GLB vero in cinque pezzi, corpo + testa con due occhi, radice composite. I
numeri si riproducono senza asset versionati.
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

from app.ai.provider import OfflineProvider                      # noqa: E402
from app.authoring import AuthoringService                       # noqa: E402
from app.authoring.inspect import load_model                     # noqa: E402
from app.core.planner.retrieval import build_index               # noqa: E402
from app.core.session import Session                             # noqa: E402
from tests.authoring_fixtures import write_knight_glb            # noqa: E402

# Sopra questa soglia un'operazione locale non sembra piu' una reazione a un
# gesto. Non e' una legge, e' il numero che si usa per leggere la tabella.
INTERATTIVO_MS = 100.0


def cronometra(quante: int, fai) -> tuple[float, float]:
    """Mediana e massimo in millisecondi. La mediana, perche' una misura sola
    su una macchina qualunque non vuol dire niente."""
    tempi = []
    for _ in range(quante):
        inizio = time.perf_counter()
        fai()
        tempi.append((time.perf_counter() - inizio) * 1000.0)
    return statistics.median(tempi), max(tempi)


def costruisci(svc: AuthoringService) -> dict:
    """Il cavaliere: corpo mesh, testa mesh con occhi, radice composite."""
    svc.set_frame(growth_axis="+Y", front="+Z", up="+Y")
    svc.select("knight/Body")
    body = svc.create_component("body", role="torso", provides=["torso_mount"],
                                description="A boxy knight body",
                                tags=["knight", "humanoid"])
    svc.add_socket(body.key, "base", direction=(0, -1, 0), radius=0.2)
    svc.snap_socket_to_face(body.key, "base", "-Y")
    svc.add_mount(body.key, "head_mount", socket="neck", direction=(0, 1, 0),
                  radius=0.15)
    svc.snap_socket_to_face(body.key, "neck", "+Y")
    svc.add_param(body.key, "width", default=1.0, min=0.3, max=2.5,
                  transform="scale_x", semantic_role="width")

    svc.select(["knight/Head", "knight/Eye_L", "knight/Eye_R"])
    head = svc.create_component("head", role="head", provides=["head_mount"],
                                description="A helmeted knight head with eyes",
                                tags=["head"])
    svc.add_socket(head.key, "base", direction=(0, -1, 0), radius=0.15)
    svc.snap_socket_to_face(head.key, "base", "-Y")

    root = svc.create_component("knight", objects=(), role="subject",
                                provides=["creature"], tags=["knight"],
                                description="A complete knight: body and head",
                                synonyms=["paladin"])
    svc.add_mount(root.key, "torso_mount", socket="core", radius=0.25)
    svc.set_parent(body.key, root.key, child_id="body", level=1,
                   requirement={"capability": "torso_mount"})
    svc.set_parent(head.key, body.key, child_id="head", level=2,
                   requirement={"capability": "head_mount"})
    return {"body": body.key, "head": head.key, "root": root.key}


def misura(temporanea: Path, quante: int) -> dict:
    glb = write_knight_glb(temporanea / "source")
    destinazione = temporanea / "plugins"
    misure: dict[str, tuple[float, float]] = {}

    misure["import GLB (5 oggetti, 60 triangoli)"] = cronometra(
        quante, lambda: load_model(glb))

    svc = AuthoringService(session=Session(provider=OfflineProvider()))
    svc.create_authoring_project("bench", destination=str(destinazione))
    svc.import_model(glb)
    chiavi = costruisci(svc)

    # Staging a freddo: la prima volta si emette e si carica un registry.
    svc._invalidate()
    svc._staged_session = None
    misure["staging a freddo (emit + registry)"] = cronometra(
        1, lambda: svc._stage())

    misure["preview rebuild (radice, detail 3)"] = cronometra(
        quante, lambda: svc.build_component(chiavi["root"], detail_level=3,
                                            check=False))
    misure["preview rebuild + quality gate"] = cronometra(
        quante, lambda: svc.build_component(chiavi["root"], detail_level=3,
                                            check=True))

    valori = iter([0.4, 0.8, 1.2, 1.6, 2.0] * max(1, quante))
    misure["slider update (un parametro)"] = cronometra(
        quante, lambda: svc.build_component(chiavi["body"], detail_level=1,
                                            params={"width": next(valori)},
                                            check=False))

    lab = svc.draft_lab(chiavi["body"])
    misure["Component Lab: una build"] = cronometra(
        quante, lambda: lab.build({"width": 1.3}, remember=False))
    misure["Component Lab: trait compatibili"] = cronometra(
        quante, lambda: lab.traits())

    misure["detail level preview (un livello)"] = cronometra(
        quante, lambda: svc.detail_preview(chiavi["root"], 2))
    misure["semantic search preview"] = cronometra(
        quante, lambda: svc.search_staged("knight head", 8))
    misure["planner preview (testo reso)"] = cronometra(
        quante, lambda: svc.planner_preview(chiavi["head"]))
    misure["frame report (due archi)"] = cronometra(
        quante, lambda: svc.frame_report())

    misure["validation (tutti i validatori)"] = cronometra(
        quante, lambda: svc.validate())
    misure["save plugin (3 JSON + 2 GLB)"] = cronometra(
        quante, lambda: svc.save_plugin(destinazione))

    sessione = svc.session
    sessione.catalog()
    misure["install: reload del registry"] = cronometra(
        quante, lambda: sessione.reload_plugins(destinazione))
    registro = sessione.catalog()
    misure["semantic reindex (100 componenti)"] = cronometra(
        quante, lambda: build_index(registro))
    misure["install and test (end to end)"] = cronometra(
        max(1, quante // 2), lambda: svc.install_plugin(destinazione))

    pulita = AuthoringService(session=Session(provider=OfflineProvider()))
    pulita.create_authoring_project("bench2", destination=str(destinazione))
    pulita.import_model(glb)
    costruisci(pulita)
    progetto = temporanea / "work.3dgenproj"
    misure["salva progetto authoring"] = cronometra(
        quante, lambda: pulita.save_project(progetto))
    misure["riapri progetto authoring"] = cronometra(
        quante, lambda: AuthoringService(
            session=Session(provider=OfflineProvider())).load_project(progetto))
    pulita.close()
    svc.close()
    return misure


INTERATTIVE = ("import GLB", "preview rebuild", "slider update",
               "Component Lab", "detail level", "semantic search",
               "planner preview", "frame report", "salva progetto")


def main(ripetizioni: int = 5, destinazione: str = "") -> int:
    with tempfile.TemporaryDirectory() as temporanea:
        misure = misura(Path(temporanea), ripetizioni)

    print("%-40s %11s %11s %s" % ("passo", "mediana", "peggiore", "interattivo"))
    print("-" * 78)
    for nome, (mediana, massimo) in misure.items():
        atteso = any(nome.startswith(p) for p in INTERATTIVE)
        verdetto = "-"
        if atteso:
            verdetto = "si" if mediana <= INTERATTIVO_MS else "NO"
        print("%-40s %8.2f ms %8.2f ms %s" % (nome, mediana, massimo, verdetto))
    print("-" * 78)
    print("«interattivo» = mediana sotto %.0f ms, misurato solo dove un gesto "
          "dell'utente lo richiede." % INTERATTIVO_MS)

    if destinazione:
        percorso = Path(destinazione)
        percorso.parent.mkdir(parents=True, exist_ok=True)
        percorso.write_text(json.dumps(
            {nome: {"median_ms": mediana, "worst_ms": massimo}
             for nome, (mediana, massimo) in misure.items()}, indent=2),
            encoding="utf-8")
        print("scritto: %s" % percorso)
    return 0


if __name__ == "__main__":
    argomenti = [a for a in sys.argv[1:] if a != "--json"]
    quante = int(argomenti[0]) if argomenti and argomenti[0].isdigit() else 5
    file = next((a for a in argomenti if not a.isdigit()), "")
    raise SystemExit(main(quante, file))
