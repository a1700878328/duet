"""REST endpoints: auth + rooms + messages."""

import asyncio
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .brain import default_provider
from .char_gen import generate_character_options
from .config import settings
from .crud import ensure_room_scene, is_member, messages_after, room_to_out
from .db import get_session
from .imagegen.anima import char_seed
from .imagegen.portrait import generate_portrait
from .models import Message, NpcCard, Room, RoomMember, User, UserCharacterCard
from .npc_gen import generate_npcs
from .scene_logs import logs_from_meta, scene_key
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
    SceneLogEntryOut,
    SceneLogOut,
    TtsIn,
    TtsOut,
    UserCharacterCardIn,
    UserCharacterCardOut,
    UserOut,
)
from .security import (
    create_token,
    get_current_user,
    hash_password,
    verify_password,
)
from .stats import default_stats, initial_stats_from_card
from .voice import store as voice_store
from .world_presets import preset_npcs, scene_options, start_scene

router = APIRouter(prefix="/api")

SessionDep = Annotated[AsyncSession, Depends(get_session)]
CurrentUser = Annotated[User, Depends(get_current_user)]


async def _broadcast_cards_changed(room_id: int) -> None:
    # REST mutations happen outside the room WebSocket loop, so notify connected
    # clients explicitly when membership/cards change.
    from .ws import hub

    await hub.get(room_id).broadcast({"type": "cards_changed"})


async def _broadcast_lobby_changed() -> None:
    from .ws import notify_lobby_rooms_changed

    await notify_lobby_rooms_changed()


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
    user = await session.scalar(select(User).where(User.username == body.username))
    if user is None or not verify_password(user.password_hash, body.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid credentials",
        )
    return AuthOut(token=create_token(user.id), user=UserOut.model_validate(user))


@router.get("/me", response_model=MeOut)
async def me(user: CurrentUser) -> MeOut:
    return MeOut(user=UserOut.model_validate(user))


@router.get("/me/character-cards", response_model=list[UserCharacterCardOut])
async def list_my_character_cards(
    user: CurrentUser, session: SessionDep
) -> list[UserCharacterCardOut]:
    cards = (
        await session.scalars(
            select(UserCharacterCard)
            .where(UserCharacterCard.owner_id == user.id)
            .order_by(UserCharacterCard.updated_at.desc(), UserCharacterCard.id.desc())
        )
    ).all()
    return [UserCharacterCardOut.model_validate(c) for c in cards]


@router.post("/me/character-cards", response_model=UserCharacterCardOut)
async def create_my_character_card(
    body: UserCharacterCardIn, user: CurrentUser, session: SessionDep
) -> UserCharacterCardOut:
    card = UserCharacterCard(
        owner_id=user.id,
        name=body.name,
        persona=body.persona,
        appearance=body.appearance,
        voice_id=body.voice_id,
        voice_ref_url=body.voice_ref_url,
        voice_ref_text=body.voice_ref_text,
        avatar_url=body.avatar_url,
        source_world_card=body.source_world_card,
    )
    session.add(card)
    await session.commit()
    await session.refresh(card)
    return UserCharacterCardOut.model_validate(card)


@router.put("/me/character-cards/{card_id}", response_model=UserCharacterCardOut)
async def update_my_character_card(
    card_id: int,
    body: UserCharacterCardIn,
    user: CurrentUser,
    session: SessionDep,
) -> UserCharacterCardOut:
    card = await session.get(UserCharacterCard, card_id)
    if card is None or card.owner_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="character card not found"
        )
    card.name = body.name
    card.persona = body.persona
    card.appearance = body.appearance
    card.voice_id = body.voice_id
    card.voice_ref_url = body.voice_ref_url
    card.voice_ref_text = body.voice_ref_text
    card.avatar_url = body.avatar_url
    card.source_world_card = body.source_world_card
    await session.commit()
    await session.refresh(card)
    return UserCharacterCardOut.model_validate(card)


@router.delete("/me/character-cards/{card_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_character_card(
    card_id: int, user: CurrentUser, session: SessionDep
) -> None:
    card = await session.get(UserCharacterCard, card_id)
    if card is None or card.owner_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="character card not found"
        )
    await session.delete(card)
    await session.commit()


