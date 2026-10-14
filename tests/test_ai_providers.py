"""Contratti della pipeline unica provider/modello/failover."""
from __future__ import annotations

import os

import pytest

from app.ai.provider import (FailoverProvider, LLMError, LLMProvider,
                             ChatProvider, make_provider)
from app.core.config import PROVIDERS, SETTINGS
from app.core.planner.planner import LLMPlanner, PlanRequest
from app.core.planner.vocabulary import Vocabulary


class _Fake(LLMProvider):
    def __init__(self, key: str, model: str, result=None, error: str = ""):
        self.key = key
        self.name = key
        self.model = model
        self.result = result
        self.error = error
        self.last_outcome = "pending"

    def available(self) -> bool:
        return True

    def complete_json(self, system, user, temperature=0.2, schema=None):
        if self.error:
            self.last_outcome = "rate_limited"
            raise LLMError(self.error)
        self.last_outcome = "ok"
        return self.result


def _empty(monkeypatch, *names: str) -> None:
    for name in names:
        monkeypatch.setenv(name, "")


def test_new_providers_are_registry_entries_without_a_second_client():
    assert {"cloudflare", "nvidia_nim", "cerebras"} <= set(PROVIDERS)
    assert PROVIDERS["nvidia_nim"].endpoint.endswith("/chat/completions")
    assert PROVIDERS["cerebras"].endpoint.endswith("/chat/completions")
    assert PROVIDERS["cloudflare"].endpoint_template


def test_cloudflare_requires_account_id_and_never_becomes_configured_by_key_alone(monkeypatch):
    _empty(monkeypatch, "CLOUDFLARE_API_KEY", "CLOUDFLARE_API_TOKEN",
           "cloudflare_api", "CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_ACCOUNT",
           "cloudflare_account_id", "cloudflare_id")
    monkeypatch.setenv("cloudflare_api", "token-without-account")
    assert not SETTINGS.configured("cloudflare")
    assert SETTINGS.missing_requirements("cloudflare") == ("CLOUDFLARE_ACCOUNT_ID",)


def test_cloudflare_id_alias_completes_the_endpoint_requirements(monkeypatch):
    _empty(monkeypatch, "CLOUDFLARE_API_KEY", "CLOUDFLARE_API_TOKEN",
           "cloudflare_api", "CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_ACCOUNT",
           "cloudflare_account_id")
    monkeypatch.setenv("cloudflare_api", "token-for-test")
    monkeypatch.setenv("cloudflare_id", "account-for-test")
    assert SETTINGS.configured("cloudflare")
    assert SETTINGS.endpoint("cloudflare").endswith("/ai/v1/chat/completions")


def test_lowercase_credentials_added_to_env_are_supported_without_logging_value(monkeypatch):
    _empty(monkeypatch, "CEREBRAS_API_KEY")
    monkeypatch.setenv("cerebras_api", "cerebras-secret")
    assert SETTINGS.configured("cerebras")
    provider = ChatProvider("cerebras")
    assert "cerebras-secret" not in repr(provider)
    assert "cerebras-secret" not in str(provider.provenance())


def test_each_provider_keeps_its_own_model_catalog():
    assert "qwen-3.8-27b" in SETTINGS.models("cerebras")
    assert "openai/gpt-oss-20b" in SETTINGS.models("nvidia_nim")
    assert "@cf/openai/gpt-oss-20b" in SETTINGS.models("cloudflare")
    assert SETTINGS.models("cerebras") != SETTINGS.models("nvidia_nim")


def test_chain_normalization_places_openrouter_before_ollama(monkeypatch):
    monkeypatch.setenv("GEN3D_LLM_CHAIN", "cerebras,openrouter,nvidia_nim,ollama")
    _empty(monkeypatch, "CLOUDFLARE_API_KEY", "CLOUDFLARE_API_TOKEN",
           "cloudflare_api", "CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_ACCOUNT",
           "cloudflare_account_id", "cloudflare_id")
    assert SETTINGS.chain() == ["cerebras", "nvidia_nim", "openrouter", "ollama"]


