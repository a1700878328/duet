"""Character color-poison guard (registry-driven, fail-closed).

Ported faithfully from rp_system/image_gen.py. This is the whole anti-hallucination
value: any positive prompt that mixes a registered char's trigger/alias with that
char's wrong_color_negatives is rejected before submission. Color authority is
character_facts.json exclusively — hand-written hair/eye colors are forbidden.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from .registry import UnverifiedCharacter, resolve

_FACTS_PATH = Path(__file__).resolve().parent / "character_facts.json"


class PoisonedPromptError(Exception):
    """Positive prompt holds a color that conflicts with the registry — reject."""


class UnverifiedNamedCharacter(Exception):
    """Positive holds an unregistered named-char tag name (series) — reject."""


@lru_cache(maxsize=1)
def _registry_guard_index() -> tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...]:
    out: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = []
    try:
        chars = json.loads(_FACTS_PATH.read_text(encoding="utf-8")).get(
            "characters", {}
        )
    except Exception:
        chars = {}
    for name, info in chars.items():
        aliases = [name, *list(info.get("aliases", []))]
        trig = info.get("trigger", "")
        aliases += [t.strip() for t in trig.split(",") if t.strip()]
        wrongs = [
            w.strip().lower()
            for w in info.get("wrong_color_negatives", "").split(",")
            if w.strip()
        ]
        out.append((name, tuple(aliases), tuple(wrongs)))
    return tuple(out)


def _alias_present(alias: str, text_low: str) -> bool:
    a = alias.strip().lower()
    if not a:
        return False
    if a.isascii():
        if len(a) < 5:  # skip short aliases like 'rio' to avoid false hits
            return False
        return (
            re.search(r"(?<![a-z])" + re.escape(a) + r"(?![a-z])", text_low) is not None
        )
    return a in text_low


def assert_no_poisoned_colors(positive_texts: list[str]) -> None:
    """Raise PoisonedPromptError if any positive text mixes a char + its wrong color."""
    index = _registry_guard_index()
    if not index:
        return
    for text in positive_texts:
        norm = text.lower().replace("_", " ")
        for name, aliases, wrongs in index:
            if not any(_alias_present(a, norm) for a in aliases):
                continue
            hits = [w for w in wrongs if w in norm]
            if hits:
                raise PoisonedPromptError(
                    f"角色 '{name}' 正向提示词出现禁用颜色 {hits}"
                    f"（违反 character_facts.json）。外观必须走 registry，"
                    f"禁止手写发色/瞳色。片段: ...{text[:120]}"
                )


def registry_wrong_color_negatives(char_name: str) -> str:
    norm = char_name.lower().replace("_", " ")
    for name, aliases, wrongs in _registry_guard_index():
        if char_name == name or any(_alias_present(a, norm) for a in aliases):
            return ", ".join(wrongs)
    return ""


_CHAR_TAG_RE = re.compile(r"^[a-z0-9][a-z0-9 '._-]*\([a-z0-9][a-z0-9 _-]+\)$")
_NON_CHAR_PARENS = {
    "cosplay",
    "official art",
    "alternate costume",
    "swimsuit",
    "game cg",
    "medium",
    "style",
    "artist",
}


def _extract_char_tags(text: str) -> list[str]:
    out: list[str] = []
    for seg in text.split(","):
        s = seg.strip().replace("\\(", "(").replace("\\)", ")").lower()
        if not s or s.startswith("(") or ":" in s or "(" not in s:
            continue
        if _CHAR_TAG_RE.match(s):
            inner = s[s.index("(") + 1 : s.rindex(")")].strip()
            if inner in _NON_CHAR_PARENS:
                continue
            out.append(s)
    return out


def assert_named_chars_registered(positive_texts: list[str]) -> None:
    """Named-char tags in positives must be registered in character_facts.json,
    else fail-closed. Stops hallucinating an unverified char's look."""
    for text in positive_texts:
        for tag in _extract_char_tags(text):
            try:
                resolve(tag)
            except UnverifiedCharacter as e:
                raise UnverifiedNamedCharacter(
                    f"角色标签 '{tag}' 未在 character_facts.json 登记。"
                    f"禁止凭脑补生成具名角色,请先登记其权威外貌(带 source-url)再生成。"
                ) from e


def classify_clip_texts(workflow: dict[str, Any]) -> list[str]:
    """Extract positive CLIPTextEncode texts from a graph (negatives excluded)."""
    neg_ids: set[str] = set()
    for node in workflow.values():
        if isinstance(node, dict) and node.get("class_type") == "KSampler":
            neg = node.get("inputs", {}).get("negative")
            if isinstance(neg, list) and neg:
                neg_ids.add(str(neg[0]))
    pos_texts: list[str] = []
    for nid, node in workflow.items():
        if isinstance(node, dict) and node.get("class_type") == "CLIPTextEncode":
            t = node.get("inputs", {}).get("text")
            if isinstance(t, str) and str(nid) not in neg_ids:
                pos_texts.append(t)
    return pos_texts


def assert_workflow_safe(workflow: dict[str, Any]) -> None:
    """Run both guards over a full ComfyUI graph before submission."""
    texts = classify_clip_texts(workflow)
    assert_no_poisoned_colors(texts)
    assert_named_chars_registered(texts)
