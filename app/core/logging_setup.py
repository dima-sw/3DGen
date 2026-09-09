"""Logging leggibile: console + buffer in memoria consultabile dalla UI."""
from __future__ import annotations

import logging
from collections import deque
from typing import Deque

_RING: Deque[str] = deque(maxlen=2000)


class RingHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            _RING.append(self.format(record))
        except Exception:
            pass


def setup(level: str = "INFO") -> None:
    root = logging.getLogger("gen3d")
    if root.handlers:
        return
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    fmt = logging.Formatter("%(asctime)s  %(levelname)-7s %(name)-22s %(message)s", "%H:%M:%S")
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    ring = RingHandler()
    ring.setFormatter(fmt)
    root.addHandler(console)
    root.addHandler(ring)
    root.propagate = False


def get(name: str) -> logging.Logger:
    return logging.getLogger(f"gen3d.{name}")


def tail(n: int = 200) -> list[str]:
    return list(_RING)[-n:]
