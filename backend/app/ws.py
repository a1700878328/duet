"""WebSocket room hub + per-room async coordinator.

One coordinator per active room (kept in an in-memory dict). The coordinator
holds a lock that serialises seq allocation + persistence, and an `ai_busy`
flag so only one AI turn runs at a time.
"""

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from .brain import BrainProvider, default_provider
from .config import settings
from .crud import member_label, messages_after, next_seq
from .db import SessionFactory
from .director import direct_beat
from .imagegen.scene_prompt import build_scene_prompt
from .imagegen.service import generate_raw_duo, generate_raw_single
from .lore import store as lore_store
from .memory import store as memory_store
from .models import Message, NpcCard, Room, RoomMember, User
from .prompts import (
    build_npc_system_prompt,
    build_system_prompt,
    history_to_messages,
)
from .schemas import MessageOut
from .security import user_from_token
from .speaker_guard import sanitize

router = APIRouter()


class RoomCoordinator:
    """Per-room state: connected sockets + serialisation primitives."""

    def __init__(self, room_id: int) -> None:
        self.room_id = room_id
        self.sockets: dict[WebSocket, User] = {}
        self.lock = asyncio.Lock()
        self.ai_busy = False
        self.image_busy = False

    async def broadcast(self, payload: dict[str, Any]) -> None:
        stale: list[WebSocket] = []
        for ws in list(self.sockets):
            try:
                await ws.send_json(payload)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self.sockets.pop(ws, None)


class Hub:
    def __init__(self) -> None:
        self._rooms: dict[int, RoomCoordinator] = {}

    def get(self, room_id: int) -> RoomCoordinator:
        coord = self._rooms.get(room_id)
        if coord is None:
            coord = RoomCoordinator(room_id)
            self._rooms[room_id] = coord
        return coord

    def drop_if_empty(self, room_id: int) -> None:
        coord = self._rooms.get(room_id)
        if coord is not None and not coord.sockets:
            self._rooms.pop(room_id, None)


hub = Hub()
brain: BrainProvider = default_provider()


def _msg_payload(msg: Message) -> dict[str, Any]:
    return MessageOut.model_validate(msg).model_dump(mode="json")


async def _persist_message(
    *,
    room_id: int,
    author_type: str,
    speaker_label: str,
    content: str,
    author_user_id: int | None,
) -> Message:
    async with SessionFactory() as session:
        seq = await next_seq(session, room_id)
        msg = Message(
            room_id=room_id,
            seq=seq,
            author_type=author_type,
            author_user_id=author_user_id,
            speaker_label=speaker_label,
            content=content,
        )
        session.add(msg)
        await session.commit()
        await session.refresh(msg)
        return msg


NARRATOR_FALLBACK = "[旁白]: （场景短暂沉默，发言权留给在场的人。）"


def _chunks(text: str, size: int = 12):
    for i in range(0, len(text), size):
        yield text[i : i + size]


async def _generate_guarded(
    messages: list[dict[str, str]], forbidden: list[str]
) -> tuple[str, dict[str, Any]]:
    """生成不冒充真人角色的 AI 回复。

    fail-closed：先 sanitize；若曾以真人角色名开口，附纠正指令重生成一次再 sanitize。
    """
    raw = (await brain.complete(messages)).strip()
    clean, violated = sanitize(raw, forbidden)
    info: dict[str, Any] = {
        "violated_first": violated,
        "regenerated": False,
        "violated_final": False,
    }
    if violated or not clean:
        info["regenerated"] = True
        names = "、".join(forbidden) or "（无）"
        corrective = messages + [
            {
                "role": "system",
                "content": (
                    "纠正：你刚才以真人玩家的角色名开口了，这是被禁止的。"
                    "请重写：只能扮演 NPC 或「旁白」，每段以 [NPC名]: 或 [旁白]: 开头，"
                    f"绝不能以这些真人角色名作为说话者：{names}。把发言权留给真人玩家。"
                ),
            }
        ]
        raw2 = (await brain.complete(corrective)).strip()
        clean2, violated2 = sanitize(raw2, forbidden)
        if clean2:
            clean, info["violated_final"] = clean2, violated2
    if not clean:
        clean = NARRATOR_FALLBACK
    return clean, info


