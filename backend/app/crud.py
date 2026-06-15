"""Shared data-access helpers used by both REST and WS layers."""

import json

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Message, NpcCard, Room, RoomMember
from .scene_logs import load_scene_meta
from .schemas import MemberOut, RoomOut
from .stats import default_stats
from .tasks import current_task_from_meta, task_offers_from_meta
from .timeflow import room_time
from .world_presets import scene_options, start_scene


def _scene_options_from_meta(raw: str | None) -> list[str]:
    data = load_scene_meta(raw)
    unlocked = data.get("_unlocked_scenes")
    if not isinstance(unlocked, list):
        return []
    return [str(s).strip()[:64] for s in unlocked if str(s).strip()]


def _current_task_from_meta(raw: str | None, world_card: str | None) -> dict | None:
    _ = world_card
    data = load_scene_meta(raw)
    return current_task_from_meta(data)


def _task_offers_from_meta(raw: str | None) -> list[dict]:
    return task_offers_from_meta(load_scene_meta(raw))


def effective_current_scene(room: Room) -> str:
    """Return a concrete scene when a world card defines a starting location."""
    return (room.current_scene or start_scene(room.world_card) or "").strip()


async def ensure_room_scene(session: AsyncSession, room: Room) -> str:
    """Backfill old rooms that predate world-card start scenes."""
    scene = effective_current_scene(room)
    if scene and room.current_scene != scene:
        room.current_scene = scene
        await session.commit()
        await session.refresh(room)
    return scene


async def room_to_out(session: AsyncSession, room: Room) -> RoomOut:
    current_scene = await ensure_room_scene(session, room)
    members = (
        await session.scalars(select(RoomMember).where(RoomMember.room_id == room.id))
    ).all()
    npc_scenes = (
        await session.scalars(
            select(NpcCard.scene).where(
                NpcCard.room_id == room.id, NpcCard.scene.is_not(None)
            )
        )
    ).all()
    scenes: list[str] = []
    for scene in [
        *scene_options(room.world_card),
        current_scene,
        *npc_scenes,
        *_scene_options_from_meta(room.scenes_meta),
    ]:
        scene = (scene or "").strip()
        if scene and scene not in scenes:
            scenes.append(scene)
    clock = room_time(room)
    return RoomOut(
        id=room.id,
        name=room.name,
        owner_id=room.owner_id,
        ai_mode=room.ai_mode,
        world_card=room.world_card,
        week=clock.week,
        day=clock.day,
        time_slot=clock.slot,
        time_label=clock.label,
        current_scene=room.current_scene,
        scene_options=scenes,
        current_task=_current_task_from_meta(room.scenes_meta, room.world_card),
        task_offers=_task_offers_from_meta(room.scenes_meta),
        members=[
            MemberOut(
                user_id=m.user_id,
                display_name=m.user.display_name,
                character_name=m.character_name,
                appearance=m.appearance,
                persona=m.persona,
                voice_id=m.voice_id,
                voice_ref_url=m.voice_ref_url,
                voice_ref_text=m.voice_ref_text,
                avatar_url=m.avatar_url,
                stats=json.loads(m.stats) if m.stats else default_stats(),
            )
            for m in members
        ],
    )


async def is_member(session: AsyncSession, room_id: int, user_id: int) -> bool:
    found = await session.scalar(
        select(RoomMember.user_id).where(
            RoomMember.room_id == room_id, RoomMember.user_id == user_id
        )
    )
    return found is not None


async def member_label(session: AsyncSession, room_id: int, user_id: int) -> str | None:
    return await session.scalar(
        select(RoomMember.character_name).where(
            RoomMember.room_id == room_id, RoomMember.user_id == user_id
        )
    )


async def next_seq(session: AsyncSession, room_id: int) -> int:
    current = await session.scalar(
        select(func.max(Message.seq)).where(Message.room_id == room_id)
    )
    return (current or 0) + 1


async def messages_after(
    session: AsyncSession, room_id: int, after_seq: int, limit: int = 200
) -> list[Message]:
    rows = await session.scalars(
        select(Message)
        .where(Message.room_id == room_id, Message.seq > after_seq)
        .order_by(Message.seq.asc())
        .limit(limit)
    )
    return list(rows)