def test_remote_model_override_argument_is_ignored_for_every_candidate(monkeypatch):
    monkeypatch.setenv("GEN3D_LLM_CHAIN", "cerebras,nvidia_nim,openrouter,ollama")
    chain = make_provider("cerebras", model="zai-glm-4.7", failover=True)
    assert isinstance(chain, FailoverProvider)
    assert chain.providers[0].key == "cerebras"
    assert chain.providers[0].model == PROVIDERS["cerebras"].default_model
    for candidate in chain.providers[1:]:
        assert candidate.model != "zai-glm-4.7"


def test_failover_provenance_contains_provider_and_model_pair():
    chain = FailoverProvider([
        _Fake("cerebras", "zai-glm-4.7", error="rate limited"),
        _Fake("nvidia_nim", "openai/gpt-oss-20b", result={"ok": True}),
    ])
    assert chain.complete_json("s", "u") == {"ok": True}
    provenance = chain.provenance()
    assert provenance["requested_provider"] == "cerebras"
    assert provenance["requested_model"] == "zai-glm-4.7"
    assert provenance["actual_provider"] == "nvidia_nim"
    assert provenance["actual_model"] == "openai/gpt-oss-20b"
    assert provenance["failover_count"] == 1
    assert [(a["provider"], a["model"]) for a in provenance["attempts"]] == [
        ("cerebras", "zai-glm-4.7"),
        ("nvidia_nim", "openai/gpt-oss-20b"),
    ]


def test_openrouter_is_used_before_ollama_when_all_prior_remote_candidates_fail():
    chain = FailoverProvider([
        _Fake("cerebras", "gpt-oss-120b", error="temporary failure"),
        _Fake("openrouter", "openrouter-free", result={"ok": True}),
        _Fake("ollama", "qwen2.5:7b", result={"ok": False}),
    ])
    chain.complete_json("s", "u")
    assert chain.provenance()["actual_provider"] == "openrouter"
    assert [a["provider"] for a in chain.provenance()["attempts"]] == [
        "cerebras", "openrouter"
    ]


def test_all_failures_have_deterministic_safe_diagnostic():
    chain = FailoverProvider([
        _Fake("openrouter", "free", error="first failed"),
        _Fake("ollama", "local", error="second failed"),
    ])
    with pytest.raises(LLMError) as exc:
        chain.complete_json("s", "u")
    assert "openrouter" in str(exc.value)
    assert "ollama" in str(exc.value)
    assert [a["provider"] for a in chain.provenance()["attempts"]] == [
        "openrouter", "ollama"
    ]


def test_disabled_failover_does_not_enable_local_fallback(monkeypatch):
    monkeypatch.setenv("CEREBRAS_API_KEY", "configured-for-test")
    provider = make_provider("cerebras", model="gpt-oss-120b", failover=False)
    assert isinstance(provider, ChatProvider)
    assert provider.model == PROVIDERS["cerebras"].default_model
    assert provider.allow_local_fallback is False


def test_remote_provider_defaults_are_backend_owned_and_ignore_legacy_env(monkeypatch):
    monkeypatch.setenv("HF_MODEL", "mistralai/Mistral-7B-Instruct-v0.3")
    monkeypatch.setenv("OPENROUTER_MODEL", "nvidia/old-override:free")
    assert SETTINGS.legacy_model_override("huggingface")
    assert SETTINGS.legacy_model_override("openrouter")
    assert SETTINGS.model("huggingface") == PROVIDERS["huggingface"].default_model
    assert SETTINGS.model("openrouter") == PROVIDERS["openrouter"].default_model
    assert ChatProvider("huggingface").model == PROVIDERS["huggingface"].default_model
    assert ChatProvider("openrouter").model == PROVIDERS["openrouter"].default_model


def test_provider_defaults_are_backend_owned_and_currently_distinct():
    assert SETTINGS.model("nvidia_nim") == "openai/gpt-oss-20b"
    assert SETTINGS.model("cloudflare") == "@cf/openai/gpt-oss-20b"
    assert PROVIDERS["huggingface"].default_model == "openai/gpt-oss-120b"
    assert PROVIDERS["openrouter"].default_model == "nvidia/nemotron-3.5-lightning:free"
    assert PROVIDERS["groq"].max_output_tokens == 1200


