"""Guard: importing app.char_gen must NOT make live calls (no network/brain).

Mirrors the npc_gen contract: pure import + JSON-array parsing are cheap and
side-effect-free. We make NO live brain/portrait calls here.
"""

from __future__ import annotations

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
