"""Narrative time helpers for day/phase based room clocks."""

from dataclasses import dataclass
from typing import Any

TIME_PHASES = ["清晨", "上午", "正午", "下午", "黄昏", "夜晚", "深夜"]


@dataclass(frozen=True)
class TimeSnapshot:
    week: int
    day: int
    slot: int
    world_card: str | None = None

    @property
    def label(self) -> str:
        return time_label(self.week, self.day, self.slot, world_card=self.world_card)

    @property
    def index(self) -> int:
        return time_index(self.day, self.slot)


def clamp_slot(slot: Any) -> int:
    try:
        value = int(slot)
    except (TypeError, ValueError):
        return 0
    return max(0, min(len(TIME_PHASES) - 1, value))


def week_for_day(day: int) -> int:
    return ((max(1, day) - 1) // 7) + 1


def time_index(day: int, slot: int) -> int:
    return (max(1, int(day)) - 1) * len(TIME_PHASES) + clamp_slot(slot)


def split_time_index(index: int) -> tuple[int, int]:
    value = max(0, int(index))
    return value // len(TIME_PHASES) + 1, value % len(TIME_PHASES)


def time_label(week: int, day: int, slot: int, *, world_card: str | None = None) -> str:
    phase = TIME_PHASES[clamp_slot(slot)]
    if world_card == "ksim":
        return f"冒险第{max(1, int(week))}周·第{max(1, int(day))}天·{phase}"
    return f"第{max(1, int(week))}周·第{max(1, int(day))}天·{phase}"


def room_time(room: Any) -> TimeSnapshot:
    day = max(1, int(getattr(room, "day", 1) or 1))
    slot = clamp_slot(getattr(room, "time_slot", 0))
    week = max(int(getattr(room, "week", 1) or 1), week_for_day(day))
    world_card = getattr(room, "world_card", None)
    return TimeSnapshot(week=week, day=day, slot=slot, world_card=world_card)


def advance_room_time(room: Any, steps: int = 1) -> tuple[TimeSnapshot, TimeSnapshot]:
    old = room_time(room)
    new_day, new_slot = split_time_index(old.index + max(0, int(steps)))
    new_week = week_for_day(new_day)
    room.day = new_day
    room.time_slot = new_slot
    room.week = new_week
    return old, TimeSnapshot(
        week=new_week,
        day=new_day,
        slot=new_slot,
        world_card=getattr(room, "world_card", None),
    )
