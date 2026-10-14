"""Build the three Structural Traits + Deterministic Layout benchmarks."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.build.assembler import build
from app.build.exporter import export
from app.build.scene import to_scene
from app.build.validate import validate
from app.core.effect import apply_effects
from app.core.errors import Report
from app.core.graph import CompositionGraph
from app.core.layout import resolve_layout
from app.core.registry import load
from app.core.resolver import resolve
from app.core.structural import StructuralTraitRequest, resolve_structural_traits
from app.core.traits import resolve_traits
from app.ui.offscreen import render


PLUGIN_ROOT = ROOT / "app" / "plugins"
OUTPUT = ROOT / "output" / "structural_layout_benchmark"

CASES = (
    ("nine_tail_fox", "fox", "fox_stylized:fox", "fantasy:tail_count", 9,
     "fox/body"),
    ("ten_wheel_car", "car", "vehicle_stylized:car", "vehicle:wheel_count", 10,
     "car/wheel_fl"),
    ("six_arm_humanoid", "corpo", "humanoid_anatomical:body",
     "character:arm_count", 6, "corpo/torso/arm_l"),
)


def _case(registry, root_id, root_ref, trait, count, target):
    graph = CompositionGraph(detail_level=1, seed=0)
    graph.set_root(root_id, root_ref)
    graph.structural_traits = [StructuralTraitRequest(trait, count, on=target)]
    report = Report()
    structural = resolve_structural_traits(graph, registry, report=report)
    resolved = resolve(graph, registry, report=report)
    semantic = resolve_traits(resolved, registry, report=report)
    layout = resolve_layout(resolved, registry, report=report)
    effects = apply_effects(resolved, registry, report=report)
    built = build(effects, report=report)
    validate(built, style=registry.style("low_poly"), report=report)
    if not report.ok:
        raise RuntimeError(report.describe())
    return graph, structural, semantic, layout, built, report


def _counts(resolved):
    counts = {}
    sides = {}
    for node in resolved.walk():
        role = node.component.role
        if not role:
            continue
        counts[role] = counts.get(role, 0) + 1
        side = getattr(node.link, "side", "") if node.link else ""
        if side:
            sides.setdefault(role, {})[side] = sides.setdefault(role, {}).get(side, 0) + 1
    return counts, sides


def main():
    registry = load([PLUGIN_ROOT]).freeze()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    summary = {}
    for name, root_id, root_ref, trait, count, target in CASES:
        graph, structural, semantic, layout, built, report = _case(
            registry, root_id, root_ref, trait, count, target)
        folder = OUTPUT / name
        folder.mkdir(parents=True, exist_ok=True)
        scene = to_scene(built, registry, plan=graph, ground=True)
        render(scene, folder / "canonical.png", azimuth=35.0, elevation=15.0,
               textured=False)
        if name == "nine_tail_fox":
            render(scene, folder / "front.png", azimuth=0.0, elevation=12.0,
                   textured=False)
            render(scene, folder / "rear.png", azimuth=180.0, elevation=12.0,
                   textured=False)
            render(scene, folder / "three_quarter.png", azimuth=38.0,
                   elevation=16.0, textured=False)
        export(scene, folder / "model.glb", save_plan=False, textured=False)
        (folder / "graph_rewrite_plan.json").write_text(
            json.dumps(structural.plan.to_dict(), indent=2, sort_keys=True),
            encoding="utf-8")
        (folder / "layout_plan.json").write_text(
            json.dumps(layout.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
        provenance = {"structural": structural.to_dict(),
                      "layout": layout.to_dict(),
                      "semantic": semantic.to_dict()}
        (folder / "provenance.json").write_text(
            json.dumps(provenance, indent=2, sort_keys=True), encoding="utf-8")
        counts, sides = _counts(built.composition)
        summary[name] = {
            "requested": count,
            "graph_nodes": len(graph.nodes),
            "resolved_nodes": len(built.nodes),
            "placements": len(layout.placements),
            "triangles": built.triangles,
            "role_counts": counts,
            "side_counts": sides,
            "layout_problems": [p.to_dict() for p in layout.problems],
            "diagnostic_codes": sorted(set(d.code for d in report)),
            "files": ["canonical.png", "model.glb", "graph_rewrite_plan.json",
                       "layout_plan.json", "provenance.json"] + (
                           ["front.png", "rear.png", "three_quarter.png"]
                           if name == "nine_tail_fox" else []),
        }
    (OUTPUT / "metrics.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
