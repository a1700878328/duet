from types import SimpleNamespace

import pytest

from app.director import judge_world_beat


class FakeBrain:
    async def complete(self, messages):
        assert "acts 必须输出空数组" in messages[0]["content"]
        return """
        {
          "acts": [1],
          "introduce": [{
            "name": "巡夜修女",
            "persona": "冷静、谨慎，负责夜间巡逻",
            "appearance": "a calm young nun with silver hair and a black habit",
            "voice_id": "年轻女性，清冷，低声"
          }],
          "time_jump": null,
          "unlock_scenes": ["修道院后庭"]
        }
        """


@pytest.mark.asyncio
async def test_event_only_director_clears_acts_but_keeps_world_changes() -> None:
    npc = SimpleNamespace(id=1, name="酒馆老板娘", persona="热情，会接待客人")
    member = SimpleNamespace(character_name="女骑士")

    plan = await judge_world_beat(
        "ksim",
        [member],
        [npc],
        "女骑士询问夜里的动静。",
        allow_acts=False,
        brain=FakeBrain(),
    )

    assert plan["acts"] == []
    assert plan["introduce"][0]["name"] == "巡夜修女"
    assert plan["unlock_scenes"] == ["修道院后庭"]


class TimeJumpBrain:
    async def complete(self, messages):
        return """
        {
          "narration": null,
          "acts": [],
          "introduce": [],
          "time_jump": "一周后，城镇里的流言已经传遍街角。",
          "unlock_scenes": []
        }
        """


@pytest.mark.asyncio
async def test_normal_world_beat_drops_time_jump() -> None:
    npc = SimpleNamespace(id=1, name="酒馆老板娘", persona="热情，会接待客人")
    member = SimpleNamespace(character_name="女骑士")

    plan = await judge_world_beat(
        "ksim",
        [member],
        [npc],
        "女骑士刚坐到吧台边。",
        brain=TimeJumpBrain(),
    )

    assert plan["time_jump"] is None


@pytest.mark.asyncio
async def test_forced_timeskip_keeps_time_jump() -> None:
    npc = SimpleNamespace(id=1, name="酒馆老板娘", persona="热情，会接待客人")
    member = SimpleNamespace(character_name="女骑士")

    plan = await judge_world_beat(
        "ksim",
        [member],
        [npc],
        "女骑士决定休整一阵。",
        force_timeskip=True,
        brain=TimeJumpBrain(),
    )

    assert plan["time_jump"] == "一周后，城镇里的流言已经传遍街角。"


class NarrationBrain:
    async def complete(self, messages):
        assert '"narration"' in messages[0]["content"]
        return """
        {
          "narration": "公会大厅里烛火摇晃，公告栏上的新委托还沾着未干的墨迹。",
          "acts": [],
          "introduce": [],
          "time_jump": null,
          "unlock_scenes": []
        }
        """


@pytest.mark.asyncio
async def test_world_beat_can_request_narration() -> None:
    member = SimpleNamespace(character_name="女骑士")

    plan = await judge_world_beat(
        "ksim",
        [member],
        [],
        "（刚开场）",
        brain=NarrationBrain(),
    )

    assert plan["narration"] == "公会大厅里烛火摇晃，公告栏上的新委托还沾着未干的墨迹。"
    assert plan["acts"] == []


class AutoChangeBrain:
    async def complete(self, messages):
        assert "已知可前往场景：冒险者公会、酒馆" in messages[1]["content"]
        return """
        {
          "narration": "吧台那边的笑声把公会大厅外的暮色也带得热闹起来。",
          "acts": [3],
          "introduce": [],
          "time_jump": null,
          "time_advance_steps": 1,
          "time_reason": "女骑士离开公会，花了一段路程前往酒馆。",
          "scene_change": "酒馆",
          "scene_reason": "玩家明确说要去酒馆。",
          "unlock_scenes": ["酒馆"]
        }
        """


@pytest.mark.asyncio
async def test_director_keeps_small_auto_time_and_scene_change() -> None:
    npc = SimpleNamespace(id=1, name="公会会长", persona="威严")
    member = SimpleNamespace(character_name="女骑士")

    plan = await judge_world_beat(
        "ksim",
        [member],
        [npc],
        "女骑士说：我去酒馆打听消息。",
        scene="冒险者公会",
        known_scenes=["冒险者公会", "酒馆"],
        brain=AutoChangeBrain(),
    )

    assert plan["acts"] == []
    assert plan["time_advance_steps"] == 1
    assert plan["time_reason"] == "女骑士离开公会，花了一段路程前往酒馆。"
    assert plan["scene_change"] == "酒馆"
    assert plan["scene_reason"] == "玩家明确说要去酒馆。"
    assert plan["unlock_scenes"] == ["酒馆"]


@pytest.mark.asyncio
async def test_director_can_disable_auto_changes() -> None:
    npc = SimpleNamespace(id=1, name="公会会长", persona="威严")
    member = SimpleNamespace(character_name="女骑士")

    plan = await judge_world_beat(
        "ksim",
        [member],
        [npc],
        "女骑士说：我去酒馆打听消息。",
        scene="冒险者公会",
        known_scenes=["冒险者公会", "酒馆"],
        allow_auto_changes=False,
        brain=AutoChangeBrain(),
    )

    assert plan["time_advance_steps"] == 0
    assert plan["time_reason"] is None
    assert plan["scene_change"] is None
    assert plan["scene_reason"] is None


class MultiActsBrain:
    async def complete(self, messages):
        return """
        {
          "narration": null,
          "acts": [1, 2],
          "introduce": [],
          "time_jump": null,
          "unlock_scenes": []
        }
        """


@pytest.mark.asyncio
async def test_director_ignores_existing_npc_speakers() -> None:
    npcs = [
        SimpleNamespace(id=1, name="公会会长", persona="威严"),
        SimpleNamespace(id=2, name="酒馆老板娘", persona="热情"),
    ]
    member = SimpleNamespace(character_name="女骑士")

    plan = await judge_world_beat(
        "ksim",
        [member],
        npcs,
        "女骑士刚走进城镇。",
        brain=MultiActsBrain(),
    )

    assert plan["acts"] == []
