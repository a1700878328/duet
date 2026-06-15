"""Small helpers for parsing model JSON responses."""

from __future__ import annotations

import json
from typing import Any


def _strip_fenced_json(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        nl = text.find("\n")
        if nl != -1 and text[:nl].strip().lower() in {"json", ""}:
            text = text[nl + 1 :]
    return text


def parse_json_array(raw: str) -> list[Any]:
    text = _strip_fenced_json(raw)
    start, end = text.find("["), text.rfind("]")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def parse_json_object(raw: str) -> dict[str, Any]:
    text = _strip_fenced_json(raw)
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}
