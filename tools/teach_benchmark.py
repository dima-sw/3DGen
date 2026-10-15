"""Quanto costa insegnare un concetto. Nessuna rete, misure vere.

    python tools/teach_benchmark.py [ripetizioni]

Il target di questa milestone non e' «veloce»: e' che ogni passo che l'utente
fa aspettando resti **interattivo**, e che i passi che non lo sono si paghino
raramente e si sappia quanto costano. La soglia dichiarata e' la stessa di V6:
100 ms.

Le righe che contano sono tre, e vale la pena dirle prima dei numeri:

* **l'analisi di copertura**, perche' si rifa' dopo ogni installazione (§35);
* **la specifica piu' il prompt**, perche' e' il gesto che precede ogni
  generazione;
* **lo staging di una risposta**, perche' e' cio' che separa «il modello ha
  risposto» da «posso guardarlo».

Il resto e' contesto: la decomposizione e il raffinamento sono testo, la
validazione e l'installazione passano dalla pipeline vera e costano quanto
costa quella.
"""
from __future__ import annotations

import json
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[1])]

from app.ai.provider import OfflineProvider                        # noqa: E402
from app.core.session import Options, Session                      # noqa: E402
from app.teach import TeachService, coverage as cov                # noqa: E402
from app.teach.knowledge import TeachKnowledge                     # noqa: E402
from tests.teach_fixtures import (data_component, dragon_decomposition,  # noqa: E402
                                  dragon_refinement, python_component,
                                  suitable_with_parameters, write_part_glb)

INTERACTIVE_MS = 100.0
PROXIES = ("dragon.body", "dragon.wing", "dragon.leg", "dragon.tail")


def measure(label: str, run, repeats: int, *, interactive: bool | None = None):
    times = []
    out = None
    for _ in range(max(1, repeats)):
        start = time.perf_counter()
        out = run()
        times.append((time.perf_counter() - start) * 1000.0)
    median = statistics.median(times)
    return {"label": label, "median": median, "worst": max(times),
            "interactive": interactive, "value": out}


def fresh(root: Path, name: str):
    session = Session(provider=OfflineProvider())
    service = TeachService(session=session, knowledge=TeachKnowledge(),
                           staging_root=root / ("staging_" + name))
    service.create_project("dragon", style_target="cartoon low-poly",
                           detail_target=2,
                           destination=str(root / ("library_" + name)))
    return service


def hierarchy(service):
    service.decomposition_prompt()
    service.import_decomposition(dragon_decomposition())
    service.refinement_prompt()
    service.import_refinement(dragon_refinement())