@router.get("/rooms", response_model=list[RoomOut])
async def list_rooms(user: CurrentUser, session: SessionDep) -> list[RoomOut]:
    # Public lobby for remote two-player testing: every signed-in user can see
    # available rooms, then joining still creates an explicit room membership.
    rooms = (await session.scalars(select(Room).order_by(Room.id.desc()))).all()
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
    await _broadcast_lobby_changed()
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
        await _broadcast_cards_changed(room_id)
        await _broadcast_lobby_changed()
    await session.refresh(room)
    return await room_to_out(session, room)


@router.delete("/rooms/{room_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_room(room_id: int, user: CurrentUser, session: SessionDep) -> None:
    """删除房间（仅房主）+ 连带清掉成员/消息/NPC 卡。

    用标量查 owner + Core delete（不加载 members 关系），避开"清空复合主键"的
    级联冲突。
    """
    owner_id = await session.scalar(select(Room.owner_id).where(Room.id == room_id))
    if owner_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="room not found"
        )
    if owner_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="只有房主能删除房间"
        )
    for model in (Message, NpcCard, RoomMember):
        await session.execute(delete(model).where(model.room_id == room_id))
    await session.execute(delete(Room).where(Room.id == room_id))
    await session.commit()
    await _broadcast_lobby_changed()


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


@router.get("/rooms/{room_id}/scene-log", response_model=SceneLogOut)
async def get_scene_log(
    room_id: int,
    user: CurrentUser,
    session: SessionDep,
) -> SceneLogOut:
    if not await is_member(session, room_id, user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="not a member"
        )
    room = await session.get(Room, room_id)
    if room is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="room not found"
        )
    current_scene = await ensure_room_scene(session, room)
    npc_scenes = (
        await session.scalars(
            select(NpcCard.scene).where(
                NpcCard.room_id == room_id,
                NpcCard.scene.is_not(None),
            )
        )
    ).all()
    logs = logs_from_meta(room.scenes_meta)
    scenes: list[str] = []
    for raw_scene in [
        current_scene,
        *scene_options(room.world_card),
        *[s or "" for s in npc_scenes],
        *logs.keys(),
    ]:
        name = scene_key(raw_scene)
        if name and name not in scenes:
            scenes.append(name)
    return SceneLogOut(
        current_scene=scene_key(current_scene),
        scenes=scenes,
        logs={
            scene: [SceneLogEntryOut(**entry) for entry in entries]
            for scene, entries in logs.items()
        },
    )


# ---- 角色卡（Phase A）：玩家卡 + NPC 卡 ----


async def _require_member(session: AsyncSession, room_id: int, user_id: int) -> None:
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
        voice_ref_url=m.voice_ref_url,
        voice_ref_text=m.voice_ref_text,
        avatar_url=m.avatar_url,
        stats=json.loads(m.stats) if m.stats else default_stats(),
    )


_AUDIO_DIR = Path(__file__).resolve().parent / "media" / "audio"


def _audio_media_path(url: str | None) -> Path | None:
    if not url or not url.startswith("/media/audio/"):
        return None
    name = Path(url).name
    if not name:
        return None
    return _AUDIO_DIR / name


async def _voice_design_for_card(
    *, name: str, persona: str | None, appearance: str | None
) -> str:
    brain = default_provider()
    prompt = (
        "你是角色配音导演。根据角色卡生成一句 ElevenLabs Voice Design 描述，"
        "只输出一句话，不要解释。整体风格必须像原创日本动画/视觉小说里的声优配音："
        "音高变化有旋律感，情绪表演鲜明，停顿干净，吐字清楚。"
        "年轻女性/可爱角色要清亮、软萌、甜而不腻、尾音轻快，有轻微撒娇感；"
        "冷淡角色也要有动画感和反差可爱；男性或年长角色保持年龄但仍偏动画配音质感。"
        "格式包含：性别/年龄感、音色/音高、语速/节奏、情绪气质、"
        "声优式表演关键词。声音必须贴合角色人设和外貌；不要写台词；"
        "不要模仿名人或真实个人；不要超过 160 个中文字符。\n"
        f"角色名：{name}\n"
        f"人设：{persona or '（无）'}\n"
        f"外貌：{appearance or '（无）'}"
    )
    try:
        brain.temperature = 0.4
        brain.max_tokens = max(getattr(brain, "max_tokens", 800), 800)
    except Exception:
        pass
    raw = await brain.complete(
        [
            {"role": "system", "content": "只输出声音设计描述。"},
            {"role": "user", "content": prompt},
        ]
    )
    return (raw or "").strip().strip("\"'“”")[:200]


