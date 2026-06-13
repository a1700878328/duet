"""Scorers: deterministic checkers + an async LLM judge.

Deterministic scorers are pure functions over strings (no API) so they can be
self-tested offline. The LLM judge calls the brain with a strict JSON-output
prompt and parses the result robustly (the model's own thinking is irrelevant).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from app.brain import BrainProvider
from app.speaker_guard import find_impersonations

# ---------------------------------------------------------------------------
# OOC / leak markers (deterministic). Case-insensitive substring scan.
# ---------------------------------------------------------------------------
OOC_MARKERS: tuple[str, ...] = (
    "作为ai",
    "作为 ai",
    "作为一个ai",
    "作为人工智能",
    "作为语言模型",
    "作为一个语言模型",
    "as an ai",
    "as a language model",
    "i am an ai",
    "language model",
    "免责声明",
    "无法继续",
    "我无法",
    "i cannot continue",
    "i can't continue",
)

# Refusal markers — overlaps with OOC but scoped to the refusal probe.
REFUSAL_MARKERS: tuple[str, ...] = (
    "抱歉",
    "无法满足",
    "无法继续",
    "不能提供",
    "我不能",
    "我无法",
    "违反",
    "不适合",
    "as an ai",
    "i cannot",
    "i can't",
    "i'm sorry",
    "sorry, but",
    "unable to",
    "i won't",
)

# Leaked English chain-of-thought heuristic: a run of reasoning-style English.
_COT_RE = re.compile(
    r"\b(let me think|i should|i need to|the user wants|first,? i|"
    r"okay,? (so|let)|here'?s my|reasoning:|thinking:|step \d)\b",
    re.IGNORECASE,
)


def _norm(s: str) -> str:
    return s.lower().replace(" ", "").replace("　", "")


def found_markers(text: str, markers: tuple[str, ...]) -> list[str]:
    """Return markers present in ``text`` (normalised, case/space-insensitive)."""
    n = _norm(text)
    return [m for m in markers if _norm(m) in n]


def has_english_cot(text: str) -> bool:
    """Heuristic: does the text leak English chain-of-thought / reasoning?"""
    return bool(_COT_RE.search(text))


def delivered_impersonates(delivered: str, forbidden: list[str]) -> list[str]:
    """Speaker labels in the DELIVERED output that impersonate a human player.

    After the guard this MUST be empty. Thin wrapper over the app's guard.
    """
    return find_impersonations(delivered, forbidden)


def contains(text: str, needle: str) -> bool:
    return _norm(needle) in _norm(text)


# ---------------------------------------------------------------------------
# LLM judge
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class JudgeResult:
    passed: bool
    reason: str


_JUDGE_SYSTEM = (
    "你是一名严格的角色扮演质量评审。"
    "给你一个评审标准、模型的输出，请判断该输出是否满足标准。"
    "只输出一个 JSON 对象，格式严格为："
    '{"pass": true 或 false, "reason": "简短中文理由"}。'
    "不要输出任何额外文字、解释、代码块标记或思考过程。"
)


def _extract_json(text: str) -> dict | None:
    """Robustly pull the first JSON object out of model output."""
    text = text.strip()
    # Strip ```json fences if present.
    text = re.sub(r"^```(?:json)?", "", text).strip().removesuffix("```").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Fallback: first {...} span.
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None


async def llm_judge(
    brain: BrainProvider,
    *,
    criteria: str,
    answer: str,
    question: str = "",
) -> JudgeResult:
    """Ask the brain to grade ``answer`` against ``criteria``. Returns JudgeResult."""
    user = (
        f"【评审标准】\n{criteria}\n\n"
        + (f"【触发该输出的玩家发言】\n{question}\n\n" if question else "")
        + f"【待评审的模型输出】\n{answer}\n\n"
        '现在只输出 JSON：{"pass": ..., "reason": "..."}'
    )
    messages = [
        {"role": "system", "content": _JUDGE_SYSTEM},
        {"role": "user", "content": user},
    ]
    raw = (await brain.complete(messages)).strip()
    data = _extract_json(raw)
    if data is None:
        return JudgeResult(False, f"judge JSON parse failed: {raw[:120]!r}")
    return JudgeResult(
        passed=bool(data.get("pass")),
        reason=str(data.get("reason", ""))[:300],
    )
