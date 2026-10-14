"""Production diagnostics for Archetypes + Profiles V1.

Offline mode measures payloads, direct-path regressions, and deterministic
geometry deltas. ``--network`` additionally performs safe provider/planner
smokes and writes only provenance and validated plans, never credentials.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.ai.provider import ChatProvider
from app.core.config import SETTINGS
from app.core.planner.planner import LLMPlanner, MockPlanner, PlanRequest, SISTEMA
from app.core.planner.schema import plan_schema
from app.core.registry import load
from app.core.session import Options, Session
from app.ui.offscreen import render


PLUGIN_ROOT = ROOT / "app" / "plugins"
OUTPUT = ROOT / "output" / "archetype_validation"
PROMPT = "crea una lince low-poly"
VIEWS = {
    "front": {"azimuth": 0.0, "elevation": 12.0},
    "side": {"azimuth": 90.0, "elevation": 12.0},
    "three_quarter": {"azimuth": 38.0, "elevation": 16.0},
}

CASES = {
    "lynx": {
        "folder": "real_lynx", "prompt": PROMPT,
        "root": "fox_stylized:fox",
        "concept": {"requested": "lynx",
                    "archetypes": ["archetype_metadata:felid"],
                    "adaptations": [
                        {"param": "tail_length", "value": 0.76},
                        {"param": "ear_size", "value": 1.28},
                        {"param": "leg_length", "value": 0.78},
                        {"description": "large paws"},
                        {"trait": "std:ear_super_lynx_factor", "value": 1.0},
                    ]},
    },
    "buggy": {
        "folder": "real_buggy", "prompt": "dune buggy low-poly",
        "root": "vehicle_stylized:car",
        "concept": {"requested": "dune buggy",
                    "archetypes": ["archetype_metadata:car_like"],
                    "adaptations": [
                        {"param": "wheel_size", "value": 0.82},
                        {"param": "ground_clearance", "value": 0.42},
                        {"description": "open cabin"},
                    ]},
    },
    "bonsai": {
        "folder": "real_bonsai", "prompt": "bonsai low-poly",
        "root": "tree_stylized:tree",
        "concept": {"requested": "bonsai",
                    "archetypes": ["archetype_metadata:tree"],
                    "adaptations": [
                        {"param": "height", "value": 1.8},
                        {"param": "crown_width", "value": 2.8},
                        {"param": "trunk_width", "value": 0.62},
                        {"param": "branch_spread", "value": 1.2},
                    ]},
    },
    "eagle": {
        "folder": "eagle_semantic", "prompt": "aquila low-poly",
        "root": "",
        "concept": {"requested": "eagle",
                    "archetypes": ["archetype_metadata:raptor"],
                    "adaptations": [
                        {"description": "wing pair"},
                        {"description": "beak"},
                        {"description": "talons"},
                    ]},
    },
}


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True,
                               ensure_ascii=False), encoding="utf-8")


def json_bytes(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False,
                          separators=(",", ":")).encode("utf-8"))


def request_payload(provider: ChatProvider, system: str, user: str,
                    schema: dict | None) -> dict:
    payload = {
        "model": provider.model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "temperature": 0.2,
        "max_tokens": int(provider.spec.max_output_tokens),
    }
    if schema is not None and provider.structured:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "piano", "strict": False,
                            "schema": schema},
        }
    elif provider.spec.json_mode:
        payload["response_format"] = {"type": "json_object"}
    return payload


def rendered(vocabulary, compact: bool, prompt: str = PROMPT) -> str:
    request = PlanRequest(prompt=prompt, vocabulary=vocabulary,
                          style="low_poly", detail_level=3, seed=17)
    return LLMPlanner._render_message(request, compact=compact)[0]


def payload_audit(registry) -> dict:
    vocabulary = Session(registry=registry, planner=MockPlanner()).vocabulary()
    schema = plan_schema()
    baseline = replace(vocabulary, archetypes=(), archetype_details=(),
                       profiles=(), bindings=())
    global_only = replace(vocabulary, archetype_details=(), profiles=(), bindings=())

    def estimated(current) -> int:
        return LLMPlanner._estimate_payload(
            SISTEMA, rendered(current, False), schema)

    audit: dict[str, Any] = {
        "comparison_context": {
            "historical_pre_compaction_estimate_bytes": 42215,
            "historical_compact_estimate_bytes": 22089,
            "original_archetype_benchmark_normal_bytes": {
                "baseline": 45862,
                "global_index": 46674,
                "shortlist": 47744,
            },
            "production_before_shared_param_refs_bytes": 26004,
            "note": "Historical values are retained from the approved task reports.",
        },
        "explanation": (
            "The legacy benchmark serializes the normal planner form. Production "
            "selects compact per provider budget, then ChatProvider adds its actual "
            "model/output fields and provider-specific response_format."),
        "benchmark_normal_estimate": {
            "baseline_bytes": estimated(baseline),
            "with_global_index_bytes": estimated(global_only),
            "with_shortlist_bytes": estimated(vocabulary),
        },
        "providers": {},
    }
    groups = {
        "component_vocabulary": ("components",),
        "traits_vocabulary": ("traits",),
        "structural_traits_vocabulary": ("structural_traits",),
        "archetype_global_index": ("archetypes",),
        "detailed_shortlist": ("archetype_details",),
        "other_vocabulary": ("capabilities", "effects", "styles", "profiles",
                             "plugins", "tags", "bindings"),
    }
    for name in ("groq", "cloudflare", "cohere"):
        provider = ChatProvider(name)
        normal = rendered(vocabulary, False)
        compact = rendered(vocabulary, True)
        compact_selected = bool(provider.input_budget and
                                LLMPlanner._estimate_payload(
                                    SISTEMA, normal, schema) > provider.input_budget)
        user = compact if compact_selected else normal
        payload = request_payload(provider, SISTEMA, user, schema)
        total = json_bytes(payload)
        breakdown = {}
        for label, fields in groups.items():
            empty = replace(vocabulary, **{field: () for field in fields})
            breakdown[label + "_bytes"] = total - json_bytes(request_payload(
                provider, SISTEMA, rendered(empty, compact_selected), schema))
        without_system = request_payload(provider, "", user, schema)
        breakdown["system_prompt_bytes"] = total - json_bytes(without_system)
        if provider.structured:
            no_schema = request_payload(provider, SISTEMA, user, {})
            breakdown["planner_schema_bytes"] = total - json_bytes(no_schema)
        else:
            breakdown["planner_schema_bytes"] = 0
        breakdown["conversation_history_bytes"] = 0
        attributed = sum(breakdown.values())
        breakdown["other_bytes"] = total - attributed
        base_payload = request_payload(provider, SISTEMA,
                                       rendered(baseline, compact_selected), schema)
        global_payload = request_payload(provider, SISTEMA,
                                         rendered(global_only, compact_selected), schema)
        direct_user = rendered(vocabulary, compact_selected, prompt="fox")
        direct_total = json_bytes(request_payload(
            provider, SISTEMA, direct_user, schema))
        direct_without_shortlist = json_bytes(request_payload(
            provider, SISTEMA,
            rendered(replace(vocabulary, archetype_details=()),
                     compact_selected, prompt="fox"), schema))
        audit["providers"][name] = {
            "configured": SETTINGS.configured(name),
            "selected_serialization": "compact" if compact_selected else "normal",
            "input_budget_bytes": provider.input_budget,
            "serialized_http_request_prompt_messages_bytes": json_bytes(
                {"messages": payload["messages"]}),
            "user_prompt_bytes": len(user.encode("utf-8")),
            "normal_actual_body_bytes": json_bytes(request_payload(
                provider, SISTEMA, normal, schema)),
            "compact_actual_body_bytes": json_bytes(request_payload(
                provider, SISTEMA, compact, schema)),
            "selected_actual_body_bytes": total,
            "selected_before_archetypes_bytes": json_bytes(base_payload),
            "selected_with_global_index_bytes": json_bytes(global_payload),
            "selected_with_shortlist_bytes": total,
            "direct_prompt_actual_body_bytes": direct_total,
            "direct_prompt_detailed_shortlist_bytes": (
                direct_total - direct_without_shortlist),
            "breakdown_note": "Vocabulary values are marginal serialized deltas.",
            "breakdown": breakdown,
        }
    dump(OUTPUT / "payload" / "audit.json", audit)
    return audit


def diagnostics(result) -> list[dict]:
    return [{"code": d.code, "message": d.message, "where": d.where,
             "why": d.why, "severity": d.severity,
             "alternatives": list(d.alternatives)}
            for d in result.report.sorted()]


def direct_regressions(registry) -> dict:
    report = {}
    for prompt in ("fox", "car", "tree", "humanoid"):
        result = Session(registry=registry, planner=MockPlanner()).generate(
            prompt, Options(detail_level=2, seed=17, check=False, repair=False),
            remember=False)
        root = result.plan.node(result.plan.root_id).ref if result.plan else ""
        report[prompt] = {
            "planner": result.planner,
            "root": root,
            "concept_resolution_used": result.concept_resolution is not None,
            "valid": bool(result.report.ok and result.build is not None),
            "diagnostic_codes": sorted(result.report.codes()),
        }
    dump(OUTPUT / "payload" / "direct_regressions.json", report)
    return report


def union_bounds(nodes) -> np.ndarray | None:
    bounds = [node.mesh.bounds for node in nodes if node.mesh is not None]
    if not bounds:
        return None
    return np.array([np.min([b[0] for b in bounds], axis=0),
                     np.max([b[1] for b in bounds], axis=0)])


def role_bounds(result, role: str) -> np.ndarray | None:
    return union_bounds([node for node in result.build.geometry()
                         if node.role == role])


def dimension(bounds: np.ndarray | None, axis: int) -> float:
    return 0.0 if bounds is None else float(bounds[1][axis] - bounds[0][axis])


def geom_metrics(case: str, result) -> dict[str, float]:
    size = result.build.size
    if case == "lynx":
        torso = role_bounds(result, "torso")
        head = role_bounds(result, "head")
        return {
            "tail_relative_length": dimension(role_bounds(result, "tail"), 2) /
                                    dimension(torso, 2),
            "ear_relative_height": dimension(role_bounds(result, "ears"), 1) /
                                   dimension(head, 1),
            "leg_relative_length": dimension(role_bounds(result, "limb"), 1) /
                                   dimension(torso, 1),
        }
    if case == "buggy":
        body = role_bounds(result, "vehicle_body")
        wheels = role_bounds(result, "wheel")
        return {
            "wheel_relative_size": dimension(wheels, 1) / dimension(body, 1),
            "ground_clearance": float(body[0][1] - wheels[0][1]),
            "body_width_length_ratio": dimension(body, 0) / dimension(body, 2),
        }
    trunk = role_bounds(result, "tree_trunk")
    crown = role_bounds(result, "tree_crown")
    branches = role_bounds(result, "tree_branch")
    return {
        "height": float(size[1]),
        "trunk_width_height_ratio": dimension(trunk, 0) / dimension(trunk, 1),
        "crown_width_height_ratio": dimension(crown, 0) / dimension(crown, 1),
        "branch_spread": dimension(branches, 0),
    }


def visual_postmortem(registry) -> dict:
    metric_for_param = {
        "lynx": {"tail_length": "tail_relative_length",
                 "ear_size": "ear_relative_height",
                 "leg_length": "leg_relative_length"},
        "buggy": {"wheel_size": "wheel_relative_size",
                  "ground_clearance": "ground_clearance"},
        "bonsai": {"height": "height",
                   "trunk_width": "trunk_width_height_ratio",
                   "crown_width": "crown_width_height_ratio",
                   "branch_spread": "branch_spread"},
    }
    summary = {}
    for name in ("lynx", "buggy", "bonsai"):
        case = CASES[name]
        canonical = Session(registry=registry, planner=MockPlanner()).build(
            {"version": "1.0", "style": "low_poly", "detail_level": 3,
             "seed": 17, "root": {"id": "root", "ref": case["root"]}},
            Options(detail_level=3, seed=17, check=False))
        semantic = {"version": "1.3", "style": "low_poly", "detail_level": 3,
                    "seed": 17, "concept": case["concept"]}
        adapted = Session(registry=registry, planner=MockPlanner(
            scripts={case["prompt"]: semantic})).generate(
                case["prompt"], Options(detail_level=3, seed=17, check=False,
                                        repair=False), remember=False)
        folder = OUTPUT / "visual_postmortem" / name
        for label, result in (("canonical", canonical), ("adapted", adapted)):
            scene = result.scene(registry)
            for view, camera in VIEWS.items():
                render(scene, folder / (label + "_" + view + ".png"),
                       textured=False, **camera)
        before = geom_metrics(name, canonical)
        after = geom_metrics(name, adapted)
        resolution = adapted.concept_resolution.to_dict()
        selected = resolution.get("coverage", [{}])[0]
        supported = selected.get("supported", [])
        applied = resolution.get("materialized_params", {})
        statuses = []
        for adaptation in case["concept"]["adaptations"]:
            param = adaptation.get("param", "")
            metric = metric_for_param[name].get(param, "")
            is_supported = any(
                all(candidate.get(key) == value
                    for key, value in adaptation.items())
                for candidate in supported)
            is_applied = param in applied if param else False
            delta = (after[metric] - before[metric]) if metric else 0.0
            relative = abs(delta) / max(abs(before.get(metric, 0.0)), 1e-9)
            statuses.append({
                "adaptation": adaptation,
                "status": {
                    "supported": is_supported,
                    "applied": is_applied,
                    "effective": bool(is_applied and metric and relative > 0.01),
                },
                "metric": metric,
                "before": before.get(metric),
                "after": after.get(metric),
                "relative_change_percent": round(relative * 100.0, 3),
            })
        case_report = {
            "canonical_root": case["root"],
            "adapted_root": resolution.get("selected_root_implementation", ""),
            "same_root_topology_proxy": (
                resolution.get("selected_root_implementation") == case["root"]),
            "before": before, "after": after,
            "adaptations": statuses,
            "unsupported": resolution.get("unsupported", []),
        }
        dump(folder / "metrics.json", case_report)
        summary[name] = case_report
    dump(OUTPUT / "visual_postmortem" / "summary.json", summary)
    return summary


def safe_result(result, provider: ChatProvider) -> dict:
    resolution = (result.concept_resolution.to_dict()
                  if result.concept_resolution is not None else {})
    proposal = (dict(result.plan_json.get("concept") or {})
                if isinstance(result.plan_json, dict) else {})
    rejected = [item for item in resolution.get("diagnostics", [])
                if item.get("code") in {"ARCHETYPE_NOT_FOUND",
                                        "ARCHETYPE_ALIAS_AMBIGUOUS",
                                        "PROFILE_NOT_FOUND",
                                        "PROFILE_ALIAS_AMBIGUOUS"}]
    selected = next((item for item in resolution.get("coverage", [])
                     if item.get("candidate") == resolution.get("selected_binding")), {})
    return {
        "prompt": result.prompt,
        "requested_provider": result.requested_provider,
        "actual_provider": result.actual_provider,
        "requested_model": result.requested_model,
        "actual_model": result.actual_model,
        "llm_semantic_proposal": proposal,
        "planner_plan": result.plan_json,
        "validated_archetypes": resolution.get("archetypes", []),
        "rejected_semantic_ids": rejected,
        "candidate_bindings": resolution.get("candidate_bindings", []),
        "ranking": resolution.get("coverage", []),
        "selected_binding": resolution.get("selected_binding", ""),
        "selected_implementation": resolution.get(
            "selected_root_implementation", ""),
        "supported_adaptations": selected.get("supported", []),
        "unsupported_adaptations": resolution.get("unsupported", []),
        "repair_used": result.repaired,
        "final_build": "valid" if result.report.ok and result.build is not None
                       else "invalid",
        "triangles": result.triangles,
        "diagnostics": diagnostics(result),
        "provider_request_metrics": dict(provider.last_request_metrics),
        "provenance": result.provenance,
    }


def network_validation(registry, providers: list[str], real_provider: str,
                       case_names: list[str], delay: float) -> dict:
    preflight_path = OUTPUT / "payload" / "provider_planner_preflight.json"
    try:
        preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        preflight = {}
    for name in providers:
        provider = ChatProvider(name)
        provider.allow_local_fallback = False
        try:
            result = Session(provider=provider, registry=registry).plan(
                PROMPT, Options(style="low_poly", detail_level=3, seed=17,
                                check=False, repair=False))
            preflight[name] = {
                "status": "ok", "http": provider.last_status_code,
                "planner": result.planner,
                "plan_shape": "concept" if result.concept_resolution else "root",
                "report_ok": result.report.ok,
                "diagnostic_codes": sorted(result.report.codes()),
                "request_metrics": dict(provider.last_request_metrics),
            }
        except Exception as exc:
            preflight[name] = {
                "status": provider.last_outcome,
                "http": provider.last_status_code,
                "safe_error": provider._safe(str(exc)),
                "request_metrics": dict(provider.last_request_metrics),
            }
    dump(preflight_path, preflight)

    runs = {}
    for index, name in enumerate(case_names):
        case = CASES[name]
        provider = ChatProvider(real_provider)
        provider.allow_local_fallback = False
        try:
            result = Session(provider=provider, registry=registry).generate(
                case["prompt"], Options(style="low_poly", detail_level=3,
                                        seed=17, check=True, repair=True),
                remember=False)
            report = safe_result(result, provider)
        except Exception as exc:
            report = {
                "prompt": case["prompt"],
                "requested_provider": real_provider,
                "actual_provider": "",
                "status": provider.last_outcome,
                "http": provider.last_status_code,
                "safe_error": provider._safe(str(exc)),
                "provider_request_metrics": dict(provider.last_request_metrics),
                "final_build": "invalid",
            }
        dump(OUTPUT / case["folder"] / "report.json", report)
        runs[name] = report
        if delay > 0 and index + 1 < len(case_names):
            time.sleep(delay)

    # Older reports from an interrupted validation can be normalized without
    # repeating paid/rate-limited calls. The materialized plan retains the
    # exact concept object returned by the planner.
    for case in CASES.values():
        path = OUTPUT / case["folder"] / "report.json"
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        planner_plan = report.get("planner_plan")
        if isinstance(planner_plan, dict) and isinstance(
                planner_plan.get("concept"), dict):
            report["llm_semantic_proposal"] = dict(planner_plan["concept"])
            dump(path, report)
    reliability_path = OUTPUT / "payload" / "single_planner_reliability.json"
    if runs:
        reliability = {
            "number_runs": len(runs),
            "semantic_mapping_valid_first_try": sum(
                1 for value in runs.values()
                if value.get("llm_semantic_proposal") and
                not value.get("repair_used")),
            "repair_required": sum(bool(value.get("repair_used"))
                                   for value in runs.values()),
            "invalid_ids_proposed": sum(
                len(value.get("rejected_semantic_ids", []))
                for value in runs.values()),
            "backend_rejection": sum(
                1 for value in runs.values()
                if any(item.get("severity") == "error"
                       for item in value.get("diagnostics", []))),
            "successful_build": sum(value.get("final_build") == "valid"
                                    for value in runs.values()),
        }
        dump(reliability_path, reliability)
    else:
        try:
            reliability = json.loads(reliability_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            reliability = {"number_runs": 0}
    return {"preflight": preflight, "reliability": reliability}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network", action="store_true")
    parser.add_argument("--providers", default="groq,cloudflare,cohere")
    parser.add_argument("--real-provider", default="groq")
    parser.add_argument("--cases", default=",".join(CASES))
    parser.add_argument("--delay", type=float, default=0.0)
    args = parser.parse_args()
    registry = load([PLUGIN_ROOT]).freeze()
    summary = {
        "payload": payload_audit(registry),
        "direct": direct_regressions(registry),
        "visual": visual_postmortem(registry),
    }
    if args.network:
        providers = [name.strip() for name in args.providers.split(",")
                     if name.strip()]
        case_names = [name.strip() for name in args.cases.split(",")
                      if name.strip()]
        unknown = [name for name in case_names if name not in CASES]
        if unknown:
            parser.error("unknown cases: %s" % ", ".join(unknown))
        summary["network"] = network_validation(registry, providers,
                                                args.real_provider, case_names,
                                                max(args.delay, 0.0))
    dump(OUTPUT / "summary.json", summary)
    print(json.dumps({
        "payload": {name: data["selected_actual_body_bytes"]
                    for name, data in summary["payload"]["providers"].items()},
        "direct": summary["direct"],
        "visual_effective": {
            name: {item["adaptation"].get("param") or
                   item["adaptation"].get("description") or
                   item["adaptation"].get("trait"): item["status"]
                  for item in report["adaptations"]}
            for name, report in summary["visual"].items()},
        "network": summary.get("network", {}),
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