async def _voice_reference_text(
    name: str, persona: str | None, appearance: str | None
) -> str:
    """Generate a character-specific audition line for voice design/cloning."""
    brain = default_provider()
    prompt = (
        "为这个角色写一段用于语音设计试听的中文台词。要求："
        "第一人称，像角色本人开口；必须体现职业/身份、性格、说话风格和与玩家的关系；"
        "台词要方便生成日本动漫/视觉小说声优感：有自然语气词、情绪起伏、短停顿、"
        "轻微口癖或尾音；可爱或反差可爱优先，但不能违背角色设定；"
        "不要旁白、动作描写、括号、引号；不要露骨色情；100 到 180 个中文字符。\n"
        f"角色名：{name}\n"
        f"人设：{persona or '（无）'}\n"
        f"外貌：{appearance or '（无）'}"
    )
    try:
        brain.temperature = 0.65
        brain.max_tokens = max(getattr(brain, "max_tokens", 800), 900)
        raw = await brain.complete(
            [
                {"role": "system", "content": "只输出角色试听台词。"},
                {"role": "user", "content": prompt},
            ]
        )
    except Exception:
        raw = ""
    line = re.sub(r"\s+", "", (raw or "").strip().strip("\"'“”"))
    if len(line) >= 80:
        return line[:220]
    tone = "我会记住每一笔账，也会认真回应你的每一句话。"
    if persona and any(w in persona for w in ("冷", "寡言", "沉默")):
        tone = "我会安静地看清局势，然后在必要的时候开口。"
    elif persona and any(w in persona for w in ("活泼", "开朗", "热情")):
        tone = "今天一定会很有意思，我已经有点期待接下来的故事了。"
    elif persona and any(w in persona for w in ("商人", "借贷", "高利贷", "债")):
        tone = (
            "钱可以先拿去用，利息嘛，我们慢慢算清楚。别紧张，我最喜欢守信用的客人了。"
        )
    return f"你好，我是{name}。{tone}"


def _write_audio_bytes(
    *, room_id: int, owner_key: str, name: str, voice_id: str | None, audio: bytes
) -> str:
    _AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    key = "\x00".join(
        [str(room_id), owner_key, name, voice_id or "", os.urandom(8).hex()]
    )
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
    filename = f"ref_{digest}.{voice_store.extension}"
    path = _AUDIO_DIR / filename
    path.write_bytes(audio)
    return f"/media/audio/{filename}"


async def _write_voice_reference(
    *, room_id: int, owner_key: str, name: str, voice_id: str | None, ref_text: str
) -> str:
    audio = await voice_store.synth(ref_text, voice_id)
    if not audio:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=("参考语音生成失败，请检查 Eleven/Fish API key、voice_id 或配额"),
        )
    return _write_audio_bytes(
        room_id=room_id, owner_key=owner_key, name=name, voice_id=voice_id, audio=audio
    )


async def _design_and_write_voice(
    *,
    room_id: int,
    owner_key: str,
    name: str,
    persona: str | None,
    appearance: str | None,
    voice_id: str | None,
) -> tuple[str, str, str]:
    design = await _voice_design_for_card(
        name=name, persona=persona, appearance=appearance
    )
    if not design:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="生成音色描述失败"
        )
    ref_text = await _voice_reference_text(name, persona, appearance)
    designed = await voice_store.design_voice(
        name=name, voice_description=design, reference_text=ref_text
    )
    if designed:
        ref_url = _write_audio_bytes(
            room_id=room_id,
            owner_key=owner_key,
            name=name,
            voice_id=designed.voice_id,
            audio=designed.reference_audio,
        )
        return designed.voice_id, ref_url, designed.reference_text
    ref_url = await _write_voice_reference(
        room_id=room_id,
        owner_key=owner_key,
        name=name,
        voice_id=design,
        ref_text=ref_text,
    )
    return design, ref_url, ref_text