async def _run_ai_turn(
    coord: RoomCoordinator, npc: NpcCard | None = None
) -> None:
    turn_id = uuid.uuid4().hex
    async with SessionFactory() as session:
        room = await session.get(Room, coord.room_id)
        if room is None:
            return
        members = list(
            await session.scalars(
                select(RoomMember).where(RoomMember.room_id == coord.room_id)
            )
        )
        history = await messages_after(session, coord.room_id, 0, limit=200)
        world_card = room.world_card
        player_names = [m.character_name for m in members if m.character_name]
        if npc is not None:
            other_npc_names = list(
                await session.scalars(
                    select(NpcCard.name).where(
                        NpcCard.room_id == coord.room_id, NpcCard.id != npc.id
                    )
                )
            )
            system_prompt = build_npc_system_prompt(
                room, members, npc, other_npc_names
            )
            forbidden = player_names + other_npc_names
            ai_label = npc.name
        else:
            system_prompt = build_system_prompt(room, members)
            forbidden = player_names
            ai_label = "AI"

    messages = history_to_messages(
        system_prompt, history, window=settings.history_window
    )
    scope = f"room_{coord.room_id}"
    recent = " ".join(
        m.content for m in history[-5:] if m.author_type == "user"
    )[:600].strip()

    # 长期记忆召回：注入与当前对话相关的历史事实（剧情/角色/关系）。
    if recent:
        recall = await asyncio.to_thread(memory_store.search, scope, recent, 4)
        if recall:
            messages.insert(1, {"role": "system", "content": recall})
            print(f"[MEM] room={coord.room_id} 召回 {len(recall)}c", flush=True)

    # 世界卡 lore RAG：按最近对话检索相关设定片段，注入为附加 system 消息。
    if world_card == "ksim" and recent:
        lore = await asyncio.to_thread(lore_store.search_formatted, recent, 4)
        if lore:
            messages.insert(1, {"role": "system", "content": lore})
            print(f"[LORE] room={coord.room_id} +{len(lore)}c", flush=True)

    finish_reason = "stop"
    guard: dict[str, Any] = {}
    try:
        content, guard = await _generate_guarded(messages, forbidden)
    except Exception as exc:  # noqa: BLE001 — surface as a room error, keep serving
        finish_reason = "error"
        content = ""
        await coord.broadcast(
            {"type": "error", "code": "ai_error", "detail": str(exc)}
        )

    if not content:
        content = "（……）"
        if finish_reason == "stop":
            finish_reason = "empty"

    if guard.get("violated_first"):
        print(
            f"[GUARD] room={coord.room_id} 冒充真人角色已拦截 "
            f"regenerated={guard.get('regenerated')} "
            f"violated_final={guard.get('violated_final')}",
            flush=True,
        )

    # 缓冲→守卫→重流：客户端永远看不到被冒充的文本。先落库拿真 seq 再流。
    msg = await _persist_message(
        room_id=coord.room_id,
        author_type="ai",
        speaker_label=ai_label,
        content=content,
        author_user_id=None,
    )
    for chunk in _chunks(content):
        await coord.broadcast(
            {"type": "ai_delta", "turn_id": turn_id, "seq": msg.seq, "delta": chunk}
        )
        await asyncio.sleep(0.01)
    await coord.broadcast(
        {
            "type": "ai_done",
            "turn_id": turn_id,
            "seq": msg.seq,
            "content": content,
            "finish_reason": finish_reason,
        }
    )

    # 后台写入长期记忆（best-effort，不挡主路）：让 mem0 从本回合抽取耐久事实。
    last_user = next(
        (m.content for m in reversed(history) if m.author_type == "user"), ""
    )
    if last_user and finish_reason in {"stop", "empty"}:
        asyncio.create_task(
            asyncio.to_thread(memory_store.remember, scope, last_user, content)
        )


