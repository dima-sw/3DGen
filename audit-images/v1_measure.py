"""V1: misure obbligatorie sugli 8 prompt del PRODUCT-AUDIT."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(r"C:\Users\dimit\Desktop\Projects\3DGen")
sys.path.insert(0, str(ROOT))

from app.core.planner.retrieval import (build_index, estimate_tokens,  # noqa: E402
                                        shortlist)
from app.core.planner.vocabulary import build_vocabulary               # noqa: E402
from app.core.registry import load                                     # noqa: E402

PROMPTS = {
    "01_fox": "Una volpe cartoon low-poly.",
    "02_humanoid": "Un umanoide cartoon con testa enorme, gambe corte e mani grandi.",
    "03_robot4arms": "Un robot con quattro braccia.",
    "04_jeep6wheels": "Una jeep cartoon con sei ruote.",
    "05_fishman": "Un pesce con corpo umanoide.",
    "06_house": "Una casa alta, slanciata e leggermente curva.",
    "07_dragon": "Un drago cartoon con ali, corna e coda.",
    "08_tree": "Un albero fantasy con chioma asimmetrica.",
}

registry = load([ROOT / "app" / "plugins"]).freeze()
t0 = time.perf_counter()
index = build_index(registry)
index_seconds = time.perf_counter() - t0

full = build_vocabulary(registry, style="low_poly")
full_text = full.to_text()
out = {
    "installed_components": len(registry.components()),
    "index_build_seconds": round(index_seconds, 3),
    "full_vocabulary": {"chars": len(full_text),
                        "tokens": estimate_tokens(full_text),
                        "components": len(full.components)},
    "prompts": {},
}
print("vocabolario completo: %d char, ~%d token, %d componenti"
      % (len(full_text), estimate_tokens(full_text), len(full.components)))
print("indice costruito in %.3f s\n" % index_seconds)

for name, prompt in PROMPTS.items():
    t0 = time.perf_counter()
    rosa = shortlist(registry, prompt, index=index, style="low_poly")
    retrieval_seconds = time.perf_counter() - t0
    vocab = build_vocabulary(registry, style="low_poly", components=rosa.components)
    text = vocab.to_text()
    row = {
        "prompt": prompt,
        "shortlist": len(rosa),
        "of_total": rosa.total,
        "retrieval_seconds": round(retrieval_seconds, 4),
        "chars": len(text),
        "tokens": estimate_tokens(text),
        "reduction": round(1 - estimate_tokens(text) / estimate_tokens(full_text), 3),
        "fallback": rosa.fallback,
        "top": [[h.id, round(h.score, 3)] for h in rosa.hits
                if h.reason == "query"][:10],
        "closure": [h.id for h in rosa.hits if h.reason.startswith("closure")],
        "ids": rosa.ids,
    }
    out["prompts"][name] = row
    print("%-16s rosa %2d/%d  %5.1f ms  %6d char  ~%5d token  -%.0f%%"
          % (name, len(rosa), rosa.total, retrieval_seconds * 1000,
             len(text), estimate_tokens(text), row["reduction"] * 100))
    print("     top: %s" % ", ".join("%s(%.2f)" % (i, s) for i, s in row["top"][:5]))

Path(sys.argv[1]).write_text(json.dumps(out, indent=2, ensure_ascii=False),
                             encoding="utf-8")
