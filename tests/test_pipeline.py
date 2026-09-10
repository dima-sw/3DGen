"""La pipeline dalla frase al file, completamente offline.

Questi test erano scritti contro la strada storica — `GenerationPlan`,
template, `build_scene` — che non esiste piu'. Le domande sono rimaste: la
sessione produce un modello esportabile? La cronologia si comporta bene? Un
fornitore rotto ferma la generazione? A cambiare e' cio' a cui vengono poste.
"""
from __future__ import annotations

import pytest
import trimesh

from app.ai.provider import (ChatProvider, FailoverProvider, LLMError,
                             LLMProvider, OfflineProvider)
from app.build.exporter import export, validate
from app.core.planner.planner import MockPlanner
from app.core.session import Options, Session

OFFLINE = OfflineProvider()


def sessione() -> Session:
    return Session(provider=OFFLINE, planner=MockPlanner())


# --------------------------------------------------------------------------- #
# Dalla frase al file
# --------------------------------------------------------------------------- #
def test_full_pipeline_to_glb(tmp_path):
    s = sessione()
    s.generate("un albero con un nido e un uccello", Options(detail_level=3))

    scene = s.scene
    assert scene is not None and len(scene.nodes) >= 4
    assert all(c.ok for c in validate(scene)), \
        [c.label for c in validate(scene) if not c.ok]

    out = export(scene, tmp_path / "modello.glb")
    assert out.exists() and out.stat().st_size > 2000

    ricaricato = trimesh.load(out)
    assert len(ricaricato.geometry) == len(scene.nodes)


@pytest.mark.parametrize("fmt", ["glb", "obj", "stl", "ply"])
def test_all_export_formats(tmp_path, fmt):
    s = sessione()
    s.generate("una casa")
    out = export(s.scene, tmp_path / ("m." + fmt))
    assert out.exists() and out.stat().st_size > 100


@pytest.mark.parametrize("nome", ["con", "aux", "nul", "com1", "prn"])
def test_windows_device_names_are_neutralised(tmp_path, nome):
    """CON, AUX e simili non sono file: scriverci sopra blocca il processo."""
    s = sessione()
    s.generate("una casa")
    out = export(s.scene, tmp_path / (nome + ".glb"))
    assert out.name != nome + ".glb"
    assert out.exists() and out.stat().st_size > 100


def test_export_rejects_unknown_format(tmp_path):
    s = sessione()
    s.generate("una casa")
    with pytest.raises(ValueError):
        export(s.scene, tmp_path / "m.xyz")


# --------------------------------------------------------------------------- #
# Cronologia
# --------------------------------------------------------------------------- #
def test_history_keeps_every_generation():
    s = sessione()
    s.generate("una casa con un pianeta sopra")
    s.generate("un albero con un nido")
    assert len(s.history) == 2
    assert s.current.prompt.startswith("un albero")


def test_history_undo_redo():
    s = sessione()
    s.generate("una casa con un pianeta sopra")
    s.generate("un albero con un nido")

    prima = s.history[0].scene.triangle_count
    dopo = s.history[1].scene.triangle_count
    assert s.scene.triangle_count == dopo

    s.undo()
    assert s.scene.triangle_count == prima
    s.redo()
    assert s.scene.triangle_count == dopo

    # una nuova azione dopo un undo taglia il ramo futuro
    s.undo()
    s.generate("un pesce")
    assert not s.can_redo()
    assert len(s.history) == 2


def test_changing_a_parameter_and_rebuilding_changes_the_model():
    """Si corregge il **piano**, non la mesh: e' il senso della cronologia."""
    s = sessione()
    s.generate("una casa")
    piano = s.current_plan
    prima = s.scene.dimensions()[0]

    piano.nodes[piano.root_id].overrides["width"] = 20.0
    s.regenerate()

    assert s.scene.dimensions()[0] > prima * 2


def test_the_same_prompt_and_seed_give_the_same_model():
    """Riproducibilita': stesso piano, stessi plugin, stesso seme."""
    uno = sessione().generate("un albero con un nido e un uccello")
    due = sessione().generate("un albero con un nido e un uccello")
    assert uno.plan_json == due.plan_json
    assert uno.triangles == due.triangles


def test_every_seed_is_reproducible():
    """Il seme e' l'unico grado di liberta', e a parita' di seme non ce n'e'.

    Non si pretende che semi diversi diano modelli diversi — il planner finto
    sceglie per corrispondenza lessicale, e una frase che nomina una cosa sola
    da' quella cosa comunque. Si pretende che **lo stesso** seme dia sempre lo
    stesso piano: e' la riproducibilita', ed e' l'unica delle due che serve.
    """
    prompt = "qualcosa con delle ali e dei cristalli"
    for seme in (0, 7, 4242):
        uno = sessione().generate(prompt, Options(seed=seme))
        due = sessione().generate(prompt, Options(seed=seme))
        assert uno.plan_json == due.plan_json, seme
        assert uno.triangles == due.triangles


# --------------------------------------------------------------------------- #
# Resilienza dei provider
# --------------------------------------------------------------------------- #
class _Broken(LLMProvider):
    name = "rotto"

    def available(self) -> bool:
        return True

    def complete_json(self, system, user, temperature=0.2, schema=None):
        raise LLMError("simulazione di guasto")


class _Working(LLMProvider):
    name = "funzionante"

    def available(self) -> bool:
        return True

    def complete_json(self, system, user, temperature=0.2, schema=None):
        return {"root": {"id": "r", "ref": "primitives:block"}}


def test_failover_skips_broken_providers():
    chain = FailoverProvider([_Broken(), _Broken(), _Working()])
    result = chain.complete_json("s", "u")
    assert result["root"]["ref"] == "primitives:block"
    assert chain.last_used == "funzionante"
    assert len(chain.attempts) == 3


def test_failover_raises_when_all_fail():
    with pytest.raises(LLMError):
        FailoverProvider([_Broken(), _Broken()]).complete_json("s", "u")


def test_session_survives_total_llm_failure():
    """Nessun fornitore disponibile: si ottiene comunque un modello, e si dice."""
    from app.core.planner.planner import LLMPlanner

    s = Session(provider=FailoverProvider([_Broken()]),
                planner=LLMPlanner(FailoverProvider([_Broken()])))
    risultato = s.generate("una casa con un pianeta sopra")

    assert s.scene is not None and s.scene.nodes
    assert risultato.planner == "mock_fallback", \
        "il ripiego deve vedersi, non sembrare una generazione vera"
    assert any("non ha risposto" in d.message for d in risultato.diagnostics)


def test_json_extraction_from_noisy_answer():
    text = 'Ecco il piano:\n```json\n{"root": {"ref": "x"}}\n```\nSpero vada bene.'
    assert LLMProvider._extract_json(text)["root"]["ref"] == "x"


def test_provider_without_key_is_unavailable(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("NEXT_PUBLIC_GROQ_API_KEY", raising=False)
    assert not ChatProvider("groq").available()
