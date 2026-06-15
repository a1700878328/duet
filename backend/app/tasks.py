"""Lightweight quest/task helpers stored inside Room.scenes_meta.

The first implementation is deliberately JSON-in-meta rather than a table: it
keeps the story loop malleable while the quest mechanics are still being tuned.
NPCs can emit hidden markers such as:

[[委托:{"标题":"清剿洞窟","奖励":{"金钱":30,"经验":20}}]]
[[完成委托:{"task_id":"abc"}]]
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from .json_utils import parse_json_object

TASK_OFFERS_KEY = "_task_offers"
CURRENT_TASK_KEY = "_current_task"
COMPLETED_TASKS_KEY = "_completed_tasks"

_TASK_OFFER_RE = re.compile(r"\[\[\s*委托\s*:\s*(.*?)\s*\]\]", re.DOTALL)
_TASK_COMPLETE_RE = re.compile(
    r"\[\[\s*(?:完成委托|委托完成)\s*:?\s*(.*?)\s*\]\]", re.DOTALL
)


def extract_task_directives(
    text: str,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    """Strip hidden task markers from model text and return parsed payloads."""
    offers: list[dict[str, Any]] = []
    completions: list[dict[str, Any]] = []

    def offer_repl(match: re.Match[str]) -> str:
        data = parse_json_object(match.group(1))
        if data:
            offers.append(data)
        return ""

    def complete_repl(match: re.Match[str]) -> str:
        raw = match.group(1).strip()
        data = parse_json_object(raw) if raw else {}
        completions.append(data)
        return ""

    clean = _TASK_OFFER_RE.sub(offer_repl, text or "")
    clean = _TASK_COMPLETE_RE.sub(complete_repl, clean)
    return clean.strip(), offers, completions


def _str_list(value: Any, limit: int = 8) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()[:160]] if value.strip() else []
    if not isinstance(value, list):
        return [str(value).strip()[:160]] if str(value).strip() else []
    out: list[str] = []
    for item in value[:limit]:
        text = str(item).strip()[:160]
        if text:
            out.append(text)
    return out


def _int_reward(value: Any) -> int:
    try:
        return max(0, min(100000, int(value or 0)))
    except (TypeError, ValueError):
        return 0


def _favor_reward(value: Any, issuer: str) -> dict[str, int]:
    if isinstance(value, (int, float)):
        amount = int(value)
        return {issuer: amount} if amount else {}
    if not isinstance(value, dict):
        return {}
    out: dict[str, int] = {}
    for name, raw in value.items():
        try:
            amount = int(raw)
        except (TypeError, ValueError):
            continue
        if amount:
            out[str(name)[:80]] = max(-100, min(100, amount))
    return out


def normalize_task_offer(
    payload: dict[str, Any],
    *,
    issuer: str,
    issuer_npc_id: int | None,
    time_label: str,
) -> dict[str, Any]:
    """Turn a loose AI quest payload into the stable task shape used by UI."""
    rewards_raw = payload.get("rewards") or payload.get("奖励") or {}
    if not isinstance(rewards_raw, dict):
        rewards_raw = {}
    title = (
        payload.get("title")
        or payload.get("标题")
        or payload.get("name")
        or payload.get("名称")
        or "未命名委托"
    )
    description = (
        payload.get("description")
        or payload.get("描述")
        or payload.get("detail")
        or payload.get("详情")
        or ""
    )
    objectives = (
        payload.get("objectives")
        or payload.get("目标")
        or payload.get("任务目标")
        or payload.get("requirements")
        or []
    )
    money = _int_reward(rewards_raw.get("money", rewards_raw.get("金钱")))
    exp = _int_reward(
        rewards_raw.get("exp", rewards_raw.get("experience", rewards_raw.get("经验")))
    )
    items = _str_list(
        rewards_raw.get("items", rewards_raw.get("物品", rewards_raw.get("道具"))),
        limit=6,
    )
    favor = _favor_reward(rewards_raw.get("favor", rewards_raw.get("好感度")), issuer)
    if not favor:
        favor_amount = _int_reward(payload.get("好感度奖励"))
        favor = {issuer: favor_amount} if favor_amount else {}

    return {
        "id": str(payload.get("id") or payload.get("task_id") or uuid.uuid4().hex[:12]),
        "title": str(title).strip()[:120] or "未命名委托",
        "issuer": str(payload.get("issuer") or payload.get("委托方") or issuer)[:120],
        "issuer_npc_id": issuer_npc_id,
        "status": "可接取",
        "description": str(description).strip()[:1200],
        "objectives": _str_list(objectives),
        "rewards": {
            "金钱": money,
            "经验": exp,
            "物品": items,
            "好感度": favor,
        },
        "created_at": time_label,
    }


def task_offers_from_meta(meta: dict[str, Any]) -> list[dict[str, Any]]:
    offers = meta.get(TASK_OFFERS_KEY)
    return (
        [o for o in offers if isinstance(o, dict)] if isinstance(offers, list) else []
    )


def current_task_from_meta(meta: dict[str, Any]) -> dict[str, Any] | None:
    task = meta.get(CURRENT_TASK_KEY)
    return task if isinstance(task, dict) else None


def task_state_from_meta(meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "current_task": current_task_from_meta(meta),
        "offers": task_offers_from_meta(meta),
    }
