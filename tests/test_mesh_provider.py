"""Quarta strategia: mesh da un modello, ripulita prima di entrare in scena.

Il servizio vero e' esterno. Qui si prova tutto il percorso — richiesta,
pulizia, controllo di qualita', innesto, ripiego — con fornitori finti.
"""
from __future__ import annotations

import numpy as np
import pytest
import trimesh

from app.ai.mesh_provider import (
    HuggingFaceMeshGenerator, MeshGenerationError, MeshGenerator, MeshRequest,
    MeshService, ProceduralStubGenerator, clean_incoming, default_generators,
    is_acceptable, quality_report,
)
from app.build.strategy import AI_MESH, FALLBACK, TEMPLATE, GeneratorManager
from app.core.spec import GenerationPlan


class FakeGenerator(MeshGenerator):
    """Sostituisce il servizio: restituisce cio' che gli si dice."""

    name = "finto"

    def __init__(self, mesh=None, error: str = "", ready: bool = True) -> None:
        self.mesh = mesh
        self.error = error
        self.ready = ready
        self.calls = 0

    def available(self) -> bool:
        return self.ready

    def generate(self, request: MeshRequest):
        self.calls += 1
        if self.error:
            raise MeshGenerationError(self.error)
        return self.mesh


def messy_mesh() -> trimesh.Trimesh:
    """Come arriva spesso da fuori: vertici doppi, scala e posizione a caso."""
    base = trimesh.creation.icosphere(subdivisions=3, radius=7.0)
    base.apply_translation([120.0, -40.0, 33.0])
    vertices = np.vstack([base.vertices, base.vertices[:20]])   # duplicati
    return trimesh.Trimesh(vertices=vertices, faces=base.faces, process=False)


# --------------------------------------------------------------------------- #
# Pulizia
# --------------------------------------------------------------------------- #
def test_incoming_mesh_is_rescaled_and_grounded():
    cleaned = clean_incoming(messy_mesh(), MeshRequest("x", target_size=2.0))
    extents = cleaned.bounds[1] - cleaned.bounds[0]
    assert float(np.max(extents)) == pytest.approx(2.0, rel=0.02)
    assert cleaned.bounds[0][1] == pytest.approx(0.0, abs=1e-6), "appoggiata sulla base"
    centre = (cleaned.bounds[0] + cleaned.bounds[1]) / 2
    assert abs(centre[0]) < 1e-6 and abs(centre[2]) < 1e-6, "centrata in pianta"


def test_duplicate_vertices_are_removed():
    dirty = messy_mesh()
    cleaned = clean_incoming(dirty, MeshRequest("x"))
    assert len(cleaned.vertices) < len(dirty.vertices)


def test_too_dense_meshes_are_decimated():
    dense = trimesh.creation.icosphere(subdivisions=5)
    cleaned = clean_incoming(dense, MeshRequest("x", max_faces=1000))
    assert len(cleaned.faces) <= 1400


def test_empty_mesh_is_refused():
    with pytest.raises(MeshGenerationError):
        clean_incoming(trimesh.Trimesh(), MeshRequest("x"))


# --------------------------------------------------------------------------- #
# Controllo di qualita'
# --------------------------------------------------------------------------- #
def test_a_good_mesh_is_accepted():
    ok, reason = is_acceptable(trimesh.creation.icosphere(subdivisions=3))
    assert ok and reason == "ok"


def test_a_mesh_with_too_few_faces_is_refused():
    ok, reason = is_acceptable(trimesh.creation.box((1, 1, 1)))
    assert not ok and "facce" in reason


def test_a_flat_mesh_is_refused():
    piatta = trimesh.Trimesh(
        vertices=np.array([[0, 0, 0], [1, 0, 0], [1, 0, 1], [0, 0, 1]] * 20, dtype=float),
        faces=np.array([[i * 4, i * 4 + 1, i * 4 + 2] for i in range(20)]
                       + [[i * 4, i * 4 + 2, i * 4 + 3] for i in range(20)]),
        process=False)
    ok, reason = is_acceptable(piatta)
    assert not ok


def test_a_shattered_mesh_is_refused():
    pezzi = [trimesh.creation.icosphere(subdivisions=2) for _ in range(20)]
    for index, pezzo in enumerate(pezzi):
        pezzo.apply_translation([index * 5.0, 0, 0])
    ok, reason = is_acceptable(trimesh.util.concatenate(pezzi))
    assert not ok and "pezzi" in reason


def test_quality_report_describes_the_mesh():
    report = quality_report(trimesh.creation.icosphere(subdivisions=3))
    assert report["watertight"] and report["components"] == 1
    assert report["faces"] > 100 and report["volume"] > 0


