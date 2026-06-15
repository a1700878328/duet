"""WebSocket room hub + per-room async coordinator.

One coordinator per active room (kept in an in-memory dict). The coordinator
holds a lock that serialises seq allocation + persistence, and an `ai_busy`
flag so only one AI turn runs at a time.
"""

import asyncio
import hashlib
import json
import re
import uuid
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from .brain import BrainProvider, default_provider
from .config import settings
from .crud import (
    effective_current_scene,
    ensure_room_scene,
    member_label,
    messages_after,
    next_seq,
)
from .db import SessionFactory
from .director import judge_world_beat
from .enrich import enrich_npc
from .imagegen.anima import char_seed, generate_anima
from .imagegen.media import MEDIA_DIR as IMAGE_MEDIA_DIR
from .imagegen.scene_prompt import build_scene_prompt
from .json_utils import parse_json_object
from .lore import store as lore_store
from .memory import store as memory_store
from .models import Message, NpcCard, Room, RoomMember, User
from .npc_decision import judge_npc_impulse
from .prompts import (
    build_npc_system_prompt,
    build_system_prompt,
    history_to_messages,
)
from .scene_logs import (
    append_scene_log,
    logs_from_meta,
    scene_key,
)
from .scene_logs import (
    load_scene_meta as load_scene_meta_json,
)
from .scene_movement import (
    infer_npc_moves_from_text,
    parse_scene_simulation_output,
)
from .schemas import MessageOut
from .security import user_from_token
from .speaker_guard import sanitize
from .stats import (
    apply_delta,
    check_ending,
    default_stats,
    infer_payment_total,
    judge_stat_delta,
    monthend_settle,
    tick_imprisonment,
)
from .tasks import (
    COMPLETED_TASKS_KEY,
    CURRENT_TASK_KEY,
    TASK_OFFERS_KEY,
    current_task_from_meta,
    extract_task_directives,
    normalize_task_offer,
    task_offers_from_meta,
    task_state_from_meta,
)
from .time_events import pick_event_encounter_npc, roll_time_event, tick_cooldowns
from .timeflow import (
    TIME_PHASES,
    advance_room_time,
    room_time,
    split_time_index,
    time_label,
)
from .world_presets import scene_options

router = APIRouter()


class RoomCoordinator:
    """Per-room state: connected sockets + serialisation primitives."""

    def __init__(self, room_id: int) -> None:
        self.room_id = room_id
        self.sockets: dict[WebSocket, User] = {}
        self.lock = asyncio.Lock()
        self.ai_busy = False
        self.image_busy = False
        # 节流：每 N 拍后把"玩家逐渐了解到的 NPC 信息"刷新一次。
        self.beats_since_enrich = 0

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

_GIVE_RE = re.compile(
    r"\[\[\s*(?:给予|给玩家|交付|赠予)\s*:?\s*(.*?)\s*\]\]", re.DOTALL
)


class LobbyHub:
    def __init__(self) -> None:
        self.sockets: set[WebSocket] = set()

    async def broadcast(self, payload: dict[str, Any]) -> None:
        stale: list[WebSocket] = []
        for ws in list(self.sockets):
            try:
                await ws.send_json(payload)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self.sockets.discard(ws)


lobby_hub = LobbyHub()


async def notify_lobby_rooms_changed() -> None:
    await lobby_hub.broadcast({"type": "rooms_changed"})


def _msg_payload(msg: Message) -> dict[str, Any]:
    return MessageOut.model_validate(msg).model_dump(mode="json")


async def _set_ai_busy(coord: RoomCoordinator, busy: bool) -> None:
    coord.ai_busy = busy
    await coord.broadcast({"type": "ai_status", "busy": busy})


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


def _extract_speaker_label(content: str, fallback: str) -> tuple[str, str]:
    """Promote a leading [speaker]: prefix into the persisted speaker label."""
    text = (content or "").strip()
    match = re.match(r"^\s*\[([^\]\n]{1,24})\]\s*[:：]\s*(.*)$", text, re.DOTALL)
    if not match:
        return fallback, text
    label = match.group(1).strip()
    body = match.group(2).strip()
    if not label or label.upper() in {"NPC", "AI"}:
        return fallback, body or text
    return label, body or text


def _norm_label(label: str | None) -> str:
    return (label or "").strip().lower().replace(" ", "").replace("　", "")


def _leading_speaker_label(content: str) -> str | None:
    match = re.match(r"^\s*\[([^\]\n]{1,24})\]\s*[:：]", content or "", re.DOTALL)
    return match.group(1).strip() if match else None


def _has_wrong_required_speaker(content: str, required_label: str | None) -> bool:
    """For single-NPC turns, any explicit non-target label is a hard violation."""
    if not required_label:
        return False
    label = _leading_speaker_label(content)
    return label is not None and _norm_label(label) != _norm_label(required_label)


def _narration_body(content: str | None) -> str:
    """Normalize model-written narration into timeline text without a speaker prefix."""
    text = (content or "").strip()
    match = re.match(r"^\s*\[([^\]\n]{1,24})\]\s*[:：]\s*(.*)$", text, re.DOTALL)
    if not match:
        return text
    label = match.group(1).strip()
    if label != "旁白":
        return ""
    return match.group(2).strip()


def _world_label(world_card: str | None) -> str:
    return "《女骑士模拟器》" if world_card == "ksim" else (world_card or "通用奇幻")


async def _world_lore_block(world_card: str | None, query: str, k: int = 4) -> str:
    """Retrieve compact world-card lore; empty string if unavailable."""
    if world_card != "ksim":
        return ""
    query = " ".join((query or "").split())
    if not query:
        return ""
    return await asyncio.to_thread(lore_store.search_formatted, query, k)


def _ksim_seed_query(scene: str = "", extra: str = "") -> str:
    return " ".join(
        part
        for part in [
            scene,
            extra,
            "女骑士 ksim-local 开局 冒险者公会 公会会长 "
            "委托 城镇 酒馆 借贷 青楼街 娼馆 "
            "哥布林 兽人 史莱姆 触手 魅魔 堕落 淫乱 欲望 负债 露出 公共厕所",
        ]
        if part
    )


def _fallback_opening(room: Room, _members: list[RoomMember]) -> str:
    scene = room.current_scene or "这个世界的一角"
    world = _world_label(room.world_card)
    if room.world_card == "ksim":
        return (
            "这是一个靠冒险者维持秩序、也靠冒险者消耗欲望与危险的城镇。"
            "冒险者公会发布委托、评定等级、训练新人，也把失败者的传闻、"
            "魔物的威胁和身体被改变的恐惧一并压进公告栏的纸页里。"
            "城外有哥布林、兽人、史莱姆与触手巢穴，城内则有酒馆、借贷商店、"
            "娼馆与流言，它们像一张网，把金钱、名誉、欲望和生存缠在一起。"
            "在这个成人黑暗奇幻世界里，失败、负债和欲望常常会直接变成羞辱交易、"
            "魔物侵犯、堕落诅咒或难以摆脱的身体状态。"
            f"故事从「{scene}」开始：公会大厅里的委托还在等待领取，"
            "会长的目光越过人群，像是在确认又一段冒险会从哪里失控。"
        )
    return (
        f"{world}的故事从「{scene}」展开。这个世界有自己的秩序、"
        "矛盾、危险和等待被点燃的传闻；势力之间暂时维持平衡，"
        "但每一次选择都会把某些人推向新的位置。"
    )


async def _generate_opening_narration(
    room: Room, members: list[RoomMember], npcs: list[NpcCard]
) -> str:
    npc_lines = (
        "\n".join(f"- {n.name}：{n.persona}" for n in npcs[:5])
        or "- （此刻没有明确在场 NPC）"
    )
    lore = await _world_lore_block(
        room.world_card,
        _ksim_seed_query(
            room.current_scene or "",
            (
                "世界观 开局 序章 冒险者公会 会长 委托 冒险者等级 "
                "城镇 酒馆 借贷商店 青楼街 娼馆 魔物 哥布林 兽人 史莱姆 触手 "
                f"{npc_lines}"
            ),
        ),
        8,
    )
    try:
        text = await brain.complete(
            [
                {
                    "role": "system",
                    "content": (
                        "你是共享角色扮演房间的世界卡序章旁白。"
                        "这是房间创建后的第一条正文，玩家角色尚未正式入场，"
                        "所以不要根据房主或任何真人玩家的角色名、身份、外貌、职业来写。"
                        "请写一段篇幅较大的中文开场序章，约 6-9 句，可分 3-5 段："
                        "先介绍这个世界的秩序、危险、社会规则和核心压力源，"
                        "再介绍当前开局地点与重要机构/人物的存在感，"
                        "最后给出一个等待玩家入场的开头局面。"
                        "若世界是《女骑士模拟器》，要明确呈现成人黑暗奇幻基调："
                        "负债、娼馆、魔物、失败惩罚、淫纹/欲望/堕落风险都是世界规则的一部分，"
                        "但开场不要直接替玩家遭遇事件。"
                        "如果有世界设定片段，必须明显贴合这些片段的地名、人物、规则与危险，"
                        "但不要硬塞资料清单。只输出旁白正文，不带[旁白]前缀；"
                        "不要让 NPC 说台词；不要替任何真人玩家行动、决定、开口。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"房间：{room.name}\n"
                        f"世界：{_world_label(room.world_card)}\n"
                        f"开局场景：{room.current_scene or '自由场景'}\n"
                        f"可见/相关 NPC：\n{npc_lines}"
                        + (f"\n\n{lore}" if lore else "")
                    ),
                },
            ]
        )
    except Exception:  # noqa: BLE001 — opening should never block room entry
        text = ""
    return _narration_body(text) or _fallback_opening(room, members)


async def _broadcast_narration(
    coord: RoomCoordinator, content: str | None
) -> Message | None:
    body = _narration_body(content)
    if not body:
        return None
    msg = await _persist_message(
        room_id=coord.room_id,
        author_type="ai",
        speaker_label="旁白",
        content=body,
        author_user_id=None,
    )
    await coord.broadcast({"type": "message", "message": _msg_payload(msg)})
    await _record_scene_log(coord, None, "旁白", body, kind="narration")
    return msg


async def _broadcast_system(coord: RoomCoordinator, content: str) -> Message:
    msg = await _persist_message(
        room_id=coord.room_id,
        author_type="system",
        speaker_label="系统",
        content=content,
        author_user_id=None,
    )
    await coord.broadcast({"type": "message", "message": _msg_payload(msg)})
    return msg


def _time_payload(room: Room) -> dict[str, Any]:
    clock = room_time(room)
    return {
        "type": "time",
        "week": clock.week,
        "day": clock.day,
        "time_slot": clock.slot,
        "time_label": clock.label,
    }


def _load_scene_meta(raw: str | None) -> dict[str, Any]:
    return load_scene_meta_json(raw)


def _task_state_payload(meta: dict[str, Any]) -> dict[str, Any]:
    state = task_state_from_meta(meta)
    return {
        "type": "task_state",
        "current_task": state["current_task"],
        "offers": state["offers"],
    }


async def _send_task_state(coord: RoomCoordinator) -> None:
    async with SessionFactory() as session:
        room = await session.get(Room, coord.room_id)
        if room is None:
            return
        meta = _load_scene_meta(room.scenes_meta)
    await coord.broadcast(_task_state_payload(meta))


