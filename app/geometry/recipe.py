"""Ricette di parti: dati, non codice.

Una parte non e' una classe da scrivere ma una descrizione che dice quale
albero della grammatica costruire e dove si attacca. Sta in un file JSON, si
aggiunge senza toccare il motore, e l'LLM puo' scriverne di nuove al volo per
cio' che il catalogo non copre.

    PARTE = PARAMETRI + SOCKET + OPERAZIONI + VINCOLI

Le espressioni nelle ricette ("length * 0.9") sono aritmetica pura valutata da
un interprete ristretto: nessuna chiamata arbitraria, nessun accesso a nomi che
non siano i parametri della ricetta. Vale anche per le ricette scritte dall'LLM.
"""
from __future__ import annotations

import ast
import json
import math
import operator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from pydantic import BaseModel, ConfigDict, Field as PField

from app.core.logging_setup import get
from app.geometry import sdf

log = get("geometry.recipe")

RECIPE_DIR = Path(__file__).resolve().parent / "parts"

# campi dei nodi della grammatica che devono restare interi
INT_FIELDS = {"axis", "count", "sections", "subdiv"}

_BINOPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
           ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod}
_UNARY = {ast.USub: operator.neg, ast.UAdd: operator.pos}
_FUNCS = {"min": min, "max": max, "abs": abs, "sqrt": math.sqrt,
          "sin": math.sin, "cos": math.cos, "tan": math.tan,
          "radians": math.radians, "clamp": lambda v, lo, hi: max(lo, min(hi, v))}


class RecipeError(ValueError):
    pass


def evaluate(expression: Any, variables: dict[str, float]) -> float:
    """Aritmetica sui parametri della ricetta. Solo numeri, mai codice."""
    if isinstance(expression, bool):
        return float(expression)
    if isinstance(expression, (int, float)):
        return float(expression)
    if not isinstance(expression, str):
        raise RecipeError("espressione non valida: %r" % (expression,))
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise RecipeError("espressione illeggibile %r: %s" % (expression, exc)) from exc
    return float(_eval_node(tree.body, variables, expression))


def _eval_node(node: ast.AST, variables: dict[str, float], source: str) -> float:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise RecipeError("costante non numerica in %r" % source)
        return float(node.value)
    if isinstance(node, ast.Name):
        if node.id not in variables:
            raise RecipeError("parametro sconosciuto '%s' in %r" % (node.id, source))
        return float(variables[node.id])
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        return _BINOPS[type(node.op)](_eval_node(node.left, variables, source),
                                      _eval_node(node.right, variables, source))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_eval_node(node.operand, variables, source))
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS:
            raise RecipeError("funzione non ammessa in %r" % source)
        args = [_eval_node(a, variables, source) for a in node.args]
        if node.keywords:
            raise RecipeError("argomenti nominati non ammessi in %r" % source)
        return float(_FUNCS[node.func.id](*args))
    if isinstance(node, ast.IfExp):
        cond = _eval_node(node.test, variables, source)
        return _eval_node(node.body if cond else node.orelse, variables, source)
    raise RecipeError("costrutto non ammesso in %r" % source)


def _vec(value: Any, variables: dict[str, float]) -> np.ndarray:
    if isinstance(value, (list, tuple)):
        return np.array([evaluate(v, variables) for v in value], dtype=float)
    v = evaluate(value, variables)
    return np.array([v, v, v], dtype=float)