async def _refresh_member_voice_reference(room_id: int, member: RoomMember) -> None:
    voice_id, ref_url, ref_text = await _design_and_write_voice(
        room_id=room_id,
        owner_key=f"member:{member.user_id}",
        name=member.character_name,
        persona=member.persona,
        appearance=member.appearance,
        voice_id=member.voice_id,
    )
    member.voice_id = voice_id
    member.voice_ref_url = ref_url
    member.voice_ref_text = ref_text


async def _refresh_npc_voice_reference(room_id: int, npc: NpcCard) -> None:
    voice_id, ref_url, ref_text = await _design_and_write_voice(
        room_id=room_id,
        owner_key=f"npc:{npc.id}",
        name=npc.name,
        persona=npc.persona,
        appearance=npc.appearance,
        voice_id=npc.voice_id,
    )
    npc.voice_id = voice_id
    npc.voice_ref_url = ref_url
    npc.voice_ref_text = ref_text


async def list_cards(room_id: int, user: CurrentUser, session: SessionDep) -> CardsOut:
    await _require_member(session, room_id, user.id)
    members = (
        await session.scalars(select(RoomMember).where(RoomMember.room_id == room_id))
    ).all()
    npcs = (
        await session.scalars(select(NpcCard).where(NpcCard.room_id == room_id))
    ).all()
    god = NpcCardOut(
        id=0,
        name="上帝",
        persona=(
            "上帝视角的暗中导演。只接受玩家私聊，不作为普通 NPC 公开接话；"
            "私聊会强制影响当前场景 NPC 的行动与局势。"
        ),
        appearance=None,
        voice_id=None,
        voice_ref_url=None,
        voice_ref_text=None,
        avatar_url=None,
        active=True,
        scene=None,
        discovered="可私聊：把想强制发生的事告诉上帝。",
        created_by_ai=True,
    )
    return CardsOut(
        players=[_member_card(m, m.user.display_name) for m in members],
        npcs=[god, *[NpcCardOut.model_validate(n) for n in npcs]],
    )


@router.get("/rooms/{room_id}/preset-characters", response_model=list[NpcCardOut])
async def preset_characters(
    room_id: int, user: CurrentUser, session: SessionDep
) -> list[NpcCardOut]:
    """World-card important NPCs that players may choose as their PC."""
    await _require_member(session, room_id, user.id)
    room = await session.get(Room, room_id)
    if room is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="room not found"
        )
    names = {p["name"] for p in preset_npcs(room.world_card)}
    if not names:
        return []
    npcs = (
        await session.scalars(
            select(NpcCard).where(
                NpcCard.room_id == room_id,
                NpcCard.name.in_(names),
                NpcCard.active.is_(True),
            )
        )
    ).all()
    return [NpcCardOut.model_validate(n) for n in npcs]


_PROTAGONIST_CARDS: dict[str, CharDraftOut] = {
    "ksim": CharDraftOut(
        name="瑟琳娜",
        persona=(
            "《女骑士模拟器》的原作主角。出身没落贵族家庭的年轻女骑士，为了复兴家族荣耀"
            "而成为冒险者。银白短发、冰蓝眼眸，身穿轻便板甲。性格认真固执、荣誉感强，"
            "但命运——和这个世界的黑暗——会一步步将她推向堕落。"
            "初始自带「落难贵族」buff：消费标准高，起点资金多。"
        ),
        appearance=(
            "1girl, short silver-white hair, blue eyes, fair skin, "
            "worn steel breastplate, red cape, riding boots, "
            "noble bearing but tired expression, guild hall background"
        ),
        voice_id="年轻女性，清澈明亮，带着贵族式的克制和一丝疲惫",
    ),
}


