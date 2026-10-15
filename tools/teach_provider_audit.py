"""Il banco con un modello vero. **Evidenza, non Definition of Done** (§51).

    python tools/teach_provider_audit.py [concetto] [provider]

Serve a misurare una cosa che i test deterministici non possono misurare: che
un modello reale, davanti al prompt che Teach genera, risponda **nella forma
che lo schema descrive** e produca un'ontologia utilizzabile. Tutto il resto —
che l'ontologia diventi copertura, che la copertura diventi un plugin, che il
plugin si installi — e' gia' provato senza rete.

§51 chiede esplicitamente che una quota esaurita o un rate limit non rendano
rossa la milestone: per questo questo file **non e' un test**. Se nessun
provider e' configurato lo dice e esce con 0.

Che cosa misura:

    pass 1       la decomposizione: forma valida, nodi, mandatory/optional
    pass 2       il raffinamento: forma valida, che cosa ha cambiato
    schema       la risposta passa `jsonschema` contro lo schema dichiarato
    copertura    i quattro stati sulla libreria installata
    prompt       quanti caratteri costano i prompt che abbiamo mandato
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[1])]

from app.ai.provider import make_provider                          # noqa: E402
from app.core.session import Session                               # noqa: E402
from app.teach import TeachService, coverage as cov                # noqa: E402
from app.teach.errors import TeachError                            # noqa: E402
from app.teach.knowledge import TeachKnowledge                     # noqa: E402
from app.teach.schema import DECOMPOSITION_SCHEMA, REFINEMENT_SCHEMA  # noqa: E402


def check_schema(payload, schema) -> str:
    try:
        import jsonschema
    except ImportError:
        return "jsonschema non installato: non verificato"
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError as exc:
        return "NON conforme: %s" % str(exc).splitlines()[0]
    return "conforme"


def main(concept: str = "dragon", provider_name: str = "") -> int:
    provider = make_provider(provider_name or None)
    if not provider.available():
        print("nessun provider configurato: l'audit di §51 non e' la "
              "Definition of Done, e qui si ferma senza errore")
        return 0

    root = Path(tempfile.mkdtemp(prefix="3dgen-teach-audit-"))
    session = Session(provider=provider)
    service = TeachService(session=session, knowledge=TeachKnowledge(),
                           staging_root=root / "staging")
    service.create_project(concept, style_target="cartoon low-poly",
                           detail_target=2, destination=str(root / "library"))
    print("concetto: %s | provider: %s" % (concept,
                                           getattr(provider, "name", "?")))
    print()

    first = service.decomposition_prompt()
    print("pass 1: prompt di %d caratteri" % first.characters)
    try:
        raw = service.ask(first)
    except TeachError as exc:
        print("pass 1 non riuscito: %s - %s" % (exc.code, exc.message))
        return 0
    payload = json.loads(raw)
    print("  schema: %s" % check_schema(payload, DECOMPOSITION_SCHEMA))
    try:
        report = service.import_decomposition(payload)
    except TeachError as exc:
        print("  import rifiutato: %s - %s" % (exc.code, exc.message))
        print("  (un rifiuto e' una misura: la forma non era usabile)")
        return 0
    print("  nodi: %d (%d mandatory, %d optional)"
          % (report.detail["nodes"], report.detail["mandatory"],
             report.detail["optional"]))
    print()
    print(service.project.root.describe())
    for node in service.project.nodes():
        if node.depth:
            print(node.describe())
    print()

    second = service.refinement_prompt()
    print("pass 2: prompt di %d caratteri" % second.characters)
    try:
        raw = service.ask(second)
        payload = json.loads(raw)
        print("  schema: %s" % check_schema(payload, REFINEMENT_SCHEMA))
        report = service.import_refinement(payload)
        print("  nodi: %d" % report.detail["nodes"])
        for change in report.detail["changes"][:8]:
            print("  - %s" % change)
    except (TeachError, ValueError) as exc:
        print("  pass 2 non riuscito: %s" % exc)

    print()
    coverage = service.analyse()
    print(cov.tree_text(service.project))
    print()
    print("stati: %s" % ", ".join(
        "%s %d" % (k, v) for k, v in service.summary()["counts"].items()))
    print("coda: %d nodi mandatory da costruire" % len(service.queue()))
    print("copertura calcolata in %.1f ms" % (coverage.seconds * 1000.0))
    print()
    node = service.next_node()
    if node is not None:
        state = service.project.state(node.id)
        if state.candidates:
            bundle = service.suitability_prompt(node.id)
            print("prompt di idoneita' per %s: %d caratteri"
                  % (node.id, bundle.characters))
        else:
            bundle = service.implementation_prompt(node.id)
            print("prompt di implementazione per %s: %d caratteri"
                  % (node.id, bundle.characters))
    print()
    print("prompt generati: %d" % len(service.exchanges()))
    service.close()
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    raise SystemExit(main(args[0] if args else "dragon",
                          args[1] if len(args) > 1 else ""))
