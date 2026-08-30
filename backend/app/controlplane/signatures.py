"""Stable interaction signatures.

Used by the learning loop to group "the same kind of question" across
paraphrases, so that a validated failure on one phrasing can influence the
routing of a later, similar interaction (clarification #4).

Deliberately coarse: `workflow:intent` is the signature whenever an intent is
recognised; only truly generic questions fall back to a keyword hash.
"""
from __future__ import annotations

import hashlib

from app.evaluators._text import content_tokens

INTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "return_policy": ("return", "returns", "refund", "exchange", "send back", "return window", "money back"),
    "warranty": ("warranty", "guarantee", "guaranteed", "coverage period"),
    "support_hours": ("support hours", "opening hours", "hours of operation", "when are you open", "available hours"),
    "shipping": ("shipping", "delivery", "dispatch", "arrive", "tracking"),
    "pricing": ("price", "pricing", "cost", "fee", "charge", "subscription cost"),
    "cancellation": ("cancel", "cancellation", "terminate subscription", "close account"),
    "forecast": ("forecast", "next quarter", "predict", "projection", "market share", "outlook", "will the market"),
    "eligibility": ("eligible", "eligibility", "qualify", "qualifies", "approval", "approve", "loan", "claim decision"),
    "compensation": ("salary", "compensation", "pay band", "bonus", "ctc", "remuneration"),
    "policy_lookup": ("policy", "procedure", "guideline", "handbook", "sop"),
    "account_action": ("reset password", "update address", "change email", "close ticket", "issue refund"),
}

_ALL_INTENT_TERMS = {t for terms in INTENT_KEYWORDS.values() for t in terms}


def detect_intent(text: str) -> str:
    low = (text or "").lower()
    for name, kws in INTENT_KEYWORDS.items():
        if any(kw in low for kw in kws):
            return name
    return "general"


def signature_for(workflow: str, text: str) -> str:
    intent = detect_intent(text)
    if intent != "general":
        return f"{workflow}:{intent}"
    toks = sorted(t for t in content_tokens(text) if len(t) > 5)[:5]
    if not toks:
        return f"{workflow}:general"
    digest = hashlib.sha1("-".join(toks).encode()).hexdigest()[:8]
    return f"{workflow}:general:{digest}"