@router.get("/rooms/{room_id}/protagonist", response_model=CharDraftOut | None)
async def get_protagonist(
    room_id: int, user: CurrentUser, session: SessionDep
) -> CharDraftOut | None:
    """Return the world card's canonical protagonist card, if one exists."""
    await _require_member(session, room_id, user.id)
    room = await session.get(Room, room_id)
    if room is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="room not found"
        )
    return _PROTAGONIST_CARDS.get(room.world_card or "")


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
        if body.voice_id != member.voice_id:
            member.voice_ref_url = None
            member.voice_ref_text = None
        member.voice_id = body.voice_id
    if body.voice_ref_url is not None:
        member.voice_ref_url = body.voice_ref_url
    if body.voice_ref_text is not None:
        member.voice_ref_text = body.voice_ref_text
    if body.avatar_url is not None:
        member.avatar_url = body.avatar_url
    if body.reset_stats or member.stats is None:
        member.stats = json.dumps(
            initial_stats_from_card(member.character_name, member.persona),
            ensure_ascii=False,
        )
    await session.commit()
    await session.refresh(member)
    await _broadcast_cards_changed(room_id)
    return _member_card(member, user.display_name)


@router.post("/rooms/{room_id}/me-card/voice", response_model=MemberOut)
async def generate_my_voice(
    room_id: int, user: CurrentUser, session: SessionDep
) -> MemberOut:
    """Generate a role voice design and auditionable reference."""
    if not settings.voice_generation_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="语音生成已临时关闭",
        )
    member = await session.scalar(
        select(RoomMember).where(
            RoomMember.room_id == room_id, RoomMember.user_id == user.id
        )
    )
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="not a member"
        )
    await _refresh_member_voice_reference(room_id, member)
    await session.commit()
    await session.refresh(member)
    await _broadcast_cards_changed(room_id)
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
    try:
        drafts = await generate_character_options(
            room.world_card, body.hint, body.count
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI 发散角色失败，请稍后再试或直接自己描述",
        ) from exc
    if not drafts:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI 没有生成可用角色，请再试一次或直接自己描述",
        )

    async def draft_out(d: dict) -> CharDraftOut:
        avatar_url: str | None = None
        appearance = d.get("appearance")
        if appearance and settings.media_generation_enabled:
            try:
                result = await generate_portrait(
                    appearance,
                    name=d.get("name"),
                    persona=d.get("persona"),
                    nsfw=room.world_card == "ksim",
                    seed=char_seed(room_id, d["name"]),
                )
                avatar_url = result.get("url")
            except Exception:
                avatar_url = None
        return CharDraftOut(
            name=d["name"],
            persona=d.get("persona", ""),
            appearance=appearance,
            voice_id=d.get("voice_id"),
            avatar_url=avatar_url,
        )

    out = await asyncio.gather(*(draft_out(d) for d in drafts))
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
    await _broadcast_cards_changed(room_id)
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
        await session.scalars(select(NpcCard.name).where(NpcCard.room_id == room_id))
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
    for npc in created:
        if settings.media_generation_enabled and npc.appearance:
            try:
                result = await generate_portrait(
                    npc.appearance or npc.name or "1person",
                    name=npc.name,
                    persona=npc.persona,
                    nsfw=room.world_card == "ksim",
                    seed=char_seed(room_id, npc.name),
                )
                if result.get("url"):
                    npc.avatar_url = result["url"]
            except Exception:
                pass
        if settings.voice_generation_enabled:
            try:
                await _refresh_npc_voice_reference(room_id, npc)
            except Exception:
                pass
    await session.commit()
    for npc in created:
        await session.refresh(npc)
    await _broadcast_cards_changed(room_id)
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
    if body.voice_id != npc.voice_id:
        npc.voice_ref_url = None
        npc.voice_ref_text = None
    npc.voice_id = body.voice_id
    await session.commit()
    await session.refresh(npc)
    await _broadcast_cards_changed(room_id)
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
        await _broadcast_cards_changed(room_id)
    return {"status": "ok"}