async def _handle_say(coord: RoomCoordinator, user: User, content: str) -> None:
    content = content.strip()
    if not content:
        return
    async with SessionFactory() as session:
        label = await member_label(session, coord.room_id, user.id)
    speaker = label or user.display_name
    msg = await _persist_message(
        room_id=coord.room_id,
        author_type="user",
        speaker_label=speaker,
        content=content,
        author_user_id=user.id,
    )
    await coord.broadcast({"type": "message", "message": _msg_payload(msg)})


async def _handle_advance(
    coord: RoomCoordinator, npc: NpcCard | None = None
) -> None:
    if coord.ai_busy:
        await coord.broadcast(
            {
                "type": "error",
                "code": "ai_busy",
                "detail": "an AI turn is already in flight",
            }
        )
        return
    coord.ai_busy = True
    try:
        await _run_ai_turn(coord, npc)
    finally:
        coord.ai_busy = False


async def _handle_director_beat(
    coord: RoomCoordinator, *, force_timeskip: bool = False
) -> None:
    """导演拍：决定哪些 NPC 反应 + 是否推进叙事时间，再逐个让 NPC 发言。"""
    if coord.ai_busy:
        await coord.broadcast(
            {"type": "error", "code": "ai_busy", "detail": "上一拍还没演完"}
        )
        return
    coord.ai_busy = True
    try:
        async with SessionFactory() as session:
            room = await session.get(Room, coord.room_id)
            if room is None:
                return
            members = list(
                await session.scalars(
                    select(RoomMember).where(RoomMember.room_id == coord.room_id)
                )
            )
            npcs = list(
                await session.scalars(
                    select(NpcCard).where(NpcCard.room_id == coord.room_id)
                )
            )
            history = await messages_after(session, coord.room_id, 0, limit=200)
            world_card = room.world_card

        if not npcs:
            await _run_ai_turn(coord, None)
            return

        recent = "\n".join(
            f"{m.speaker_label}: {m.content}"
            for m in history[-8:]
            if m.author_type in {"user", "ai"}
        )
        plan = await direct_beat(
            world_card, members, npcs, recent, force_timeskip=force_timeskip
        )

        if plan.get("time_jump"):
            summary = plan["time_jump"]
            msg = await _persist_message(
                room_id=coord.room_id,
                author_type="ai",
                speaker_label="旁白",
                content=f"⏳ {summary}",
                author_user_id=None,
            )
            await coord.broadcast({"type": "message", "message": _msg_payload(msg)})
            asyncio.create_task(
                asyncio.to_thread(
                    memory_store.remember,
                    f"room_{coord.room_id}",
                    "[时间推进]",
                    summary,
                )
            )

        by_id = {n.id: n for n in npcs}
        acted = False
        for npc_id in plan.get("acts", []):
            npc = by_id.get(npc_id)
            if npc is not None:
                await _run_ai_turn(coord, npc)
                acted = True

        if not acted and not plan.get("time_jump"):
            await _run_ai_turn(coord, None)
    finally:
        coord.ai_busy = False


