"""Smoke developer-only per i provider AI configurati.

Uso: ``python tools/ai_provider_smoke.py``.
Fa una chat minima, non avvia l'app e non stampa header, token o account id.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.provider import ChatProvider
from app.core.config import PROVIDERS, SETTINGS


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", help="prova solo questa chiave registry")
    args = parser.parse_args()
    names = [args.provider] if args.provider else list(PROVIDERS)
    print("provider\tdefault_model\tstatus\thttp\tms\tsafe_error")
    for name in names:
        if name not in PROVIDERS:
            print("%s\t-\tUNKNOWN\t-\t0\tprovider non presente nel registry" % name)
            continue
        provider = ChatProvider(name)
        note = ("legacy model override ignored"
                if SETTINGS.legacy_model_override(name) else "")
        if not SETTINGS.configured(name):
            missing = ",".join(SETTINGS.missing_requirements(name)) or "credential"
            error = "manca %s" % missing
            if note:
                error = "%s; %s" % (note, error)
            print("%s\t%s\tUNCONFIGURED\t-\t0\t%s" %
                  (name, provider.model, error))
            continue
        started = time.perf_counter()
        try:
            provider.complete_json(
                "Return one JSON object and no prose.",
                '{"ok":true}', temperature=0, schema=None)
            status = "OK"
            error = ""
        except Exception as exc:  # smoke report: never abort remaining providers
            status = provider.last_outcome.upper()
            error = provider._safe(str(exc)).replace("\t", " ")[:240]
        if note:
            error = ("%s; %s" % (note, error)).rstrip("; ")
        elapsed = round((time.perf_counter() - started) * 1000)
        print("%s\t%s\t%s\t%s\t%s\t%s" %
              (name, provider.model, status,
               provider.last_status_code or "-", elapsed, error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