# ---- 立绘/头像 + NPC 启停（Phase E） ----


@router.post("/rooms/{room_id}/me-card/avatar", response_model=MemberOut)
async def generate_my_avatar(
    room_id: int, user: CurrentUser, session: SessionDep
) -> MemberOut:
    if not settings.media_generation_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="生图已临时关闭",
        )
    member = await session.scalar(
        select(RoomMember).where(
            RoomMember.room_id == room_id, RoomMember.user_id == user.id
        )
    )
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="not a member"
        )
    _room_avatar = await session.get(Room, room_id)
    _nsfw_avatar = _room_avatar is not None and _room_avatar.world_card == "ksim"
    result = await generate_portrait(
        member.appearance or member.character_name or "1person",
        name=member.character_name,
        persona=member.persona,
        nsfw=_nsfw_avatar,
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
    await _broadcast_cards_changed(room_id)
    return _member_card(member, user.display_name)


@router.post("/rooms/{room_id}/npcs/{npc_id}/avatar", response_model=NpcCardOut)
async def generate_npc_avatar(
    room_id: int, npc_id: int, user: CurrentUser, session: SessionDep
) -> NpcCardOut:
    if not settings.media_generation_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="生图已临时关闭",
        )
    await _require_member(session, room_id, user.id)
    npc = await session.get(NpcCard, npc_id)
    if npc is None or npc.room_id != room_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="npc not found"
        )
    _room_npca = await session.get(Room, room_id)
    _nsfw_npca = _room_npca is not None and _room_npca.world_card == "ksim"
    result = await generate_portrait(
        npc.appearance or npc.name or "1person",
        name=npc.name,
        persona=npc.persona,
        nsfw=_nsfw_npca,
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
    await _broadcast_cards_changed(room_id)
    return NpcCardOut.model_validate(npc)


@router.post("/rooms/{room_id}/npcs/{npc_id}/voice", response_model=NpcCardOut)
async def generate_npc_voice(
    room_id: int, npc_id: int, user: CurrentUser, session: SessionDep
) -> NpcCardOut:
    if not settings.voice_generation_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="语音生成已临时关闭",
        )
    await _require_member(session, room_id, user.id)
    npc = await session.get(NpcCard, npc_id)
    if npc is None or npc.room_id != room_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="npc not found"
        )
    await _refresh_npc_voice_reference(room_id, npc)
    await session.commit()
    await session.refresh(npc)
    await _broadcast_cards_changed(room_id)
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
    await _broadcast_cards_changed(room_id)
    return NpcCardOut.model_validate(npc)


@router.post("/rooms/{room_id}/tts", response_model=TtsOut)
async def synth_tts(
    room_id: int, body: TtsIn, user: CurrentUser, session: SessionDep
) -> TtsOut:
    """合成一段台词音频（按 voice_id/provider 走语音服务），返回 /media url。

    文件名按 (voice_id + 文本) 内容哈希 → 幂等：同台词同声音只合成一次，
    之后命中磁盘直接复用，刷新页面/重播都不再重复生成。
    """
    if not settings.voice_generation_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="语音合成已临时关闭",
        )
    await _require_member(session, room_id, user.id)
    key = (
        f"{(body.voice_id or '').strip()}\x00{body.voice_ref_url or ''}"
        f"\x00{body.voice_ref_text or ''}\x00{body.text.strip()}"
    )
    if body.regenerate:
        key = f"{key}\x00regen\x00{hashlib.sha1(os.urandom(16)).hexdigest()}"
    ext = voice_store.extension
    name = hashlib.sha1(key.encode("utf-8")).hexdigest() + f".{ext}"
    path = _AUDIO_DIR / name
    if not path.exists():
        audio = await voice_store.synth(
            body.text,
            body.voice_id,
            reference_audio_path=_audio_media_path(body.voice_ref_url),
            reference_text=body.voice_ref_text,
        )
        if not audio:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail="语音合成失败"
            )
        _AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        path.write_bytes(audio)
    return TtsOut(url=f"/media/audio/{name}")
