"""Tiny shared text utilities. No heavy NLP in Tier 1."""
from __future__ import annotations

import re

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
_WORD = re.compile(r"[A-Za-z][A-Za-z'-]+")
_STOP = {
    "the", "a", "an", "and", "or", "but", "if", "then", "of", "to", "in", "on",
    "for", "with", "as", "is", "are", "was", "were", "be", "been", "being", "it",
    "this", "that", "these", "those", "you", "your", "we", "our", "they", "their",
    "i", "he", "she", "his", "her", "at", "by", "from", "can", "will", "would",
    "should", "may", "might", "do", "does", "did", "have", "has", "had", "not",
    "no", "yes", "please", "about", "into", "out", "up", "down", "so", "than",
}


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_SPLIT.split(text or "") if s.strip()]


def tokens(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text or "")]


def content_tokens(text: str) -> set[str]:
    return {t for t in tokens(text) if t not in _STOP and len(t) > 2}


def containment(a: str, b: str) -> float:
    """Fraction of a's content tokens that also appear in b. Cheap, directional."""
    ta = content_tokens(a)
    if not ta:
        return 1.0
    tb = content_tokens(b)
    return len(ta & tb) / len(ta)


def jaccard(a: str, b: str) -> float:
    ta, tb = content_tokens(a), content_tokens(b)
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


_NUM_UNIT = re.compile(
    r"(\d[\d,]*(?:\.\d+)?)\s*"
    r"(day|days|week|weeks|month|months|year|years|hour|hours|%|percent|"
    r"usd|dollar|dollars|rupee|rupees)?",
    re.IGNORECASE,
)

_UNIT_TO_DAYS = {
    "day": 1, "days": 1, "week": 7, "weeks": 7, "month": 30, "months": 30,
    "year": 365, "years": 365,
}


def numbers_with_units(text: str) -> list[tuple[float, str, int]]:
    """Return (value, normalized_unit, char_offset) for numeric mentions."""
    out: list[tuple[float, str, int]] = []
    for m in _NUM_UNIT.finditer(text or ""):
        raw = m.group(1).replace(",", "")
        try:
            val = float(raw)
        except ValueError:
            continue
        unit = (m.group(2) or "").lower()
        out.append((val, unit, m.start()))
    return out


def to_days(value: float, unit: str) -> float | None:
    return value * _UNIT_TO_DAYS[unit] if unit in _UNIT_TO_DAYS else None
