"""Regole dichiarative sui parametri risolti.

Un componente puo' dire «la distanza fra gli occhi deve stare dentro la
larghezza della testa» senza che il core sappia che cosa siano occhi e teste:

    Constraint("eye_spacing < width", message="gli occhi escono dalla testa")

Il core valuta l'espressione e riporta. Il significato e' del plugin.

## Tre severita', e la terza e' quella utile

- `error`   il modello non e' valido: si costruisce lo stesso, ma il referto lo
            dice. (Regola del progetto: nessuna richiesta resta senza risposta.)
- `warning` sospetto, si va avanti.
- `clamp`   **si corregge da soli**: il vincolo nomina un parametro e un valore
            di rientro, e il sistema ce lo riporta. E' la severita' piu' utile
            perche' evita che un piano quasi giusto produca un modello rotto.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.core.errors import ERROR, WARNING
from app.core.params import ExpressionError, ParamSpec, evaluate

CLAMP = "clamp"


@dataclass(frozen=True)
class Constraint:
    """Una regola che i parametri devono rispettare."""

    expression: str                  # deve valutare a vero
    message: str = ""
    severity: str = ERROR
    source: str = ""                 # chi l'ha dichiarata, per la diagnosi
    # solo per severity="clamp": che cosa correggere e a quale valore
    target: str = ""
    to: str = ""

    def describe(self) -> str:
        return self.message or ("la regola '%s' non e' rispettata" % self.expression)


def check(constraints, values: dict, schema: dict[str, ParamSpec] | None = None,
          scopes: dict | None = None, report=None, where: str = "") -> dict:
    """Verifica i vincoli e, dove dichiarato, corregge.

    Restituisce i valori — eventualmente corretti. Non solleva: un vincolo
    violato e' una diagnosi, non un incidente.
    """
    from app.core.params import numeric

    out = dict(values)
    for regola in constraints or ():
        ambiti = dict(scopes or {})
        ambiti["self"] = numeric(out)
        try:
            soddisfatto = bool(evaluate(regola.expression, ambiti["self"], ambiti))
        except ExpressionError as exc:
            if report is not None:
                report.warn("CONSTRAINT_BROKEN",
                            "regola non valutabile: %s" % regola.expression,
                            where=where or regola.source, why=str(exc))
            continue

        if soddisfatto:
            continue

        if regola.severity == CLAMP and regola.target:
            nuovo = _corretto(regola, out, ambiti, schema)
            if nuovo is not None:
                if report is not None:
                    report.note("CONSTRAINT_CLAMPED",
                                "%s: '%s' portato a %s"
                                % (regola.describe(), regola.target, nuovo),
                                where=where or regola.source)
                out[regola.target] = nuovo
                continue

        if report is not None:
            report.add("CONSTRAINT_VIOLATED", regola.describe(),
                       where=where or regola.source,
                       why="non e' vero che %s" % regola.expression,
                       severity=ERROR if regola.severity == ERROR else WARNING)
    return out


def _corretto(regola: Constraint, values: dict, scopes: dict,
              schema: dict[str, ParamSpec] | None):
    """Il valore di rientro per un vincolo che sa correggersi."""
    from app.core.params import numeric

    if not regola.to:
        return None
    try:
        valore = evaluate(regola.to, numeric(values), scopes)
    except ExpressionError:
        return None
    if schema and regola.target in schema:
        return schema[regola.target].coerce(valore)
    return valore