def main(repeats: int = 7) -> int:
    root = Path(tempfile.mkdtemp(prefix="3dgen-teach-bench-"))
    rows = []
    try:
        # --------------------------------------------------- i due passi #
        service = fresh(root, "prompts")
        rows.append(measure("prompt: decomposizione (testo reso)",
                            service.decomposition_prompt, repeats,
                            interactive=True))
        service.import_decomposition(dragon_decomposition())
        rows.append(measure("import: decomposizione (11 nodi)",
                            lambda: service.import_decomposition(
                                dragon_decomposition()), repeats,
                            interactive=True))
        rows.append(measure("prompt: raffinamento",
                            service.refinement_prompt, repeats,
                            interactive=True))
        rows.append(measure("import: raffinamento (10 nodi)",
                            lambda: service.import_refinement(
                                dragon_refinement()), repeats,
                            interactive=True))

        # ------------------------------------------------- la copertura #
        rows.append(measure("ANALISI DI COPERTURA (10 nodi, 97 componenti)",
                            service.analyse, repeats, interactive=True))
        node = "dragon.head.eye"
        rows.append(measure("candidati di un nodo",
                            lambda: cov.candidates_for(
                                service.project,
                                service.project.require_node(node),
                                registry=service.session.catalog(),
                                index=service.session.component_index(),
                                knowledge=service.knowledge,
                                style=service.project.style), repeats,
                            interactive=True))
        component = service.candidates(node)[0].component_id
        rows.append(measure("dossier di un candidato (con la misura)",
                            lambda: service.dossier(node, component), repeats,
                            interactive=True))
        rows.append(measure("prompt: idoneita'",
                            lambda: service.suitability_prompt(node, component),
                            repeats, interactive=True))
        rows.append(measure("prompt: deep validation (con il sorgente)",
                            lambda: service.deep_validation_prompt(node,
                                                                    component),
                            repeats, interactive=True))
        rows.append(measure("progresso e albero",
                            lambda: (service.summary(), service.tree()),
                            repeats, interactive=True))
        rows.append(measure("coda dependency-aware", service.queue, repeats,
                            interactive=True))

        # ----------------------------------------- giallo -> verde (§18) #
        service.suitability_prompt(node, component)
        service.import_suitability(node, suitable_with_parameters({"size": 0.12}),
                                   component_id=component)
        rows.append(measure("Component Lab: una build",
                            lambda: service.lab(node, component).build(),
                            repeats, interactive=True))
        rows.append(measure("apply AI suggestion",
                            lambda: service.apply_suggestion(node, component),
                            repeats, interactive=True))
        recipe = measure("save variant (giallo -> verde)",
                         lambda: service.save_variant(
                             node, "dragon_eye", component_id=component),
                         1, interactive=True)
        rows.append(recipe)
        for proxy in PROXIES:
            service.accept_candidate(proxy,
                                     service.candidates(proxy)[0].component_id)

        # ------------------------------------- la specifica e il prompt #
        snout = "dragon.head.snout"
        for candidate in list(service.candidates(snout)):
            service.reject_candidate(snout, candidate.component_id)
        rows.append(measure("SPECIFICA TECNICA (con la misura dei riferimenti)",
                            lambda: service.spec(snout), repeats,
                            interactive=True))
        rows.append(measure("specifica senza misurare",
                            lambda: service.spec(snout, measure=False), repeats,
                            interactive=True))
        rows.append(measure("PROMPT DI IMPLEMENTAZIONE",
                            lambda: service.implementation_prompt(snout),
                            repeats, interactive=True))
        spec = service.spec(snout)
        payload = python_component(spec.plugin_id, "snout",
                                   capability=spec.provides[0], role="snout")
        rows.append(measure("parse dell'inviluppo",
                            lambda: __import__("app.teach.staging",
                                               fromlist=["x"]).parse_envelope(
                                json.dumps(payload)), repeats,
                            interactive=True))
        rows.append(measure("STAGING DI UNA RISPOSTA (2 file, con ispezione)",
                            lambda: service.import_implementation(snout, payload),
                            repeats, interactive=True))
        artifact = service.import_implementation(snout, payload)
        service.trust_artifact(artifact.id)
        rows.append(measure("validazione in processo (carica, costruisce, cerca)",
                            lambda: service.validate_artifact(artifact.id),
                            repeats, interactive=False))
        rows.append(measure("validazione in un sottoprocesso",
                            lambda: service.validate_artifact(artifact.id,
                                                              isolate=True),
                            max(1, repeats // 3), interactive=False))
        rows.append(measure("accept: installa, reindicizza, ricalcola",
                            lambda: service.accept_artifact(artifact.id), 1,
                            interactive=False))

        # ------------------------------------------- il corno dai dati #
        horn = "dragon.head.horn"
        glb = write_part_glb(root / "assets")
        service.supply_asset(horn, glb)
        hspec = service.spec(horn)
        hpayload = data_component(hspec.plugin_id, "horn",
                                  capability=hspec.provides[0], mesh=glb.name)
        service.implementation_prompt(horn)
        hart = service.import_implementation(horn, hpayload)
        rows.append(measure("validazione di un plugin dati (nessuna fiducia)",
                            lambda: service.validate_artifact(hart.id), repeats,
                            interactive=False))
        service.accept_artifact(hart.id)

        # ----------------------------------------- i composite e la fine #
        rows.append(measure("composite intermedio (emesso e installato)",
                            lambda: service.emit_composite("dragon.head"), 1,
                            interactive=False))
        rows.append(measure("COMPOSITE DELLA RADICE (emesso e installato)",
                            service.emit_composite, 1, interactive=False))
        rows.append(measure("referto di completamento (costruisce la radice)",
                            service.completion_report, repeats,
                            interactive=False))
        final = service.finish()
        rows.append(measure("esporta la conoscenza",
                            lambda: service.export_knowledge(
                                root / "knowledge.json"), repeats,
                            interactive=True))
        saved = measure("salva il progetto",
                        lambda: service.save_project(root / "dragon"), repeats,
                        interactive=True)
        rows.append(saved)
        path = service.save_project(root / "dragon")
        rows.append(measure("riapri il progetto",
                            lambda: fresh(root, "reopen").load_project(path),
                            max(1, repeats // 3), interactive=False))

        # ----------------------- la prova finale, fuori da Teach (§38) #
        session = service.session
        rows.append(measure("Session.shortlist(concetto)",
                            lambda: session.shortlist("dragon"), repeats,
                            interactive=True))
        rows.append(measure("Session.generate(concetto) fuori da Teach",
                            lambda: session.generate("a cartoon dragon",
                                                     Options(detail_level=2)),
                            repeats, interactive=False))

        # ------------------------------------------- il secondo concetto #
        store = TeachKnowledge.load(root / "knowledge.json")
        second = TeachService(session=session, knowledge=store,
                              staging_root=root / "staging_second")
        second.create_project("wyvern", description="a two-legged winged dragon",
                              detail_target=2,
                              destination=str(root / "library_second"))
        second.decomposition_prompt()
        second.import_decomposition({
            "concept": "wyvern",
            "description": "a two-legged winged dragon",
            "root": {"name": "wyvern", "role": "creature", "mandatory": True,
                     "children": [
                         {"name": "body", "role": "body", "mandatory": True},
                         {"name": "head", "role": "head", "mandatory": True,
                          "children": [{"name": "eye", "role": "eye",
                                        "mandatory": True, "count": 2}]},
                         {"name": "wing", "role": "wing", "mandatory": True,
                          "count": 2},
                         {"name": "leg", "role": "leg", "mandatory": True,
                          "count": 2},
                         {"name": "tail", "role": "tail", "mandatory": True}]}})
        rows.append(measure("copertura di un secondo concetto (con la conoscenza)",
                            second.analyse, repeats, interactive=True))

        report(rows, repeats)
        summary(service, second, final)
        second.close()
        service.close()
        return 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


def report(rows, repeats: int) -> None:
    print()
    print("Teach 3DGen - costi, mediana di %d (ms). Soglia interattiva: %.0f ms"
          % (repeats, INTERACTIVE_MS))
    print("%-52s %10s %10s  %s" % ("passo", "mediana", "peggiore",
                                   "interattivo"))
    print("-" * 88)
    for row in rows:
        verdict = "-"
        if row["interactive"]:
            verdict = "si" if row["median"] <= INTERACTIVE_MS else "NO"
        print("%-52s %10.2f %10.2f  %s" % (row["label"][:52], row["median"],
                                           row["worst"], verdict))


def summary(service, second, final) -> None:
    print()
    print("Esito del concetto")
    print("-" * 88)
    print(final.describe())
    progress = service.progress()
    print()
    print(cov.tree_text(service.project))
    print()
    print("radice: %s | triangoli: %d" % (service.project.root_component,
                                          final.triangles))
    print("progresso: %s" % progress.describe())
    print()
    print("Secondo concetto, con la conoscenza del primo")
    print("-" * 88)
    print(cov.tree_text(second.project))
    counts = second.summary()["counts"]
    print("stati: %s" % ", ".join("%s %d" % (k, v) for k, v in counts.items()))


if __name__ == "__main__":
    raise SystemExit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 7))