# --------------------------------------------------------------------------- #
# Servizio: ordine, ripieghi, tempi
# --------------------------------------------------------------------------- #
def test_service_uses_the_first_working_generator():
    rotto = FakeGenerator(error="servizio giu'")
    buono = FakeGenerator(mesh=trimesh.creation.icosphere(subdivisions=3))
    outcome = MeshService([rotto, buono]).generate(MeshRequest("prova"))
    assert outcome.ok and outcome.generator == "finto"
    assert rotto.calls == 1 and buono.calls == 1
    assert [a.ok for a in outcome.attempts] == [False, True]


def test_unconfigured_generators_are_skipped():
    spento = FakeGenerator(ready=False)
    outcome = MeshService([spento]).generate(MeshRequest("prova"))
    assert not outcome.ok and spento.calls == 0
    assert outcome.attempts[0].detail == "non configurato"


def test_unusable_meshes_are_rejected_not_returned():
    scadente = FakeGenerator(mesh=trimesh.creation.box((1, 1, 1)))
    outcome = MeshService([scadente]).generate(MeshRequest("prova"))
    assert not outcome.ok, "una mesh inutilizzabile non deve entrare in scena"


def test_service_without_generators_reports_it():
    outcome = MeshService([]).generate(MeshRequest("prova"))
    assert not outcome.ok and outcome.attempts == []


def test_stub_generator_produces_something_usable():
    """Permette di sviluppare e provare il percorso senza servizi esterni."""
    outcome = MeshService([ProceduralStubGenerator()]).generate(
        MeshRequest("una creatura mai vista", target_size=1.5))
    assert outcome.ok
    assert outcome.report["faces"] > 200
    assert outcome.report["components"] == 1


def test_stub_is_deterministic_for_the_same_prompt():
    a = MeshService([ProceduralStubGenerator()]).generate(MeshRequest("stesso", seed=3))
    b = MeshService([ProceduralStubGenerator()]).generate(MeshRequest("stesso", seed=3))
    assert a.report["faces"] == b.report["faces"]


def test_the_stub_seed_does_not_depend_on_the_process():
    """`hash()` sulle stringhe cambia a ogni avvio di Python.

    Confrontare due chiamate dentro lo stesso processo non se ne accorge: il
    test passava, e il generatore produceva una forma diversa a ogni
    esecuzione. Il seme va fissato sul testo, e questo lo inchioda.
    """
    from app.ai.mesh_provider import _stable_seed

    assert _stable_seed("una creatura mai vista") == 754129696
    assert _stable_seed("stesso") == _stable_seed("stesso")


# --------------------------------------------------------------------------- #
# Il fornitore vero richiede un servizio esterno
# --------------------------------------------------------------------------- #
def test_remote_generator_is_unavailable_without_a_key(monkeypatch):
    monkeypatch.setattr("app.core.config.SETTINGS.api_key", lambda *_: "")
    assert not HuggingFaceMeshGenerator().available()


def test_remote_generator_reports_a_dead_service():
    generator = HuggingFaceMeshGenerator(model="modello/inesistente", api_key="finta")
    generator.endpoint = "http://127.0.0.1:9/nulla"
    with pytest.raises(MeshGenerationError):
        generator.generate(MeshRequest("prova", timeout=1))


def test_default_generators_do_not_include_the_stub():
    """Lo stub non deve mascherare l'assenza del servizio vero."""
    assert all(g.name != "stub" for g in default_generators())


# --------------------------------------------------------------------------- #
# Integrazione con il gestore delle strategie
# --------------------------------------------------------------------------- #
def test_ai_mesh_is_not_attempted_without_a_service():
    plan = GenerationPlan(template="chair", strategy="ai_mesh")
    assert AI_MESH not in GeneratorManager()._applicable(plan)
    assert GeneratorManager().build(plan).strategy == TEMPLATE


def test_ai_mesh_is_used_when_configured():
    service = MeshService([ProceduralStubGenerator()])
    plan = GenerationPlan(prompt="un oggetto mai visto", template="inesistente",
                          strategy="ai_mesh")
    outcome = GeneratorManager(mesh_service=service).build(plan)
    assert outcome.strategy == AI_MESH
    assert outcome.scene.nodes
    assert any("controllane la qualita" in w for w in outcome.scene.warnings)


def test_ai_mesh_failure_falls_through_to_the_last_resort():
    service = MeshService([FakeGenerator(error="servizio giu'")])
    plan = GenerationPlan(prompt="x", template="inesistente", strategy="ai_mesh")
    outcome = GeneratorManager(mesh_service=service).build(plan)
    assert outcome.strategy == FALLBACK
    assert outcome.scene.triangle_count > 0, "regola 9: qualcosa esce sempre"


def test_template_still_wins_over_ai_mesh():
    """L'AI resta l'ultima risorsa, non la strada principale."""
    service = MeshService([ProceduralStubGenerator()])
    outcome = GeneratorManager(mesh_service=service).build(
        GenerationPlan(prompt="una jeep", template="vehicle", strategy="template"))
    assert outcome.strategy == TEMPLATE
