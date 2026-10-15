"""Hand-written plans: the engine ceiling, with no planner involved."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(r"C:\Users\dimit\Desktop\Projects\3DGen")
sys.path.insert(0, str(ROOT))

from app.ai.provider import OfflineProvider          # noqa: E402
from app.core.planner.planner import MockPlanner     # noqa: E402
from app.core.session import Options, Session        # noqa: E402

PLANS = {
    "m01_fox": {"version": "1.3", "style": "low_poly", "detail_level": 3,
                "root": {"id": "fox", "ref": "fox_stylized:fox"}},

    "m01b_fox_concept": {"version": "1.3", "style": "low_poly",
                         "concept": {"requested": "fox",
                                     "archetypes": ["archetype_metadata:felid"]}},

    "m02_humanoid_cartoon": {
        "version": "1.3", "style": "low_poly", "detail_level": 2,
        "traits": [{"trait": "body_mass", "value": 0.8, "scope": "subtree"}],
        "root": {"id": "body", "ref": "humanoid_anatomical:body",
                 "effects": [{"type": "fx:chunky", "amount": 0.7,
                              "scope": "subtree"}]}},

    "m03_robot_4arms": {
        "version": "1.3", "style": "low_poly", "detail_level": 2,
        "structural_traits": [{"trait": "character:arm_count", "value": 4,
                               "mode": "best_effort"}],
        "root": {"id": "body", "ref": "humanoid_anatomical:body",
                 "children": [{"id": "rhead", "swap": "robot:head"}]}},

    "m03b_humanoid_4arms": {
        "version": "1.3", "style": "low_poly", "detail_level": 2,
        "structural_traits": [{"trait": "character:arm_count", "value": 4,
                               "mode": "best_effort"}],
        "root": {"id": "body", "ref": "humanoid_anatomical:body"}},

    "m04_car_6wheels": {
        "version": "1.3", "style": "low_poly", "detail_level": 3,
        "structural_traits": [{"trait": "vehicle:wheel_count", "value": 6,
                               "mode": "best_effort"}],
        "root": {"id": "car", "ref": "vehicle_stylized:car"}},

    "m05_fishman": {
        "version": "1.3", "style": "low_poly", "detail_level": 2,
        "root": {"id": "body", "ref": "humanoid_anatomical:body",
                 "children": [{"id": "torso", "swap": "fish:fish_body"}]}},

    "m06_house_tall": {
        "version": "1.3", "style": "low_poly", "detail_level": 3,
        "root": {"id": "house", "ref": "architecture:house",
                 "params": {},
                 "effects": [{"type": "fx:lanky", "amount": 0.8,
                              "scope": "subtree"},
                             {"type": "fx:bend", "amount": 0.3,
                              "scope": "subtree"}]}},

    "m07_dragon": {
        "version": "1.3", "style": "low_poly", "detail_level": 2,
        "root": {"id": "body", "ref": "fish:fish_body",
                 "children": [{"id": "head", "swap": "creature:dragon_head"},
                              {"id": "wing_l", "ref": "fantasy:wing"},
                              {"id": "wing_r", "ref": "fantasy:wing"}]}},

    "m08_tree": {
        "version": "1.3", "style": "low_poly", "detail_level": 3,
        "traits": [{"trait": "tree:leafiness", "value": 0.9, "scope": "subtree"}],
        "root": {"id": "tree", "ref": "tree_stylized:tree",
                 "params": {"asymmetry": 0.9}}},
}

outdir = Path(sys.argv[1])
outdir.mkdir(parents=True, exist_ok=True)
from app.ui.offscreen import render                  # noqa: E402

rows = []
for name, plan in PLANS.items():
    s = Session(provider=OfflineProvider(), planner=MockPlanner())
    t0 = time.perf_counter()
    r = s.build(plan, Options(style="low_poly",
                              detail_level=plan.get("detail_level", 2)))
    secs = round(time.perf_counter() - t0, 3)
    refs = ["%s->%s" % (n.id, n.ref) for n in r.resolved.walk()] \
        if r.resolved is not None else []
    row = {"name": name, "ok": r.ok, "tris": r.triangles, "seconds": secs,
           "nodes": len(refs), "refs": refs,
           "diag": [str(d)[:200] for d in (r.diagnostics or [])][:8],
           "report": r.report.describe()[:1200] if r.report is not None else "",
           "structural": str(r.structural.to_dict())[:600] if r.structural else "",
           "traits": str(r.traits.to_dict())[:600] if r.traits else "",
           "concept": str(r.concept_resolution.to_dict())[:900]
                      if r.concept_resolution else ""}
    scene = r.scene(s.catalog())
    if scene is not None and scene.triangle_count:
        imgs = []
        for label, az, el in (("front", 0.0, 8.0), ("three_quarter", 38.0, 16.0),
                              ("side", 90.0, 6.0)):
            p = outdir / f"{name}_{label}.png"
            render(scene, p, size=(760, 520), azimuth=az, elevation=el)
            imgs.append(p.name)
        row["images"] = imgs
    rows.append(row)
    print(name, "ok" if r.ok else "FAIL", r.triangles, "tris", len(refs),
          "nodes", secs, "s", flush=True)

(outdir / "metrics_manual.json").write_text(
    json.dumps(rows, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
