"""Audit harness: run the 8 audit prompts through the full pipeline.

Usage:
    python run_audit.py offline <outdir>
    python run_audit.py llm <outdir> [provider]
"""
from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(r"C:\Users\dimit\Desktop\Projects\3DGen")
sys.path.insert(0, str(ROOT))

from app.core.session import Options, Session          # noqa: E402

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

ANGLES = [("front", 0.0, 8.0), ("three_quarter", 38.0, 16.0), ("side", 90.0, 6.0)]


def session_for(mode: str, provider_key: str = ""):
    if mode == "offline":
        from app.ai.provider import OfflineProvider
        from app.core.planner.planner import MockPlanner
        return Session(provider=OfflineProvider(), planner=MockPlanner()), "mock"
    from app.ai.provider import make_provider
    from app.core.planner.planner import LLMPlanner
    prov = make_provider(provider_key or None)
    return Session(provider=prov, planner=LLMPlanner(prov)), provider_key or "chain"


def components_of(result):
    refs = []
    if result.resolved is not None:
        for node in result.resolved.walk():
            refs.append("%s -> %s" % (node.id, node.ref))
    return refs


def main() -> int:
    mode = sys.argv[1]
    outdir = Path(sys.argv[2])
    provider_key = sys.argv[3] if len(sys.argv) > 3 else ""
    outdir.mkdir(parents=True, exist_ok=True)

    from app.ui.offscreen import render

    rows = []
    for name, prompt in PROMPTS.items():
        row = {"name": name, "prompt": prompt, "mode": mode}
        try:
            session, tag = session_for(mode, provider_key)
            t0 = time.perf_counter()
            result = session.generate(prompt, Options(style="low_poly"))
            row["seconds"] = round(time.perf_counter() - t0, 3)
            row["ok"] = bool(result.ok)
            row["triangles"] = int(result.triangles or 0)
            row["planner"] = getattr(result, "planner", tag)
            row["provider"] = result.actual_provider
            row["model"] = result.actual_model
            row["failover"] = result.failover_count
            row["diagnostics"] = [str(d) for d in (result.diagnostics or [])][:25]
            row["describe"] = result.describe()
            row["explain"] = result.explain()[:40]
            row["changes"] = result.changes()[:20]
            row["skipped"] = result.skipped()[:20]
            row["components"] = components_of(result)
            row["plan_json"] = result.plan_json
            row["repaired"] = result.repaired
            if result.build is not None:
                row["build_describe"] = result.build.describe()
            if result.report is not None:
                row["report"] = result.report.describe()
            if result.layout is not None:
                row["layout"] = str(result.layout.to_dict())[:1500]
            if result.structural is not None:
                row["structural"] = str(result.structural.to_dict())[:1500]
            if result.traits is not None:
                row["traits_res"] = str(result.traits.to_dict())[:1500]
            if result.concept_resolution is not None:
                row["concept"] = str(result.concept_resolution.to_dict())[:2000]
            scene = result.scene()
            if scene is not None:
                imgs = []
                for label, az, el in ANGLES:
                    path = outdir / f"{name}_{mode}_{label}.png"
                    render(scene, path, size=(760, 520), azimuth=az, elevation=el)
                    imgs.append(path.name)
                row["images"] = imgs
                row["parts"] = len(getattr(scene, "parts", []) or [])
                try:
                    import numpy as np
                    b = result.mesh().bounds
                    row["bbox"] = [round(float(v), 3) for v in (b[1] - b[0])]
                except Exception:
                    pass
            else:
                row["images"] = []
        except Exception as exc:
            row["error"] = f"{type(exc).__name__}: {exc}"
            row["trace"] = traceback.format_exc()[-1500:]
        rows.append(row)
        print(json.dumps({k: v for k, v in row.items()
                          if k in ("name", "ok", "triangles", "seconds", "provider",
                                   "model", "error")}), flush=True)

    (outdir / f"metrics_{mode}.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
