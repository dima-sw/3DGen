"""Generate the fox benchmark renders, GLBs and diagnostic metrics.

This is deliberately a small benchmark harness rather than runtime plugin
logic.  It keeps the canonical view order and the metric interpretation
repeatable without adding fox knowledge to the core.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import trimesh

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.build.assembler import build
from app.build.exporter import export
from app.build.validate import silhouette_fill, validate
from app.build.visual import _dense_points, _solidity, analyse, silhouette
from app.core.graph import CompositionGraph
from app.core.registry import load
from app.core.resolved import ResolvedComposition
from app.core.scene import Scene, SceneNode
from app.geometry.kernel import faces_per_normal
from app.core.effect import apply_effects
from app.core.resolver import resolve
from app.ui.offscreen import render


PLUGIN_ROOT = ROOT / "app" / "plugins"
OUTPUT = ROOT / "output" / "fox_stylized_benchmark"


def _scene(out, registry, graph) -> Scene:
    scene = Scene(plan=graph)
    for node in out.geometry():
        scene.add(SceneNode(id=node.id, name=node.ref, mesh=node.mesh.copy(),
                            material=registry.material(node.material),
                            tags=list(node.tags)))
    return scene


def _rotated_fill(mesh: trimesh.Trimesh, angle: float, cells: int = 32) -> float:
    turned = mesh.copy()
    turned.apply_transform(trimesh.transformations.rotation_matrix(
        np.radians(angle), (0.0, 1.0, 0.0)))
    bounds = turned.bounds
    points = _dense_points(turned, target=cells * cells * 18)
    mask = silhouette(points, (0, 1), grid=cells, bounds=(bounds[0], bounds[1]))
    return _solidity(mask)


def _hierarchy(out) -> dict[str, int | float]:
    totals = {"primary": 0, "secondary": 0, "accents": 0}
    for node in out.geometry():
        counts = node.piece.metadata.get("hierarchy_triangles", {})
        for key in totals:
            totals[key] += int(counts.get(key, 0))
    total = sum(totals.values()) or 1
    return {
        **totals,
        "primary_percent": round(totals["primary"] * 100.0 / total, 2),
        "secondary_percent": round(totals["secondary"] * 100.0 / total, 2),
        "accents_percent": round(totals["accents"] * 100.0 / total, 2),
    }


def build_detail(registry, detail: int):
    graph = CompositionGraph(detail_level=detail, seed=0)
    graph.set_root("fox", "fox_stylized:fox")
    resolved: ResolvedComposition = resolve(graph, registry)
    if not resolved.ok:
        raise RuntimeError(resolved.report.describe())
    result = build(apply_effects(resolved, registry), report=resolved.report)
    diagnostics = validate(result, style=registry.style("low_poly"))
    if diagnostics.errors():
        raise RuntimeError(diagnostics.describe())
    return graph, result, _scene(result, registry, graph), diagnostics


def main() -> None:
    registry = load([PLUGIN_ROOT]).freeze()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    metrics = {"benchmark": "fox_stylized", "details": {}}

    views = {
        "front": {"azimuth": 0.0, "elevation": 12.0},
        "side": {"azimuth": 90.0, "elevation": 12.0},
        "three_quarter": {"azimuth": 38.0, "elevation": 16.0},
        "back_three_quarter": {"azimuth": 142.0, "elevation": 16.0},
    }
    for detail in (1, 2, 3):
        graph, out, scene, diagnostics = build_detail(registry, detail)
        folder = OUTPUT / f"detail_{detail}"
        folder.mkdir(parents=True, exist_ok=True)
        for name, camera in views.items():
            if detail < 3 and name == "back_three_quarter":
                continue
            render(scene, folder / f"{name}.png", **camera, textured=False)
        export(scene, folder / "fox.glb", save_plan=False, textured=False)

        report = analyse(scene)
        combined = out.combined()
        dims = [float(v) for v in out.size]
        metrics["details"][str(detail)] = {
            "node_count": len(out.nodes),
            "piece_count": len(list(out.geometry())),
            "triangles": out.triangles,
            "bounds": [[round(float(v), 6) for v in row] for row in out.bounds],
            "height": round(dims[1], 6),
            "length": round(dims[2], 6),
            "visible_parts": report.visible_parts,
            "hidden_parts": report.hidden_parts,
            "largest_part_share": round(report.largest_share, 6),
            "blobbiness": round(report.blobbiness, 6),
            "faces_per_normal": round(
                faces_per_normal(combined) if combined is not None else 0.0, 6),
            "silhouette_fill": {
                "front": round(silhouette_fill(out, axis=2), 6),
                "side": round(silhouette_fill(out, axis=0), 6),
                "three_quarter": round(_rotated_fill(combined, 38.0), 6),
            },
            "visual_solidity": {k: round(v, 6) for k, v in report.solidity.items()},
            "hierarchy": _hierarchy(out),
            "validation_codes": sorted(set(diagnostics.codes())),
            "paths": [node.node.path for node in out.walk()],
        }

    (OUTPUT / "metrics.json").write_text(
        json.dumps(metrics, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(metrics, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