# --------------------------------------------------------------------------- #
# Socket
# --------------------------------------------------------------------------- #
@dataclass
class Socket:
    """Punto di attacco: dove va una parte, in che verso, con che spessore.

    `up` non e' decorativo: senza un secondo vettore la rotazione di attacco
    resterebbe indeterminata attorno all'asse, e una testa attaccata di lato
    guarderebbe in su. Convenzione del catalogo: ogni parte cresce lungo +X
    dalla propria base, con il dorso verso +Y.
    """

    name: str
    position: np.ndarray
    direction: np.ndarray
    radius: float
    kind: str = "generic"
    up: np.ndarray = field(default_factory=lambda: np.array([0.0, 1.0, 0.0]))

    def __post_init__(self) -> None:
        self.position = np.asarray(self.position, dtype=float)
        self.direction = _unit(self.direction, (0.0, 1.0, 0.0))
        self.up = _orthogonal_up(self.direction, self.up)
        self.radius = max(float(self.radius), 1e-3)

    def frame(self) -> np.ndarray:
        """Terna ortonormale (direzione, dorso, laterale) come colonne."""
        third = np.cross(self.direction, self.up)
        return np.column_stack([self.direction, self.up, third])


def _unit(vector, fallback) -> np.ndarray:
    v = np.asarray(vector, dtype=float)
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-9 else np.asarray(fallback, dtype=float)


def _orthogonal_up(direction: np.ndarray, up) -> np.ndarray:
    """Rende `up` ortogonale alla direzione, scegliendone uno se degenere."""
    u = _unit(up, (0.0, 1.0, 0.0))
    u = u - direction * float(direction @ u)
    if float(np.linalg.norm(u)) < 1e-6:
        candidate = np.array([0.0, 1.0, 0.0])
        if abs(float(direction @ candidate)) > 0.9:
            candidate = np.array([0.0, 0.0, 1.0])
        u = candidate - direction * float(direction @ candidate)
    return _unit(u, (0.0, 1.0, 0.0))


class SocketSpec(BaseModel):
    """Uno o piu' socket generati con la stessa regola."""

    model_config = ConfigDict(extra="forbid")

    name: str
    position: list[Any] = PField(default_factory=lambda: [0, 0, 0])
    direction: list[Any] = PField(default_factory=lambda: [0, 1, 0])
    up: list[Any] = PField(default_factory=lambda: [0, 1, 0])
    radius: Any = 0.1
    kind: str = "generic"
    arrangement: str = "single"          # single | pair | radial | row
    count: Any = 1
    axis: int = 0                        # asse di distribuzione per radial/row
    spacing: Any = 0.2                   # passo per row
    ring: Any = 0.2                      # raggio dell'anello per radial

    def build(self, variables: dict[str, float]) -> list[Socket]:
        pos = _vec(self.position, variables)
        direction = _vec(self.direction, variables)
        up = _vec(self.up, variables)
        radius = evaluate(self.radius, variables)
        count = max(int(round(evaluate(self.count, variables))), 0)
        axis = int(self.axis) % 3

        if self.arrangement == "single":
            return [Socket(self.name, pos, direction, radius, self.kind, up)]

        if self.arrangement == "pair":
            # riflessione sull'asse indicato: e' la simmetria bilaterale
            out = []
            for suffix, sign in (("l", -1.0), ("r", 1.0)):
                p, d, u = pos.copy(), direction.copy(), up.copy()
                p[axis] = abs(p[axis]) * sign
                d[axis] = abs(d[axis]) * sign
                u[axis] = u[axis] * sign
                out.append(Socket("%s_%s" % (self.name, suffix), p, d, radius, self.kind, u))
            return out

        if self.arrangement == "radial":
            ring = evaluate(self.ring, variables)
            u, w = [i for i in range(3) if i != axis]
            out = []
            for i in range(count):
                a = 2.0 * math.pi * i / max(count, 1)
                p = pos.copy()
                p[u] += ring * math.cos(a)
                p[w] += ring * math.sin(a)
                d = np.zeros(3)
                d[u], d[w] = math.cos(a), math.sin(a)
                d = d + direction * 0.35
                spoke = np.zeros(3)
                spoke[axis] = 1.0
                out.append(Socket("%s_%d" % (self.name, i), p, d, radius, self.kind, spoke))
            return out

        if self.arrangement == "row":
            spacing = evaluate(self.spacing, variables)
            out = []
            for i in range(count):
                p = pos.copy()
                p[axis] += spacing * (i - (count - 1) / 2.0)
                out.append(Socket("%s_%d" % (self.name, i), p, direction, radius, self.kind, up))
            return out

        raise RecipeError("disposizione socket sconosciuta: %s" % self.arrangement)


