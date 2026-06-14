"""Shared data-access helpers used by both REST and WS layers."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Message, Room, RoomMember
from .schemas import MemberOut, RoomOut


async def room_to_out(session: AsyncSession, room: Room) -> RoomOut:
    members = (
        await session.scalars(
            select(RoomMember).where(RoomMember.room_id == room.id)
        )
    ).all()
    return RoomOut(
        id=room.id,
        name=room.name,
        owner_id=room.owner_id,
        ai_mode=room.ai_mode,
        world_card=room.world_card,
        week=room.week,
        members=[
            MemberOut(
                user_id=m.user_id,
                display_name=m.user.display_name,
                character_name=m.character_name,
                appearance=m.appearance,
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


async def member_label(
    session: AsyncSession, room_id: int, user_id: int
) -> str | None:
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
