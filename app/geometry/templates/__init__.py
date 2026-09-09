"""Registry dei generatori procedurali parametrici.

Ogni template dichiara il proprio schema di parametri: e' questo schema che
viene mostrato all'LLM, ed e' contro questo schema che i valori prodotti
dall'LLM vengono validati e clampati. L'LLM non puo' inventare parametri.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from app.core.spec import ComponentSpec, MaterialSpec


@dataclass
class ParamDef:
    """Un parametro di un generatore.

    `vary` dice quanto quel parametro puo' cambiare fra una variante e l'altra:
      - numerici: ampiezza relativa del disturbo (0.12 = +-12%)
      - booleani: probabilita' di essere ribaltato
      - a scelta multipla: probabilita' di pescare un'altra opzione
    Vale zero, cioe' "non toccare", per tutto cio' che cambierebbe il senso
    dell'oggetto (il tipo di carrozzeria, il numero di porte, il tipo di arma).
    """

    default: Any
    min: float | None = None
    max: float | None = None
    choices: list[Any] | None = None
    desc: str = ""
    vary: float = 0.0

    def coerce(self, value: Any) -> Any:
        """Valida e clampa un valore proposto dall'LLM. Non solleva mai."""
        try:
            if isinstance(self.default, bool):
                if isinstance(value, str):
                    return value.strip().lower() in ("true", "1", "yes", "si", "sì", "y")
                return bool(value)
            if self.choices is not None:
                v = str(value).strip().lower()
                return v if v in [str(c).lower() for c in self.choices] else self.default
            if isinstance(self.default, int):
                v = int(round(float(value)))
            else:
                v = float(value)
            if self.min is not None:
                v = max(v, type(v)(self.min))
            if self.max is not None:
                v = min(v, type(v)(self.max))
            return v
        except (TypeError, ValueError):
            return self.default


BuildFn = Callable[[dict[str, Any]], list[ComponentSpec]]
# Un template puo' dichiarare di volersi costruire come grafo di parti invece
# che come primitive incollate. I parametri restano quelli — sono la lingua con
# cui utente e LLM lo descrivono — cambia solo cosa li realizza.
AssemblyFn = Callable[[dict[str, Any]], Any]


@dataclass
class Template:
    name: str
    category: str
    description: str
    params: dict[str, ParamDef]
    materials: dict[str, MaterialSpec]
    build: BuildFn
    keywords: list[str] = field(default_factory=list)
    assembly: AssemblyFn | None = None   # se c'e', si costruisce come assemblaggio
    primary_material: str = ""   # materiale che riceve il colore chiesto genericamente
    palette: list[str] = field(default_factory=list)  # colori plausibili per le varianti

    def varying_params(self) -> dict[str, ParamDef]:
        return {k: p for k, p in self.params.items() if p.vary > 0.0}

    def defaults(self) -> dict[str, Any]:
        return {k: p.default for k, p in self.params.items()}

    def sanitize(self, raw: dict[str, Any] | None) -> dict[str, Any]:
        out = self.defaults()
        for k, v in (raw or {}).items():
            if k in self.params:
                out[k] = self.params[k].coerce(v)
        return out

    def schema_line(self) -> str:
        parts = []
        for k, p in self.params.items():
            if p.choices is not None:
                rng = "|".join(str(c) for c in p.choices)
            elif isinstance(p.default, bool):
                rng = "true|false"
            elif p.min is not None:
                rng = f"{p.min}..{p.max}"
            else:
                rng = "num"
            parts.append(f"{k}({rng})")
        return f"- {self.name} [{self.category}]: {self.description}\n    params: " + ", ".join(parts)


TEMPLATES: dict[str, Template] = {}


def register(t: Template) -> Template:
    TEMPLATES[t.name] = t
    return t


def get(name: str) -> Template | None:
    return TEMPLATES.get(name)


def llm_catalog() -> str:
    """Descrizione compatta di tutti i template, da iniettare nel system prompt."""
    return "\n".join(t.schema_line() for t in TEMPLATES.values())


_LOADED = False


def load_all() -> None:
    global _LOADED
    from app.geometry.templates import (  # noqa: F401
        basic, building, character, furniture, nature, vehicle, weapon,
    )
    if not _LOADED:
        from app.geometry.templates import variation_profile

        variation_profile.apply(TEMPLATES)
        _LOADED = True