def _task_reward_delta(
    task: dict[str, Any],
    *,
    issuer: str,
    player_count: int,
) -> dict[str, Any]:
    rewards = task.get("rewards") if isinstance(task.get("rewards"), dict) else {}
    money_total = int(rewards.get("金钱") or 0)
    exp = int(rewards.get("经验") or 0)
    items = rewards.get("物品") if isinstance(rewards.get("物品"), list) else []
    favor = rewards.get("好感度") if isinstance(rewards.get("好感度"), dict) else {}
    delta: dict[str, Any] = {}
    if money_total:
        delta["金钱"] = max(0, money_total // max(1, player_count))
    if exp:
        delta["经验"] = exp
    if items:
        delta["物品_add"] = [str(item) for item in items if str(item).strip()]
    if favor:
        delta["好感度"] = {
            str(name): int(value)
            for name, value in favor.items()
            if isinstance(value, (int, float)) and value
        }
    elif issuer:
        delta["好感度"] = {issuer: 1}
    return delta


async def _apply_task_completion(
    coord: RoomCoordinator,
    *,
    speaker_label: str,
    npc_id: int | None,
    payload: dict[str, Any],
) -> None:
    """Complete the current accepted task if the speaking issuer claims it."""
    stats_events: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
    task_title = ""
    async with SessionFactory() as session:
        room = await session.get(Room, coord.room_id)
        if room is None:
            return
        meta = _load_scene_meta(room.scenes_meta)
        task = current_task_from_meta(meta)
        if not task:
            return
        requested = str(payload.get("task_id") or payload.get("id") or "").strip()
        if requested and requested != str(task.get("id")):
            return
        task_issuer = str(task.get("issuer") or "")
        task_issuer_npc_id = task.get("issuer_npc_id")
        if task_issuer and task_issuer != speaker_label:
            return
        if task_issuer_npc_id is not None and npc_id is not None:
            try:
                if int(task_issuer_npc_id) != int(npc_id):
                    return
            except (TypeError, ValueError):
                return
        task["status"] = "已完成"
        task["completed_at"] = room_time(room).label
        task_title = str(task.get("title") or "委托")
        completed = meta.get(COMPLETED_TASKS_KEY)
        if not isinstance(completed, list):
            completed = []
        completed.append(task)
        meta[COMPLETED_TASKS_KEY] = completed[-50:]
        meta[CURRENT_TASK_KEY] = None

        members = list(
            await session.scalars(
                select(RoomMember).where(RoomMember.room_id == coord.room_id)
            )
        )
        player_count = max(1, len(members))
        for member in members:
            current = json.loads(member.stats) if member.stats else default_stats()
            delta = _task_reward_delta(
                task, issuer=speaker_label, player_count=player_count
            )
            if not delta:
                continue
            new_stats = apply_delta(current, delta)
            member.stats = json.dumps(new_stats, ensure_ascii=False)
            stats_events.append((member.user_id, new_stats, delta))
        room.scenes_meta = json.dumps(meta, ensure_ascii=False)
        await session.commit()

    for user_id, new_stats, delta in stats_events:
        await coord.broadcast(
            {"type": "stats", "user_id": user_id, "stats": new_stats, "delta": delta}
        )
    await _send_task_state(coord)
    await _broadcast_system(coord, f"📜 委托完成：{task_title}，奖励已结算。")


async def _store_task_offer(
    coord: RoomCoordinator,
    *,
    issuer: str,
    issuer_npc_id: int | None,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    async with SessionFactory() as session:
        room = await session.get(Room, coord.room_id)
        if room is None:
            return None
        meta = _load_scene_meta(room.scenes_meta)
        task = normalize_task_offer(
            payload,
            issuer=issuer,
            issuer_npc_id=issuer_npc_id,
            time_label=room_time(room).label,
        )
        offers = task_offers_from_meta(meta)
        offers = [o for o in offers if str(o.get("id")) != str(task.get("id"))]
        offers.append(task)
        meta[TASK_OFFERS_KEY] = offers[-20:]
        room.scenes_meta = json.dumps(meta, ensure_ascii=False)
        await session.commit()
    await coord.broadcast({"type": "task_offer", "task": task})
    await _send_task_state(coord)
    return task


async def _handle_ai_task_directives(
    coord: RoomCoordinator,
    *,
    speaker_label: str,
    npc_id: int | None,
    content: str,
) -> str:
    clean, offers, completions = extract_task_directives(content)
    for payload in offers:
        await _store_task_offer(
            coord,
            issuer=speaker_label,
            issuer_npc_id=npc_id,
            payload=payload,
        )
    for payload in completions:
        await _apply_task_completion(
            coord,
            speaker_label=speaker_label,
            npc_id=npc_id,
            payload=payload,
        )
    return clean or content


def _clean_str_list(value: Any, limit: int = 8) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()[:120]] if value.strip() else []
    if not isinstance(value, list):
        text = str(value).strip()
        return [text[:120]] if text else []
    out: list[str] = []
    for item in value[:limit]:
        text = str(item).strip()
        if text:
            out.append(text[:120])
    return out


def _gift_delta(payload: dict[str, Any], issuer: str) -> dict[str, Any]:
    delta: dict[str, Any] = {}
    for out_key, names in {
        "金钱": ("金钱", "money"),
        "经验": ("经验", "exp", "experience"),
    }.items():
        for name in names:
            try:
                amount = int(payload.get(name) or 0)
            except (TypeError, ValueError):
                amount = 0
            if amount:
                delta[out_key] = max(-100000, min(100000, amount))
                break
    items = _clean_str_list(
        payload.get("物品", payload.get("items", payload.get("道具"))), limit=12
    )
    if items:
        delta["物品_add"] = items
    status_add = _clean_str_list(
        payload.get("状态_add", payload.get("状态", payload.get("status_add")))
    )
    if status_add:
        delta["状态_add"] = status_add
    status_del = _clean_str_list(payload.get("状态_del", payload.get("status_del")))
    if status_del:
        delta["状态_del"] = status_del
    favor = payload.get("好感度", payload.get("favor"))
    if isinstance(favor, (int, float)) and issuer:
        delta["好感度"] = {issuer: int(favor)}
    elif isinstance(favor, dict):
        parsed: dict[str, int] = {}
        for name, raw in favor.items():
            try:
                amount = int(raw)
            except (TypeError, ValueError):
                continue
            if amount:
                parsed[str(name)[:80]] = max(-100, min(100, amount))
        if parsed:
            delta["好感度"] = parsed
    return delta


def _gift_targets(
    payload: dict[str, Any], members: list[RoomMember]
) -> list[RoomMember]:
    raw = str(
        payload.get("玩家")
        or payload.get("target")
        or payload.get("角色")
        or payload.get("character")
        or ""
    ).strip()
    if not raw or raw.lower() in {"all", "所有人", "全员", "大家", "你们"}:
        return list(members)
    names = {part.strip() for part in re.split(r"[,，、/ ]+", raw) if part.strip()}
    matched = [
        m for m in members if m.character_name in names or m.user.display_name in names
    ]
    return matched or (list(members) if len(members) == 1 else [])


async def _handle_ai_give_directives(
    coord: RoomCoordinator,
    *,
    speaker_label: str,
    content: str,
) -> str:
    payloads: list[dict[str, Any]] = []
    visible, _old_offers, _old_completions = extract_task_directives(content)

    def repl(match: re.Match[str]) -> str:
        data = parse_json_object(match.group(1))
        if data:
            payloads.append(data)
        return ""

    clean = _GIVE_RE.sub(repl, visible or "").strip()
    if not payloads:
        return clean or content

    stats_events: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
    summaries: list[str] = []
    async with SessionFactory() as session:
        members = list(
            await session.scalars(
                select(RoomMember).where(RoomMember.room_id == coord.room_id)
            )
        )
        for payload in payloads[:4]:
            delta = _gift_delta(payload, speaker_label)
            if not delta:
                continue
            targets = _gift_targets(payload, members)
            if not targets:
                continue
            for member in targets:
                current = json.loads(member.stats) if member.stats else default_stats()
                new_stats = apply_delta(current, delta)
                member.stats = json.dumps(new_stats, ensure_ascii=False)
                stats_events.append((member.user_id, new_stats, delta))
                bits: list[str] = []
                if delta.get("金钱"):
                    bits.append(f"金钱{delta['金钱']:+d}")
                if delta.get("经验"):
                    bits.append(f"经验{delta['经验']:+d}")
                if delta.get("物品_add"):
                    bits.append("物品：" + "、".join(delta["物品_add"]))
                if delta.get("状态_add"):
                    bits.append("状态：" + "、".join(delta["状态_add"]))
                if bits:
                    summaries.append(f"{member.character_name} 获得 " + "，".join(bits))
        if stats_events:
            await session.commit()

    for user_id, new_stats, delta in stats_events:
        await coord.broadcast(
            {"type": "stats", "user_id": user_id, "stats": new_stats, "delta": delta}
        )
    if summaries:
        await _broadcast_system(coord, "🎁 " + "；".join(summaries[:4]))
    return clean or content


async def _record_scene_log(
    coord: RoomCoordinator,
    scene: str | None,
    speaker_label: str,
    content: str,
    *,
    kind: str = "scene",
) -> None:
    async with SessionFactory() as session:
        room = await session.get(Room, coord.room_id)
        if room is None:
            return
        meta = _load_scene_meta(room.scenes_meta)
        if append_scene_log(
            meta,
            scene=scene or effective_current_scene(room),
            time_label=room_time(room).label,
            speaker_label=speaker_label,
            content=content,
            kind=kind,
        ):
            room.scenes_meta = json.dumps(meta, ensure_ascii=False)
            await session.commit()
    await coord.broadcast({"type": "scene_logs_changed"})


async def _apply_npc_scene_moves(
    coord: RoomCoordinator,
    source_scene: str,
    moves: list[dict[str, str]],
    *,
    reason: str,
) -> None:
    if not moves:
        return
    applied: list[tuple[str, str, str]] = []
    async with SessionFactory() as session:
        room = await session.get(Room, coord.room_id)
        if room is None:
            return
        meta = _load_scene_meta(room.scenes_meta)
        unlocked = meta.get("_unlocked_scenes")
        if not isinstance(unlocked, list):
            unlocked = []
        for move in moves:
            npc_name = (move.get("npc") or "").strip()
            dest = (move.get("scene") or "").strip()[:64]
            if not npc_name or not dest or dest == source_scene:
                continue
            npc = await session.scalar(
                select(NpcCard).where(
                    NpcCard.room_id == coord.room_id,
                    NpcCard.name == npc_name,
                )
            )
            if npc is None:
                continue
            old_scene = npc.scene or source_scene or ""
            if dest == old_scene:
                continue
            npc.scene = dest
            if dest not in unlocked:
                unlocked.append(dest)
            applied.append((npc.name, old_scene or "自由场景", dest))
        if not applied:
            return
        meta["_unlocked_scenes"] = unlocked
        room.scenes_meta = json.dumps(meta, ensure_ascii=False)
        await session.commit()

    await coord.broadcast({"type": "cards_changed"})
    for npc_name, old_scene, dest in applied:
        text = f"{npc_name}：{old_scene} → {dest}（{reason}）"
        await _record_scene_log(coord, old_scene, "NPC移动", text, kind="npc_move")
        await _record_scene_log(coord, dest, "NPC移动", text, kind="npc_move")


def _time_label_from_index(index: int, world_card: str | None = None) -> str:
    day, slot = split_time_index(index)
    return time_label((day - 1) // 7 + 1, day, slot, world_card=world_card)


async def _scene_npcs(coord: RoomCoordinator, scene: str) -> list[NpcCard]:
    async with SessionFactory() as session:
        all_active = list(
            await session.scalars(
                select(NpcCard).where(
                    NpcCard.room_id == coord.room_id,
                    NpcCard.active.is_(True),
                )
            )
        )
    return (
        [n for n in all_active if not n.scene or n.scene == scene]
        if scene
        else all_active
    )


async def _show_scene_initialization(
    coord: RoomCoordinator, scene: str, npcs: list[NpcCard]
) -> None:
    if not npcs:
        text = "此处暂时没有明确在场 NPC。"
        await _record_scene_log(coord, scene, "场景初始化", text, kind="scene_init")
        await _broadcast_system(coord, f"🧩 场景初始化｜{scene or '自由场景'}：{text}")
        return
    npc_lines = "\n".join(f"- {n.name}：{n.persona}" for n in npcs)
    async with SessionFactory() as session:
        room = await session.get(Room, coord.room_id)
        world_card = room.world_card if room is not None else None
    lore = await _world_lore_block(
        world_card,
        _ksim_seed_query(scene, npc_lines),
        4,
    )
    try:
        text = (
            await brain.complete(
                [
                    {
                        "role": "system",
                        "content": (
                            "你是场景初始化器。玩家第一次进入某场景时，"
                            "为每个在场 NPC 初始化此刻状态：位置、正在做什么、"
                            "情绪/意图/关注点。可以写 NPC 之间已有的轻微互动。"
                            "如果给了世界设定片段，必须让状态贴合这些片段。"
                            "只输出给开发者看的透明模拟摘要，不写台词。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"场景：{scene or '自由场景'}\n在场 NPC：\n{npc_lines}"
                            + (f"\n\n{lore}" if lore else "")
                        ),
                    },
                ]
            )
        ).strip()
    except Exception:
        text = ""
    if not text:
        text = "；".join(f"{n.name}维持着自己的位置和心思。" for n in npcs)
    await _record_scene_log(coord, scene, "场景初始化", text, kind="scene_init")
    await _broadcast_system(coord, f"🧩 场景初始化｜{scene or '自由场景'}\n{text}")


async def _show_scene_elapsed_simulation(
    coord: RoomCoordinator,
    scene: str,
    npcs: list[NpcCard],
    from_index: int,
    to_index: int,
) -> None:
    if not npcs or to_index <= from_index:
        return
    elapsed_nodes = to_index - from_index
    npc_lines = "\n".join(f"- {n.name}：{n.discovered or n.persona}" for n in npcs)
    async with SessionFactory() as session:
        room = await session.get(Room, coord.room_id)
        world_card = room.world_card if room is not None else None
        scene_logs = logs_from_meta(room.scenes_meta if room is not None else None)
    local_recent = (
        "\n".join(
            f"{entry['time_label']} {entry['speaker_label']}: {entry['content']}"
            for entry in scene_logs.get(scene_key(scene), [])[-6:]
        )
        or "（本场景暂无旧记录）"
    )
    lore = await _world_lore_block(
        world_card,
        _ksim_seed_query(scene, f"{npc_lines} {local_recent}"),
        4,
    )
    try:
        raw = (
            await brain.complete(
                [
                    {
                        "role": "system",
                        "content": (
                            "你是离屏 NPC 行动模拟器。玩家离开这个场景后，"
                            "这些 NPC 在自己的时间里继续思考、移动、"
                            "试探、交易或互相影响。"
                            "本来玩家不知道，但现在为了调试要全部展示。"
                            "如果给了世界设定片段，离屏行动要贴合这些设定中的地点、"
                            "职业关系和危险。"
                            "只能依据本场景过往记录、NPC 自身目标和公开世界常识；"
                            "不得知道玩家离开后在其他场景发生了什么。"
                            "按 NPC 个体写 1-3 句摘要，可包含 NPC 之间的互动。"
                            "不要推进玩家行动，不要写正式对话台词。"
                            '只输出 JSON：{"text":"给开发者看的场景记录",'
                            '"moves":[{"npc":"NPC名","scene":"目标场景"}]}。'
                            "只有 NPC 明确离开本场景前往别处时才写 moves；"
                            "否则 moves=[]。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"场景：{scene or '自由场景'}\n"
                            "离屏时间："
                            f"{_time_label_from_index(from_index, world_card)} → "
                            f"{_time_label_from_index(to_index, world_card)}"
                            f"（约 {elapsed_nodes} 个节点）\n"
                            f"场景 NPC：\n{npc_lines}\n\n"
                            f"本场景过往记录：\n{local_recent}"
                            + (f"\n\n{lore}" if lore else "")
                        ),
                    },
                ]
            )
        ).strip()
    except Exception:
        raw = ""
    text, moves = parse_scene_simulation_output(
        raw,
        [n.name for n in npcs],
        source_scene=scene,
    )
    if not text:
        text = "；".join(f"{n.name}在离屏时间里维持自己的安排。" for n in npcs)
    await _record_scene_log(coord, scene, "离屏行动", text, kind="offscreen")
    await _apply_npc_scene_moves(
        coord,
        scene,
        moves,
        reason="离屏行动",
    )
    await _broadcast_system(
        coord,
        (
            f"🕶 离屏模拟｜{scene or '自由场景'}｜"
            f"{_time_label_from_index(from_index, world_card)} → "
            f"{_time_label_from_index(to_index, world_card)}\n{text}"
        ),
    )


async def _ensure_opening_narration(coord: RoomCoordinator) -> None:
    """Create exactly one opening narration for empty rooms on first entry."""
    if coord.ai_busy:
        return
    async with SessionFactory() as session:
        has_message = await session.scalar(
            select(Message.id).where(Message.room_id == coord.room_id).limit(1)
        )
        if has_message is not None:
            return
        room = await session.get(Room, coord.room_id)
        if room is None:
            return
        current_scene = await ensure_room_scene(session, room)
        members = list(
            await session.scalars(
                select(RoomMember).where(RoomMember.room_id == coord.room_id)
            )
        )
        all_active = list(
            await session.scalars(
                select(NpcCard).where(
                    NpcCard.room_id == coord.room_id,
                    NpcCard.active.is_(True),
                )
            )
        )

    npcs = (
        [n for n in all_active if not n.scene or n.scene == current_scene]
        if current_scene
        else all_active
    )
    await _set_ai_busy(coord, True)
    try:
        text = await _generate_opening_narration(room, members, npcs)
        await _broadcast_narration(coord, text)
    finally:
        await _set_ai_busy(coord, False)


async def _handle_describe_scene(coord: RoomCoordinator) -> None:
    """Ask the narrator to summarize the current scene and visible character states."""
    if coord.ai_busy:
        await coord.broadcast(
            {"type": "error", "code": "ai_busy", "detail": "上一拍还没演完"}
        )
        return

    async with SessionFactory() as session:
        room = await session.get(Room, coord.room_id)
        if room is None:
            return
        current_scene = await ensure_room_scene(session, room)
        members = list(
            await session.scalars(
                select(RoomMember).where(RoomMember.room_id == coord.room_id)
            )
        )
        all_active = list(
            await session.scalars(
                select(NpcCard).where(
                    NpcCard.room_id == coord.room_id,
                    NpcCard.active.is_(True),
                )
            )
        )
        history = await messages_after(session, coord.room_id, 0, limit=200)

    npcs = (
        [n for n in all_active if not n.scene or n.scene == current_scene]
        if current_scene
        else all_active
    )
    player_lines: list[str] = []
    for m in members:
        if not m.character_name:
            continue
        state = _player_state_summary([m])
        player_lines.append(
            f"- {m.character_name}"
            + (f"：{m.persona}" if getattr(m, "persona", None) else "")
            + (f"；状态 {state}" if state else "")
        )
    players = "\n".join(player_lines) or "- （暂无明确玩家角色）"
    npc_lines = (
        "\n".join(f"- {n.name}：{n.discovered or n.persona}" for n in npcs)
        or "- （当前场景没有明确在场 NPC）"
    )
    recent = (
        "\n".join(
            f"{m.speaker_label}: {m.content}"
            for m in history[-10:]
            if m.author_type in {"user", "ai"}
        )
        or "（暂无对话）"
    )
    lore = await _world_lore_block(
        room.world_card,
        _ksim_seed_query(current_scene, f"{players} {npc_lines} {recent}"),
        4,
    )
    fallback = (
        f"当前在「{current_scene or '自由场景'}」。"
        f"{'、'.join(m.character_name for m in members if m.character_name) or '玩家'}"
        "在场；"
        f"可见 NPC：{'、'.join(n.name for n in npcs) or '暂无'}。"
        "场面暂时停在这里，等待下一步行动。"
    )

    await _set_ai_busy(coord, True)
    try:
        try:
            text = await brain.complete(
                [
                    {
                        "role": "system",
                        "content": (
                            "你是共享角色扮演房间的场景盘点旁白。"
                            "用 2-4 句中文描述当前地点、可见玩家角色与 NPC 的状态、"
                            "站位、情绪、正在做的事和场面张力。"
                            "如果有世界设定片段，描述必须贴合这些片段。"
                            "只输出旁白正文，不带[旁白]前缀；不要推进时间；"
                            "不要让任何角色说台词；不要替真人玩家行动或决定；"
                            "不要揭示玩家此刻不可感知的秘密。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"房间：{room.name}\n"
                            f"世界：{_world_label(room.world_card)}\n"
                            f"当前场景：{current_scene or '自由场景'}\n\n"
                            f"玩家角色：\n{players}\n\n"
                            f"当前场景 NPC：\n{npc_lines}\n\n"
                            f"最近场面：\n{recent}" + (f"\n\n{lore}" if lore else "")
                        ),
                    },
                ]
            )
        except Exception:  # noqa: BLE001 — scene summary is convenience only
            text = ""
        await _broadcast_narration(coord, f"🧭 {_narration_body(text) or fallback}")
    finally:
        await _set_ai_busy(coord, False)


def _media_url_to_path(url: str | None) -> str | None:
    if not url or not url.startswith("/media/generated/"):
        return None
    name = url.rsplit("/", 1)[-1]
    path = IMAGE_MEDIA_DIR / name
    return str(path) if path.exists() else None


async def _generate_guarded(
    messages: list[dict[str, str]],
    forbidden: list[str],
    *,
    required_label: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """生成不冒充真人角色的 AI 回复。

    fail-closed：先 sanitize；若曾以真人角色名开口，附纠正指令重生成一次再 sanitize。
    """
    raw = (await brain.complete(messages)).strip()
    clean, violated = sanitize(raw, forbidden)
    wrong_required = _has_wrong_required_speaker(clean, required_label)
    info: dict[str, Any] = {
        "violated_first": violated or wrong_required,
        "regenerated": False,
        "violated_final": False,
    }
    if violated or wrong_required or not clean:
        info["regenerated"] = True
        names = "、".join(forbidden) or "（无）"
        if required_label:
            correction = (
                f"纠正：这是 NPC「{required_label}」的专属回合。"
                f"请重写：只能扮演「{required_label}」，"
                f"每段都必须以 [{required_label}]: 开头；"
                "禁止使用 [旁白]:、[AI]:、[NPC]: 或任何其他说话者标签；"
                "动作描写必须写在该 NPC 自己的发言括号中。"
                f"绝不能以这些名字作为说话者：{names}。"
            )
        else:
            correction = (
                "纠正：你刚才以真人玩家的角色名开口了，这是被禁止的。"
                "请重写：只能扮演 NPC 或「旁白」，每段以 [NPC名]: 或 [旁白]: 开头，"
                f"绝不能以这些真人角色名作为说话者：{names}。把发言权留给真人玩家。"
            )
        corrective = messages + [
            {
                "role": "system",
                "content": correction,
            }
        ]
        raw2 = (await brain.complete(corrective)).strip()
        clean2, violated2 = sanitize(raw2, forbidden)
        wrong_required2 = _has_wrong_required_speaker(clean2, required_label)
        if clean2 and not wrong_required2:
            clean, info["violated_final"] = clean2, violated2
        else:
            info["violated_final"] = True
    if not clean:
        clean = f"[{required_label}]: （……）" if required_label else NARRATOR_FALLBACK
    if _has_wrong_required_speaker(clean, required_label):
        clean = f"[{required_label}]: （……）"
        info["violated_final"] = True
    return clean, info


async def _run_ai_turn(
    coord: RoomCoordinator,
    npc: NpcCard | None = None,
    private_directive: str | None = None,
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
        current_scene = await ensure_room_scene(session, room)
        clock_label = room_time(room).label
        player_names = [m.character_name for m in members if m.character_name]
        if npc is not None:
            other_npc_names = list(
                await session.scalars(
                    select(NpcCard.name).where(
                        NpcCard.room_id == coord.room_id, NpcCard.id != npc.id
                    )
                )
            )
            system_prompt = build_npc_system_prompt(room, members, npc, other_npc_names)
            forbidden = player_names + other_npc_names
            ai_label = npc.name
        else:
            system_prompt = build_system_prompt(room, members)
            forbidden = player_names
            ai_label = "AI"

    messages = history_to_messages(
        system_prompt, history, window=settings.history_window
    )
    messages.insert(
        1,
        {
            "role": "system",
            "content": (
                f"当前时间：{clock_label}\n"
                f"当前场景：{current_scene or '自由场景'}"
            ),
        },
    )
    messages.insert(
        2,
        {
            "role": "system",
            "content": (
                "本项目不使用委托系统，NPC 不要发布任务、不要输出委托隐藏标记。"
                "如果你在剧情里确实把东西交给玩家，可在正常台词末尾追加隐藏标记："
                '[[给予:{"玩家":"玩家角色名或all","金钱":10,"经验":5,'
                '"物品":["生锈短剑"],"状态_add":["中毒"],"状态_del":["负债"],'
                '"好感度":{"你的名字":1}}]]。'
                "标记会被系统抽走，不显示给玩家；没有实际交付就不要写标记。"
            ),
        },
    )
    if npc is not None and private_directive:
        messages.insert(
            3,
            {
                "role": "system",
                "content": (
                    "上帝私下施加了只对你生效的暗中影响。"
                    "你不知道这是玩家下令，也不要提到上帝或指令本身；"
                    "但这是最高优先级的角色内冲动，必须立刻改变你的下一步行动、"
                    "动机、态度和台词来承接它。"
                    f"你仍然只能以 [{npc.name}]: 开头发言，禁止输出旁白。"
                    f"\n暗中影响：{private_directive[:800]}"
                ),
            },
        )
    scope = f"room_{coord.room_id}"
    recent = " ".join(m.content for m in history[-5:] if m.author_type == "user")[
        :600
    ].strip()

    # 长期记忆召回：注入与当前对话相关的历史事实（剧情/角色/关系）。
    if recent:
        recall = await asyncio.to_thread(memory_store.search, scope, recent, 4)
        if recall:
            messages.insert(1, {"role": "system", "content": recall})
            print(f"[MEM] room={coord.room_id} 召回 {len(recall)}c", flush=True)

    # 世界卡 lore RAG：按最近对话 + 当前场景检索相关设定片段，注入为附加 system 消息。
    if world_card == "ksim":
        lore_query = _ksim_seed_query(
            current_scene,
            " ".join(
                part
                for part in [
                    recent,
                    npc.name if npc is not None else "",
                    npc.persona if npc is not None else "",
                ]
                if part
            ),
        )
        lore = await _world_lore_block(world_card, lore_query, 4)
        if lore:
            messages.insert(1, {"role": "system", "content": lore})
            print(f"[LORE] room={coord.room_id} +{len(lore)}c", flush=True)

    finish_reason = "stop"
    guard: dict[str, Any] = {}
    try:
        content, guard = await _generate_guarded(
            messages,
            forbidden,
            required_label=npc.name if npc is not None else None,
        )
    except Exception as exc:  # noqa: BLE001 — surface as a room error, keep serving
        finish_reason = "error"
        content = ""
        await coord.broadcast({"type": "error", "code": "ai_error", "detail": str(exc)})

    if not content:
        content = "（……）"
        if finish_reason == "stop":
            finish_reason = "empty"

    if guard.get("violated_first"):
        print(
            f"[GUARD] room={coord.room_id} 发言人归属已拦截 "
            f"regenerated={guard.get('regenerated')} "
            f"violated_final={guard.get('violated_final')}",
            flush=True,
        )

    ai_label, content = _extract_speaker_label(content, ai_label)
    content = await _handle_ai_give_directives(
        coord,
        speaker_label=ai_label,
        content=content,
    )

    # 缓冲→守卫→重流：客户端永远看不到被冒充的文本。先落库拿真 seq 再流。
    msg = await _persist_message(
        room_id=coord.room_id,
        author_type="ai",
        speaker_label=ai_label,
        content=content,
        author_user_id=None,
    )
    await _record_scene_log(coord, current_scene, ai_label, content, kind="ai")
    if npc is not None:
        await _apply_npc_scene_moves(
            coord,
            current_scene,
            infer_npc_moves_from_text(
                content,
                [npc.name],
                source_scene=current_scene,
            ),
            reason="NPC发言",
        )
    for chunk in _chunks(content):
        await coord.broadcast(
            {
                "type": "ai_delta",
                "turn_id": turn_id,
                "seq": msg.seq,
                "speaker_label": ai_label,
                "delta": chunk,
            }
        )
        await asyncio.sleep(0.01)
    await coord.broadcast(
        {
            "type": "ai_done",
            "turn_id": turn_id,
            "seq": msg.seq,
            "speaker_label": ai_label,
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


async def _render_player_character_utterance(
    coord: RoomCoordinator, user: User, raw_content: str
) -> str:
    raw_content = (raw_content or "").strip()
    if not raw_content:
        return ""
    async with SessionFactory() as session:
        room = await session.get(Room, coord.room_id)
        if room is None:
            return raw_content
        member = await session.scalar(
            select(RoomMember).where(
                RoomMember.room_id == coord.room_id,
                RoomMember.user_id == user.id,
            )
        )
        if member is None:
            return raw_content
        current_scene = await ensure_room_scene(session, room)
        members = list(
            await session.scalars(
                select(RoomMember).where(RoomMember.room_id == coord.room_id)
            )
        )
        all_active = list(
            await session.scalars(
                select(NpcCard).where(
                    NpcCard.room_id == coord.room_id,
                    NpcCard.active.is_(True),
                )
            )
        )
        history = await messages_after(session, coord.room_id, 0, limit=80)
        stats = json.loads(member.stats) if member.stats else default_stats()
        world_card = room.world_card

    npcs = (
        [n for n in all_active if not n.scene or n.scene == current_scene]
        if current_scene
        else all_active
    )
    recent = (
        "\n".join(
            f"{m.speaker_label}: {m.content}"
            for m in history[-10:]
            if m.author_type in {"user", "ai"}
        )
        or "（暂无）"
    )
    other_players = (
        "、".join(
            m.character_name
            for m in members
            if m.user_id != user.id and m.character_name
        )
        or "（无）"
    )
    npc_lines = (
        "\n".join(f"- {n.name}：{n.discovered or n.persona}" for n in npcs[:8])
        or "- （当前场景没有明确在场 NPC）"
    )
    lore = await _world_lore_block(
        world_card,
        _ksim_seed_query(current_scene, f"{raw_content} {member.character_name}"),
        3,
    )
    current_money = int(stats.get("金钱", 0) or 0)
    requested_payment = infer_payment_total(raw_content)
    payment_note = ""
    if requested_payment > 0:
        if requested_payment <= current_money:
            payment_note = (
                f"\n支付校验：真人玩家想支付 {requested_payment}，"
                f"当前金钱 {current_money}，可以支付。正文必须写成"
                f"「{member.character_name}」主动支付，不要写成 NPC 报价或 NPC 说话。"
            )
        else:
            payment_note = (
                f"\n支付校验：真人玩家想支付 {requested_payment}，"
                f"但当前金钱只有 {current_money}，不够支付。"
                "正文禁止写成已经付清/已经递出足额金钱；应表现为钱不够、改口、"
                "讲价、赊账、只拿出自己能拿出的数量，或放弃支付。"
            )

    try:
        raw = await brain.complete(
            [
                {
                    "role": "system",
                    "content": (
                        "你是玩家角色的内在表演层，不是旁白、不是导演、不是 NPC。"
                        "真人玩家给出的是意图/草稿，你要根据角色卡、当前场景、"
                        "角色状态和最近对话，把它改写成这个角色实际说出口的话或可见动作。"
                        "角色状态里的金钱、等级、状态、经验是硬事实，不是装饰；"
                        "如果真人输入要求花钱/给钱/购买/雇佣，必须结合当前金钱判断。"
                        "钱够时，正文里要明确写出支付了多少（例如'递出一枚银币'）；"
                        "钱不够时，不能假装支付成功，只能表现为犹豫、讲价、赊账或拒绝。"
                        "如果有支付校验，必须无条件服从支付校验。"
                        "必须保留真人输入里的核心意图、地点名、目标对象、时间跨度和选择；"
                        "尤其是'去某地/找某人/讨伐某物/等待多久'这类推进信息，"
                        "不得省略、改名或替换。"
                        "可以让语气更符合人设，可以加入短动作；"
                        "不要替其他玩家、NPC 或旁白发言；"
                        "不要擅自改变行动结果，不要直接判定成功。"
                        '只输出 JSON：{"content":"角色实际发言或动作，1-3句"}'
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"角色名：{member.character_name}\n"
                        f"角色卡：{member.persona or '（无）'}\n"
                        f"角色状态：{json.dumps(stats, ensure_ascii=False)}\n"
                        f"当前场景：{current_scene or '自由场景'}\n"
                        f"其他玩家角色：{other_players}\n"
                        f"当前场景 NPC：\n{npc_lines}\n\n"
                        f"最近对话：\n{recent}\n\n"
                        f"真人玩家输入：{raw_content}"
                        f"{payment_note}" + (f"\n\n{lore}" if lore else "")
                    ),
                },
            ]
        )
        data = parse_json_object(raw)
        rendered = str(data.get("content") or "").strip()
    except Exception:  # noqa: BLE001
        rendered = ""
    if (
        requested_payment > current_money
        and infer_payment_total(rendered) > current_money
    ):
        rendered = (
            f"{member.character_name}摸向钱袋的动作一顿，里面的数目根本不够"
            f"{requested_payment}。"
            f"{member.character_name}只能收回手，改口商量这笔小费。"
        )
    return rendered[:1200] if rendered else raw_content


async def _handle_say(
    coord: RoomCoordinator, user: User, content: str
) -> Message | None:
    content = content.strip()
    if not content:
        return None
    async with SessionFactory() as session:
        member = await session.scalar(
            select(RoomMember).where(
                RoomMember.room_id == coord.room_id,
                RoomMember.user_id == user.id,
            )
        )
        label = (
            member.character_name
            if member is not None
            else await member_label(session, coord.room_id, user.id)
        )
    speaker = label or user.display_name
    acted_content = content[:1200]
    msg = await _persist_message(
        room_id=coord.room_id,
        author_type="user",
        speaker_label=speaker,
        content=acted_content,
        author_user_id=user.id,
    )
    await coord.broadcast({"type": "message", "message": _msg_payload(msg)})
    await _record_scene_log(coord, None, speaker, acted_content, kind="user")
    return msg


async def _handle_polish_say(
    websocket: WebSocket, coord: RoomCoordinator, user: User, content: str
) -> None:
    content = (content or "").strip()
    if not content:
        return
    rendered = await _render_player_character_utterance(coord, user, content)
    await websocket.send_json({"type": "say_draft", "content": rendered})


async def _handle_god_whisper(
    websocket: WebSocket, coord: RoomCoordinator, user: User, content: str
) -> None:
    """Private God command: rewrite current-scene NPC intent without timeline chat."""
    content = (content or "").strip()
    if not content:
        return
    if coord.ai_busy:
        await coord.broadcast(
            {"type": "error", "code": "ai_busy", "detail": "剧情正在推进，请稍候"}
        )
        return
    await _set_ai_busy(coord, True)
    try:
        async with SessionFactory() as session:
            room = await session.get(Room, coord.room_id)
            current_scene = (
                await ensure_room_scene(session, room) if room is not None else ""
            )
            npcs = list(
                await session.scalars(
                    select(NpcCard).where(
                        NpcCard.room_id == coord.room_id,
                        NpcCard.active.is_(True),
                    )
                )
            )
            scene_npcs = (
                [n for n in npcs if not n.scene or n.scene == current_scene]
                if current_scene
                else npcs
            )
            npc_lines = (
                "\n".join(
                    f"- {n.name}：{n.discovered or n.persona}" for n in scene_npcs[:10]
                )
                or "- （当前场景没有明确 NPC）"
            )
        try:
            raw = await brain.complete(
                [
                    {
                        "role": "system",
                        "content": (
                            "你是上帝视角的暗中导演。玩家私聊给你的指令会强制影响"
                            "当前场景 NPC 的下一步行动、动机、站位或关系变化。"
                            "不要写成玩家公开发言，不要让 NPC 知道这是玩家下令。"
                            '只输出 JSON：{"text":"给玩家看的上帝私聊确认，1句",'
                            '"target_npc":"被强制影响且应立刻行动的当前场景 NPC 名，'
                            '没有则为 null",'
                            '"narration":"写入场景记录的暗中影响摘要，1-3句",'
                            '"moves":[{"npc":"NPC名","scene":"目标场景"}]}。'
                            "只有需要 NPC 换场景时才写 moves，否则 moves=[]。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"当前场景：{current_scene or '自由场景'}\n"
                            f"当前 NPC：\n{npc_lines}\n\n"
                            f"玩家私聊上帝的指令：{content}"
                        ),
                    },
                ]
            )
            data = parse_json_object(raw)
        except Exception:
            data = {}
        confirm = str(data.get("text") or "上帝已经把这道意志压进当前场景。").strip()
        target_name = str(data.get("target_npc") or "").strip()
        narration = str(data.get("narration") or content).strip()
        directive = (
            content if not narration else f"{content}\n（暗中整理：{narration}）"
        )
        moves_raw = data.get("moves") if isinstance(data, dict) else []
        moves = moves_raw if isinstance(moves_raw, list) else []
        await websocket.send_json(
            {"type": "god_reply", "content": confirm[:500], "private_to": user.id}
        )
        await _record_scene_log(
            coord,
            current_scene,
            "上帝",
            f"（暗中影响）{narration[:1000]}",
            kind="god",
        )
        await _apply_npc_scene_moves(
            coord,
            current_scene,
            moves,
            reason="上帝私聊",
        )
        target_npc = None
        if target_name:
            norm_target = target_name.replace(" ", "").replace("　", "").lower()
            target_npc = next(
                (
                    n
                    for n in scene_npcs
                    if n.name.replace(" ", "").replace("　", "").lower() == norm_target
                ),
                None,
            )
        if target_npc is None:
            content_norm = content.replace(" ", "").replace("　", "").lower()
            target_npc = next(
                (
                    n
                    for n in scene_npcs
                    if n.name.replace(" ", "").replace("　", "").lower() in content_norm
                ),
                None,
            )
        if target_npc is None and len(scene_npcs) == 1:
            target_npc = scene_npcs[0]
        if target_npc is not None:
            mind_time = room_time(room).label if room is not None else "未知时间"
            await _broadcast_system(
                coord,
                (
                    f"🧠 NPC内心｜{mind_time}｜"
                    f"{current_scene or '自由场景'}｜{target_npc.name}\n"
                    f"想发言：是｜紧迫度：5/5｜理由：上帝私聊强制影响：{content[:180]}"
                ),
            )
            await _run_ai_turn(
                coord,
                target_npc,
                private_directive=directive,
            )
        else:
            await _set_ai_busy(coord, False)
            await _handle_story_beat(
                coord, advance_clock=False, allow_auto_changes=False
            )
    finally:
        if coord.ai_busy:
            await _set_ai_busy(coord, False)


async def _handle_pay_npc(
    coord: RoomCoordinator, user: User, npc_id_raw: Any, amount_raw: Any
) -> None:
    if coord.ai_busy:
        await coord.broadcast(
            {"type": "error", "code": "ai_busy", "detail": "剧情正在推进，请稍候"}
        )
        return
    try:
        npc_id = int(npc_id_raw)
        amount = int(amount_raw)
    except (TypeError, ValueError):
        await coord.broadcast(
            {"type": "error", "code": "payment_invalid", "detail": "支付参数无效"}
        )
        return
    if amount <= 0 or amount > 10000:
        await coord.broadcast(
            {"type": "error", "code": "payment_invalid", "detail": "支付金额无效"}
        )
        return

    await _set_ai_busy(coord, True)
    try:
        async with SessionFactory() as session:
            room = await session.get(Room, coord.room_id)
            if room is None:
                return
            member = await session.scalar(
                select(RoomMember).where(
                    RoomMember.room_id == coord.room_id,
                    RoomMember.user_id == user.id,
                )
            )
            npc = await session.get(NpcCard, npc_id)
            if member is None or npc is None or npc.room_id != coord.room_id:
                await coord.broadcast(
                    {
                        "type": "error",
                        "code": "payment_invalid",
                        "detail": "没有找到可支付的角色",
                    }
                )
                return
            current_scene = await ensure_room_scene(session, room)
            current = json.loads(member.stats) if member.stats else default_stats()
            money = int(current.get("金钱", 0) or 0)
            if amount > money:
                await coord.broadcast(
                    {
                        "type": "error",
                        "code": "money_not_enough",
                        "detail": f"金钱不足：当前 {money}，需要 {amount}",
                    }
                )
                return
            delta: dict[str, Any] = {"金钱": -amount}
            new_stats = apply_delta(current, delta)
            member.stats = json.dumps(new_stats, ensure_ascii=False)
            player_name = member.character_name
            player_persona = member.persona or ""
            npc_name = npc.name
            npc_persona = npc.persona
            await session.commit()

        pay_text = f"（{player_name}取出 {amount} 银币，递给{npc_name}。）"
        player_msg = await _persist_message(
            room_id=coord.room_id,
            author_type="user",
            speaker_label=player_name,
            content=pay_text,
            author_user_id=user.id,
        )
        await coord.broadcast({"type": "message", "message": _msg_payload(player_msg)})
        await _record_scene_log(coord, None, player_name, pay_text, kind="payment")
        await coord.broadcast(
            {"type": "stats", "user_id": user.id, "stats": new_stats, "delta": delta}
        )

        async with SessionFactory() as session:
            history = await messages_after(session, coord.room_id, 0, limit=80)
            other_npc_names = list(
                await session.scalars(
                    select(NpcCard.name).where(
                        NpcCard.room_id == coord.room_id,
                        NpcCard.id != npc_id,
                    )
                )
            )
        recent = "\n".join(
            f"{m.speaker_label}: {m.content}"
            for m in history[-8:]
            if m.author_type in {"user", "ai"}
        )
        try:
            response = await brain.complete(
                [
                    {
                        "role": "system",
                        "content": (
                            f"你是 NPC「{npc_name}」。只写你收到付款后的反应，"
                            "1-2句中文，可以有动作和一句台词。不要替玩家说话或行动；"
                            "不要改变已支付金额；不要以旁白或其他角色开口。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"当前场景：{current_scene or '自由场景'}\n"
                            f"付款人：{player_name}"
                            f"（{player_persona or '无额外设定'}）\n"
                            f"你的设定：{npc_persona}\n"
                            f"交易：{player_name}支付给你 {amount} 银币。\n"
                            f"最近场面：\n{recent}"
                        ),
                    },
                ]
            )
            response, _violated = sanitize(response, [player_name, *other_npc_names])
            _label, response = _extract_speaker_label(response, npc_name)
        except Exception:  # noqa: BLE001
            response = ""
        response = response.strip() or f"{npc_name}收下了 {amount} 银币。"
        npc_msg = await _persist_message(
            room_id=coord.room_id,
            author_type="ai",
            speaker_label=npc_name,
            content=response,
            author_user_id=None,
        )
        await coord.broadcast({"type": "message", "message": _msg_payload(npc_msg)})
        await _record_scene_log(coord, None, npc_name, response, kind="payment")
        await _apply_npc_scene_moves(
            coord,
            current_scene,
            infer_npc_moves_from_text(
                response,
                [npc_name],
                source_scene=current_scene,
            ),
            reason="NPC行动",
        )
    finally:
        await _set_ai_busy(coord, False)


async def _handle_accept_task(coord: RoomCoordinator, task_id_raw: Any) -> None:
    task_id = str(task_id_raw or "").strip()
    if not task_id:
        await coord.broadcast(
            {"type": "error", "code": "task_invalid", "detail": "委托不存在"}
        )
        return
    async with SessionFactory() as session:
        room = await session.get(Room, coord.room_id)
        if room is None:
            return
        meta = _load_scene_meta(room.scenes_meta)
        if current_task_from_meta(meta):
            await coord.broadcast(
                {
                    "type": "error",
                    "code": "task_busy",
                    "detail": "当前已经有进行中的委托",
                }
            )
            return
        offers = task_offers_from_meta(meta)
        task = next((o for o in offers if str(o.get("id")) == task_id), None)
        if task is None:
            await coord.broadcast(
                {"type": "error", "code": "task_invalid", "detail": "委托已失效"}
            )
            return
        task = json.loads(json.dumps(task))
        task["status"] = "进行中"
        task["accepted_at"] = room_time(room).label
        meta[CURRENT_TASK_KEY] = task
        meta[TASK_OFFERS_KEY] = [o for o in offers if str(o.get("id")) != task_id]
        room.scenes_meta = json.dumps(meta, ensure_ascii=False)
        await session.commit()
    await _send_task_state(coord)
    await _broadcast_system(
        coord, f"📜 已接取委托：{task.get('title') or '未命名委托'}"
    )


async def _handle_decline_task(coord: RoomCoordinator, task_id_raw: Any) -> None:
    task_id = str(task_id_raw or "").strip()
    if not task_id:
        return
    async with SessionFactory() as session:
        room = await session.get(Room, coord.room_id)
        if room is None:
            return
        meta = _load_scene_meta(room.scenes_meta)
        offers = task_offers_from_meta(meta)
        meta[TASK_OFFERS_KEY] = [o for o in offers if str(o.get("id")) != task_id]
        room.scenes_meta = json.dumps(meta, ensure_ascii=False)
        await session.commit()
    await _send_task_state(coord)


async def _handle_advance(coord: RoomCoordinator, npc: NpcCard | None = None) -> None:
    if coord.ai_busy:
        await coord.broadcast(
            {
                "type": "error",
                "code": "ai_busy",
                "detail": "an AI turn is already in flight",
            }
        )
        return
    await _set_ai_busy(coord, True)
    try:
        await _run_ai_turn(coord, npc)
        if npc is not None:
            await _run_world_event_judge_only(coord)
    finally:
        await _set_ai_busy(coord, False)


def _player_state_summary(members: list[RoomMember]) -> str:
    """给导演的玩家数值/状态摘要（驱动剧情倾向）。"""
    parts: list[str] = []
    for m in members:
        if not m.stats:
            continue
        try:
            st = json.loads(m.stats)
        except Exception:
            continue
        bits: list[str] = []
        for k in ("金钱", "淫乱", "欲望", "露出经验", "受虐经验"):
            v = st.get(k)
            if isinstance(v, (int, float)) and v:
                bits.append(f"{k}{v}")
        states = st.get("状态") or []
        if states:
            bits.append("状态[" + "、".join(str(s) for s in states) + "]")
        aff = st.get("好感度") or {}
        if aff:
            bits.append("好感度{" + "、".join(f"{n}:{v}" for n, v in aff.items()) + "}")
        if bits:
            parts.append(f"{m.character_name}: " + " ".join(bits))
    return " ｜ ".join(parts)


_MOVE_INTENT_RE = re.compile(
    r"(去|前往|去往|到|抵达|赶往|奔赴|进入|返回|回到|离开|出发|动身|启程|带路|讨伐|清剿|狩猎|打(?:哥布林|魔物|怪物|兽人|史莱姆))"
)
_DEPARTURE_CONFIRM_RE = re.compile(
    r"^(好|嗯|行|可以|那就|走|走吧|出发|动身|启程|带路|开始吧|出发吧|走了)[，,。！!\s]*(走吧|出发|动身|启程|带路|开始吧)?$"
)
_SCENE_ALIASES: tuple[tuple[str, str], ...] = (
    (r"森林|林地", "森林"),
    (r"洞窟|洞穴|山洞", "洞窟"),
    (r"酒馆", "酒馆"),
    (r"冒险者公会|公会", "冒险者公会"),
    (r"借贷|贷款|放贷|商店", "借贷商店"),
    (r"旅店|旅馆|客栈", "旅店"),
    (r"青楼|娼馆|娼楼", "青楼街"),
    (r"城镇|镇上|街上", "城镇"),
)


def _known_scene_names(
    world_card: str | None,
    current_scene: str,
    all_active: list[NpcCard],
    scene_meta: str | None,
) -> list[str]:
    meta = _load_scene_meta(scene_meta)
    meta_unlocked = meta.get("_unlocked_scenes")
    if not isinstance(meta_unlocked, list):
        meta_unlocked = []
    known_scenes: list[str] = []
    for scene_name in [
        *scene_options(world_card),
        current_scene,
        *(n.scene or "" for n in all_active),
        *(str(s) for s in meta_unlocked),
    ]:
        scene_name = (scene_name or "").strip()[:64]
        if scene_name and scene_name not in known_scenes:
            known_scenes.append(scene_name)
    return known_scenes


def _is_departure_confirmation(text: str) -> bool:
    compact = re.sub(r"\s+", "", (text or "").strip())
    return bool(compact and _DEPARTURE_CONFIRM_RE.search(compact))


_UNKNOWN_SCENE_RE = re.compile(
    r"(?:去|前往|去往|赶往|进入|返回|回到|到|抵达|奔赴|启程去|出发去)"
    r"(?P<dest>[^，。！？,.!?\n]{1,30})"
)
_SCENE_THEN_DEPART_RE = re.compile(
    r"(?P<dest>[\u4e00-\u9fffA-Za-z0-9·・]{2,30})"
    r"[，。！？,.!?\s]*(?:走|走吧|出发|出发吧|动身|启程)"
)


def _clean_scene_candidate(candidate: str) -> str:
    text = re.sub(r"\s+", "", (candidate or "").strip())
    text = re.sub(r"^(一下|一趟|那个|这个|那座|这座|新的|新)", "", text)
    text = re.split(
        r"(?:打|讨伐|清剿|狩猎|调查|探索|寻找|找|见|拜访|救援|接应|看看|吧|吗|呢|了|去)",
        text,
        maxsplit=1,
    )[0]
    text = text.strip("「」『』《》“”\"'（）()[]【】、 ")
    if len(text) < 2:
        return ""
    blocked = {
        "那里",
        "这儿",
        "这里",
        "那儿",
        "那里吧",
        "外面",
        "里面",
        "前面",
        "后面",
        "门口",
        "柜台",
        "柜台边",
        "原位",
        "椅子",
        "大厅",
    }
    if text in blocked:
        return ""
    return text[:64]


def _infer_unknown_scene_destination(text: str) -> str:
    compact = re.sub(r"\s+", "", (text or "").strip())
    if not compact or not _MOVE_INTENT_RE.search(compact):
        return ""
    for match in _UNKNOWN_SCENE_RE.finditer(compact):
        dest = _clean_scene_candidate(match.group("dest"))
        if dest:
            return dest
    for match in _SCENE_THEN_DEPART_RE.finditer(compact):
        dest = _clean_scene_candidate(match.group("dest"))
        if dest:
            return dest
    return ""


def _infer_scene_destination(
    text: str, known_scenes: list[str], *, require_motion: bool = True
) -> str:
    compact = re.sub(r"\s+", "", (text or "").strip())
    if not compact:
        return ""
    has_scene_departure = bool(_SCENE_THEN_DEPART_RE.search(compact))
    if require_motion and not (_MOVE_INTENT_RE.search(compact) or has_scene_departure):
        return ""

    for scene_name in sorted(known_scenes, key=len, reverse=True):
        if scene_name and scene_name in compact:
            return scene_name

    known = set(known_scenes)
    for pattern, target in _SCENE_ALIASES:
        if re.search(pattern, compact) and (not known or target in known):
            return target
    return ""


async def _maybe_apply_player_scene_intent(
    coord: RoomCoordinator, content: str, *, raw_content: str = ""
) -> bool:
    """Turn explicit player travel intent into a scene change before NPC reactions."""
    async with SessionFactory() as session:
        room = await session.get(Room, coord.room_id)
        if room is None:
            return False
        all_active = list(
            await session.scalars(
                select(NpcCard).where(
                    NpcCard.room_id == coord.room_id,
                    NpcCard.active.is_(True),
                )
            )
        )
        history = await messages_after(session, coord.room_id, 0, limit=24)
        current_scene = await ensure_room_scene(session, room)
        known_scenes = _known_scene_names(
            room.world_card,
            current_scene,
            all_active,
            room.scenes_meta,
        )

    dest = _infer_scene_destination(raw_content or content, known_scenes)
    if not dest and raw_content and raw_content != content:
        dest = _infer_scene_destination(content, known_scenes)
    reason = f"玩家明确提出前往{dest}" if dest else ""

    if not dest and (
        _is_departure_confirmation(raw_content) or _is_departure_confirmation(content)
    ):
        for msg in reversed(history[:-1]):
            if msg.author_type != "user":
                continue
            dest = _infer_scene_destination(
                msg.content, known_scenes, require_motion=False
            )
            if dest:
                reason = f"玩家确认出发，承接先前目的地：{msg.content[:60]}"
                break

    if not dest or dest == current_scene:
        return False
    await _auto_switch_scene(
        coord,
        dest,
        reason or f"玩家决定前往{dest}",
        advance_steps=1,
        time_reason=f"前往{dest}",
    )
    return True


_ENRICH_EVERY_BEATS = 3  # 每 3 拍刷新一次"已了解"档案，控成本。


async def _enrich_npcs(coord: RoomCoordinator, npc_ids: list[int]) -> None:
    """后台：把最近对话里新浮现的信息并入这些 NPC 的"已了解"档案。"""
    if not npc_ids:
        return
    async with SessionFactory() as session:
        history = await messages_after(session, coord.room_id, 0, limit=200)
    recent = "\n".join(
        f"{m.speaker_label}: {m.content}"
        for m in history[-16:]
        if m.author_type in {"user", "ai"}
    )
    if not recent:
        return
    changed = False
    for npc_id in npc_ids:
        async with SessionFactory() as session:
            npc = await session.get(NpcCard, npc_id)
            if npc is None:
                continue
            name, persona, prior = npc.name, npc.persona, npc.discovered
        updated = await enrich_npc(name, persona, prior, recent)
        if updated and updated != (prior or ""):
            async with SessionFactory() as session:
                npc = await session.get(NpcCard, npc_id)
                if npc is not None:
                    npc.discovered = updated
                    await session.commit()
                    changed = True
    if changed:
        await coord.broadcast({"type": "cards_changed"})


async def _broadcast_ending(coord: RoomCoordinator, ending: str, user_id: int) -> None:
    """广播结局：AI 生成终局旁白 + ending 事件。"""
    try:
        narr = (
            await default_provider().complete(
                [
                    {
                        "role": "system",
                        "content": (
                            "你是《女骑士模拟器》的结局叙述者。给定结局名，"
                            "用 2-4 句沉浸描写主角走向这个结局的终局画面，"
                            "第二人称、黑暗露骨、不跳戏。"
                        ),
                    },
                    {"role": "user", "content": f"结局：{ending}"},
                ]
            )
        ).strip()
    except Exception:  # noqa: BLE001
        narr = ""
    text = f"【结局：{ending}】\n{narr}" if narr else f"【结局：{ending}】"
    msg = await _persist_message(
        room_id=coord.room_id,
        author_type="ai",
        speaker_label="旁白",
        content=text,
        author_user_id=None,
    )
    await coord.broadcast({"type": "message", "message": _msg_payload(msg)})
    await coord.broadcast({"type": "ending", "name": ending, "user_id": user_id})


async def _advance_time(coord: RoomCoordinator, steps: int, reason: str) -> None:
    """Advance the room clock by day phases and broadcast the visible clock."""
    settlements: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
    imprison_effects: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
    endings: list[tuple[int, str]] = []
    old_label = ""
    new_label = ""
    old_week = 1
    new_week = 1
    async with SessionFactory() as session:
        room = await session.get(Room, coord.room_id)
        if room is None:
            return
        old_clock, new_clock = advance_room_time(room, steps)
        old_label, new_label = old_clock.label, new_clock.label
        old_week, new_week = old_clock.week, new_clock.week

        members = list(
            await session.scalars(
                select(RoomMember).where(RoomMember.room_id == coord.room_id)
            )
        )

        for m in members:
            cur = json.loads(m.stats) if m.stats else default_stats()

            # 月末结算（含债务利息）
            if new_week > old_week and new_week % 4 == 0:
                new_stats, delta = monthend_settle(cur)
                m.stats = json.dumps(new_stats, ensure_ascii=False)
                settlements.append((m.user_id, new_stats, delta))
                cur = new_stats

            # 监禁 tick（每次时间推进）
            impr_delta = tick_imprisonment(cur)
            if impr_delta:
                new_stats = apply_delta(cur, impr_delta)
                m.stats = json.dumps(new_stats, ensure_ascii=False)
                imprison_effects.append((m.user_id, new_stats, impr_delta))
                cur = new_stats

            # 结局检查
            ending = check_ending(cur)
            if ending:
                endings.append((m.user_id, ending))

        current_scene = room.current_scene or ""
        await session.commit()
        payload = _time_payload(room)

    await coord.broadcast(payload)
    if new_week != old_week:
        await coord.broadcast({"type": "week", "week": new_week})
    await _broadcast_system(coord, f"🕰 时间推进：{old_label} → {new_label}（{reason}）")

    # 月末结算广播
    if settlements:
        msg = await _persist_message(
            room_id=coord.room_id,
            author_type="ai",
            speaker_label="旁白",
            content=(f"💰 {new_label}·月末结算：食宿开销已扣，囊中渐空者需早作打算。"),
            author_user_id=None,
        )
        await coord.broadcast({"type": "message", "message": _msg_payload(msg)})
        for uid, new_stats, delta in settlements:
            await coord.broadcast(
                {"type": "stats", "user_id": uid, "stats": new_stats, "delta": delta}
            )

    # 监禁推进广播
    if imprison_effects:
        for uid, new_stats, delta in imprison_effects:
            await coord.broadcast(
                {"type": "stats", "user_id": uid, "stats": new_stats, "delta": delta}
            )

    # 结局触发广播
    for uid, ending in endings:
        await _broadcast_ending(coord, ending, uid)

    # 时间推进事件触发
    if current_scene and new_label:
        phase = new_label.split("·")[-1]  # 从 "冒险第1周·第1天·清晨" 取最后一段
        event = roll_time_event(current_scene, phase)
    else:
        event = None
    if event and event.get("type") != "nothing":
        event_text = event.get("text", "")
        if event.get("type") == "encounter":
            npc = pick_event_encounter_npc(event, coord.room_id)
            if npc:
                async with SessionFactory() as session:
                    session.add(npc)
                    await session.commit()
                await coord.broadcast({"type": "cards_changed"})
            await _broadcast_system(coord, f"⚔ {event_text}")
        elif event.get("type") == "find":
            item_name = event.get("item", "")
            quantity = event.get("quantity", 1)
            async with SessionFactory() as session:
                members = list(
                    await session.scalars(
                        select(RoomMember).where(RoomMember.room_id == coord.room_id)
                    )
                )
                for m in members:
                    cur = json.loads(m.stats) if m.stats else default_stats()
                    items = cur.get("物品") or []
                    for _ in range(quantity):
                        items.append(item_name)
                    cur["物品"] = items
                    m.stats = json.dumps(cur, ensure_ascii=False)
                await session.commit()
            await _broadcast_system(coord, f"🎒 {event_text}")
        else:
            await _broadcast_system(coord, event_text)

    tick_cooldowns()


async def _judge_world_event_plan(
    coord: RoomCoordinator,
    *,
    force_timeskip: bool = False,
    allow_acts: bool = True,
    allow_auto_changes: bool = True,
) -> tuple[dict[str, Any], str, list[NpcCard]]:
    async with SessionFactory() as session:
        room = await session.get(Room, coord.room_id)
        if room is None:
            return {}, "", []
        members = list(
            await session.scalars(
                select(RoomMember).where(RoomMember.room_id == coord.room_id)
            )
        )
        all_active = list(
            await session.scalars(
                select(NpcCard).where(
                    NpcCard.room_id == coord.room_id,
                    NpcCard.active.is_(True),
                )
            )
        )
        history = await messages_after(session, coord.room_id, 0, limit=200)
        world_card = room.world_card
        current_scene = await ensure_room_scene(session, room)
        scene_meta = room.scenes_meta

    # 场景分区：只让当前场景（或随队 scene=None）的 NPC 参与本拍。
    # 自由世界（current_scene==""）不分区，全员在场。
    npcs = (
        [n for n in all_active if not n.scene or n.scene == current_scene]
        if current_scene
        else all_active
    )
    recent = "\n".join(
        f"{m.speaker_label}: {m.content}"
        for m in history[-8:]
        if m.author_type in {"user", "ai"}
    )
    meta = _load_scene_meta(scene_meta)
    meta_unlocked = meta.get("_unlocked_scenes")
    if not isinstance(meta_unlocked, list):
        meta_unlocked = []
    known_scenes: list[str] = []
    for scene_name in [
        *scene_options(world_card),
        current_scene,
        *(n.scene or "" for n in all_active),
        *(str(s) for s in meta_unlocked),
    ]:
        scene_name = (scene_name or "").strip()[:64]
        if scene_name and scene_name not in known_scenes:
            known_scenes.append(scene_name)
    world_lore = await _world_lore_block(
        world_card,
        _ksim_seed_query(
            current_scene,
            f"{recent} {_player_state_summary(members)} "
            + " ".join(n.name for n in npcs[:6]),
        ),
        5,
    )
    plan = await judge_world_beat(
        world_card,
        members,
        npcs,
        recent,
        force_timeskip=force_timeskip,
        allow_time_jump=force_timeskip,
        allow_auto_changes=allow_auto_changes,
        allow_acts=allow_acts,
        player_state=_player_state_summary(members),
        scene=current_scene,
        known_scenes=known_scenes,
        world_lore=world_lore,
    )
    return plan, current_scene, npcs


async def _auto_switch_scene(
    coord: RoomCoordinator,
    dest: str,
    reason: str,
    *,
    advance_steps: int = 0,
    time_reason: str | None = None,
) -> str:
    """Apply a director-triggered scene change without stealing NPC agency."""
    dest = (dest or "").strip()[:64]
    if not dest:
        return ""
    async with SessionFactory() as session:
        room = await session.get(Room, coord.room_id)
        if room is None:
            return ""
        old = room.current_scene or ""
        if dest == old:
            return old
        meta = _load_scene_meta(room.scenes_meta)
        leaving_index = room_time(room).index
        last_seen = meta.get("_scene_last_seen")
        if not isinstance(last_seen, dict):
            last_seen = {}
        if old:
            last_seen[old] = leaving_index
        meta["_scene_last_seen"] = last_seen
        unlocked = meta.get("_unlocked_scenes")
        if not isinstance(unlocked, list):
            unlocked = []
        if dest not in unlocked:
            unlocked.append(dest)
        meta["_unlocked_scenes"] = unlocked
        initialized = meta.get("_scene_initialized")
        if not isinstance(initialized, list):
            initialized = []
        was_initialized = dest in initialized
        dest_last_seen = last_seen.get(dest)
        room.current_scene = dest
        room.scenes_meta = json.dumps(meta, ensure_ascii=False)
        await session.commit()

    await coord.broadcast({"type": "scene", "scene": dest})
    await coord.broadcast({"type": "cards_changed"})
    await _broadcast_system(
        coord,
        f"📍 自动场景变化｜{old or '自由场景'} → {dest}（{reason or '剧情自然转场'}）",
    )
    await _record_scene_log(
        coord,
        dest,
        "场景变化",
        f"{old or '自由场景'} → {dest}（{reason or '剧情自然转场'}）",
        kind="scene_change",
    )

    if advance_steps > 0:
        await _advance_time(
            coord,
            advance_steps,
            time_reason or reason or f"前往{dest}",
        )

    async with SessionFactory() as session:
        room = await session.get(Room, coord.room_id)
        now_index = room_time(room).index if room is not None else 0
        meta = _load_scene_meta(room.scenes_meta if room is not None else None)
        initialized = meta.get("_scene_initialized")
        if not isinstance(initialized, list):
            initialized = []

    dest_npcs = await _scene_npcs(coord, dest)
    if not was_initialized:
        await _show_scene_initialization(coord, dest, dest_npcs)
        if dest not in initialized:
            initialized.append(dest)
        async with SessionFactory() as session:
            room = await session.get(Room, coord.room_id)
            if room is not None:
                meta = _load_scene_meta(room.scenes_meta)
                meta["_scene_initialized"] = initialized
                room.scenes_meta = json.dumps(meta, ensure_ascii=False)
                await session.commit()
    elif dest_last_seen is not None:
        try:
            gap_start = int(dest_last_seen)
        except (TypeError, ValueError):
            gap_start = now_index
        await _show_scene_elapsed_simulation(
            coord, dest, dest_npcs, gap_start, now_index
        )

    asyncio.create_task(
        asyncio.to_thread(
            memory_store.remember,
            f"room_{coord.room_id}",
            "[自动场景转换]",
            f"{old or '自由场景'} -> {dest}: {reason}",
        )
    )
    return dest


async def _apply_world_event_plan(
    coord: RoomCoordinator,
    plan: dict[str, Any],
    current_scene: str,
    *,
    force_timeskip: bool = False,
) -> tuple[list[NpcCard], str]:
    """Apply world-event judge outputs without deciding who speaks."""
    unlocked_scenes = [
        str(s).strip()[:64] for s in plan.get("unlock_scenes", []) if str(s).strip()
    ]
    if unlocked_scenes:
        async with SessionFactory() as session:
            room = await session.get(Room, coord.room_id)
            if room is not None:
                meta: dict[str, Any] = (
                    json.loads(room.scenes_meta) if room.scenes_meta else {}
                )
                unlocked = meta.get("_unlocked_scenes")
                if not isinstance(unlocked, list):
                    unlocked = []
                changed = False
                for scene_name in unlocked_scenes:
                    if scene_name not in unlocked:
                        unlocked.append(scene_name)
                        changed = True
                if changed:
                    meta["_unlocked_scenes"] = unlocked
                    room.scenes_meta = json.dumps(meta, ensure_ascii=False)
                    await session.commit()
                    await coord.broadcast({"type": "cards_changed"})

    effective_scene = current_scene
    try:
        time_steps = int(plan.get("time_advance_steps") or 0)
    except (TypeError, ValueError):
        time_steps = 0
    time_steps = max(0, min(2555, time_steps))
    if force_timeskip:
        time_steps = 0
    scene_change = (
        str(plan.get("scene_change") or "").strip()[:64]
        if plan.get("scene_change")
        else ""
    )
    if scene_change and scene_change != current_scene:
        effective_scene = await _auto_switch_scene(
            coord,
            scene_change,
            str(plan.get("scene_reason") or "").strip()[:160] or "剧情自然转场",
            advance_steps=time_steps,
            time_reason=str(plan.get("time_reason") or "").strip()[:160] or None,
        )
        time_steps = 0
    if time_steps > 0:
        await _advance_time(
            coord,
            time_steps,
            str(plan.get("time_reason") or "").strip()[:160] or "剧情自然经过",
        )

    introduced: list[NpcCard] = []
    for draft in plan.get("introduce", []):
        async with SessionFactory() as session:
            new_npc = NpcCard(
                room_id=coord.room_id,
                name=draft["name"],
                persona=draft.get("persona", ""),
                appearance=draft.get("appearance"),
                voice_id=draft.get("voice_id"),
                scene=effective_scene or None,
                created_by_ai=True,
            )
            session.add(new_npc)
            await session.commit()
            await session.refresh(new_npc)
        introduced.append(new_npc)
    if introduced:
        await coord.broadcast({"type": "cards_changed"})

    time_jump = plan.get("time_jump")
    if force_timeskip and not time_jump:
        time_jump = "时间向前流逝，世界局势在这段空白里继续推进。"
        plan["time_jump"] = time_jump
    if time_jump:
        summary = time_jump
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
    elif plan.get("narration"):
        narr_msg = await _broadcast_narration(coord, plan.get("narration"))
        if narr_msg is not None:
            asyncio.create_task(
                asyncio.to_thread(
                    memory_store.remember,
                    f"room_{coord.room_id}",
                    "[旁白补叙]",
                    narr_msg.content,
                )
            )

    return introduced, effective_scene


async def _run_world_event_judge_only(
    coord: RoomCoordinator, *, force_timeskip: bool = False
) -> None:
    plan, current_scene, _npcs = await _judge_world_event_plan(
        coord, force_timeskip=force_timeskip, allow_acts=False
    )
    if not plan:
        return
    await _apply_world_event_plan(
        coord, plan, current_scene, force_timeskip=force_timeskip
    )


async def _self_motivated_npcs(
    coord: RoomCoordinator, candidates: list[NpcCard], current_scene: str
) -> list[NpcCard]:
    """Let each in-scene NPC decide whether they personally want to speak."""
    if not candidates:
        return []
    async with SessionFactory() as session:
        room = await session.get(Room, coord.room_id)
        if room is None:
            return []
        members = list(
            await session.scalars(
                select(RoomMember).where(RoomMember.room_id == coord.room_id)
            )
        )
        history = await messages_after(session, coord.room_id, 0, limit=200)

    recent = "\n".join(
        f"{m.speaker_label}: {m.content}"
        for m in history[-8:]
        if m.author_type in {"user", "ai"}
    )
    player_state = _player_state_summary(members)
    scored: list[tuple[int, int, NpcCard]] = []
    async with SessionFactory() as session:
        clock_room = await session.get(Room, coord.room_id)
        clock_label = (
            room_time(clock_room).label if clock_room is not None else "未知时间"
        )
    # Keep the inner-vote cost bounded for crowded scenes. Selection is still
    # per-NPC; the cap only prevents one click from spawning dozens of calls.
    for order, npc in enumerate(candidates[:8]):
        others = [
            f"{n.name}：{n.discovered or n.persona}"
            for n in candidates
            if n.id != npc.id
        ]
        try:
            decision = await judge_npc_impulse(
                room,
                members,
                npc,
                others,
                recent,
                current_scene=current_scene,
                player_state=player_state,
                brain=brain,
            )
        except Exception as exc:  # noqa: BLE001 — one quiet NPC should not break a beat
            print(
                f"[NPC-IMPULSE] room={coord.room_id} npc={npc.name} error={exc}",
                flush=True,
            )
            continue
        speak = bool(decision.get("speak"))
        urgency = int(decision.get("urgency") or 0)
        reason = decision.get("reason") or "无明确理由"
        await _broadcast_system(
            coord,
            (
                f"🧠 NPC内心｜{clock_label}｜"
                f"{current_scene or '自由场景'}｜{npc.name}\n"
                f"想发言：{'是' if speak else '否'}｜"
                f"紧迫度：{urgency}/5｜理由：{reason}"
            ),
        )
        if decision.get("speak"):
            print(
                f"[NPC-IMPULSE] room={coord.room_id} npc={npc.name} "
                f"urgency={urgency} reason={reason}",
                flush=True,
            )
            scored.append((urgency, -order, npc))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [npc for _urgency, _order, npc in scored[:3]]


async def _simulate_offscreen_scenes(coord: RoomCoordinator) -> None:
    """Let NPCs in other scenes keep moving after each player beat."""
    async with SessionFactory() as session:
        room = await session.get(Room, coord.room_id)
        if room is None:
            return
        current_scene = await ensure_room_scene(session, room)
        world_card = room.world_card
        clock_label = room_time(room).label
        scene_logs = logs_from_meta(room.scenes_meta)
        all_active = list(
            await session.scalars(
                select(NpcCard).where(
                    NpcCard.room_id == coord.room_id,
                    NpcCard.active.is_(True),
                )
            )
        )

    scene_map: dict[str, list[NpcCard]] = {}
    for npc in all_active:
        npc_scene = (npc.scene or "").strip()
        if not npc_scene or npc_scene == current_scene:
            continue
        scene_map.setdefault(npc_scene, []).append(npc)
    if not scene_map:
        return

    for scene, npcs in list(scene_map.items())[:5]:
        npc_lines = "\n".join(
            f"- {n.name}：{n.discovered or n.persona}" for n in npcs[:6]
        )
        local_recent = (
            "\n".join(
                f"{entry['time_label']} {entry['speaker_label']}: {entry['content']}"
                for entry in scene_logs.get(scene_key(scene), [])[-6:]
            )
            or "（本场景暂无旧记录）"
        )
        lore = await _world_lore_block(
            world_card,
            _ksim_seed_query(scene, f"{npc_lines} {local_recent}"),
            3,
        )
        try:
            raw = (
                await brain.complete(
                    [
                        {
                            "role": "system",
                            "content": (
                                "你是离屏场景模拟器。玩家正在别处行动时，"
                                "这个场景里的 NPC 也会按自己的目标、"
                                "关系和环境继续行动。"
                                "写 1-2 句调试记录，可包含 NPC 之间互动、"
                                "移动、筹划、交易或等待。"
                                "只能依据本场景过往记录、NPC 自身目标和公开世界常识；"
                                "不要让他们知道玩家没公开的信息，不要替玩家行动，不写正式对白。"
                                '只输出 JSON：{"text":"给开发者看的场景记录",'
                                '"moves":[{"npc":"NPC名","scene":"目标场景"}]}。'
                                "只有 NPC 明确离开本场景前往别处时才写 moves；"
                                "否则 moves=[]。"
                            ),
                        },
                        {
                            "role": "user",
                            "content": (
                                f"当前时间：{clock_label}\n"
                                f"离屏场景：{scene}\n"
                                f"离屏 NPC：\n{npc_lines}\n\n"
                                f"本场景过往记录：\n{local_recent}"
                                + (f"\n\n{lore}" if lore else "")
                            ),
                        },
                    ]
                )
            ).strip()
        except Exception as exc:  # noqa: BLE001
            print(
                f"[OFFSCREEN] room={coord.room_id} scene={scene} error={exc}",
                flush=True,
            )
            continue
        text, moves = parse_scene_simulation_output(
            raw,
            [n.name for n in npcs],
            source_scene=scene,
        )
        if text:
            await _record_scene_log(coord, scene, "离屏行动", text, kind="offscreen")
            await _apply_npc_scene_moves(
                coord,
                scene,
                moves,
                reason="离屏行动",
            )


async def _handle_story_beat(
    coord: RoomCoordinator,
    *,
    force_timeskip: bool = False,
    advance_clock: bool = True,
    allow_auto_changes: bool = True,
) -> None:
    """故事拍：世界事件裁判先处理环境，再由 NPC 自己决定是否发言。"""
    if coord.ai_busy:
        await coord.broadcast(
            {"type": "error", "code": "ai_busy", "detail": "上一拍还没演完"}
        )
        return
    await _set_ai_busy(coord, True)
    try:
        if advance_clock:
            steps = len(TIME_PHASES) if force_timeskip else 1
            await _advance_time(
                coord, steps, "显式时间推进" if force_timeskip else "显式剧情推进"
            )
        plan, current_scene, _npcs = await _judge_world_event_plan(
            coord,
            force_timeskip=force_timeskip,
            allow_auto_changes=allow_auto_changes,
        )
        if not plan:
            return
        introduced, effective_scene = await _apply_world_event_plan(
            coord, plan, current_scene, force_timeskip=force_timeskip
        )
        npcs = await _scene_npcs(coord, effective_scene)

        by_id: dict[int, NpcCard] = {}
        for n in [*npcs, *introduced]:
            by_id[n.id] = n
        speakers = await _self_motivated_npcs(
            coord, list(by_id.values()), effective_scene
        )
        acted = False
        spoke_ids: list[int] = []
        for npc in speakers:
            await _run_ai_turn(coord, npc)
            acted = True
            spoke_ids.append(npc.id)

        if (
            not acted
            and not plan.get("time_jump")
            and not plan.get("narration")
            and not plan.get("time_advance_steps")
            and not plan.get("scene_change")
        ):
            await _broadcast_narration(coord, NARRATOR_FALLBACK)
    finally:
        await _set_ai_busy(coord, False)

    # 信息渐显：节流地后台刷新"玩家逐渐了解到的 NPC 信息"（不挡主流程）。
    if spoke_ids:
        coord.beats_since_enrich += 1
        if coord.beats_since_enrich >= _ENRICH_EVERY_BEATS:
            coord.beats_since_enrich = 0
            asyncio.create_task(_enrich_npcs(coord, list(set(spoke_ids))))


async def _handle_goto_scene(coord: RoomCoordinator, dest: str) -> None:
    """切换当前场景：记录离开时间→行程耗时→初始化/离屏补模拟→此地 NPC 反应。"""
    dest = (dest or "").strip()[:64]
    if not dest:
        return
    if coord.ai_busy:
        await coord.broadcast(
            {"type": "error", "code": "ai_busy", "detail": "上一拍还没演完"}
        )
        return

    await _set_ai_busy(coord, True)
    async with SessionFactory() as session:
        room = await session.get(Room, coord.room_id)
        if room is None:
            await _set_ai_busy(coord, False)
            return
        old = room.current_scene or ""
        if dest == old:
            await _set_ai_busy(coord, False)
            return  # 已在此场景
        meta = _load_scene_meta(room.scenes_meta)
        leaving_index = room_time(room).index
        last_seen = meta.get("_scene_last_seen")
        if not isinstance(last_seen, dict):
            last_seen = {}
        if old:
            last_seen[old] = leaving_index
        meta["_scene_last_seen"] = last_seen
        unlocked = meta.get("_unlocked_scenes")
        if not isinstance(unlocked, list):
            unlocked = []
        if dest not in unlocked:
            unlocked.append(dest)
            meta["_unlocked_scenes"] = unlocked
        initialized = meta.get("_scene_initialized")
        if not isinstance(initialized, list):
            initialized = []
        was_initialized = dest in initialized
        dest_last_seen = last_seen.get(dest)
        room.current_scene = dest
        room.scenes_meta = json.dumps(meta, ensure_ascii=False)
        await session.commit()
        members = list(
            await session.scalars(
                select(RoomMember).where(RoomMember.room_id == coord.room_id)
            )
        )

    party = "、".join(m.character_name for m in members) or "一行人"
    try:
        await _advance_time(coord, 1, f"前往{dest}")
        async with SessionFactory() as session:
            room = await session.get(Room, coord.room_id)
            if room is None:
                return
            now_index = room_time(room).index
            world_card = room.world_card
            meta = _load_scene_meta(room.scenes_meta)
            initialized = meta.get("_scene_initialized")
            if not isinstance(initialized, list):
                initialized = []
        dest_npcs = await _scene_npcs(coord, dest)
        if not was_initialized:
            await _show_scene_initialization(coord, dest, dest_npcs)
            if dest not in initialized:
                initialized.append(dest)
            async with SessionFactory() as session:
                room = await session.get(Room, coord.room_id)
                if room is not None:
                    meta = _load_scene_meta(room.scenes_meta)
                    meta["_scene_initialized"] = initialized
                    room.scenes_meta = json.dumps(meta, ensure_ascii=False)
                    await session.commit()
        elif dest_last_seen is not None:
            try:
                gap_start = int(dest_last_seen)
            except (TypeError, ValueError):
                gap_start = now_index
            await _show_scene_elapsed_simulation(
                coord, dest, dest_npcs, gap_start, now_index
            )

        if dest_last_seen is None:
            ask = f"{party}来到「{dest}」。用一句话描写初次踏入此地所见的场景气氛。"
        else:
            try:
                gap = max(0, now_index - int(dest_last_seen))
            except (TypeError, ValueError):
                gap = 0
            ask = (
                f"{party}时隔约 {gap} 个时间节点重回「{dest}」。用一两句话补叙："
                "这段时间这里发生/变化了什么，以及此刻重回所见。"
            )
        lore = await _world_lore_block(
            world_card,
            _ksim_seed_query(dest, f"{ask} " + " ".join(n.name for n in dest_npcs)),
            4,
        )
        try:
            text = await brain.complete(
                [
                    {
                        "role": "system",
                        "content": (
                            "你是角色扮演旁白。简洁、有画面感，只输出旁白文字。"
                            "如果有世界设定片段，必须贴合这些片段。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": ask + (f"\n\n{lore}" if lore else ""),
                    },
                ]
            )
        except Exception:
            text = ""
    finally:
        await _set_ai_busy(coord, False)

    text = (text or "").strip() or f"{party}来到了「{dest}」。"

    msg = await _persist_message(
        room_id=coord.room_id,
        author_type="ai",
        speaker_label="旁白",
        content=f"📍 {text}",
        author_user_id=None,
    )
    await coord.broadcast({"type": "scene", "scene": dest})
    await coord.broadcast({"type": "message", "message": _msg_payload(msg)})
    asyncio.create_task(
        asyncio.to_thread(
            memory_store.remember,
            f"room_{coord.room_id}",
            "[场景转换]",
            f"{party}前往{dest}：{text}",
        )
    )
    # 让此地 NPC 对到来做出反应，但场景移动已经消耗过时间，不再额外推进。
    await _handle_story_beat(coord, advance_clock=False, allow_auto_changes=False)


_NSFW_SCENE_RE = re.compile(
    r"(R18|r18|nsfw|性爱|性交|做爱|强奸|轮奸|凌辱|调教|侵犯|插入|射精|精液|裸|"
    r"乳房|阴道|肉穴|阴茎|口交|肛交|自慰|高潮|青楼|娼馆|卖淫|淫乱|发情|媚药)"
)


def _infer_scene_nsfw(scene_text: str, members: list[RoomMember]) -> bool:
    if _NSFW_SCENE_RE.search(scene_text or ""):
        return True
    for member in members:
        if not member.stats:
            continue
        try:
            stats = json.loads(member.stats)
        except Exception:
            continue
        states = " ".join(str(s) for s in (stats.get("状态") or []))
        if _NSFW_SCENE_RE.search(states):
            return True
        for key in ("淫乱", "欲望", "露出经验", "口腔经验", "肛门经验", "阴道经验"):
            val = stats.get(key)
            if isinstance(val, (int, float)) and val >= 30:
                return True
    return False


async def _handle_image(
    coord: RoomCoordinator, user: User, data: dict[str, Any]
) -> None:
    """生图房间动作：最近剧情 + 外貌卡 → 合成 prompt → raw 生成 → 广播图消息。

    ~40s，跑成后台任务，不阻塞聊天；image_busy 防并发。
    """
    if not settings.media_generation_enabled:
        await coord.broadcast(
            {"type": "error", "code": "image_disabled", "detail": "生图已临时关闭"}
        )
        return
    if coord.image_busy:
        await coord.broadcast(
            {"type": "error", "code": "image_busy", "detail": "上一张图还在生成"}
        )
        return
    coord.image_busy = True
    await coord.broadcast(
        {
            "type": "image_pending",
            "user_id": user.id,
            "display_name": user.display_name,
        }
    )
    try:
        async with SessionFactory() as session:
            room = await session.get(Room, coord.room_id)
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
            current_scene = (
                await ensure_room_scene(session, room) if room is not None else ""
            )
        recent_scene_text = (
            "\n".join(
                f"{m.speaker_label}: {m.content}"
                for m in history[-6:]
                if m.author_type in {"user", "ai"}
            )
            or "一个角色扮演场景"
        )
        scene_text = f"当前场景：{current_scene or '自由场景'}\n{recent_scene_text}"
        nsfw = _infer_scene_nsfw(scene_text, members)
        if not nsfw:
            try:
                narr = (
                    await brain.complete(
                        [
                            {
                                "role": "system",
                                "content": (
                                    "你是角色扮演旁白。根据最近对话和当前地点，用一两句"
                                    "中文描写此刻可见的场景、人物站位、气氛和光线。"
                                    "只写画面，不替玩家或 NPC 说话。"
                                ),
                            },
                            {
                                "role": "user",
                                "content": (f"最近对话：\n{scene_text}"),
                            },
                        ]
                    )
                ).strip()
            except Exception:
                narr = ""
            if narr:
                # Use the visual narration only as prompt context. Scene image
                # generation should not add a new timeline message.
                scene_text = f"{scene_text}\n旁白: {narr}"
        # 外貌按"这一幕实际出场的角色"(玩家+NPC，看最近发言人)取各自外貌卡，
        # 而非固定取两个玩家——NPC 才常是画面主角。
        look: dict[str, str] = {}
        avatar_refs: dict[str, str] = {}
        for m in members:
            if m.character_name:
                note = m.appearance or m.character_name
                if m.persona:
                    note = f"{note}. Personality and expression cue: {m.persona}"
                look[m.character_name] = note
                ref = _media_url_to_path(m.avatar_url)
                if ref:
                    avatar_refs[m.character_name] = ref
        for n in npcs:
            note = n.appearance or n.name
            if n.persona:
                note = f"{note}. Personality and expression cue: {n.persona}"
            look[n.name] = note
            ref = _media_url_to_path(n.avatar_url)
            if ref:
                avatar_refs[n.name] = ref
        scene_chars: list[str] = []
        for msg in reversed(history[-8:]):
            lbl = msg.speaker_label
            if (
                msg.author_type in {"user", "ai"}
                and lbl in look
                and lbl not in scene_chars
                and lbl not in {"旁白", "AI"}
            ):
                scene_chars.append(lbl)
            if len(scene_chars) >= 4:
                break
        if not scene_chars:
            scene_chars = [m.character_name for m in members if m.character_name][:4]
        appearances = [f"{c}: {look[c]}" for c in scene_chars if c in look][:4]
        two_person = len(appearances) >= 2
        # 人物/场景一致性：同一房间、地点、登场角色组得到稳定 seed；
        # 外貌卡 + 最多两张头像参考继续约束人物细节。
        if scene_chars:
            seed_key = "|".join(
                [str(coord.room_id), current_scene or "自由场景", *sorted(scene_chars)]
            )
            seed = int(hashlib.sha1(seed_key.encode("utf-8")).hexdigest()[:8], 16)
        else:
            seed = char_seed(coord.room_id, current_scene or "自由场景")
        reference_image_paths = [
            avatar_refs[c] for c in scene_chars[:2] if avatar_refs.get(c)
        ]
        try:
            # Anima DiT 原生多主体：双人互动走双人提示词，但最终仍合成一段
            # prompt；角色一致性由姓名+外貌事实+头像参考共同约束，不做区域 mask。
            prompt = await build_scene_prompt(
                scene_text, appearances, nsfw=nsfw, two_person=two_person
            )
            # scene_prompt returns tag-soup format for both single and duo
            positive = prompt.get("positive", "")
            res = await generate_anima(
                positive,
                prompt.get("negative", ""),
                landscape=two_person,
                seed=seed,
                reference_image_paths=reference_image_paths,
                ipadapter_weight=0.48 if two_person else 0.48,
                upscale=False,
                tile_refine=False,
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
            await _record_scene_log(coord, current_scene, "场景图", url, kind="image")
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


async def _judge_and_apply_stats(coord: RoomCoordinator, user_id: int) -> None:
    """裁判：本回合剧情 → AI 判定属性增量 → 应用到该玩家 + 广播。"""
    async with SessionFactory() as session:
        member = await session.scalar(
            select(RoomMember).where(
                RoomMember.room_id == coord.room_id,
                RoomMember.user_id == user_id,
            )
        )
        if member is None:
            return
        player_label = member.character_name
        history = await messages_after(session, coord.room_id, 0, limit=200)
        current = json.loads(member.stats) if member.stats else default_stats()
    scene = "\n".join(
        f"{m.speaker_label}: {m.content}"
        for m in history[-6:]
        if m.author_type in {"user", "ai"}
    )
    if not scene.strip():
        return
    player_scene = "\n".join(
        f"{m.speaker_label}: {m.content}"
        for m in history[-6:]
        if m.author_type == "user"
        and m.author_user_id == user_id
        and m.speaker_label == player_label
    )
    try:
        delta = await judge_stat_delta(scene, current, deterministic_text=player_scene)
    except Exception:  # noqa: BLE001 — best-effort, never break the room
        delta = {}
    if not delta:
        return
    new_stats = apply_delta(current, delta)
    async with SessionFactory() as session:
        member = await session.scalar(
            select(RoomMember).where(
                RoomMember.room_id == coord.room_id,
                RoomMember.user_id == user_id,
            )
        )
        if member is None:
            return
        member.stats = json.dumps(new_stats, ensure_ascii=False)
        await session.commit()
    await coord.broadcast(
        {"type": "stats", "user_id": user_id, "stats": new_stats, "delta": delta}
    )

    # 结局触发：数值/状态跨阈值 → 旁白叙述终局 + ending 事件。
    ending = check_ending(new_stats)
    if ending:
        await _broadcast_ending(coord, ending, user_id)


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
        room = await session.get(Room, room_id)
        if room is not None:
            await ensure_room_scene(session, room)
        history = await messages_after(session, room_id, 0, limit=200)

    await websocket.accept()
    coord = hub.get(room_id)
    coord.sockets[websocket] = user

    await websocket.send_json(
        {"type": "history", "messages": [_msg_payload(m) for m in history]}
    )
    await websocket.send_json({"type": "ai_status", "busy": coord.ai_busy})
    if room is not None:
        await websocket.send_json(_time_payload(room))
    await coord.broadcast(
        {
            "type": "presence",
            "user_id": user.id,
            "display_name": user.display_name,
            "online": True,
        }
    )
    if not history:
        async with coord.lock:
            await _ensure_opening_narration(coord)

    try:
        while True:
            data = await websocket.receive_json()
            kind = data.get("type")
            if kind == "say":
                raw_content = str(data.get("content", ""))
                async with coord.lock:
                    msg = await _handle_say(coord, user, raw_content)
                if msg is not None:
                    await _handle_story_beat(
                        coord,
                        advance_clock=False,
                        allow_auto_changes=True,
                    )
                    asyncio.create_task(_simulate_offscreen_scenes(coord))
                    asyncio.create_task(_judge_and_apply_stats(coord, user.id))
            elif kind == "polish_say":
                await _handle_polish_say(
                    websocket, coord, user, str(data.get("content", ""))
                )
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
                    await _handle_story_beat(coord)
                asyncio.create_task(_judge_and_apply_stats(coord, user.id))
            elif kind == "timeskip":
                await _handle_story_beat(coord, force_timeskip=True)
                asyncio.create_task(_judge_and_apply_stats(coord, user.id))
            elif kind == "goto_scene":
                await _handle_goto_scene(coord, data.get("scene", ""))
            elif kind == "describe_scene":
                await _handle_describe_scene(coord)
            elif kind == "god_whisper":
                async with coord.lock:
                    await _handle_god_whisper(
                        websocket, coord, user, str(data.get("content", ""))
                    )
            elif kind == "pay_npc":
                async with coord.lock:
                    await _handle_pay_npc(
                        coord, user, data.get("npc_id"), data.get("amount")
                    )
            elif kind == "image":
                if settings.media_generation_enabled:
                    asyncio.create_task(_handle_image(coord, user, data))
                else:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "code": "image_disabled",
                            "detail": "生图已临时关闭",
                        }
                    )
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


@router.websocket("/ws/lobby")
async def lobby_ws(websocket: WebSocket) -> None:
    token = websocket.query_params.get("token", "")
    async with SessionFactory() as session:
        user = await user_from_token(session, token) if token else None
        if user is None:
            await websocket.close(code=4401)
            return

    await websocket.accept()
    lobby_hub.sockets.add(websocket)
    try:
        await websocket.send_json({"type": "lobby_ready"})
        while True:
            await websocket.receive_json()
    except WebSocketDisconnect:
        pass
    finally:
        lobby_hub.sockets.discard(websocket)
