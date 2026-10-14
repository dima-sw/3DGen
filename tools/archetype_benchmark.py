"""Generate deterministic Archetypes + Profiles V1 benchmark artifacts."""
from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.build.exporter import export
from app.core.planner.planner import (LLMPlanner, SISTEMA, MockPlanner,
                                      PlanRequest)
from app.core.planner.schema import plan_schema
from app.core.planner.vocabulary import build_vocabulary
from app.core.registry import load
from app.core.session import Options, Session
from app.ui.offscreen import render


PLUGIN_ROOT = ROOT / "app" / "plugins"
OUTPUT = ROOT / "output" / "archetype_benchmark"

CASES = {
    "lynx_no_plugin": {
        "prompt": "crea una lince low-poly",
        "concept": {
            "requested": "lynx",
            "archetypes": ["archetype_metadata:felid"],
            "adaptations": [
                {"param": "tail_length", "value": 0.76},
                {"param": "ear_size", "value": 1.28},
                {"param": "leg_length", "value": 0.78},
                {"description": "large paws"},
                {"trait": "std:ear_super_lynx_factor", "value": 1.0},
            ],
        },
    },
    "dune_buggy_no_plugin": {
        "prompt": "dune buggy low-poly",
        "concept": {
            "requested": "dune buggy",
            "archetypes": ["archetype_metadata:car_like"],
            "adaptations": [
                {"param": "wheel_size", "value": 0.82},
                {"param": "ground_clearance", "value": 0.42},
                {"description": "open cabin"},
            ],
        },
    },
    "bonsai_no_plugin": {
        "prompt": "bonsai low-poly",
        "concept": {
            "requested": "bonsai",
            "archetypes": ["archetype_metadata:tree"],
            "adaptations": [
                {"param": "height", "value": 1.8},
                {"param": "crown_width", "value": 2.8},
                {"param": "trunk_width", "value": 0.62},
                {"param": "branch_spread", "value": 1.2},
            ],
        },
    },
    "eagle_unrepresentable": {
        "prompt": "eagle low-poly",
        "concept": {
            "requested": "eagle",
            "archetypes": ["archetype_metadata:raptor"],
            "adaptations": [
                {"description": "wing pair"},
                {"description": "beak"},
                {"description": "talons"},
            ],
        },
    },
}


def dump(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")


def diagnostics(report) -> list[dict]:
    return [{"code": d.code, "message": d.message, "where": d.where,
             "why": d.why, "severity": d.severity,
             "alternatives": list(d.alternatives)} for d in report.sorted()]


def payload_metrics(registry) -> dict:
    vocabulary_object = build_vocabulary(registry)
    vocabulary = vocabulary_object.to_dict()
    baseline_vocabulary = replace(
        vocabulary_object, archetypes=(), archetype_details=(), profiles=(), bindings=())
    global_vocabulary = replace(
        vocabulary_object, archetype_details=(), profiles=(), bindings=())

    def request_bytes(current) -> int:
        request = PlanRequest(prompt="crea una lince low-poly", vocabulary=current,
                              style="low_poly", detail_level=3, seed=17)
        message, _ = LLMPlanner._render_message(request)
        return LLMPlanner._estimate_payload(SISTEMA, message, plan_schema())

    sizes = {
        "baseline_bytes": request_bytes(baseline_vocabulary),
        "with_global_index_bytes": request_bytes(global_vocabulary),
        "with_shortlist_bytes": request_bytes(vocabulary_object),
        "global_index_entries": len(vocabulary["archetypes"]),
        "shortlist_entries": len(vocabulary["archetype_details"]),
        "shortlist_limit": vocabulary_object.metadata["concept_shortlist_limit"],
    }
    sizes["increase_percent"] = round(
        (sizes["with_shortlist_bytes"] - sizes["baseline_bytes"])
        * 100.0 / sizes["baseline_bytes"], 3)
    return sizes


def main() -> None:
    registry = load([PLUGIN_ROOT]).freeze()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    summary = {"payload": payload_metrics(registry), "cases": {}}
    views = {
        "front": {"azimuth": 0.0, "elevation": 12.0},
        "side": {"azimuth": 90.0, "elevation": 12.0},
        "three_quarter": {"azimuth": 38.0, "elevation": 16.0},
    }

    for name, case in CASES.items():
        folder = OUTPUT / name
        folder.mkdir(parents=True, exist_ok=True)
        semantic_plan = {"version": "1.3", "style": "low_poly",
                         "detail_level": 3, "seed": 17,
                         "concept": case["concept"]}
        planner = MockPlanner(scripts={case["prompt"]: semantic_plan})
        session = Session(registry=registry, planner=planner)
        result = session.generate(case["prompt"], Options(
            detail_level=3, seed=17, check=True, repair=False), remember=False)
        resolution = result.concept_resolution
        resolved = resolution.to_dict() if resolution else {}
        dump(folder / "semantic_plan.json", semantic_plan)
        dump(folder / "concept_resolution.json", resolved)
        dump(folder / "coverage.json", resolved.get("coverage", []))
        dump(folder / "provenance.json", resolved.get("provenance", {}))
        dump(folder / "diagnostics.json", diagnostics(result.report))
        if result.plan is not None:
            dump(folder / "composition_graph.json", result.plan.to_dict())

        reload_ok = False
        if result.build is not None and result.plan is not None:
            scene = result.scene(registry)
            for view, camera in views.items():
                render(scene, folder / (view + ".png"), **camera, textured=False)
            export(scene, folder / "model.glb", save_plan=False, textured=False)
            reload_planner = MockPlanner()
            reloaded = Session(registry=registry, planner=reload_planner).build(
                result.plan.to_dict(), Options(check=False))
            reload_ok = bool(reloaded.report.ok and reloaded.build is not None
                             and not reload_planner.calls)

        summary["cases"][name] = {
            "build_valid": bool(result.report.ok and result.build is not None),
            "selected_root": resolved.get("selected_root_implementation", ""),
            "selected_binding": resolved.get("selected_binding", ""),
            "supported": len(resolved.get("coverage", [{}])[0].get("supported", []))
                         if resolved.get("coverage") else 0,
            "unsupported": len(resolved.get("unsupported", [])),
            "reload_without_planner": reload_ok,
            "diagnostic_codes": sorted(result.report.codes()),
            "triangles": result.triangles,
        }

    dump(OUTPUT / "summary.json", summary)
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
