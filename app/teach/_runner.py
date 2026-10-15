"""Carica un plugin in staging in un processo separato, e stampa un referto.

Esiste per **robustezza**, non per sicurezza, e §30 della milestone chiede di
dire esattamente questo: un plugin generato che cicla per sempre o che fa
cadere l'interprete non deve portarsi via la finestra di chi lo stava provando.
Un timeout e un processo a parte risolvono quello.

Non risolvono niente altro. Questo processo ha lo stesso accesso al filesystem,
alla rete e ai processi di chi lo ha lanciato: non e' una sandbox, non viene
chiamata sandbox, e chi legge il referto non deve credere di averne una. La
fiducia la concede una persona guardando il codice (`inspect_python` le mostra
che cosa guardare), non questo file.

Si invoca come **script** con `-I`, e la radice del repository la mette lui
stesso in `sys.path` leggendola da `__file__`:

    python -E app/teach/_runner.py --path <container> --component plugin:nome

`-E` ignora le variabili d'ambiente, cosi' l'avvio e' riproducibile; il sito
dei pacchetti resta, perche' senza `numpy` e `trimesh` non si costruisce
niente e un referto che dice soltanto «manca un modulo» non misura nulla. La
radice del repository la mette questo file leggendola da `__file__`, invece di
dipendere da come e' stato lanciato. Niente di tutto questo e' sicurezza.

Stampa **una** riga di JSON sull'ultima riga di stdout. Il chiamante legge
quella: tutto il resto puo' essere rumore di import.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# La radice del repository: `app/teach/_runner.py` -> due livelli sopra. Serve
# perche' `-I` non mette la cartella dello script in `sys.path`.
ROOT = str(Path(__file__).resolve().parents[2])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--path", action="append", default=[],
                        help="una cartella che il registry deve scandire")
    parser.add_argument("--component", default="",
                        help="l'id del componente da costruire")
    parser.add_argument("--style", default="low_poly")
    parser.add_argument("--detail", type=int, default=2)
    args = parser.parse_args(argv)

    out = {"installed": [], "triangles": 0, "built": False,
           "retrievable": False, "diagnostics": []}
    try:
        from app.core.session import Options, Session

        session = Session(plugin_paths=tuple(args.path))
        registry = session.catalog()
        plugin = args.component.partition(":")[0]
        out["installed"] = sorted(c.id for c in registry.components()
                                  if c.plugin == plugin)
        for entry in registry.report:
            out["diagnostics"].append({"code": entry.code, "message": entry.message,
                                       "where": entry.where, "why": entry.why,
                                       "severity": entry.severity})
        if args.component and registry.component(args.component) is None:
            out["diagnostics"].append({
                "code": "TEACH_COMPONENT_NOT_INSTALLED",
                "message": "'%s' non risulta installato dopo il caricamento"
                           % args.component,
                "where": "", "why": "", "severity": "error"})
        elif args.component:
            plan = {"version": "1.3", "style": args.style,
                    "detail_level": int(args.detail), "seed": 0,
                    "root": {"id": "subject", "ref": args.component}}
            result = session.build(plan, Options(style=args.style,
                                                 detail_level=int(args.detail),
                                                 check=True))
            if result is not None:
                out["triangles"] = int(result.triangles)
                out["built"] = bool(result.ok)
                if result.report is not None:
                    for entry in result.report:
                        out["diagnostics"].append({
                            "code": entry.code, "message": entry.message,
                            "where": entry.where, "why": entry.why,
                            "severity": entry.severity})
            name = args.component.partition(":")[2].replace("_", " ")
            hits = {i for i, _ in session.component_index().search(name, limit=12)}
            out["retrievable"] = args.component in hits
    except BaseException as exc:                           # noqa: BLE001
        # Qualunque cosa: un plugin generato puo' alzare qualunque cosa, e un
        # referto illeggibile sarebbe peggio di un referto che dice che e'
        # andata male.
        out["diagnostics"].append({"code": "TEACH_RUN_FAILED",
                                   "message": "%s: %s" % (type(exc).__name__, exc),
                                   "where": "", "why": "", "severity": "error"})
    sys.stdout.write("\n" + json.dumps(out) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
