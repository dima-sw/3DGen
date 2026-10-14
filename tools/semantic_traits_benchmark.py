"""Generate small visual benchmarks for Semantic Traits V1."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.ai.provider import OfflineProvider
from app.build.exporter import export
from app.core.graph import CompositionGraph
from app.core.session import Options, Session
from app.core.traits import TraitRequest
from app.ui.offscreen import render


OUTPUT = ROOT / "output" / "semantic_traits_benchmark"


def _session() -> Session:
    session = Session(provider=OfflineProvider())
    session.catalog()
    return session


def _body_mass(value: float) -> CompositionGraph:
    graph = CompositionGraph(style="low_poly", detail_level=2, seed=11)
    graph.set_root("root", "humanoid_anatomical:body")
    graph.traits = [TraitRequest("body_mass", value)]
    return graph


def _leafiness(value: float) -> CompositionGraph:
    graph = CompositionGraph(style="low_poly", detail_level=2, seed=7)
    graph.set_root("tree", "tree_stylized:tree")
    graph.traits = [TraitRequest("leafiness", value)]
    return graph


def _write_case(session: Session, folder: Path, name: str, graph: CompositionGraph) -> dict:
    result = session.build(graph, Options(detail_level=graph.detail_level, check=True))
    if not result.ok:
        raise RuntimeError(result.report.describe())
    scene = result.scene(session.catalog())
    folder.mkdir(parents=True, exist_ok=True)
    render(scene, folder / f"{name}.png", azimuth=38.0, elevation=16.0,
           textured=False)
    export(scene, folder / f"{name}.glb", save_plan=False, textured=False)
    return {
        "triangles": result.triangles,
        "nodes": len(result.resolved.nodes),
        "applied": len(result.traits.applied),
        "diagnostics": sorted(result.report.codes()),
        "values": result.traits.values,
    }


def main() -> None:
    session = _session()
    metrics = {"body_mass": {}, "leafiness": {}}
    for value in (0.0, 0.5, 1.0):
        key = str(value).replace(".", "_")
        metrics["body_mass"][str(value)] = _write_case(
            session, OUTPUT / "body_mass", f"body_mass_{key}", _body_mass(value))
    for value in (0.2, 0.6, 1.0):
        key = str(value).replace(".", "_")
        metrics["leafiness"][str(value)] = _write_case(
            session, OUTPUT / "leafiness", f"leafiness_{key}", _leafiness(value))
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "metrics.json").write_text(
        json.dumps(metrics, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(metrics, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
