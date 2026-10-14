"""Provider LLM intercambiabili, con catena di failover.

Il resto dell'applicazione conosce solo l'interfaccia LLMProvider. Tutti i
fornitori usati qui espongono un endpoint in stile OpenAI /chat/completions,
quindi basta una sola implementazione parametrizzata dai dati in config.
"""
from __future__ import annotations

import json
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import requests

from app.core.config import PROVIDERS, SETTINGS
from app.core.logging_setup import get

log = get("ai.provider")

JSON_BLOCK = re.compile(r"\{.*\}", re.S)
_MODEL_CACHE: dict[str, tuple[float, tuple[str, ...]]] = {}


class LLMError(RuntimeError):
    """Errore classificato senza includere credenziali o payload sensibili."""

    def __init__(self, message: str, *, kind: str = "provider_error",
                 retryable: bool = True, status_code: int | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.retryable = bool(retryable)
        self.status_code = status_code


@dataclass(frozen=True)
class ProviderCandidate:
    """Una scelta indivisibile: il modello appartiene al provider."""

    provider: str
    model: str


def _identity(provider: Any) -> str:
    key = str(getattr(provider, "key", "") or "")
    if key and key != "abstract":
        return key
    # Fixture/provider implementations without a real registry key are not
    # deduplicated: only registry identities must be unique in a chain.
    return ""


def _model(provider: Any) -> str:
    return str(getattr(provider, "model", "") or "")


class LLMProvider(ABC):
    """Un fornitore di risposte JSON. Una domanda, una risposta, nessuno stato.

    Il resto dell'applicazione non sa quale sia: chiede un oggetto JSON e lo
    riceve. Nessun modulo del core nomina un'API specifica — cambiare
    fornitore e' una riga in configurazione, e aggiungerne uno nuovo non tocca
    ne' il planner ne' la sessione.

    `schema` e' facoltativo e cambia solo **quanto ci si puo' fidare** della
    risposta: chi lo sa vincolare restituisce un oggetto gia' della forma
    giusta, chi non lo sa lo ignora e la risposta viene letta come prima. In
    nessuno dei due casi ci si fida senza validare: lo schema riduce i giri di
    correzione, non li sostituisce.
    """

    name: str = "abstract"
    key: str = "abstract"
    model: str = ""
    allow_local_fallback: bool = True
    phase: str = "generation"
    input_budget: int | None = None

    @abstractmethod
    def available(self) -> bool: ...

    @abstractmethod
    def complete_json(self, system: str, user: str,
                      temperature: float = 0.2,
                      schema: dict[str, Any] | None = None) -> dict[str, Any]: ...

    @property
    def structured(self) -> bool:
        """Sa vincolare la risposta a uno schema? Per predefinito, no."""
        return False

    def provenance(self) -> dict[str, Any]:
        """Provenienza sicura e serializzabile dell'ultima chiamata."""
        return {}

    def set_phase(self, phase: str) -> None:
        self.phase = phase

    def record_request_metrics(self, metrics: dict[str, Any]) -> None:
        del metrics

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any]:
        text = (text or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\n?", "", text).rstrip("`").strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        m = JSON_BLOCK.search(text)
        if not m:
            raise LLMError("nessun JSON nella risposta del modello")
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError as exc:
            raise LLMError("JSON malformato: %s" % exc) from exc


class ChatProvider(LLMProvider):
    """Client generico per endpoint compatibili OpenAI."""

    def __init__(self, provider_key: str, model: str | None = None) -> None:
        spec = PROVIDERS[provider_key]
        self.key = provider_key
        self.name = spec.label
        self.spec = spec
        self.api_key = SETTINGS.api_key(provider_key)
        selected_model = model if spec.local and model else SETTINGS.model(provider_key)
        self.model = selected_model.strip()
        self.endpoint = SETTINGS.endpoint(provider_key)
        self.last_outcome = "pending"
        self.last_diagnostic = ""
        self.last_status_code: int | None = None
        self.last_error_kind = ""
        self.last_request_metrics: dict[str, Any] = {}
        self.phase = "generation"
        self.input_budget = getattr(spec, "input_budget", None)

    def available(self) -> bool:
        return SETTINGS.configured(self.key) and bool(self.endpoint)

    def models(self, refresh: bool = False) -> tuple[str, ...]:
        """Catalogo locale, con discovery opzionale solo per provider locali."""
        local = SETTINGS.models(self.key)
        spec = self.spec
        if not refresh or not spec.model_listing:
            return local
        now = time.monotonic()
        cached = _MODEL_CACHE.get(self.key)
        if cached and now - cached[0] < 30.0:
            return cached[1] or local
        if spec.model_listing == "ollama":
            endpoint = SETTINGS.ollama_endpoint + "/v1/models"
            try:
                response = requests.get(endpoint, timeout=3)
                data = response.json() if response.ok else {}
                discovered = tuple(str(item.get("id", "")).strip()
                                   for item in data.get("data", [])
                                   if isinstance(item, dict) and item.get("id"))
                values = tuple(dict.fromkeys(discovered))
                _MODEL_CACHE[self.key] = (now, values)
                return values or local
            except (requests.RequestException, ValueError, TypeError):
                _MODEL_CACHE[self.key] = (now, ())
        return local

    def set_phase(self, phase: str) -> None:
        self.phase = phase

    def record_request_metrics(self, metrics: dict[str, Any]) -> None:
        self.last_request_metrics = dict(metrics or {})

    def _ollama_model(self) -> None:
        if self.key != "ollama":
            return
        installed = self.models(refresh=True)
        if not installed:
            return
        if self.model in installed:
            return
        esclusi = ("embed", "embedding", "vision", "vl", "whisper",
                   "rerank", "tts", "audio", "guard", "safety")
        compatibili = sorted(m for m in installed
                             if not any(token in m.lower() for token in esclusi))
        if compatibili:
            self.model = compatibili[0]

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = "Bearer %s" % self.api_key
        if self.key == "openrouter":
            h["HTTP-Referer"] = "https://localhost/3dgen"
            h["X-Title"] = "3DGen"
        return h

    @property
    def structured(self) -> bool:
        return bool(getattr(self.spec, "json_schema", False))

    def complete_json(self, system: str, user: str,
                      temperature: float = 0.2,
                      schema: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.available():
            self.last_outcome = "unavailable"
            self.last_error_kind = "config_error"
            missing = SETTINGS.missing_requirements(self.key)
            detail = ("; manca " + ", ".join(missing)) if missing else ""
            raise LLMError("provider %s non configurato%s" % (self.name, detail),
                           kind="config_error", retryable=False)

        self._ollama_model()

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": float(temperature),
            "max_tokens": int(getattr(self.spec, "max_output_tokens", 2400)),
        }
        # Tre gradini, dal piu' forte al piu' debole: uno schema vincolante,
        # "rispondi in JSON", niente. Si scende solo di quanto serve, e cio'
        # che arriva viene comunque validato.
        if schema is not None and self.structured:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "piano", "strict": False,
                                "schema": schema},
            }
        elif self.spec.json_mode:
            payload["response_format"] = {"type": "json_object"}

        timeout = SETTINGS.request_timeout * (4 if self.key == "ollama" else 1)
        body_bytes = len(json.dumps(payload, ensure_ascii=False,
                                    separators=(",", ":")).encode("utf-8"))
        self.last_request_metrics = dict(self.last_request_metrics)
        self.last_request_metrics["payload_bytes"] = body_bytes
        log.info("LLM phase=%s provider=%s model=%s payload_bytes=%d",
                 self.phase, self.name, self.model, body_bytes)
        try:
            r = requests.post(self.endpoint, headers=self._headers(),
                              json=payload, timeout=timeout)
        except requests.RequestException as exc:
            self.last_outcome = "connection_error"
            self.last_error_kind = "connection_error"
            self.last_diagnostic = self._safe(str(exc))
            raise LLMError("%s irraggiungibile: %s" %
                           (self.name, self.last_diagnostic),
                           kind="connection_error") from exc

        self.last_status_code = r.status_code
        if r.status_code >= 400:
            kind, outcome, retryable = self._http_classification(r.status_code)
            self.last_outcome = outcome
            self.last_error_kind = kind
            self.last_diagnostic = self._safe_response(r)
            raise LLMError("%s ha risposto %d: %s" %
                           (self.name, r.status_code, self.last_diagnostic),
                           kind=kind, retryable=retryable,
                           status_code=r.status_code)

        try:
            data = r.json()
            content = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError) as exc:
            self.last_outcome = "invalid_response"
            self.last_error_kind = "invalid_response"
            self.last_diagnostic = self._safe(str(exc))
            raise LLMError("risposta inattesa da %s" % self.name,
                           kind="invalid_response") from exc
        try:
            result = self._extract_json(content)
        except LLMError:
            self.last_outcome = "invalid_json"
            self.last_error_kind = "invalid_json"
            self.last_diagnostic = "il contenuto non e' JSON valido"
            raise
        self.last_outcome = "ok"
        self.last_error_kind = ""
        self.last_diagnostic = ""
        return result

    def provenance(self) -> dict[str, Any]:
        actual = self.key if self.last_outcome == "ok" else ""
        return {
            "requested_provider": self.key,
            "requested_model": self.model,
            "actual_provider": actual,
            "actual_model": self.model if actual else "",
            "failover_count": 0,
            "attempts": [{"provider": self.key, "model": self.model,
                          "outcome": self.last_outcome,
                          "diagnostic": self.last_diagnostic,
                          "error_kind": self.last_error_kind,
                          "status_code": self.last_status_code,
                          "phase": self.phase,
                          "request_metrics": dict(self.last_request_metrics)}],
        }

    @staticmethod
    def _http_classification(status: int) -> tuple[str, str, bool]:
        if status in (401, 403):
            return "auth_config_error", "auth_error", False
        if status == 402:
            return "quota_exhausted", "quota_exhausted", True
        if status == 408:
            return "timeout", "timeout", True
        if status == 410:
            return "model_or_endpoint_unavailable", "model_unavailable", True
        if status == 413:
            return "payload_too_large", "payload_too_large", False
        if status == 429:
            return "rate_limited", "rate_limited", True
        if status >= 500:
            return "server_error", "server_error", True
        if status >= 400:
            return "invalid_request", "request_error", False
        return "provider_error", "request_error", True

    def _safe(self, text: str) -> str:
        value = str(text or "")
        if self.api_key:
            value = value.replace(self.api_key, "[redacted]")
        value = re.sub(r"\borg_[A-Za-z0-9_-]+\b", "org_[redacted]", value)
        return re.sub(r"(?i)(bearer\s+)[^\s]+", r"\1[redacted]", value)

    def _safe_response(self, response) -> str:
        return self._safe(response.text).replace("\r", " ").replace("\n", " ")[:600]


class OfflineProvider(LLMProvider):
    """Segnaposto: il planning avviene con le regole locali, senza rete."""

    name = "Locale (regole)"
    key = "offline"

    def available(self) -> bool:
        return True

    def complete_json(self, system: str, user: str,
                      temperature: float = 0.2,
                      schema: dict[str, Any] | None = None) -> dict[str, Any]:
        raise LLMError("provider offline: si usa il planner a regole")


class FailoverProvider(LLMProvider):
    """Prova i provider in ordine finche' uno restituisce JSON valido.

    Realizza la regola 13 della roadmap: l'applicazione continua a funzionare
    anche se un singolo fornitore e' giu', ha esaurito il credito o e' a limite.
    """

    key = "chain"

    def __init__(self, providers: list[LLMProvider]) -> None:
        seen = set()
        self.providers = []
        for provider in providers:
            identity = _identity(provider)
            if identity and identity in seen:
                continue
            if identity:
                seen.add(identity)
            self.providers.append(provider)
        self.name = " > ".join(p.name for p in self.providers) or "nessuno"
        self.last_used: str = ""
        self.last_used_model: str = ""
        self.last_used_key: str = ""
        self.attempts: list[dict[str, str]] = []
        self.requested_provider = _identity(self.providers[0]) if self.providers else ""
        self.requested_model = _model(self.providers[0]) if self.providers else ""
        budgets = [p.input_budget for p in self.providers if p.input_budget]
        self.input_budget = min(budgets) if budgets else None

    def available(self) -> bool:
        return any(p.available() for p in self.providers)

    def set_phase(self, phase: str) -> None:
        self.phase = phase
        for provider in self.providers:
            provider.set_phase(phase)

    def record_request_metrics(self, metrics: dict[str, Any]) -> None:
        self.last_request_metrics = dict(metrics or {})
        for provider in self.providers:
            provider.record_request_metrics(self.last_request_metrics)

    @property
    def structured(self) -> bool:
        return any(p.structured for p in self.providers)

    def complete_json(self, system: str, user: str,
                      temperature: float = 0.2,
                      schema: dict[str, Any] | None = None) -> dict[str, Any]:
        self.attempts = []
        self.last_used = ""
        self.last_used_model = ""
        self.last_used_key = ""
        errors: list[str] = []
        log.info("LLM phase=%s primary=%s model=%s", self.phase,
                 self.requested_provider, self.requested_model)
        for p in self.providers:
            provider_id = _identity(p)
            model = _model(p)
            if not p.available():
                self.attempts.append({"provider": provider_id, "model": model,
                                      "outcome": "unavailable",
                                      "diagnostic": "provider non disponibile",
                                      "error_kind": "config_error",
                                      "phase": self.phase})
                continue
            try:
                result = p.complete_json(system, user, temperature,
                                         schema=schema)
                self.last_used = p.name
                self.last_used_model = model
                self.last_used_key = provider_id
                self.attempts.append({"provider": provider_id, "model": model,
                                      "outcome": "ok", "diagnostic": "",
                                      "phase": self.phase,
                                      "request_metrics": dict(getattr(
                                          p, "last_request_metrics", {}))})
                log.info("LLM %s completed actual_provider=%s failovers=%d",
                         self.phase, provider_id, len(self.attempts) - 1)
                return result
            except LLMError as exc:
                diagnostic = str(exc)
                errors.append("%s: %s" % (p.name, diagnostic))
                outcome = str(getattr(p, "last_outcome", "error"))
                self.attempts.append({"provider": provider_id, "model": model,
                                      "outcome": outcome, "diagnostic": diagnostic,
                                      "error_kind": getattr(exc, "kind", "provider_error"),
                                      "status_code": getattr(exc, "status_code", None),
                                      "phase": self.phase,
                                      "request_metrics": dict(getattr(
                                          p, "last_request_metrics", {}))})
                log.warning("LLM phase=%s attempt=%d provider=%s model=%s outcome=%s kind=%s diagnostic=%s",
                            self.phase, len(self.attempts), provider_id, model,
                            outcome, getattr(exc, "kind", "provider_error"), diagnostic)
        raise LLMError(" | ".join(errors) or "nessun provider configurato")

    def provenance(self) -> dict[str, Any]:
        return {
            "requested_provider": self.requested_provider,
            "requested_model": self.requested_model,
            "actual_provider": self.last_used_key,
            "actual_model": self.last_used_model,
            "failover_count": max(0, len(self.attempts) - 1),
            "phase": self.phase,
            "attempts": [dict(a) for a in self.attempts],
        }


def make_provider(name: str | None = None, model: str | None = None,
                  failover: bool = True) -> LLMProvider:
    """Provider singolo (per test mirati) oppure catena di failover."""
    if name:
        key = name.lower()
        if key == "offline" or key not in PROVIDERS:
            return OfflineProvider()
        p = ChatProvider(key, model=model)
        if not failover:
            p.allow_local_fallback = False
            return p
        names = [key] + [n for n in SETTINGS.available_chain() if n != key]
        return FailoverProvider([ChatProvider(n, model=model if n == key else None)
                                 for n in names])

    chain = [ChatProvider(k) for k in SETTINGS.available_chain()]
    if not chain:
        log.warning("nessun provider LLM configurato: modalita offline")
        return OfflineProvider()
    return FailoverProvider(chain)
