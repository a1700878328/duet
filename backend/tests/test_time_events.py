from app import time_events


def test_roll_time_event_matches_scene_and_phase(monkeypatch) -> None:
    monkeypatch.setattr(
        time_events,
        "_EVENT_TABLE",
        {
            "森林@夜晚": [
                {"type": "encounter", "npc_name": "哥布林", "weight": 1}
            ]
        },
    )
    monkeypatch.setattr(time_events.random, "uniform", lambda _lo, _hi: 0)

    assert time_events.roll_time_event("森林", "夜晚")["npc_name"] == "哥布林"
    assert time_events.roll_time_event("森林", "清晨") is None


def test_encounter_npc_respects_cooldown(monkeypatch) -> None:
    monkeypatch.setattr(time_events, "_ENCOUNTER_COOLDOWN", {})
    event = {
        "type": "encounter",
        "npc_name": "哥布林",
        "npc_persona": "森林遭遇敌人",
    }

    first = time_events.pick_event_encounter_npc(event, room_id=42)
    second = time_events.pick_event_encounter_npc(event, room_id=42)

    assert first is not None
    assert first.name == "哥布林"
    assert first.room_id == 42
    assert second is None

    for _ in range(7):
        time_events.tick_cooldowns()

    assert time_events.pick_event_encounter_npc(event, room_id=42) is not None