def test_failover_deduplicates_provider_keys():
    one = _Fake("groq", "a", error="down")
    two = _Fake("groq", "b", result={"ok": True})
    chain = FailoverProvider([one, two])
    with pytest.raises(LLMError):
        chain.complete_json("s", "u")
    assert [a["provider"] for a in chain.attempts] == ["groq"]


@pytest.mark.parametrize(("status", "kind", "outcome"), [
    (410, "model_or_endpoint_unavailable", "model_unavailable"),
    (413, "payload_too_large", "payload_too_large"),
    (429, "rate_limited", "rate_limited"),
    (503, "server_error", "server_error"),
])
def test_http_errors_keep_operational_classification(status, kind, outcome):
    assert ChatProvider._http_classification(status)[:2] == (kind, outcome)


def test_http_diagnostic_keeps_safe_provider_body_without_secret(monkeypatch):
    class Response:
        status_code = 410
        text = '{"detail":"model retired","token":"secret"}'

    monkeypatch.setenv("GROQ_API_KEY", "secret")
    monkeypatch.setattr("app.ai.provider.requests.post", lambda *a, **k: Response())
    with pytest.raises(LLMError) as exc:
        ChatProvider("groq").complete_json("s", "u")
    assert "410" in str(exc.value)
    assert "model retired" in str(exc.value)
    assert "secret" not in str(exc.value)


def test_planner_uses_compact_vocabulary_when_provider_budget_requires_it():
    class TinyProvider(LLMProvider):
        key = "tiny"
        name = "tiny"
        input_budget = 1

        def __init__(self):
            self.user = ""
            self.metrics = {}

        def available(self):
            return True

        def record_request_metrics(self, metrics):
            self.metrics = dict(metrics)

        def complete_json(self, system, user, temperature=0.2, schema=None):
            self.user = user
            return {"ok": True}

    provider = TinyProvider()
    LLMPlanner(provider).plan(PlanRequest("ping", Vocabulary()))
    assert "CAPABILITY (come i pezzi si incastrano)" not in provider.user
    assert provider.metrics["compact"] is True
    # Con un vocabolario **vuoto** cio' che resta e' il prompt di sistema piu'
    # lo schema: non c'e' niente da comprimere, e questo numero misura loro due.
    # Era 8 000; V3.5 ha aggiunto al prompt le chiavi `traits` e
    # `structural_traits` (+1,1 KB) e il valore misurato e' passato a 8 651.
    # La soglia sale di conseguenza, e la proprieta' che il test verifica —
    # il percorso compatto si attiva e il corpo resta piccolo — non cambia.
    assert provider.metrics["payload_estimate"] < 9216


def test_ollama_chooses_installed_compatible_model_without_downloading(monkeypatch):
    class Response:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": '{"ok":true}'}}]}

    provider = ChatProvider("ollama")
    provider.models = lambda refresh=False: ("nomic-embed-text", "qwen3:8b")
    monkeypatch.setattr("app.ai.provider.requests.post", lambda *a, **k: Response())
    assert provider.complete_json("s", "u") == {"ok": True}
    assert provider.model == "qwen3:8b"


def test_ollama_remains_allowed_to_read_local_model_override(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "local-installed:7b")
    provider = ChatProvider("ollama")
    assert provider.model == "local-installed:7b"
    assert not SETTINGS.legacy_model_override("ollama")


def test_smoke_tool_reports_ignored_legacy_remote_model_override(monkeypatch, capsys):
    from tools import ai_provider_smoke

    monkeypatch.setenv("HF_MODEL", "mistralai/Mistral-7B-Instruct-v0.3")
    monkeypatch.setattr(ai_provider_smoke.SETTINGS, "configured", lambda name: False)
    monkeypatch.setattr(ai_provider_smoke.SETTINGS, "missing_requirements",
                        lambda name: ("HF_API_KEY",))
    monkeypatch.setattr("sys.argv", ["ai_provider_smoke.py", "--provider", "huggingface"])

    assert ai_provider_smoke.main() == 0
    assert "legacy model override ignored" in capsys.readouterr().out
