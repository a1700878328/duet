from types import SimpleNamespace

from app.timeflow import TIME_PHASES, advance_room_time, room_time


def test_advance_room_time_moves_between_day_phases() -> None:
    room = SimpleNamespace(week=1, day=1, time_slot=0)

    old, new = advance_room_time(room, 1)

    assert old.label == "第1周·第1天·清晨"
    assert new.label == "第1周·第1天·上午"
    assert room.day == 1
    assert room.time_slot == 1


def test_advance_room_time_rolls_day_and_week() -> None:
    room = SimpleNamespace(week=1, day=7, time_slot=len(TIME_PHASES) - 1)

    _old, new = advance_room_time(room, 1)

    assert new.week == 2
    assert new.day == 8
    assert new.slot == 0
    assert room_time(room).label == "第2周·第8天·清晨"


def test_ksim_time_label_uses_source_week_progression() -> None:
    room = SimpleNamespace(week=1, day=1, time_slot=1, world_card="ksim")

    assert room_time(room).label == "冒险第1周·第1天·上午"

    room.day = 32
    room.time_slot = 4

    assert room_time(room).label == "冒险第5周·第32天·黄昏"
