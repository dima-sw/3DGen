"""Provider LLM intercambiabili, con catena di failover.

Il resto dell'applicazione conosce solo l'interfaccia LLMProvider. Tutti i
fornitori usati qui espongono un endpoint in stile OpenAI /chat/completions,
quindi basta una sola implementazione parametrizzata dai dati in config.
"""
from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import Any

import requests

from app.core.config import PROVIDERS, SETTINGS
from app.core.logging_setup import get

log = get("ai.provider")

JSON_BLOCK = re.compile(r"\{.*\}", re.S)


class LLMError(RuntimeError):
    pass


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

    def __init__(self, provider_key: str) -> None:
        spec = PROVIDERS[provider_key]
        self.key = provider_key
        self.name = spec.label
        self.spec = spec
        self.api_key = SETTINGS.api_key(provider_key)
        self.model = SETTINGS.model(provider_key)
        self.endpoint = SETTINGS.endpoint(provider_key)

    def available(self) -> bool:
        return SETTINGS.configured(self.key) and bool(self.endpoint)

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
            raise LLMError("provider %s non configurato" % self.name)

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": float(temperature),
            "max_tokens": 2400,
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
        log.info("richiesta a %s (%s)", self.name, self.model)
        try:
            r = requests.post(self.endpoint, headers=self._headers(),
                              json=payload, timeout=timeout)
        except requests.RequestException as exc:
            raise LLMError("%s irraggiungibile: %s" % (self.name, exc)) from exc

        if r.status_code in (401, 403):
            raise LLMError("chiave API rifiutata da %s" % self.name)
        if r.status_code == 429:
            raise LLMError("limite di richieste raggiunto su %s" % self.name)
        if r.status_code == 402:
            raise LLMError("credito esaurito su %s" % self.name)
        if r.status_code >= 400:
            raise LLMError("%s ha risposto %d: %s" % (self.name, r.status_code, r.text[:200]))

        try:
            data = r.json()
            content = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError) as exc:
            raise LLMError("risposta inattesa da %s" % self.name) from exc
        return self._extract_json(content)


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
        self.providers = providers
        self.name = " > ".join(p.name for p in providers) or "nessuno"
        self.last_used: str = ""
        self.attempts: list[str] = []

    def available(self) -> bool:
        return any(p.available() for p in self.providers)

    @property
    def structured(self) -> bool:
        return any(p.structured for p in self.providers)

    def complete_json(self, system: str, user: str,
                      temperature: float = 0.2,
                      schema: dict[str, Any] | None = None) -> dict[str, Any]:
        self.attempts = []
        errors: list[str] = []
        for p in self.providers:
            if not p.available():
                continue
            try:
                result = p.complete_json(system, user, temperature,
                                         schema=schema)
                self.last_used = p.name
                self.attempts.append("%s: ok" % p.name)
                return result
            except LLMError as exc:
                errors.append("%s: %s" % (p.name, exc))
                self.attempts.append("%s: %s" % (p.name, exc))
                log.warning("%s non utilizzabile (%s), passo al successivo", p.name, exc)
        raise LLMError(" | ".join(errors) or "nessun provider configurato")


def make_provider(name: str | None = None) -> LLMProvider:
    """Provider singolo (per test mirati) oppure catena di failover."""
    if name:
        key = name.lower()
        if key == "offline" or key not in PROVIDERS:
            return OfflineProvider()
        p = ChatProvider(key)
        return p if p.available() else OfflineProvider()

    chain = [ChatProvider(k) for k in SETTINGS.available_chain()]
    if not chain:
        log.warning("nessun provider LLM configurato: modalita offline")
        return OfflineProvider()
    return FailoverProvider(chain)
