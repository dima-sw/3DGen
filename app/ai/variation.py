"""Varianti: due generazioni dallo stesso prompt non devono essere identiche.

Regole:
  - cio' che l'utente (o l'LLM per lui) ha chiesto esplicitamente non si tocca mai:
    se hai detto "quattro porte", restano quattro porte in ogni variante;
  - varia solo cio' che il template dichiara variabile, entro i suoi limiti;
  - a parita' di seed il risultato e' identico, quindi una variante che piace
    si puo' sempre riprodurre (punto 39 della roadmap).
"""
from __future__ import annotations

import colorsys
import random

from app.core.logging_setup import get
from app.core.spec import GenerationPlan, MaterialSpec
from app.geometry.templates import TEMPLATES, load_all

log = get("ai.variation")


def _hex_to_rgb(value: str) -> tuple[float, float, float]:
    h = value.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]


def _rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join("%02x" % int(round(max(0.0, min(1.0, c)) * 255)) for c in rgb)


def jitter_color(base: str, rng: random.Random, hue: float = 0.03,
                 sat: float = 0.18, val: float = 0.16) -> str:
    """Sposta un colore restando plausibile: tinta poco, saturazione e luce di piu'."""
    r, g, b = _hex_to_rgb(base)
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    h = (h + rng.uniform(-hue, hue)) % 1.0
    s = min(1.0, max(0.0, s * (1.0 + rng.uniform(-sat, sat))))
    v = min(1.0, max(0.05, v * (1.0 + rng.uniform(-val, val))))
    return _rgb_to_hex(colorsys.hsv_to_rgb(h, s, v))


def vary(plan: GenerationPlan, seed: int | None = None) -> GenerationPlan:
    """Applica una variante al piano, rispettando quanto e' stato chiesto.

    Prima di disturbare i parametri ne conserva una copia pulita in
    `base_params`: chiamare vary() piu' volte riparte sempre da li', cosi' le
    varianti non si accumulano allontanandosi progressivamente dalla richiesta.
    """
    load_all()
    tmpl = TEMPLATES.get(plan.template)
    if tmpl is None:
        return plan

    plan.seed = int(seed if seed is not None else random.randrange(1, 10**9))
    rng = random.Random(plan.seed)
    locked = set(plan.locked)
    changed: list[str] = []

    if not plan.base_params:
        plan.base_params = dict(plan.params)
    else:
        # riparti dai valori originali; le richieste esplicite hanno la precedenza
        restored = dict(plan.base_params)
        restored.update({k: v for k, v in plan.params.items() if k in locked})
        plan.params = restored
    primary_name = tmpl.primary_material
    if primary_name and primary_name not in locked:
        plan.materials = [m for m in plan.materials if m.name != primary_name]

    for name, spec in tmpl.varying_params().items():
        if name in locked:
            continue
        current = plan.params.get(name, spec.default)

        if name == "seed":                       # i generatori con rumore proprio
            plan.params[name] = rng.randrange(0, 100000)
            changed.append(name)
        elif isinstance(spec.default, bool):
            if rng.random() < spec.vary:
                plan.params[name] = not bool(current)
                changed.append(name)
        elif spec.choices is not None:
            if rng.random() < spec.vary:
                plan.params[name] = rng.choice([c for c in spec.choices if c != current] or spec.choices)
                changed.append(name)
        else:
            # Disturbo additivo, non moltiplicativo: un parametro che vale zero
            # (l'inclinazione di un tronco, per esempio) deve poter cambiare lo
            # stesso. L'ampiezza tiene conto sia del valore sia dell'intervallo.
            span = 1.0
            if spec.min is not None and spec.max is not None:
                span = float(spec.max) - float(spec.min)
            amplitude = spec.vary * max(abs(float(current)), span * 0.12)
            plan.params[name] = spec.coerce(float(current) + rng.uniform(-amplitude, amplitude))
            changed.append(name)

    # colore: se non e' stato chiesto, pesca dalla tavolozza del template
    primary = primary_name
    if primary and primary not in locked:
        specified = next((m for m in plan.materials if m.name == primary), None)
        base = tmpl.materials.get(primary)
        if specified is None and base is not None:
            color = rng.choice(tmpl.palette) if tmpl.palette else base.base_color
            plan.materials.append(MaterialSpec(
                name=primary, base_color=jitter_color(color, rng),
                roughness=min(1.0, max(0.0, base.roughness * rng.uniform(0.85, 1.15))),
                metallic=base.metallic, opacity=base.opacity,
            ))
            changed.append("colore " + primary)

    log.info("variante seed=%d | variati: %s", plan.seed, ", ".join(changed) or "niente")
    return plan
