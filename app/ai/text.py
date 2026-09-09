"""Estrazione di numeri e misure dal linguaggio naturale, italiano e inglese.

Condiviso dal planner a regole e dal parser di creature: entrambi devono
leggere "quattro braccia", "sei tentacoli", "alto 2 metri" allo stesso modo.
"""
from __future__ import annotations

import re
import unicodedata

SPELLED = {
    "una": 1, "uno": 1, "un": 1, "due": 2, "tre": 3, "quattro": 4, "cinque": 5,
    "sei": 6, "sette": 7, "otto": 8, "nove": 9, "dieci": 10, "dodici": 12,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}

BIG = ["grande", "grosso", "enorme", "gigante", "big", "large", "huge", "massiccio", "maggiorat"]
SMALL = ["piccolo", "mini", "small", "tiny", "compatto", "ridotto", "nano"]


def normalize(text: str) -> str:
    """Minuscole senza accenti: 'Città' e 'citta' devono valere uguale."""
    t = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def number_before(text: str, words: list[str]) -> float | None:
    """Cerca 'N <parola>' oppure '<parola> N', con numeri anche a lettere."""
    for w in words:
        m = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:\w+\s+)?" + w, text)
        if m:
            return float(m.group(1).replace(",", "."))
        m = re.search(r"\b(" + "|".join(SPELLED) + r")\s+(?:\w+\s+)?" + w, text)
        if m:
            return float(SPELLED[m.group(1)])
    return None


def measure(text: str, words: list[str]) -> float | None:
    """Cerca 'lungo 5 metri', '5 m di altezza', ecc."""
    for w in words:
        for pattern in (w + r"\D{0,12}?(\d+(?:[.,]\d+)?)\s*(?:m\b|metri|meters?)",
                        r"(\d+(?:[.,]\d+)?)\s*(?:m\b|metri|meters?)\D{0,12}?" + w):
            m = re.search(pattern, text)
            if m:
                return float(m.group(1).replace(",", "."))
    return None


def has_any(text: str, words: list[str]) -> bool:
    return any(w in text for w in words)


def has_word(text: str, words: list[str]) -> bool:
    """Come has_any, ma solo su parole intere.

    Serve dove il confronto per sottostringa produce falsi positivi assurdi:
    "fin" e' dentro "indefinito", "ala" dentro "scala", "corno" dentro "giorno".
    """
    if not words:
        return False
    pattern = r"\b(?:" + "|".join(re.escape(w) for w in words) + r")\b"
    return re.search(pattern, text) is not None


def first_match(text: str, table: dict[str, list[str]]) -> str | None:
    """Chiave del gruppo il cui sinonimo piu' lungo compare nel testo."""
    best: tuple[int, str] | None = None
    for key, words in table.items():
        for word in words:
            if re.search(r"\b" + re.escape(word), text) and (best is None or len(word) > best[0]):
                best = (len(word), key)
    return best[1] if best else None


def all_matches(text: str, table: dict[str, list[str]]) -> list[str]:
    """Tutte le chiavi presenti nel testo, in ordine di comparsa."""
    found: list[tuple[int, str]] = []
    for key, words in table.items():
        positions = [m.start() for w in words
                     for m in re.finditer(r"\b" + re.escape(w), text)]
        if positions:
            found.append((min(positions), key))
    return [key for _, key in sorted(found)]
