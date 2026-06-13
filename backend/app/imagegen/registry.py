"""Authoritative character appearance registry — ported from rp_system/char_resolve.py.

Core rule: hair/eye color/appearance are FACTS, never hallucinated from model
memory. The only trusted source is the registry (character_facts.json prompt-only
chars + config.CHARACTER_LORAS LoRA chars). Unknown name => fail-closed raise.

LoRA chars use the trigger word only (the LoRA encodes the look); prompt-only
chars inject verified appearance and push wrong colors into the negative.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from .config import (
    CHARACTER_LORAS,
    NEGATIVE_PROMPT,
    STYLE_PREFIX,
    STYLE_SUFFIX,
)

FACTS_PATH = Path(__file__).resolve().parent / "character_facts.json"


class UnverifiedCharacter(Exception):
    """Character not in the authoritative registry — refuse to generate."""


@lru_cache(maxsize=1)
def _load_facts() -> dict[str, Any]:
    if FACTS_PATH.exists():
        return json.loads(FACTS_PATH.read_text(encoding="utf-8")).get("characters", {})
    return {}


def _norm(s: str) -> str:
    return s.strip().lower().replace(" ", "").replace("_", "")


def resolve(name: str) -> dict[str, Any]:
    """Return verified appearance info; raise UnverifiedCharacter if unknown."""
    facts = _load_facts()
    key = _norm(name)

    # 1) prompt-only / verified registry (with aliases)
    for cname, info in facts.items():
        cands = [cname, *info.get("aliases", [])]
        if key in {_norm(c) for c in cands}:
            return {
                "name": cname,
                "source": "facts_registry",
                "has_lora": info.get("has_lora", False),
                "lora_file": info.get("lora_file"),
                "trigger": info.get("trigger", ""),
                "appearance": info.get("appearance", ""),
                "outfit": info.get("outfit", ""),
                "wrong_color_negatives": info.get("wrong_color_negatives", ""),
                "source_urls": info.get("source_urls", []),
                "verified": info.get("verified"),
            }

    # 2) config.py LoRA chars (look encoded by LoRA; trigger-word only)
    for cname, info in CHARACTER_LORAS.items():
        cands = [cname, info.get("trigger", "")]
        if key in {_norm(c) for c in cands if c}:
            return {
                "name": cname,
                "source": "config_lora",
                "has_lora": True,
                "lora_file": info.get("file"),
                "trigger": info.get("trigger", ""),
                "appearance": info.get("appearance", ""),
                "outfit": "",
                "wrong_color_negatives": "",
                "source_urls": [],
                "verified": "config",
            }

    raise UnverifiedCharacter(
        f"角色 '{name}' 不在权威注册表。禁止臆造其发色/瞳色。"
        f"请先用 verify_character 核实并登记到 character_facts.json 再生成。"
    )


def build_character_prompt(
    name: str, scene: str = "", nsfw: bool = False
) -> tuple[str, str]:
    """Build verified positive/negative prompts. Never write colors by hand."""
    c = resolve(name)
    nsfw_tag = "(nsfw:1.2), " if nsfw else ""
    if c["has_lora"]:
        # Iron rule: LoRA chars use trigger word only (LoRA already encodes look).
        pos = f"{STYLE_PREFIX}, {nsfw_tag}{c['trigger']}, {scene}, {STYLE_SUFFIX}"
        neg = NEGATIVE_PROMPT
    else:
        # No LoRA: inject verified appearance + push wrong colors into negative.
        appearance = c["appearance"]
        outfit = f", {c['outfit']}" if c.get("outfit") else ""
        pos = (
            f"{STYLE_PREFIX}, {nsfw_tag}{c['trigger']}, {appearance}{outfit}, "
            f"{scene}, {STYLE_SUFFIX}"
        )
        neg = NEGATIVE_PROMPT
        if c.get("wrong_color_negatives"):
            neg = f"{neg}, {c['wrong_color_negatives']}"
    return pos, neg
