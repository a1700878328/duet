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

    assert brain.calls == 2
    assert drafts[0]["name"] == "艾琳"
    assert drafts[0]["appearance"].startswith("young adult woman")
