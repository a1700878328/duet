"""Guard: importing app.char_gen must NOT make live calls (no network/brain).

Mirrors the npc_gen contract: pure import + JSON-array parsing are cheap and
side-effect-free. We make NO live brain/portrait calls here.
"""

from __future__ import annotations

import json

import pytest

import app.char_gen as char_gen
from app.char_gen import _parse_json_array, generate_character_options


def test_module_exposes_expected_api() -> None:
    assert callable(generate_character_options)
    assert callable(char_gen._parse_json_array)


def test_parse_json_array_handles_fenced_block() -> None:
    raw = '```json\n[{"name": "艾琳", "appearance": "blonde hair"}]\n```'
    parsed = _parse_json_array(raw)
    assert parsed == [{"name": "艾琳", "appearance": "blonde hair"}]


def test_parse_json_array_bad_input_is_empty() -> None:
    assert _parse_json_array("not json at all") == []
    assert _parse_json_array("{}") == []


class RetryBrain:
    def __init__(self) -> None:
        self.calls = 0
        self.temperature = 0.9
        self.max_tokens = 800

    async def complete(self, messages):
        self.calls += 1
        if self.calls == 1:
            return "我来为你设计几个角色："
        return json.dumps(
            [
                {
                    "name": "艾琳",
                    "persona": "年轻女骑士，认真寡言，说话简短",
                    "appearance": (
                        "young adult woman with short blonde hair, blue eyes, "
                        "worn steel armor and a red cloak"
                    ),
                    "voice_id": "年轻女性，清澈冷静，语速偏慢",
                }
            ]
        )


@pytest.mark.asyncio
async def test_generate_character_options_retries_empty_parse() -> None:
    brain = RetryBrain()

    drafts = await generate_character_options("ksim", None, 1, brain=brain)

    assert len(drafts) == 0


@pytest.mark.asyncio
async def test_described_variants_preserve_visual_requirements(monkeypatch) -> None:
    seen: list[str] = []

    async def fake_design_character(description, **_kwargs):
        seen.append(description)
        return {
            "name": f"候选{len(seen)}",
            "persona": "冷静寡言的巡礼者",
            "appearance": "黑色修女服，戴单眼眼罩",
            "voice_id": "年轻女性，低声",
        }

    monkeypatch.setattr(
        "app.imagegen.tutorial_designer.design_character",
        fake_design_character,
    )

    drafts = await generate_character_options("ksim", "戴眼罩的修女", 3)

    assert len(drafts) == 3
    assert all("戴眼罩的修女" in desc for desc in seen)
    assert all("必须保留玩家原始描述" in desc for desc in seen[1:])
    assert all("只在姓名、性格、背景经历" in desc for desc in seen[1:])