async def _handle_image(
    coord: RoomCoordinator, user: User, data: dict[str, Any]
) -> None:
    """生图房间动作：最近剧情 + 外貌卡 → 合成 prompt → raw 生成 → 广播图消息。

    ~40s，跑成后台任务，不阻塞聊天；image_busy 防并发。
    """
    if coord.image_busy:
        await coord.broadcast(
            {"type": "error", "code": "image_busy", "detail": "上一张图还在生成"}
        )
        return
    coord.image_busy = True
    nsfw = bool(data.get("nsfw"))
    await coord.broadcast(
        {
            "type": "image_pending",
            "user_id": user.id,
            "display_name": user.display_name,
        }
    )
    try:
        async with SessionFactory() as session:
            members = list(
                await session.scalars(
                    select(RoomMember).where(RoomMember.room_id == coord.room_id)
                )
            )
            history = await messages_after(session, coord.room_id, 0, limit=200)
        scene_text = (
            "\n".join(
                f"{m.speaker_label}: {m.content}"
                for m in history[-6:]
                if m.author_type in {"user", "ai"}
            )
            or "一个角色扮演场景"
        )
        appearances = [(m.appearance or m.character_name) for m in members][:2]
        two_person = len(members) >= 2
        try:
            prompt = await build_scene_prompt(
                scene_text, appearances, nsfw=nsfw, two_person=two_person
            )
            if two_person:
                res = await generate_raw_duo(
                    prompt.get("global", ""),
                    prompt.get("left", ""),
                    prompt.get("right", ""),
                    prompt.get("negative", ""),
                    nsfw=nsfw,
                )
            else:
                res = await generate_raw_single(
                    prompt.get("positive", ""),
                    prompt.get("negative", ""),
                    nsfw=nsfw,
                )
        except Exception as exc:  # noqa: BLE001 — surface as room error
            res = {"error": str(exc)}

        url = res.get("url")
        if url:
            msg = await _persist_message(
                room_id=coord.room_id,
                author_type="image",
                speaker_label="场景图",
                content=url,
                author_user_id=user.id,
            )
            await coord.broadcast({"type": "message", "message": _msg_payload(msg)})
        else:
            await coord.broadcast(
                {
                    "type": "error",
                    "code": "image_failed",
                    "detail": res.get("error", "生成失败"),
                }
            )
    finally:
        coord.image_busy = False


@router.websocket("/ws/rooms/{room_id}")
async def room_ws(websocket: WebSocket, room_id: int) -> None:
    token = websocket.query_params.get("token", "")
    async with SessionFactory() as session:
        user = await user_from_token(session, token) if token else None
        if user is None:
            await websocket.close(code=4401)
            return
        member = await session.scalar(
            select(RoomMember).where(
                RoomMember.room_id == room_id,
                RoomMember.user_id == user.id,
            )
        )
        if member is None:
            await websocket.close(code=4403)
            return
        history = await messages_after(session, room_id, 0, limit=200)

    await websocket.accept()
    coord = hub.get(room_id)
    coord.sockets[websocket] = user

    await websocket.send_json(
        {"type": "history", "messages": [_msg_payload(m) for m in history]}
    )
    await coord.broadcast(
        {
            "type": "presence",
            "user_id": user.id,
            "display_name": user.display_name,
            "online": True,
        }
    )

    try:
        while True:
            data = await websocket.receive_json()
            kind = data.get("type")
            if kind == "say":
                async with coord.lock:
                    await _handle_say(coord, user, data.get("content", ""))
            elif kind == "advance":
                npc_id = data.get("npc_id")
                if npc_id is not None:
                    npc = None
                    try:
                        async with SessionFactory() as session:
                            cand = await session.get(NpcCard, int(npc_id))
                        if cand is not None and cand.room_id == room_id:
                            npc = cand
                    except (ValueError, TypeError):
                        npc = None
                    await _handle_advance(coord, npc)
                else:
                    # 无指定 NPC → 导演自动调度本拍谁反应。
                    await _handle_director_beat(coord)
            elif kind == "timeskip":
                await _handle_director_beat(coord, force_timeskip=True)
            elif kind == "image":
                asyncio.create_task(_handle_image(coord, user, data))
            elif kind == "typing":
                await coord.broadcast(
                    {
                        "type": "typing",
                        "user_id": user.id,
                        "display_name": user.display_name,
                        "is_typing": bool(data.get("is_typing")),
                    }
                )
            else:
                await websocket.send_json(
                    {
                        "type": "error",
                        "code": "bad_type",
                        "detail": f"unknown message type: {kind!r}",
                    }
                )
    except WebSocketDisconnect:
        pass
    finally:
        coord.sockets.pop(websocket, None)
        await coord.broadcast(
            {
                "type": "presence",
                "user_id": user.id,
                "display_name": user.display_name,
                "online": False,
            }
        )
        hub.drop_if_empty(room_id)
