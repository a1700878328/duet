"""REST endpoints: auth + rooms + messages."""

import hashlib
import json
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .char_gen import generate_character_options
from .crud import is_member, messages_after, room_to_out
from .db import get_session
from .imagegen.anima import char_seed
from .imagegen.portrait import generate_portrait
from .models import NpcCard, Room, RoomMember, User
from .npc_gen import generate_npcs
from .schemas import (
    AuthOut,
    CardsOut,
    CharDraftOut,
    CharOptionsIn,
    HealthOut,
    LoginIn,
    MeCardUpdateIn,
    MemberOut,
    MeOut,
    MessageOut,
    NpcActiveIn,
    NpcCardIn,
    NpcCardOut,
    NpcGenIn,
    RegisterIn,
    RoomCreateIn,
    RoomJoinIn,
    RoomOut,
    TtsIn,
    TtsOut,
    UserOut,
)
from .security import (
    create_token,
    get_current_user,
    hash_password,
    verify_password,
)
from .stats import default_stats
from .voice import store as voice_store
from .world_presets import preset_npcs, start_scene

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
        current_scene=start_scene(body.world_card),
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
    # 世界卡常驻主要 NPC：开场就在场（NPC 数非 0），其余怪物由 director 临场引入。
    for p in preset_npcs(room.world_card):
        session.add(
            NpcCard(
                room_id=room.id,
                name=p["name"],
                persona=p["persona"],
                appearance=p.get("appearance"),
                voice_id=p.get("voice_id"),
                scene=p.get("scene"),
                created_by_ai=True,
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
        avatar_url=m.avatar_url,
        stats=json.loads(m.stats) if m.stats else default_stats(),
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
    if body.avatar_url is not None:
        member.avatar_url = body.avatar_url
    await session.commit()
    await session.refresh(member)
    return _member_card(member, user.display_name)


@router.post(
    "/rooms/{room_id}/character-options",
    response_model=list[CharDraftOut],
)
async def character_options(
    room_id: int,
    body: CharOptionsIn,
    user: CurrentUser,
    session: SessionDep,
) -> list[CharDraftOut]:
    """Generate player-character drafts (with portraits) for in-room selection.

    SLOW: one portrait per draft, generated sequentially (~count*40s). Acceptable
    for one-time onboarding. Nothing is persisted — selection goes via PUT
    /me-card. A draft's ``avatar_url`` is null if its portrait failed; a portrait
    failure never fails the whole request.
    """
    await _require_member(session, room_id, user.id)
    room = await session.get(Room, room_id)
    if room is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="room not found"
        )
    drafts = await generate_character_options(
        room.world_card, body.hint, body.count
    )
    out: list[CharDraftOut] = []
    for d in drafts:
        avatar_url: str | None = None
        appearance = d.get("appearance")
        if appearance:
            try:
                result = await generate_portrait(appearance)
                avatar_url = result.get("url")
            except Exception:
                avatar_url = None
        out.append(
            CharDraftOut(
                name=d["name"],
                persona=d.get("persona", ""),
                appearance=appearance,
                voice_id=d.get("voice_id"),
                avatar_url=avatar_url,
            )
        )
    return out


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


@router.post("/rooms/{room_id}/npcs/generate", response_model=list[NpcCardOut])
async def generate_npcs_endpoint(
    room_id: int, body: NpcGenIn, user: CurrentUser, session: SessionDep
) -> list[NpcCardOut]:
    await _require_member(session, room_id, user.id)
    room = await session.get(Room, room_id)
    if room is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="room not found"
        )
    existing = list(
        await session.scalars(
            select(NpcCard.name).where(NpcCard.room_id == room_id)
        )
    )
    cards = await generate_npcs(room.world_card, body.hint, existing, body.count)
    created: list[NpcCard] = []
    for c in cards:
        npc = NpcCard(
            room_id=room_id,
            name=c["name"],
            persona=c["persona"],
            appearance=c["appearance"],
            voice_id=c["voice_id"],
            created_by=user.id,
            created_by_ai=True,
        )
        session.add(npc)
        created.append(npc)
    await session.commit()
    for npc in created:
        await session.refresh(npc)
    return [NpcCardOut.model_validate(npc) for npc in created]


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


# ---- 立绘/头像 + NPC 启停（Phase E） ----


@router.post("/rooms/{room_id}/me-card/avatar", response_model=MemberOut)
async def generate_my_avatar(
    room_id: int, user: CurrentUser, session: SessionDep
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
    result = await generate_portrait(
        member.appearance or member.character_name or "1person",
        seed=char_seed(room_id, member.character_name or str(member.user_id)),
    )
    if not result.get("url"):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=result.get("error", "生成头像失败"),
        )
    member.avatar_url = result["url"]
    await session.commit()
    await session.refresh(member)
    return _member_card(member, user.display_name)


@router.post("/rooms/{room_id}/npcs/{npc_id}/avatar", response_model=NpcCardOut)
async def generate_npc_avatar(
    room_id: int, npc_id: int, user: CurrentUser, session: SessionDep
) -> NpcCardOut:
    await _require_member(session, room_id, user.id)
    npc = await session.get(NpcCard, npc_id)
    if npc is None or npc.room_id != room_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="npc not found"
        )
    result = await generate_portrait(
        npc.appearance or npc.name or "1person",
        seed=char_seed(room_id, npc.name),
    )
    if not result.get("url"):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=result.get("error", "生成头像失败"),
        )
    npc.avatar_url = result["url"]
    await session.commit()
    await session.refresh(npc)
    return NpcCardOut.model_validate(npc)


@router.put("/rooms/{room_id}/npcs/{npc_id}/active", response_model=NpcCardOut)
async def set_npc_active(
    room_id: int,
    npc_id: int,
    body: NpcActiveIn,
    user: CurrentUser,
    session: SessionDep,
) -> NpcCardOut:
    await _require_member(session, room_id, user.id)
    npc = await session.get(NpcCard, npc_id)
    if npc is None or npc.room_id != room_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="npc not found"
        )
    npc.active = body.active
    await session.commit()
    await session.refresh(npc)
    return NpcCardOut.model_validate(npc)


_AUDIO_DIR = Path(__file__).resolve().parent / "media" / "audio"


@router.post("/rooms/{room_id}/tts", response_model=TtsOut)
async def synth_tts(
    room_id: int, body: TtsIn, user: CurrentUser, session: SessionDep
) -> TtsOut:
    """合成一段台词音频（按 voice_id 走 VoxCPM 声音设计），返回 /media 下的 wav url。

    文件名按 (voice_id + 文本) 内容哈希 → 幂等：同台词同声音只合成一次，
    之后命中磁盘直接复用，刷新页面/重播都不再重复生成。
    """
    await _require_member(session, room_id, user.id)
    key = f"{(body.voice_id or '').strip()}\x00{body.text.strip()}"
    name = hashlib.sha1(key.encode("utf-8")).hexdigest() + ".wav"
    path = _AUDIO_DIR / name
    if not path.exists():
        audio = await voice_store.synth(body.text, body.voice_id)
        if not audio:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail="语音合成失败"
            )
        _AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        path.write_bytes(audio)
    return TtsOut(url=f"/media/audio/{name}")
