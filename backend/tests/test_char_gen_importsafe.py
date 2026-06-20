"""Guard: importing app.char_gen must NOT make live calls (no network/brain).

Mirrors the npc_gen contract: pure import + JSON-array parsing are cheap and
side-effect-free. We make NO live brain/portrait calls here.
"""

from __future__ import annotations

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


@pytest.mark.asyncio
async def test_generate_options_skips_invalid_agent_output(monkeypatch) -> None:
    async def fake_agent_run(_task, **_kwargs):
        return {}

    monkeypatch.setattr(char_gen.agent, "run", fake_agent_run)
    drafts = await generate_character_options("ksim", None, 1)
    assert len(drafts) == 0


@pytest.mark.asyncio
async def test_described_variants_preserve_visual_requirements(monkeypatch) -> None:
    seen: list[str] = []

    async def fake_agent_run(task, **kwargs):
        assert task == "character_design"
        seen.append(kwargs["input"])
        return {
            "name": f"候选{len(seen)}",
            "persona": "冷静寡言的巡礼者",
            "appearance": "黑色修女服，戴单眼眼罩",
            "voice_id": "年轻女性，低声",
        }

    monkeypatch.setattr(char_gen.agent, "run", fake_agent_run)

    drafts = await generate_character_options("ksim", "戴眼罩的修女", 3)

    assert len(drafts) == 3
    assert all("戴眼罩的修女" in desc for desc in seen)
    assert all("必须保留玩家原始描述里" in desc for desc in seen[1:])
    assert all("同一个角色的不同插画师诠释" in desc for desc in seen[1:])


@pytest.mark.asyncio
async def test_character_design_keeps_long_appearance(monkeypatch) -> None:
    long_appearance = "银白长发，紫色眼睛，黑色修女服。" * 80

    async def fake_agent_run(task, **kwargs):
        assert task == "character_design"
        assert "appearance 写 250-700 字" in kwargs["input"]
        return {
            "name": "候选",
            "persona": "她是流亡修女。她说话低声克制。她隐藏着危险的执念。她适合黑暗奇幻剧情。",
            "appearance": long_appearance,
            "voice_id": "年轻女性，低声",
        }

    monkeypatch.setattr(char_gen.agent, "run", fake_agent_run)

    drafts = await generate_character_options("ksim", "戴眼罩的修女", 1)

    assert len(drafts) == 1
    assert len(drafts[0]["appearance"]) > 512
