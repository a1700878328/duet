import pytest

import app.npc_gen as npc_gen


@pytest.mark.asyncio
async def test_generate_npcs_retries_empty_agent_output(monkeypatch):
    calls = []

    async def fake_run(task, *, input=None, **_kwargs):
        assert task == "npc_design"
        calls.append(input)
        if len(calls) == 1:
            return []
        return [
            {
                "name": "薇拉",
                "persona": "酒馆线人，笑里藏刀。",
                "appearance": "adult woman, red hair, green eyes",
                "voice_id": "轻快女声",
            }
        ]

    monkeypatch.setattr(npc_gen.agent, "run", fake_run)

    cards = await npc_gen.generate_npcs("ksim", None, [], 1)

    assert len(calls) == 2
    assert cards[0]["name"] == "薇拉"


@pytest.mark.asyncio
async def test_generate_npcs_falls_back_when_agent_stays_empty(monkeypatch):
    async def fake_run(_task, **_kwargs):
        return []

    monkeypatch.setattr(npc_gen.agent, "run", fake_run)

    cards = await npc_gen.generate_npcs("ksim", None, ["露西亚"], 2)

    assert len(cards) == 2
    assert cards[0]["name"] != "露西亚"
    assert all(card["persona"] for card in cards)
