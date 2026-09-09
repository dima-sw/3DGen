"""Configurazione applicativa e registro dei provider LLM.

Nessuna chiave API compare mai nel codice: tutto arriva da .env.
I provider sono descritti da dati, non da codice: aggiungerne uno significa
aggiungere una riga a PROVIDERS.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]


def _user_root() -> Path:
    """Dove scrivere output, libreria e progetti.

    Da sorgente e' la cartella del progetto, ed e' giusto cosi': tutto resta
    sotto mano. **Installato**, no: `ROOT` finirebbe dentro `_internal`, cioe'
    in Programmi, dove un utente comune non puo' scrivere. In quel caso i dati
    vanno nel profilo dell'utente, che e' anche il posto in cui li cerchera'.
    """
    if getattr(sys, "frozen", False):
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        cartella = Path(base) / "3DGen"
        cartella.mkdir(parents=True, exist_ok=True)
        return cartella
    return ROOT


USER_ROOT = _user_root()
# Il .env sta accanto all'eseguibile quando c'e' un eseguibile: le chiavi sono
# dell'utente, non del pacchetto, e non vanno mai dentro la distribuzione.
for _candidato in (USER_ROOT / ".env", ROOT / ".env"):
    if _candidato.is_file():
        load_dotenv(_candidato)
        break

# Su Windows gli antivirus con "scansione HTTPS" (Avast, Kaspersky, ESET...)
# rimpiazzano i certificati con una propria root CA. Python, a differenza dei
# browser, non legge lo store di Windows e rifiuta ogni connessione. truststore
# gli fa usare lo store di sistema: la verifica resta attiva, semplicemente
# usa le CA che il sistema gia' considera valide.
try:
    import truststore

    truststore.inject_into_ssl()
    SYSTEM_TRUST_STORE = True
except Exception:  # pragma: no cover - dipendenza opzionale
    SYSTEM_TRUST_STORE = False


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _first_env(keys: tuple[str, ...]) -> str:
    for k in keys:
        v = _env(k)
        if v:
            return v
    return ""


@dataclass(frozen=True)
class ProviderSpec:
    """Descrizione di un endpoint LLM compatibile OpenAI."""

    key: str
    label: str
    endpoint: str
    key_env: tuple[str, ...]
    model_env: str
    default_model: str
    json_mode: bool = True
    free_tier: bool = False
    needs_key: bool = True
    note: str = ""


# Tutti questi espongono un endpoint in stile OpenAI /chat/completions.
PROVIDERS: dict[str, ProviderSpec] = {
    "groq": ProviderSpec(
        key="groq", label="Groq",
        endpoint="https://api.groq.com/openai/v1/chat/completions",
        key_env=("GROQ_API_KEY", "NEXT_PUBLIC_GROQ_API_KEY"),
        model_env="GROQ_MODEL", default_model="openai/gpt-oss-120b",
        json_mode=True, free_tier=True,
        note="gratis e molto veloce, ottimo per il planning JSON",
    ),
    "gemini": ProviderSpec(
        key="gemini", label="Google Gemini",
        endpoint="https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        key_env=("GEMINI_API_KEY", "NEXT_PUBLIC_GEMINI_API_KEY"),
        model_env="GEMINI_MODEL", default_model="gemini-flash-latest",
        json_mode=True, free_tier=True,
        note="free tier ampio, endpoint compatibile OpenAI",
    ),
    "mistral": ProviderSpec(
        key="mistral", label="Mistral",
        endpoint="https://api.mistral.ai/v1/chat/completions",
        key_env=("MISTRAL_API_KEY", "NEXT_PUBLIC_MISTRAL_API_KEY"),
        model_env="MISTRAL_MODEL", default_model="mistral-small-latest",
        json_mode=True, free_tier=True,
        note="piano Experiment gratuito, piu' che sufficiente per un piano JSON",
    ),
    "openrouter": ProviderSpec(
        key="openrouter", label="OpenRouter",
        endpoint="https://openrouter.ai/api/v1/chat/completions",
        key_env=("OPENROUTER_API_KEY", "NEXT_PUBLIC_OPENROUTER_API_KEY"),
        model_env="OPENROUTER_MODEL",
        default_model="nvidia/nemotron-3-ultra-550b-a55b:free",
        json_mode=False, free_tier=True,
        note="usare modelli con suffisso :free per non spendere",
    ),
    "cohere": ProviderSpec(
        key="cohere", label="Cohere",
        endpoint="https://api.cohere.ai/compatibility/v1/chat/completions",
        key_env=("COHERE_API_KEY", "NEXT_PUBLIC_COHERE_API_KEY"),
        model_env="COHERE_MODEL", default_model="command-r7b-12-2024",
        json_mode=False, free_tier=True,
        note="chiavi trial gratuite con limiti di frequenza",
    ),
    "huggingface": ProviderSpec(
        key="huggingface", label="HuggingFace",
        endpoint="https://router.huggingface.co/v1/chat/completions",
        key_env=("HF_API_KEY", "HUGGINGFACE_API_KEY", "HF_TOKEN",
                 "NEXT_PUBLIC_HUGGINGFACE_API_KEY"),
        model_env="HF_MODEL", default_model="mistralai/Mistral-7B-Instruct-v0.3",
        json_mode=False, free_tier=True,
        note="credito mensile gratuito limitato",
    ),
    "ollama": ProviderSpec(
        key="ollama", label="Ollama (locale)",
        endpoint="", key_env=(), model_env="OLLAMA_MODEL",
        default_model="qwen2.5:7b", json_mode=True, free_tier=True, needs_key=False,
        note="100% locale e offline; su 6 GB di VRAM restare su modelli 7B quantizzati",
    ),
    "openai": ProviderSpec(
        key="openai", label="OpenAI",
        endpoint="https://api.openai.com/v1/chat/completions",
        key_env=("OPENAI_API_KEY",),
        model_env="OPENAI_CHAT_MODEL", default_model="gpt-4o-mini",
        json_mode=True, free_tier=False,
        note="a pagamento: fuori dalla catena predefinita",
    ),
    "deepseek": ProviderSpec(
        key="deepseek", label="DeepSeek",
        endpoint="https://api.deepseek.com/v1/chat/completions",
        key_env=("DEEPSEEK_API_KEY", "NEXT_PUBLIC_DEEPSEEK_API_KEY"),
        model_env="DEEPSEEK_MODEL", default_model="deepseek-chat",
        json_mode=True, free_tier=False,
        note="a pagamento: fuori dalla catena predefinita",
    ),
}

# Ordine di failover predefinito: solo provider con piano gratuito.
DEFAULT_CHAIN = ["groq", "gemini", "mistral", "openrouter", "cohere", "huggingface", "ollama"]


@dataclass
class Settings:
    log_level: str = field(default_factory=lambda: _env("GEN3D_LOG_LEVEL", "INFO") or "INFO")
    output_dir: Path = field(
        default_factory=lambda: USER_ROOT / (_env("GEN3D_OUTPUT_DIR", "output") or "output"))
    library_dir: Path = field(
        default_factory=lambda: USER_ROOT / (_env("GEN3D_LIBRARY_DIR", "library") or "library"))
    request_timeout: int = field(default_factory=lambda: int(_env("GEN3D_TIMEOUT", "60") or 60))
    # "auto" sceglie in base alla macchina; basso | medio | alto forzano.
    quality: str = field(default_factory=lambda: _env("GEN3D_QUALITY", "auto") or "auto")
    ollama_endpoint: str = field(
        default_factory=lambda: (_first_env(("OLLAMA_ENDPOINT", "NEXT_PUBLIC_OLLAMA_ENDPOINT"))
                                 or "http://localhost:11434").rstrip("/"))

    # -------------------------------------------------------------- chiavi #
    def api_key(self, provider: str) -> str:
        spec = PROVIDERS.get(provider)
        return _first_env(spec.key_env) if spec else ""

    def model(self, provider: str) -> str:
        spec = PROVIDERS.get(provider)
        if not spec:
            return ""
        return _env(spec.model_env) or spec.default_model

    def endpoint(self, provider: str) -> str:
        spec = PROVIDERS.get(provider)
        if not spec:
            return ""
        if provider == "ollama":
            return self.ollama_endpoint + "/v1/chat/completions"
        return spec.endpoint

    def configured(self, provider: str) -> bool:
        spec = PROVIDERS.get(provider)
        if not spec:
            return False
        return True if not spec.needs_key else bool(self.api_key(provider))

    # --------------------------------------------------------------- catena #
    def chain(self) -> list[str]:
        """Ordine di failover: dal .env se presente, altrimenti i gratuiti."""
        raw = _env("GEN3D_LLM_CHAIN") or _env("GEN3D_LLM_PROVIDER")
        names = [n.strip().lower() for n in raw.replace(";", ",").split(",") if n.strip()]
        if not names:
            names = list(DEFAULT_CHAIN)
        return [n for n in names if n in PROVIDERS or n == "offline"]

    def available_chain(self) -> list[str]:
        """Solo i provider effettivamente configurati, nell'ordine scelto."""
        return [n for n in self.chain() if n != "offline" and self.configured(n)]

    def status_table(self) -> list[tuple[str, str, bool, bool, str]]:
        """(chiave, etichetta, configurato, gratuito, modello) per la UI."""
        rows = []
        for key, spec in PROVIDERS.items():
            rows.append((key, spec.label, self.configured(key), spec.free_tier, self.model(key)))
        return rows


SETTINGS = Settings()
SETTINGS.output_dir.mkdir(parents=True, exist_ok=True)
SETTINGS.library_dir.mkdir(parents=True, exist_ok=True)
