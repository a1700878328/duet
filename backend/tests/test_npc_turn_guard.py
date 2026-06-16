from types import SimpleNamespace

import pytest

from app import ws as ws_mod
from app.prompts import build_npc_system_prompt


class WrongSpeakerBrain:
    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, messages):
        self.calls += 1
        if self.calls == 1:
            return "[旁白]: 风从门缝里吹进来。"
        assert "专属回合" in messages[-1]["content"]
        return "[酒馆老板娘]: （眯起眼）你刚才那句话，我可不能当没听见。"


class StillWrongSpeakerBrain:
    async def complete(self, messages):
        return "[旁白]: 场面安静下来。"


class WrongUnbracketedSpeakerBrain:
    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, messages):
        self.calls += 1
        if self.calls == 1:
            return "瑟琳娜·血藤（懒洋洋地靠在吧台边）：我来替你说吧。"
        return "[公会会长]: 公会会长（皱眉）：把别人的名字从我的台词里拿掉。"


@pytest.mark.asyncio
async def test_npc_turn_regenerates_narrator_label(monkeypatch):
    brain = WrongSpeakerBrain()
    monkeypatch.setattr(ws_mod, "brain", brain)

    clean, info = await ws_mod._generate_guarded(
        [{"role": "system", "content": "只扮演酒馆老板娘"}],
        ["女骑士"],
        required_label="酒馆老板娘",
    )

    assert brain.calls == 2
    assert info["regenerated"] is True
    assert clean.startswith("[酒馆老板娘]:")
    assert "[旁白]" not in clean


@pytest.mark.asyncio
async def test_npc_turn_fails_closed_to_npc_label(monkeypatch):
    monkeypatch.setattr(ws_mod, "brain", StillWrongSpeakerBrain())

    clean, info = await ws_mod._generate_guarded(
        [{"role": "system", "content": "只扮演酒馆老板娘"}],
        ["女骑士"],
        required_label="酒馆老板娘",
    )

    assert info["violated_final"] is True
    assert clean == "[酒馆老板娘]: （……）"


@pytest.mark.asyncio
async def test_npc_turn_regenerates_unbracketed_other_npc_label(monkeypatch):
    brain = WrongUnbracketedSpeakerBrain()
    monkeypatch.setattr(ws_mod, "brain", brain)

    clean, info = await ws_mod._generate_guarded(
        [{"role": "system", "content": "只扮演公会会长"}],
        ["瑟琳娜·血藤"],
        required_label="公会会长",
    )

    assert brain.calls == 2
    assert info["regenerated"] is True
    assert clean.startswith("[公会会长]:")
    assert "瑟琳娜·血藤" not in clean


@pytest.mark.parametrize(
    "text",
    [
        "瑟琳娜·血藤（懒洋洋地靠在吧台边）：我来替你说吧。",
        "[公会会长]: 瑟琳娜·血藤（懒洋洋地靠在吧台边）：我来替你说吧。",
    ],
)
def test_required_speaker_detects_nested_or_unbracketed_other_label(text):
    assert ws_mod._has_wrong_required_speaker(text, "公会会长") is True


def test_required_speaker_prefix_is_stripped_without_changing_label():
    text = "[公会会长]: （皱眉）按规矩来。"
    assert (
        ws_mod._strip_required_speaker_prefix(text, "公会会长")
        == "（皱眉）按规矩来。"
    )


def test_npc_dialogue_guard_detects_third_person_other_role_leak():
    assert ws_mod._looks_like_npc_narration_leak(
        "会长放下茶杯，朝你挑了挑眉。“有事？”",
        npc_name="教官",
        forbidden_names=["公会会长", "瑟琳娜"],
    )


def test_npc_dialogue_guard_detects_self_third_person_narration():
    assert ws_mod._looks_like_npc_narration_leak(
        "会长站起身，绕过柜台踱到你面前。“想接点特别的任务？”",
        npc_name="公会会长",
        forbidden_names=["教官", "瑟琳娜"],
    )


def test_narration_request_is_hidden_from_npc_line():
    clean, requests = ws_mod._extract_narration_requests(
        "（擦剑）我在。[[旁白请求:会长把茶杯放回桌上，大厅安静下来。]]"
    )

    assert clean == "（擦剑）我在。"
    assert requests == ["会长把茶杯放回桌上，大厅安静下来。"]


def test_scene_image_characters_prefers_player_and_mentioned_npc():
    history = [
        SimpleNamespace(
            author_type="user",
            speaker_label="瑟琳娜·血藤",
            content="一把按住会长，压在身下",
        )
    ]

    assert ws_mod._scene_image_characters(
        history,
        member_names=["瑟琳娜·血藤"],
        npc_names=["公会会长", "教官"],
        look={"瑟琳娜·血藤": "red-haired knight", "公会会长": "guild master"},
    ) == ["瑟琳娜·血藤", "公会会长"]


def test_npc_prompt_forbids_narrator_label():
    room = type("Room", (), {"name": "测试房间", "world_card": None})()
    npc = type(
        "Npc",
        (),
        {
            "name": "酒馆老板娘",
            "persona": "消息灵通",
            "appearance": "",
        },
    )()
    prompt = build_npc_system_prompt(room, [], npc, ["公会会长"])

    assert "绝对禁止使用 [旁白]" in prompt
    assert "[[旁白请求:" in prompt
    assert "需要环境/动作旁白时用 [旁白]" not in prompt
