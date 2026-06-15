from types import SimpleNamespace

import pytest

from app.npc_decision import judge_npc_impulse


class ImpulseBrain:
    async def complete(self, messages):
        assert "不是导演" in messages[0]["content"]
        assert "酒馆老板娘" in messages[1]["content"]
        return (
            '{"speak": true, "urgency": 4, '
            '"reason": "玩家提到了酒馆传闻，她想借机套话。"}'
        )


@pytest.mark.asyncio
async def test_npc_impulse_can_choose_to_speak() -> None:
    room = SimpleNamespace(name="测试房间")
    npc = SimpleNamespace(
        name="酒馆老板娘",
        persona="热情但爱打探消息",
        discovered="玩家知道她消息灵通",
    )
    member = SimpleNamespace(character_name="女骑士", persona="")

    decision = await judge_npc_impulse(
        room,
        [member],
        npc,
        ["公会会长"],
        "女骑士询问城里的流言。",
        current_scene="酒馆",
        brain=ImpulseBrain(),
    )

    assert decision["speak"] is True
    assert decision["urgency"] == 4
    assert "套话" in decision["reason"]


class QuietBrain:
    async def complete(self, messages):
        return '{"speak": "no", "urgency": 5, "reason": "没有个人动机。"}'


@pytest.mark.asyncio
async def test_npc_impulse_respects_quiet_choice() -> None:
    room = SimpleNamespace(name="测试房间")
    npc = SimpleNamespace(name="借贷商人", persona="油滑商人", discovered=None)
    member = SimpleNamespace(character_name="女骑士", persona="")

    decision = await judge_npc_impulse(
        room,
        [member],
        npc,
        [],
        "旁白描述了街道。",
        brain=QuietBrain(),
    )

    assert decision["speak"] is False
