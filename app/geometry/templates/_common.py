"""Helper condivisi dai generatori procedurali."""
from __future__ import annotations

from typing import Any, Iterable

from app.core.spec import ComponentSpec

Vec3 = tuple[float, float, float]


def C(cid: str, primitive: str, params: dict[str, Any], *,
      pos: Vec3 = (0.0, 0.0, 0.0), rot: Vec3 = (0.0, 0.0, 0.0), scale: Vec3 = (1.0, 1.0, 1.0),
      mat: str = "default", name: str = "", parent: str | None = None,
      tags: Iterable[str] = ()) -> ComponentSpec:
    return ComponentSpec(
        id=cid, name=name or cid.replace("_", " ").title(), primitive=primitive,
        params=params, position=pos, rotation=rot, scale=scale,
        material=mat, parent=parent, tags=list(tags),
    )


# Questi tre non decidono piu' niente da soli: chiedono al profilo di stile
# (app/core/style.py), che e' l'unico posto dove sta scritto come deve venire
# un modello. Accettano ancora un nome di stile perche' i generatori lo passano
# ancora; internamente e' solo una densita'.
def sections(density: float | str, base: int = 32) -> int:
    """Segmenti dei solidi di rivoluzione, alla densita' data."""
    from app.core.style import sections_for

    return sections_for(_density(density), base=max(base // 4, 4))


def smoothness(density: float | str) -> int:
    """Suddivisioni delle icosfere. Poche: alimentano scafi convessi."""
    from app.core.style import subdivisions_for

    return subdivisions_for(_density(density))


def rounding(density: float | str, r: float) -> float:
    """Arrotondamento di uno spigolo."""
    from app.core.style import rounding_for

    return rounding_for(r, _density(density))


# Traduzione dai vecchi nomi di stile: sparira' con il campo `style`.
_LEGACY_DENSITY = {"blocky": 0.71, "lowpoly": 1.0, "stylized": 1.71, "realistic": 2.14}


def _density(value: float | str) -> float:
    if isinstance(value, str):
        return _LEGACY_DENSITY.get(value, 1.0)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 1.0
