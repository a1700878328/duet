from types import SimpleNamespace

import pytest

import app.npc_decision as npc_decision_mod
from app import ws as ws_mod
from app.npc_decision import judge_npc_impulse


class ImpulseBrain:
    async def run(self, task, *, messages=None, **_kwargs):
        assert task == "npc_impulse"
        assert "不是导演" in messages[0]["content"]
        assert "酒馆老板娘" in messages[1]["content"]
        return {
            "speak": True,
            "urgency": 4,
            "reason": "玩家提到了酒馆传闻，她想借机套话。",
        }


@pytest.mark.asyncio
async def test_npc_impulse_can_choose_to_speak(monkeypatch) -> None:
    monkeypatch.setattr(npc_decision_mod.agent, "run", ImpulseBrain().run)
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
    )

    assert decision["speak"] is True
    assert decision["urgency"] == 4
    assert "套话" in decision["reason"]


class QuietBrain:
    async def run(self, task, *, messages=None, **_kwargs):
        assert task == "npc_impulse"
        return {"speak": "no", "urgency": 5, "reason": "没有个人动机。"}


@pytest.mark.asyncio
async def test_npc_impulse_respects_quiet_choice(monkeypatch) -> None:
    monkeypatch.setattr(npc_decision_mod.agent, "run", QuietBrain().run)
    room = SimpleNamespace(name="测试房间")
    npc = SimpleNamespace(name="借贷商人", persona="油滑商人", discovered=None)
    member = SimpleNamespace(character_name="女骑士", persona="")

    decision = await judge_npc_impulse(
        room,
        [member],
        npc,
        [],
        "旁白描述了街道。",
    )

    assert decision["speak"] is False


@pytest.mark.asyncio
async def test_npc_reaction_chain_rechecks_after_npc_speaks(monkeypatch) -> None:
    first = SimpleNamespace(id=1, name="教官")
    second = SimpleNamespace(id=2, name="公会会长")
    coord = SimpleNamespace(room_id=123)
    calls: list[tuple[str, list[str]]] = []
    spoken: list[str] = []

    async def fake_self_motivated(_coord, candidates, current_scene):
        calls.append((current_scene, [npc.name for npc in candidates]))
        if len(calls) == 1:
            return [first]
        return [npc for npc in candidates if npc.name == "公会会长"]

    async def fake_run_ai_turn(_coord, npc):
        spoken.append(npc.name)

    monkeypatch.setattr(ws_mod, "_self_motivated_npcs", fake_self_motivated)
    monkeypatch.setattr(ws_mod, "_run_ai_turn", fake_run_ai_turn)

    acted, spoke_ids = await ws_mod._run_npc_reaction_chain(
        coord,
        [first, second],
        "冒险者公会",
    )

    assert acted is True
    assert spoken == ["教官", "公会会长"]
    assert spoke_ids == [1, 2]
    assert calls == [
        ("冒险者公会", ["教官", "公会会长"]),
        ("冒险者公会", ["公会会长"]),
    ]


@pytest.mark.asyncio
async def test_npc_reaction_chain_drops_stale_initial_speakers(monkeypatch) -> None:
    first = SimpleNamespace(id=1, name="教官")
    stale = SimpleNamespace(id=2, name="莉娜")
    coord = SimpleNamespace(room_id=123)
    calls: list[list[str]] = []
    spoken: list[str] = []

    async def fake_self_motivated(_coord, candidates, _current_scene):
        names = [npc.name for npc in candidates]
        calls.append(names)
        if len(calls) == 1:
            return [first, stale]
        return []

    async def fake_run_ai_turn(_coord, npc):
        spoken.append(npc.name)

    monkeypatch.setattr(ws_mod, "_self_motivated_npcs", fake_self_motivated)
    monkeypatch.setattr(ws_mod, "_run_ai_turn", fake_run_ai_turn)

    acted, spoke_ids = await ws_mod._run_npc_reaction_chain(
        coord,
        [first, stale],
        "冒险者公会",
    )

    assert acted is True
    assert spoken == ["教官"]
    assert spoke_ids == [1]
    assert calls == [["教官", "莉娜"], ["莉娜"]]
