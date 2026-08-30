"""Model / provider abstraction (§50).

The rest of ControlPlane never imports a provider SDK. It asks
``get_model_adapter(...)`` for something that can ``generate`` or ``judge``.

Default is the deterministic :class:`MockModelAdapter` — no network, fully
reproducible, sufficient for the entire demo. An OpenAI-compatible adapter is
used ONLY when ``LLM_PROVIDER=openai`` and an API key is present.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Protocol, runtime_checkable

from app.core.config import get_settings
from app.evaluators._text import containment, numbers_with_units


@runtime_checkable
class ModelAdapter(Protocol):
    name: str

    async def generate(self, prompt: str, context: list[str] | None = None, system: str | None = None) -> str: ...

    async def judge(
        self, question: str, answer: str, context: list[str] | None, criteria: str
    ) -> dict[str, Any]: ...


class MockModelAdapter:
    """Deterministic, offline. `judge` is an independent heuristic second opinion.

    It is intentionally NOT a copy of the Tier 1 grounding check: it weighs
    hedging language, numeric specificity without support, and context overlap
    differently, so it adds signal rather than echoing Tier 1.
    """

    name = "mock"

    _HEDGE = re.compile(r"\b(might|maybe|possibly|i think|not sure|approximately|around|roughly|likely)\b", re.I)
    _ABSOLUTE = re.compile(r"\b(always|never|guaranteed|definitely|exactly|certainly)\b", re.I)

    async def generate(self, prompt: str, context: list[str] | None = None, system: str | None = None) -> str:
        seed = int(hashlib.sha1((prompt or "").encode()).hexdigest(), 16)
        if context:
            return f"Based on the provided context: {context[0][:160]}"
        canned = [
            "I don't have a verified source for that, so treat this as an estimate.",
            "Here is a general answer based on common practice.",
            "The available information suggests a moderate outcome.",
        ]
        return canned[seed % len(canned)]

    async def judge(
        self, question: str, answer: str, context: list[str] | None, criteria: str
    ) -> dict[str, Any]:
        ctx = "\n".join(context or [])
        cover = containment(answer, ctx) if ctx else 0.0
        hedged = bool(self._HEDGE.search(answer))
        absolute = bool(self._ABSOLUTE.search(answer))
        numeric = len(numbers_with_units(answer))

        # risk that the answer is unsupported / overconfident
        risk = 0.0
        if ctx:
            risk += (1.0 - cover) * 0.6
        else:
            risk += 0.35  # nothing to check against
        if absolute and cover < 0.5:
            risk += 0.25
        if numeric >= 1 and cover < 0.4:
            risk += 0.2
        if hedged:
            risk -= 0.15
        risk = max(0.0, min(1.0, risk))

        label = "supported" if risk < 0.3 else ("uncertain" if risk < 0.6 else "unsupported")
        reason = (
            f"context coverage {cover:.0%}"
            + (", overconfident phrasing" if absolute and cover < 0.5 else "")
            + (", unsupported specifics" if numeric and cover < 0.4 else "")
            + (", hedged appropriately" if hedged else "")
        )
        return {
            "score": round(risk, 3),
            "label": label,
            "reason": reason.strip(", "),
            "confidence": 0.55,               # a judge can be wrong — never 1.0
            "evidence_ids": [],
            "evaluator_version": "mock_judge_v1",
        }


class OpenAIAdapter:
    """OPTIONAL. Requires `openai` and OPENAI_API_KEY. Never used in the demo path."""

    name = "openai"

    def __init__(self) -> None:
        from openai import AsyncOpenAI  # imported lazily

        s = get_settings()
        self._client = AsyncOpenAI(api_key=s.openai_api_key, base_url=s.openai_base_url)
        self._model = s.openai_judge_model

    async def generate(self, prompt: str, context: list[str] | None = None, system: str | None = None) -> str:
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        if context:
            msgs.append({"role": "system", "content": "Context:\n" + "\n".join(context)})
        msgs.append({"role": "user", "content": prompt})
        resp = await self._client.chat.completions.create(model=self._model, messages=msgs, temperature=0)
        return resp.choices[0].message.content or ""

    async def judge(
        self, question: str, answer: str, context: list[str] | None, criteria: str
    ) -> dict[str, Any]:
        schema = (
            'Return ONLY compact JSON: {"score": <0..1 risk answer is unsupported>, '
            '"label": "supported|uncertain|unsupported", "reason": "<one sentence, no chain of thought>", '
            '"confidence": <0..1>}'
        )
        prompt = (
            f"Criteria: {criteria}\nQuestion: {question}\nAnswer: {answer}\n"
            f"Context:\n{chr(10).join(context or []) or '(none provided)'}\n\n{schema}"
        )
        raw = await self.generate(prompt, system="You are a terse evaluation function.")
        try:
            data = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
        except Exception:  # noqa: BLE001
            data = {"score": 0.5, "label": "uncertain", "reason": "judge output unparseable", "confidence": 0.3}
        data.setdefault("evidence_ids", [])
        data["evaluator_version"] = f"openai_judge:{self._model}"
        return data


_MOCK = MockModelAdapter()
_OPENAI: OpenAIAdapter | None = None


def get_model_adapter(provider: str | None = None) -> ModelAdapter:
    global _OPENAI
    s = get_settings()
    provider = (provider or s.llm_provider or "mock").lower()
    if provider == "openai" and s.openai_api_key:
        if _OPENAI is None:
            try:
                _OPENAI = OpenAIAdapter()
            except Exception:  # noqa: BLE001 - fall back silently, demo must not break
                return _MOCK
        return _OPENAI
    return _MOCK
