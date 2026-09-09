"""Test end-to-end della pipeline, completamente offline."""
from __future__ import annotations

import json

import pytest
import trimesh

from app.ai.provider import (
    ChatProvider, FailoverProvider, LLMError, LLMProvider, OfflineProvider,
)
from app.ai.planner import generate_plan
from app.build.builder import build_scene
from app.build.exporter import export, validate
from app.core.session import Session

OFFLINE = OfflineProvider()


def test_full_pipeline_to_glb(tmp_path):
    session = Session(provider=OFFLINE)
    session.generate_legacy("una jeep militare verde con ruote grandi")

    scene = session.scene
    assert scene is not None and len(scene.nodes) > 20
    assert all(c.ok for c in validate(scene)), [c.label for c in validate(scene) if not c.ok]

    out = export(scene, tmp_path / "modello.glb")
    assert out.exists() and out.stat().st_size > 5000

    reloaded = trimesh.load(out)
    assert len(reloaded.geometry) == len(scene.nodes)

    plan_file = out.with_suffix(".plan.json")
    assert plan_file.exists()
    data = json.loads(plan_file.read_text(encoding="utf-8"))
    assert data["template"] == "vehicle"


@pytest.mark.parametrize("fmt", ["glb", "obj", "stl", "ply"])
def test_all_export_formats(tmp_path, fmt):
    session = Session(provider=OFFLINE)
    session.generate_legacy("una sedia")
    out = export(session.scene, tmp_path / ("m." + fmt))
    assert out.exists() and out.stat().st_size > 100


@pytest.mark.parametrize("nome", ["con", "aux", "nul", "com1", "prn"])
def test_windows_device_names_are_neutralised(tmp_path, nome):
    """CON, AUX e simili non sono file: scriverci sopra blocca il processo."""
    session = Session(provider=OFFLINE)
    session.generate_legacy("una sedia")
    out = export(session.scene, tmp_path / (nome + ".glb"))
    assert out.name != nome + ".glb"
    assert out.exists() and out.stat().st_size > 100


def test_export_rejects_unknown_format(tmp_path):
    session = Session(provider=OFFLINE)
    session.generate_legacy("una sedia")
    with pytest.raises(ValueError):
        export(session.scene, tmp_path / "m.xyz")


def test_history_undo_redo():
    session = Session(provider=OFFLINE)
    session.generate_legacy("un suv")
    first = session.current_plan.params["wheel_radius"]
    session.modify("ruote piu grandi")
    bigger = session.current_plan.params["wheel_radius"]
    assert bigger > first

    session.undo()
    assert session.current_plan.params["wheel_radius"] == first
    session.redo()
    assert session.current_plan.params["wheel_radius"] == bigger

    # una nuova azione dopo un undo taglia il ramo futuro
    session.undo()
    session.modify("fallo rosso")
    assert not session.can_redo()
    assert len(session.history) == 2      # la versione "ruote piu grandi" e' stata scartata
    assert session.current_plan.params["wheel_radius"] == first


def test_same_seed_is_reproducible():
    """Punto 39 della roadmap: a parita' di seed la generazione si ripete uguale."""
    a, _ = generate_plan("un pino alto 9 metri", OFFLINE, seed=4242)
    b, _ = generate_plan("un pino alto 9 metri", OFFLINE, seed=4242)
    assert a.params == b.params
    assert [m.model_dump() for m in a.materials] == [m.model_dump() for m in b.materials]
    assert build_scene(a).triangle_count == build_scene(b).triangle_count


def test_repeated_prompts_give_different_objects():
    """La richiesta dell'utente: lo stesso prompt non deve dare due volte lo stesso oggetto."""
    plans = [generate_plan("crea un suv", OFFLINE)[0] for _ in range(6)]
    assert len({p.seed for p in plans}) == 6
    signatures = {(tuple(sorted(p.params.items())),
                   tuple(sorted((m.name, m.base_color) for m in p.materials)))
                  for p in plans}
    assert len(signatures) >= 5, "le varianti si somigliano troppo"


# --------------------------------------------------------------------------- #
# Resilienza dei provider
# --------------------------------------------------------------------------- #
class _Broken(LLMProvider):
    name = "rotto"

    def available(self) -> bool:
        return True

    def complete_json(self, system, user, temperature=0.2):
        raise LLMError("simulazione di guasto")


class _Working(LLMProvider):
    name = "funzionante"

    def available(self) -> bool:
        return True

    def complete_json(self, system, user, temperature=0.2):
        return {"object_type": "test", "template": "chair", "params": {}}


def test_failover_skips_broken_providers():
    chain = FailoverProvider([_Broken(), _Broken(), _Working()])
    result = chain.complete_json("s", "u")
    assert result["template"] == "chair"
    assert chain.last_used == "funzionante"
    assert len(chain.attempts) == 3


def test_failover_raises_when_all_fail():
    with pytest.raises(LLMError):
        FailoverProvider([_Broken(), _Broken()]).complete_json("s", "u")


def test_session_survives_total_llm_failure():
    """Nessun provider disponibile: si deve comunque ottenere un modello."""
    session = Session(provider=FailoverProvider([_Broken()]))
    version = session.generate_legacy("una jeep militare verde")
    assert session.scene is not None and session.scene.nodes
    assert session.current_plan.template == "vehicle"
    assert "locale" in version.message.lower()


def test_json_extraction_from_noisy_answer():
    text = 'Ecco il piano:\n```json\n{"template": "chair", "params": {}}\n```\nSpero vada bene.'
    assert LLMProvider._extract_json(text)["template"] == "chair"


def test_provider_without_key_is_unavailable(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("NEXT_PUBLIC_GROQ_API_KEY", raising=False)
    assert not ChatProvider("groq").available()
