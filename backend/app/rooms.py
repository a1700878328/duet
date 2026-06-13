"""REST endpoints: auth + rooms + messages."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .crud import is_member, messages_after, room_to_out
from .db import get_session
from .models import NpcCard, Room, RoomMember, User
from .schemas import (
    AuthOut,
    CardsOut,
    HealthOut,
    LoginIn,
    MeCardUpdateIn,
    MemberOut,
    MeOut,
    MessageOut,
    NpcCardIn,
    NpcCardOut,
    RegisterIn,
    RoomCreateIn,
    RoomJoinIn,
    RoomOut,
    UserOut,
)
from .security import (
    create_token,
    get_current_user,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/api")

SessionDep = Annotated[AsyncSession, Depends(get_session)]
CurrentUser = Annotated[User, Depends(get_current_user)]


@router.get("/health", response_model=HealthOut)
async def health() -> HealthOut:
    return HealthOut()


@router.post("/auth/register", response_model=AuthOut)
async def register(body: RegisterIn, session: SessionDep) -> AuthOut:
    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        display_name=body.display_name,
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="username already taken",
        ) from exc
    await session.refresh(user)
    return AuthOut(token=create_token(user.id), user=UserOut.model_validate(user))


@router.post("/auth/login", response_model=AuthOut)
async def login(body: LoginIn, session: SessionDep) -> AuthOut:
    user = await session.scalar(
        select(User).where(User.username == body.username)
    )
    if user is None or not verify_password(user.password_hash, body.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid credentials",
        )
    return AuthOut(token=create_token(user.id), user=UserOut.model_validate(user))


@router.get("/me", response_model=MeOut)
async def me(user: CurrentUser) -> MeOut:
    return MeOut(user=UserOut.model_validate(user))


@router.get("/rooms", response_model=list[RoomOut])
async def list_rooms(user: CurrentUser, session: SessionDep) -> list[RoomOut]:
    room_ids = (
        await session.scalars(
            select(RoomMember.room_id).where(RoomMember.user_id == user.id)
        )
    ).all()
    if not room_ids:
        return []
    rooms = (
        await session.scalars(select(Room).where(Room.id.in_(room_ids)))
    ).all()
    return [await room_to_out(session, r) for r in rooms]


@router.post("/rooms", response_model=RoomOut)
async def create_room(
    body: RoomCreateIn, user: CurrentUser, session: SessionDep
) -> RoomOut:
    room = Room(
        name=body.name,
        owner_id=user.id,
        ai_mode="manual",
        world_card=body.world_card,
    )
    session.add(room)
    await session.flush()
    session.add(
        RoomMember(
            room_id=room.id,
            user_id=user.id,
            character_name=body.character_name,
            appearance=body.appearance,
        )
    )
    await session.commit()
    await session.refresh(room)
    return await room_to_out(session, room)


@router.post("/rooms/{room_id}/join", response_model=RoomOut)
async def join_room(
    room_id: int,
    body: RoomJoinIn,
    user: CurrentUser,
    session: SessionDep,
) -> RoomOut:
    room = await session.get(Room, room_id)
    if room is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="room not found"
        )
    if not await is_member(session, room_id, user.id):
        session.add(
            RoomMember(
                room_id=room_id,
                user_id=user.id,
                character_name=body.character_name,
                appearance=body.appearance,
            )
        )
        await session.commit()
    await session.refresh(room)
    return await room_to_out(session, room)


@router.get("/rooms/{room_id}/messages", response_model=list[MessageOut])
async def get_messages(
    room_id: int,
    user: CurrentUser,
    session: SessionDep,
    after_seq: Annotated[int, Query(ge=0)] = 0,
) -> list[MessageOut]:
    if not await is_member(session, room_id, user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="not a member"
        )
    rows = await messages_after(session, room_id, after_seq)
    return [MessageOut.model_validate(m) for m in rows]


# ---- 角色卡（Phase A）：玩家卡 + NPC 卡 ----


async def _require_member(
    session: AsyncSession, room_id: int, user_id: int
) -> None:
    if not await is_member(session, room_id, user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="not a member"
        )


def _member_card(m: RoomMember, display_name: str) -> MemberOut:
    return MemberOut(
        user_id=m.user_id,
        display_name=display_name,
        character_name=m.character_name,
        appearance=m.appearance,
        persona=m.persona,
        voice_id=m.voice_id,
    )


@router.get("/rooms/{room_id}/cards", response_model=CardsOut)
async def list_cards(
    room_id: int, user: CurrentUser, session: SessionDep
) -> CardsOut:
    await _require_member(session, room_id, user.id)
    members = (
        await session.scalars(
            select(RoomMember).where(RoomMember.room_id == room_id)
        )
    ).all()
    npcs = (
        await session.scalars(
            select(NpcCard).where(NpcCard.room_id == room_id)
        )
    ).all()
    return CardsOut(
        players=[_member_card(m, m.user.display_name) for m in members],
        npcs=[NpcCardOut.model_validate(n) for n in npcs],
    )


@router.put("/rooms/{room_id}/me-card", response_model=MemberOut)
async def update_my_card(
    room_id: int, body: MeCardUpdateIn, user: CurrentUser, session: SessionDep
) -> MemberOut:
    member = await session.scalar(
        select(RoomMember).where(
            RoomMember.room_id == room_id, RoomMember.user_id == user.id
        )
    )
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="not a member"
        )
    if body.character_name is not None:
        member.character_name = body.character_name
    if body.persona is not None:
        member.persona = body.persona
    if body.appearance is not None:
        member.appearance = body.appearance
    if body.voice_id is not None:
        member.voice_id = body.voice_id
    await session.commit()
    await session.refresh(member)
    return _member_card(member, user.display_name)


@router.post("/rooms/{room_id}/npcs", response_model=NpcCardOut)
async def create_npc(
    room_id: int, body: NpcCardIn, user: CurrentUser, session: SessionDep
) -> NpcCardOut:
    await _require_member(session, room_id, user.id)
    npc = NpcCard(
        room_id=room_id,
        name=body.name,
        persona=body.persona,
        appearance=body.appearance,
        voice_id=body.voice_id,
        created_by=user.id,
        created_by_ai=False,
    )
    session.add(npc)
    await session.commit()
    await session.refresh(npc)
    return NpcCardOut.model_validate(npc)


@router.put("/rooms/{room_id}/npcs/{npc_id}", response_model=NpcCardOut)
async def update_npc(
    room_id: int,
    npc_id: int,
    body: NpcCardIn,
    user: CurrentUser,
    session: SessionDep,
) -> NpcCardOut:
    await _require_member(session, room_id, user.id)
    npc = await session.get(NpcCard, npc_id)
    if npc is None or npc.room_id != room_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="npc not found"
        )
    npc.name = body.name
    npc.persona = body.persona
    npc.appearance = body.appearance
    npc.voice_id = body.voice_id
    await session.commit()
    await session.refresh(npc)
    return NpcCardOut.model_validate(npc)


@router.delete("/rooms/{room_id}/npcs/{npc_id}")
async def delete_npc(
    room_id: int, npc_id: int, user: CurrentUser, session: SessionDep
) -> dict[str, str]:
    await _require_member(session, room_id, user.id)
    npc = await session.get(NpcCard, npc_id)
    if npc is not None and npc.room_id == room_id:
        await session.delete(npc)
        await session.commit()
    return {"status": "ok"}
