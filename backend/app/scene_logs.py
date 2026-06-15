"""Helpers for per-scene debug/history logs stored in Room.scenes_meta."""

from __future__ import annotations

import json
from typing import Any

SCENE_LOG_LIMIT = 80
SCENE_LOG_KEY = "_scene_logs"


def load_scene_meta(raw: str | None) -> dict[str, Any]:
    try:
        data = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def scene_key(scene: str | None) -> str:
    return (scene or "自由场景").strip()[:64] or "自由场景"


def append_scene_log(
    meta: dict[str, Any],
    *,
    scene: str | None,
    time_label: str,
    speaker_label: str,
    content: str,
    kind: str = "scene",
) -> bool:
    body = (content or "").strip()
    if not body:
        return False
    logs = meta.get(SCENE_LOG_KEY)
    if not isinstance(logs, dict):
        logs = {}
    key = scene_key(scene)
    entries = logs.get(key)
    if not isinstance(entries, list):
        entries = []
    entries.append(
        {
            "scene": key,
            "time_label": time_label,
            "speaker_label": (speaker_label or "记录")[:128],
            "content": body[:1200],
            "kind": (kind or "scene")[:32],
        }
    )
    logs[key] = entries[-SCENE_LOG_LIMIT:]
    meta[SCENE_LOG_KEY] = logs
    return True


def logs_from_meta(raw: str | None) -> dict[str, list[dict[str, str]]]:
    meta = load_scene_meta(raw)
    logs = meta.get(SCENE_LOG_KEY)
    if not isinstance(logs, dict):
        return {}
    out: dict[str, list[dict[str, str]]] = {}
    for raw_scene, raw_entries in logs.items():
        scene = scene_key(str(raw_scene))
        if not isinstance(raw_entries, list):
            continue
        entries: list[dict[str, str]] = []
        for item in raw_entries[-SCENE_LOG_LIMIT:]:
            if not isinstance(item, dict):
                continue
            entries.append(
                {
                    "scene": scene,
                    "time_label": str(item.get("time_label") or ""),
                    "speaker_label": str(item.get("speaker_label") or "记录"),
                    "content": str(item.get("content") or ""),
                    "kind": str(item.get("kind") or "scene"),
                }
            )
        out[scene] = entries
    return out
