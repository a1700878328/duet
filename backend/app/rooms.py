"""REST endpoints: auth + rooms + messages."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .crud import is_member, messages_after, room_to_out
from .db import get_session
from .models import Room, RoomMember, User
from .schemas import (
    AuthOut,
    HealthOut,
    LoginIn,
    MeOut,
    MessageOut,
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
