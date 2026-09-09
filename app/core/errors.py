"""Diagnostica strutturata: cosa e' fallito, dove, perche', e cosa c'era invece.

Un messaggio d'errore qui non serve solo a chi legge il log. Serve anche
all'unica correzione che l'LLM ha a disposizione: se il messaggio dice
"richiedeva `head_mount`, questo componente offre `window_mount`, e queste
altre tre cose forniscono `head_mount`", il piano corretto si scrive da se'.
Un `ValueError("socket non trovato")` invece non aiuta nessuno.

Per questo un `Diagnostic` porta quattro cose separate — **che cosa**, **dove**,
**perche'**, **alternative** — e non una stringa unica in cui cercarle.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Iterator

ERROR = "error"
WARNING = "warning"
INFO = "info"

_ORDINE = {ERROR: 0, WARNING: 1, INFO: 2}


@dataclass(frozen=True)
class Diagnostic:
    """Una cosa andata storta, spiegata."""

    code: str                          # "SOCKET_INCOMPATIBLE", stabile, per i test
    message: str                       # che cosa e' successo
    where: str = ""                    # percorso nel grafo: "corpo/testa/naso"
    why: str = ""                       # la ragione, se non e' ovvia dal messaggio
    alternatives: tuple[str, ...] = ()  # che cosa si poteva usare invece
    severity: str = ERROR

    @property
    def fatal(self) -> bool:
        return self.severity == ERROR

    def describe(self) -> str:
        righe = [self.message if not self.where
                 else "%s  [%s]" % (self.message, self.where)]
        if self.why:
            righe.append("  perche': %s" % self.why)
        if self.alternatives:
            righe.append("  alternative: %s" % ", ".join(self.alternatives))
        return "\n".join(righe)

    def __str__(self) -> str:
        return self.describe()


@dataclass
class Report:
    """Tutto cio' che e' andato storto in una costruzione.

    Si raccoglie invece di sollevare: un pezzo che non si attacca non deve far
    cadere il modello intero, deve comparire nel referto. E' la stessa regola
    che il progetto applica da sempre — nessuna richiesta resta senza risposta.
    """

    entries: list[Diagnostic] = field(default_factory=list)

    def add(self, code: str, message: str, where: str = "", why: str = "",
            alternatives: Iterable[str] = (), severity: str = ERROR) -> Diagnostic:
        voce = Diagnostic(code=code, message=message, where=where, why=why,
                          alternatives=tuple(alternatives), severity=severity)
        self.entries.append(voce)
        return voce

    def warn(self, code: str, message: str, **kwargs) -> Diagnostic:
        return self.add(code, message, severity=WARNING, **kwargs)

    def note(self, code: str, message: str, **kwargs) -> Diagnostic:
        return self.add(code, message, severity=INFO, **kwargs)

    # ------------------------------------------------------------- lettura #
    @property
    def ok(self) -> bool:
        return not any(d.fatal for d in self.entries)

    def errors(self) -> list[Diagnostic]:
        return [d for d in self.entries if d.fatal]

    def codes(self) -> set[str]:
        return {d.code for d in self.entries}

    def sorted(self) -> list[Diagnostic]:
        """Prima gli errori, poi gli avvisi, poi le note. Ordine stabile."""
        return sorted(self.entries, key=lambda d: _ORDINE.get(d.severity, 9))

    def describe(self) -> str:
        return "\n".join(d.describe() for d in self.sorted())

    def extend(self, other: "Report") -> "Report":
        self.entries.extend(other.entries)
        return self

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self) -> Iterator[Diagnostic]:
        return iter(self.entries)

    def __bool__(self) -> bool:
        return bool(self.entries)
