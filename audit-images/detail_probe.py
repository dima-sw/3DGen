"""detail_level probe: same hand-written plan at detail 1..4."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\dimit\Desktop\Projects\3DGen")
sys.path.insert(0, str(ROOT))

from app.ai.provider import OfflineProvider          # noqa: E402
from app.core.planner.planner import MockPlanner     # noqa: E402
from app.core.session import Options, Session        # noqa: E402

PLANS = {
    "fox": {"version": "1.3", "root": {"id": "fox", "ref": "fox_stylized:fox"}},
    "house": {"version": "1.3", "root": {"id": "house", "ref": "architecture:house"}},
    "humanoid": {"version": "1.3",
                 "root": {"id": "body", "ref": "humanoid_anatomical:body"}},
    "humanoid_legacy": {"version": "1.3",
                        "root": {"id": "body", "ref": "humanoid:body"}},
    "car": {"version": "1.3", "root": {"id": "car", "ref": "vehicle_stylized:car"}},
    "tree": {"version": "1.3", "root": {"id": "tree", "ref": "tree_stylized:tree"}},
}

out = {}
for name, plan in PLANS.items():
    out[name] = {}
    for level in (1, 2, 3, 4):
        s = Session(provider=OfflineProvider(), planner=MockPlanner())
        p = json.loads(json.dumps(plan))
        p["detail_level"] = level
        r = s.build(p, Options(style="low_poly", detail_level=level))
        refs = []
        if r.resolved is not None:
            refs = ["%s->%s" % (n.id, n.ref) for n in r.resolved.walk()]
        out[name][level] = {"ok": r.ok, "tris": r.triangles, "nodes": len(refs),
                            "refs": refs,
                            "diag": [str(d) for d in (r.diagnostics or [])][:6]}
        print(name, level, "ok" if r.ok else "FAIL", r.triangles, "tris",
              len(refs), "nodes", flush=True)

Path(sys.argv[1]).write_text(json.dumps(out, indent=2, ensure_ascii=False,
                                        default=str), encoding="utf-8")