# --------------------------------------------------------------------------- #
# Ricetta
# --------------------------------------------------------------------------- #
class ParamSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default: float = 1.0
    min: float | None = None
    max: float | None = None
    vary: float = 0.0
    desc: str = ""

    def coerce(self, value: Any) -> float:
        try:
            v = float(value)
        except (TypeError, ValueError):
            return float(self.default)
        if self.min is not None:
            v = max(v, self.min)
        if self.max is not None:
            v = min(v, self.max)
        return v


class Recipe(BaseModel):
    """Descrizione dichiarativa di una parte componibile."""

    model_config = ConfigDict(extra="forbid")

    name: str
    category: str = "generic"
    description: str = ""
    params: dict[str, ParamSpec] = PField(default_factory=dict)
    shape: dict[str, Any] = PField(default_factory=dict)
    sockets: list[SocketSpec] = PField(default_factory=list)
    tags: list[str] = PField(default_factory=list)
    keywords: list[str] = PField(default_factory=list)
    material: str = "skin"
    hard: bool = False           # parte non fusa: occhi, denti, piastre

    # ------------------------------------------------------------------ API #
    def defaults(self) -> dict[str, float]:
        return {k: p.default for k, p in self.params.items()}

    def resolve(self, values: dict[str, Any] | None = None) -> dict[str, float]:
        out = self.defaults()
        for key, value in (values or {}).items():
            if key in self.params:
                out[key] = self.params[key].coerce(value)
        return out

    def build(self, values: dict[str, Any] | None = None) -> "Part":
        variables = self.resolve(values)
        field_tree = build_shape(self.shape, variables)
        sockets: dict[str, Socket] = {}
        for spec in self.sockets:
            for socket in spec.build(variables):
                sockets[socket.name] = socket
        return Part(recipe=self.name, field=field_tree, sockets=sockets,
                    params=variables, tags=list(self.tags), material=self.material,
                    hard=self.hard)

    def schema_line(self) -> str:
        params = ", ".join("%s(%s..%s)" % (k, p.min, p.max) for k, p in self.params.items())
        socket_names = ", ".join(s.name + ("[]" if s.arrangement != "single" else "")
                                 for s in self.sockets)
        return "- %s [%s]: %s\n    params: %s\n    socket: %s" % (
            self.name, self.category, self.description, params or "-", socket_names or "-")


@dataclass
class Part:
    """Istanza concreta: campo nel sistema locale piu' socket."""

    recipe: str
    field: sdf.Field
    sockets: dict[str, Socket] = field(default_factory=dict)
    params: dict[str, float] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    material: str = "skin"
    hard: bool = False

    # Un socket chiesto con un suffisso plausibile ma sbagliato non deve far
    # sparire la parte: "leg_front_0" vale "leg_front_l".
    _NUMERIC_TO_SIDE = {"0": "l", "1": "r", "left": "l", "right": "r",
                        "sinistra": "l", "destra": "r"}

    def socket(self, name: str) -> Socket | None:
        if name in self.sockets:
            return self.sockets[name]

        stem, _, suffix = name.rpartition("_")
        if stem and suffix in self._NUMERIC_TO_SIDE:
            alias = "%s_%s" % (stem, self._NUMERIC_TO_SIDE[suffix])
            if alias in self.sockets:
                return self.sockets[alias]
        if stem and suffix in ("l", "r"):
            for index, side in (("0", "l"), ("1", "r")):
                if suffix == side and ("%s_%s" % (stem, index)) in self.sockets:
                    return self.sockets["%s_%s" % (stem, index)]

        # tolleranza sui nomi generati: "arm" trova "arm_l"
        for key in sorted(self.sockets):
            if key.startswith(name + "_"):
                return self.sockets[key]
        return None

    def socket_names(self) -> list[str]:
        return sorted(self.sockets)


