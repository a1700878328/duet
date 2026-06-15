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
    assert "需要环境/动作旁白时用 [旁白]" not in prompt
