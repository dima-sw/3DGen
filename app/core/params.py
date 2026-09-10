"""Parametri tipati, e parametri derivati da espressioni sicure.

Ogni componente possiede il proprio vocabolario di parametri: il core non sa
che cosa sia `snout_length`, sa che e' un `distance` fra 0 e 2 con un valore
predefinito. Nessun catalogo globale di nomi — se ci fosse, aggiungere un
plugin vorrebbe dire modificare il core.

## Espressioni

Il valutatore viene da `app/geometry/recipe.py`, dove funzionava gia' bene:
`ast` con lista bianca, niente `__import__`, niente chiamate fuori da un
insieme fisso, niente indicizzazioni, niente attributi arbitrari. **Non e' stato
riscritto**, e' stato spostato e allargato agli scope.

Uno scope permette a un parametro di dipendere da chi lo contiene:

    self.eye_spacing  = self.width * 0.38
    self.height       = parent.height * 0.22
    self.radius       = root.height * 0.05

Tre soli scope, di proposito: `self`, `parent`, `root`. Bastano a tutto quello
che il vertical slice chiede, e non aprono la porta a un risolutore di vincoli
generale che nessuno ha ancora chiesto.
"""
from __future__ import annotations

import ast
import math
import operator
from dataclasses import dataclass
from typing import Any

import numpy as np

# --------------------------------------------------------------------------- #
# Espressioni
# --------------------------------------------------------------------------- #
_BINOPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
           ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod}
_UNARY = {ast.USub: operator.neg, ast.UAdd: operator.pos}
_COMPARE = {ast.Lt: operator.lt, ast.LtE: operator.le, ast.Gt: operator.gt,
            ast.GtE: operator.ge, ast.Eq: operator.eq, ast.NotEq: operator.ne}
_FUNCS = {"min": min, "max": max, "abs": abs, "sqrt": math.sqrt,
          "sin": math.sin, "cos": math.cos, "tan": math.tan,
          "radians": math.radians, "floor": math.floor, "ceil": math.ceil,
          "clamp": lambda v, lo, hi: max(lo, min(hi, v))}

SCOPES = ("self", "parent", "root")


class ExpressionError(ValueError):
    """Un'espressione illeggibile o non ammessa. Mai un'eccezione di Python."""


def evaluate(expression: Any, variables: dict[str, float],
             scopes: dict[str, dict[str, float]] | None = None) -> float:
    """Aritmetica sui parametri. Solo numeri, mai codice.

    `variables` sono i nomi nudi (`width`); `scopes` sono i vocabolari
    qualificati (`parent.height`). I nomi nudi valgono come `self`.
    """
    if isinstance(expression, bool):
        return float(expression)
    if isinstance(expression, (int, float)):
        return float(expression)
    if not isinstance(expression, str):
        raise ExpressionError("espressione non valida: %r" % (expression,))
    try:
        sintassi = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ExpressionError("espressione illeggibile %r: %s"
                              % (expression, exc)) from exc
    return float(_eval(sintassi.body, variables, scopes or {}, expression))


def _eval(node: ast.AST, variables: dict, scopes: dict, source: str) -> float:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ExpressionError("costante non numerica in %r" % source)
        return float(node.value)

    if isinstance(node, ast.Name):
        if node.id in variables:
            return float(variables[node.id])
        raise ExpressionError("parametro sconosciuto '%s' in %r" % (node.id, source))

    # `parent.height`: l'unico attributo ammesso e' uno scope dichiarato, e
    # solo di profondita' uno. Niente `a.b.c`, niente attributi di oggetti.
    if isinstance(node, ast.Attribute):
        if not isinstance(node.value, ast.Name) or node.value.id not in SCOPES:
            raise ExpressionError("attributo non ammesso in %r "
                                  "(scope validi: %s)" % (source, ", ".join(SCOPES)))
        vocabolario = scopes.get(node.value.id)
        if vocabolario is None:
            raise ExpressionError("scope '%s' non disponibile in %r"
                                  % (node.value.id, source))
        if node.attr not in vocabolario:
            raise ExpressionError("'%s.%s' non esiste in %r"
                                  % (node.value.id, node.attr, source))
        return float(vocabolario[node.attr])

    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        return _BINOPS[type(node.op)](_eval(node.left, variables, scopes, source),
                                      _eval(node.right, variables, scopes, source))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_eval(node.operand, variables, scopes, source))
    if isinstance(node, ast.Compare) and len(node.ops) == 1 \
            and type(node.ops[0]) in _COMPARE:
        return float(_COMPARE[type(node.ops[0])](
            _eval(node.left, variables, scopes, source),
            _eval(node.comparators[0], variables, scopes, source)))
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS:
            raise ExpressionError("funzione non ammessa in %r" % source)
        if node.keywords:
            raise ExpressionError("argomenti nominati non ammessi in %r" % source)
        return float(_FUNCS[node.func.id](
            *[_eval(a, variables, scopes, source) for a in node.args]))
    if isinstance(node, ast.IfExp):
        cond = _eval(node.test, variables, scopes, source)
        return _eval(node.body if cond else node.orelse, variables, scopes, source)

    raise ExpressionError("costrutto non ammesso in %r" % source)