# --------------------------------------------------------------------------- #
# Dallo schema JSON all'albero della grammatica
# --------------------------------------------------------------------------- #
def build_shape(node: dict[str, Any], variables: dict[str, float]) -> sdf.Field:
    if not isinstance(node, dict) or not node:
        raise RecipeError("nodo di forma vuoto")

    if "volume" in node:
        name = node["volume"]
        factory = sdf.VOLUMES.get(name)
        if factory is None:
            raise RecipeError("volume sconosciuto: %s" % name)
        return factory(**_kwargs(node, {"volume"}, variables))

    if "op" in node:
        name = node["op"]
        factory = sdf.OPERATIONS.get(name)
        if factory is None:
            raise RecipeError("operazione sconosciuta: %s" % name)
        child = build_shape(node.get("child", {}), variables)
        return factory(child, **_kwargs(node, {"op", "child"}, variables))

    for combinator in ("union", "intersection"):
        if combinator in node:
            children = [build_shape(c, variables) for c in node[combinator]]
            blend = node.get("blend", 0.0)
            if isinstance(blend, list):
                blend_value: Any = [evaluate(b, variables) for b in blend]
            else:
                blend_value = evaluate(blend, variables)
            cls = sdf.Union if combinator == "union" else sdf.Intersection
            return cls(children, blend_value)

    if "difference" in node:
        base = build_shape(node["difference"], variables)
        tool = build_shape(node.get("tool", {}), variables)
        return sdf.Difference(base, tool, evaluate(node.get("blend", 0.0), variables))

    raise RecipeError("nodo di forma non riconosciuto: %s" % sorted(node))


# Una ricetta e' un file che qualcuno dovra' rileggere: "comment" e' ammesso
# ovunque nell'albero della forma e non viene mai valutato.
IGNORED_KEYS = {"comment"}


def _kwargs(node: dict[str, Any], skip: set[str], variables: dict[str, float]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in node.items():
        if key in skip or key in IGNORED_KEYS:
            continue
        if isinstance(value, bool):
            out[key] = value                      # smooth: true/false, non un numero
        elif isinstance(value, (list, tuple)):
            out[key] = _nested(value, variables)
        else:
            number = evaluate(value, variables)
            out[key] = int(round(number)) if key in INT_FIELDS else number
    return out


def _nested(value, variables: dict[str, float]):
    """Liste anche annidate: le stazioni di un profilo sono una lista di terne."""
    return tuple(_nested(v, variables) if isinstance(v, (list, tuple))
                 else evaluate(v, variables) for v in value)


# --------------------------------------------------------------------------- #
# Catalogo
# --------------------------------------------------------------------------- #
CATALOG: dict[str, Recipe] = {}


def register(recipe: Recipe) -> Recipe:
    CATALOG[recipe.name] = recipe
    return recipe


def load_recipe(path: Path) -> Recipe:
    return Recipe.model_validate_json(Path(path).read_text(encoding="utf-8"))


def load_catalog(directory: Path | None = None, reload: bool = False) -> dict[str, Recipe]:
    if CATALOG and not reload:
        return CATALOG
    if reload:
        CATALOG.clear()
    folder = Path(directory) if directory is not None else RECIPE_DIR
    if not folder.is_dir():
        log.warning("cartella ricette assente: %s", folder)
        return CATALOG
    for path in sorted(folder.glob("*.json")):
        try:
            register(load_recipe(path))
        except Exception as exc:
            log.error("ricetta scartata %s: %s", path.name, exc)
    log.info("catalogo parti: %d ricette", len(CATALOG))
    return CATALOG


def get_recipe(name: str) -> Recipe | None:
    load_catalog()
    return CATALOG.get(name)


def find_recipes(keyword: str) -> list[Recipe]:
    load_catalog()
    key = keyword.lower().strip()
    return [r for r in CATALOG.values()
            if key == r.name or key in r.keywords or key in r.tags]


def catalog_summary() -> str:
    load_catalog()
    return "\n".join(r.schema_line() for r in sorted(CATALOG.values(), key=lambda r: r.name))