# --------------------------------------------------------------------------- #
# Tipi
# --------------------------------------------------------------------------- #
FLOAT, INT, BOOL, ENUM, STRING = "float", "int", "bool", "enum", "string"
VECTOR2, VECTOR3, COLOR = "vector2", "vector3", "color"
ANGLE, DISTANCE, RATIO = "angle", "distance", "ratio"

# I tipi che si comportano come numeri: differiscono per unita' e significato,
# non per come si validano. Tenerli distinti serve alla diagnostica e all'LLM.
NUMERIC = (FLOAT, ANGLE, DISTANCE, RATIO)
VECTORS = {VECTOR2: 2, VECTOR3: 3, COLOR: 3}
TYPES = (FLOAT, INT, BOOL, ENUM, STRING, VECTOR2, VECTOR3, COLOR,
         ANGLE, DISTANCE, RATIO)


@dataclass(frozen=True)
class ParamSpec:
    """Un parametro con il suo intervallo: l'LLM sceglie dentro, non fuori."""

    default: Any = 0.0
    type: str = FLOAT
    min: float | None = None
    max: float | None = None
    choices: tuple = ()
    unit: str = ""
    description: str = ""
    semantic_role: str = ""          # "length", "girth"... usato dagli effetti
    derived: str = ""                # espressione: se c'e', il valore si calcola
    required: bool = False

    @property
    def is_derived(self) -> bool:
        return bool(self.derived)

    def coerce(self, value: Any) -> Any:
        """Porta un valore dentro il contratto. Non solleva mai."""
        try:
            return self._coerce(value)
        except (TypeError, ValueError):
            return self.default

    def _coerce(self, value: Any) -> Any:
        if self.type == BOOL:
            if isinstance(value, str):
                return value.strip().lower() in ("true", "1", "si", "sì", "yes", "y")
            return bool(value)
        if self.type == STRING:
            return str(value)
        if self.type == ENUM:
            testo = str(value).strip().lower()
            ammessi = {str(c).lower(): c for c in self.choices}
            return ammessi.get(testo, self.default)
        if self.type in VECTORS:
            attesi = VECTORS[self.type]
            if isinstance(value, (list, tuple, np.ndarray)):
                numeri = [float(v) for v in value][:attesi]
            else:
                numeri = [float(value)] * attesi
            while len(numeri) < attesi:
                numeri.append(0.0)
            return tuple(self._clamp(v) for v in numeri)
        if self.type == INT:
            return int(self._clamp(int(round(float(value)))))
        return float(self._clamp(float(value)))

    def _clamp(self, value: float) -> float:
        if self.min is not None:
            value = max(value, self.min)
        if self.max is not None:
            value = min(value, self.max)
        return value

    def describe(self, name: str) -> str:
        pezzi = [self.type]
        if self.min is not None or self.max is not None:
            pezzi.append("%s..%s" % (self.min, self.max))
        if self.choices:
            pezzi.append("|".join(str(c) for c in self.choices))
        if self.unit:
            pezzi.append(self.unit)
        if self.is_derived:
            pezzi.append("= %s" % self.derived)
        return "%s (%s)" % (name, ", ".join(pezzi))


def resolve(schema: dict[str, ParamSpec], values: dict | None = None,
            scopes: dict[str, dict[str, float]] | None = None,
            report=None, where: str = "") -> dict[str, Any]:
    """Valori validi a partire da quelli chiesti.

    L'ordine conta: prima i valori espliciti (validati), poi i derivati — cosi'
    una formula puo' leggere un parametro che l'utente ha appena impostato.
    Un valore fuori intervallo viene riportato dentro e **annotato**, non
    respinto: un piano leggermente sbagliato deve comunque produrre qualcosa.
    """
    out: dict[str, Any] = {}
    chiesti = values or {}

    for nome, spec in schema.items():
        if spec.is_derived:
            continue
        if nome in chiesti:
            grezzo = chiesti[nome]
            valore = spec.coerce(grezzo)
            if report is not None and _fuori(spec, grezzo, valore):
                report.warn("PARAM_CLAMPED",
                            "'%s' portato da %s a %s" % (nome, grezzo, valore),
                            where=where, why="fuori dall'intervallo dichiarato")
            out[nome] = valore
        else:
            out[nome] = spec.default

    if report is not None:
        for nome in chiesti:
            if nome not in schema:
                report.note("PARAM_UNKNOWN", "parametro ignorato: '%s'" % nome,
                            where=where,
                            alternatives=sorted(schema)[:6])

    ambiti = dict(scopes or {})
    for nome, spec in schema.items():
        if not spec.is_derived:
            continue
        ambiti["self"] = {k: v for k, v in out.items() if isinstance(v, (int, float))}
        try:
            out[nome] = spec.coerce(evaluate(spec.derived, ambiti["self"], ambiti))
        except ExpressionError as exc:
            out[nome] = spec.default
            if report is not None:
                report.warn("PARAM_EXPRESSION",
                            "'%s' non calcolabile: %s" % (nome, exc), where=where,
                            why="si usa il valore predefinito %s" % spec.default)
    return out


def _fuori(spec: ParamSpec, grezzo: Any, valore: Any) -> bool:
    if spec.type not in NUMERIC and spec.type != INT:
        return False
    try:
        return abs(float(grezzo) - float(valore)) > 1e-9
    except (TypeError, ValueError):
        return True


def numeric(values: dict[str, Any]) -> dict[str, float]:
    """Solo i valori che un'espressione puo' usare."""
    return {k: float(v) for k, v in values.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)}
