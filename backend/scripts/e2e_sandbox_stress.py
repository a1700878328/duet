# /// script
# requires-python = ">=3.13"
# dependencies = ["httpx", "websockets"]
# ///
"""Long-ish sandbox stress probe.

Creates a ksim room, then cycles through common play actions:
say, explicit NPC turn, move/goto_scene, god_whisper, pay_npc, timeskip.

The goal is not to judge prose taste. It checks invariants that make the room
feel like a stable character sandbox:
- websocket does not get stuck busy
- NPC turns keep the requested speaker label and do not become narrator labels
- NPC scenes remain valid after moves / god commands
- stats changes persist
- scene-log records offscreen/world events
- message sequence numbers remain strictly increasing
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from typing import Any

import httpx
import websockets

BASE = os.environ.get("DUET_BASE", "http://127.0.0.1:8000")
WS = os.environ.get("DUET_WS", BASE.replace("http", "ws", 1))
ROUNDS = int(os.environ.get("DUET_STRESS_ROUNDS", "8"))
QUIET_SECONDS = float(os.environ.get("DUET_STRESS_QUIET", "8"))
HARD_SECONDS = float(os.environ.get("DUET_STRESS_HARD", "150"))


async def reg_or_login(c: httpx.AsyncClient, username: str) -> dict[str, Any]:
    body = {
        "username": username,
        "password": "pw_sandbox_stress_123",
        "display_name": "沙盒压测",
    }
    r = await c.post(f"{BASE}/api/auth/register", json=body)
    if r.status_code == 409:
        r = await c.post(
            f"{BASE}/api/auth/login",
            json={"username": body["username"], "password": body["password"]},
        )
    r.raise_for_status()
    return r.json()


async def api_get(c: httpx.AsyncClient, token: str, path: str) -> Any:
    r = await c.get(f"{BASE}{path}", headers={"Authorization": f"Bearer {token}"})
    r.raise_for_status()
    return r.json()


async def collect_until_quiet(ws, *, quiet: float = QUIET_SECONDS) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    loop = asyncio.get_event_loop()
    hard_end = loop.time() + HARD_SECONDS
    saw_busy = False
    while loop.time() < hard_end:
        try:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=quiet))
        except TimeoutError:
            if saw_busy:
                break
            break
        events.append(msg)
        if msg.get("type") == "ai_status":
            saw_busy = saw_busy or msg.get("busy") is True
            if saw_busy and msg.get("busy") is False:
                break
    return events


async def wait_for(
    ws,
    types: set[str],
    *,
    timeout: float = HARD_SECONDS,
    speaker: str | None = None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    end = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < end:
        try:
            msg = json.loads(
                await asyncio.wait_for(
                    ws.recv(), timeout=end - asyncio.get_event_loop().time()
                )
            )
        except TimeoutError:
            break
        events.append(msg)
        if msg.get("type") not in types:
            continue
        if speaker and msg.get("speaker_label") != speaker:
            continue
        return msg, events
    return None, events


def event_messages(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e["message"] for e in events if e.get("type") == "message" and e.get("message")]


def bad_ai_labels(messages: list[dict[str, Any]], npc_names: set[str]) -> list[str]:
    bad: list[str] = []
    for msg in messages:
        if msg.get("author_type") != "ai":
            continue
        label = msg.get("speaker_label") or ""
        text = (msg.get("content") or "").strip()
        if label in {"旁白", "系统", "AI", "场景图"}:
            continue
        if label not in npc_names:
            bad.append(f"unknown speaker {label}")
        if text.startswith("[旁白]") or text == "（……）":
            bad.append(f"bad content for {label}: {text[:40]}")
    return bad


def strictly_increasing(values: list[int]) -> bool:
    return all(b > a for a, b in zip(values, values[1:], strict=False))


async def main() -> int:
    username = f"sandbox_stress_{int(time.time())}"
    async with httpx.AsyncClient(timeout=180) as c:
        auth = await reg_or_login(c, username)
        token = auth["token"]
        headers = {"Authorization": f"Bearer {token}"}
        room = (
            await c.post(
                f"{BASE}/api/rooms",
                headers=headers,
                json={
                    "name": f"沙盒长跑压测 {ROUNDS}",
                    "character_name": "艾琳",
                    "world_card": "ksim",
                },
            )
        ).json()
        rid = room["id"]
        cards = await api_get(c, token, f"/api/rooms/{rid}/cards")
        npcs = [n for n in cards["npcs"] if n["id"] != 0 and n.get("active")]
        current_scene = room.get("current_scene") or "冒险者公会"
        local = [n for n in npcs if n.get("scene") == current_scene]
        if not local:
            print("FAIL: no local NPCs", current_scene, [n["name"] for n in npcs[:5]])
            return 2
        target = local[0]
        print(f"room={rid} rounds={ROUNDS} target={target['name']} scene={current_scene}")

    all_events: list[dict[str, Any]] = []
    errors: list[str] = []
    async with websockets.connect(f"{WS}/ws/rooms/{rid}?token={token}") as ws:
        history, seen = await wait_for(ws, {"history"}, timeout=20)
        all_events.extend(seen)
        if history is None:
            print("FAIL: no websocket history")
            return 3
        all_events.extend(await collect_until_quiet(ws, quiet=12))

        scene_cycle = ["酒馆", "冒险者公会", "城镇", "借贷商店"]
        for i in range(ROUNDS):
            print(f"\n-- round {i + 1}/{ROUNDS} --")
            action = i % 6
            if action == 0:
                await ws.send(
                    json.dumps(
                        {
                            "type": "say",
                            "content": (
                                "艾琳环视当前场景，问在场的人："
                                f"第{i + 1}轮，谁注意到了新的危险或机会？"
                            ),
                        },
                        ensure_ascii=False,
                    )
                )
                events = await collect_until_quiet(ws)
                print("say events", len(events))
            elif action == 1:
                await ws.send(json.dumps({"type": "advance", "npc_id": target["id"]}))
                done, events = await wait_for(
                    ws, {"ai_done", "error"}, speaker=target["name"], timeout=160
                )
                if done is None or done.get("type") != "ai_done":
                    errors.append(f"round {i + 1}: explicit npc turn failed")
                else:
                    print("npc", target["name"], (done.get("content") or "")[:70])
                    more = await collect_until_quiet(ws)
                    events.extend(more)
            elif action == 2:
                dest = scene_cycle[(i // 6) % len(scene_cycle)]
                await ws.send(
                    json.dumps({"type": "move", "scene": dest, "npcs": [target["name"]]}, ensure_ascii=False)
                )
                scene_event, events = await wait_for(
                    ws,
                    {"scene", "error", "message"},
                    timeout=160,
                    speaker=None,
                )
                while (
                    scene_event
                    and scene_event.get("type") == "message"
                    and "移动被拒绝" not in (scene_event.get("message", {}).get("content") or "")
                ):
                    next_event, more_events = await wait_for(
                        ws, {"scene", "error", "message"}, timeout=60
                    )
                    events.extend(more_events)
                    scene_event = next_event
                refused = (
                    scene_event
                    and scene_event.get("type") == "message"
                    and "移动被拒绝" in (scene_event.get("message", {}).get("content") or "")
                )
                if scene_event is None or (
                    scene_event.get("type") != "scene" and not refused
                ):
                    errors.append(f"round {i + 1}: move failed {scene_event}")
                elif refused:
                    print("move refused by NPC")
                else:
                    print("move ->", scene_event.get("scene"))
            elif action == 3:
                await ws.send(
                    json.dumps(
                        {
                            "type": "god_whisper",
                            "target_npcs": [target["name"]],
                            "scene": "酒馆",
                            "action": "去酒馆等待艾琳，并记住暗号黑铃。",
                        },
                        ensure_ascii=False,
                    )
                )
                reply, events = await wait_for(ws, {"god_reply", "error"}, timeout=60)
                more = await collect_until_quiet(ws)
                events.extend(more)
                if reply is None or reply.get("type") != "god_reply":
                    errors.append(f"round {i + 1}: god reply failed {reply}")
                else:
                    print("god", reply.get("content", "")[:70])
            elif action == 4:
                await ws.send(json.dumps({"type": "pay_npc", "npc_id": target["id"], "amount": 1}))
                stats, events = await wait_for(ws, {"stats", "error"}, timeout=160)
                more = await collect_until_quiet(ws)
                events.extend(more)
                if stats is None or stats.get("type") != "stats":
                    errors.append(f"round {i + 1}: payment stats missing {stats}")
                else:
                    print("pay delta", stats.get("delta"))
            else:
                await ws.send(json.dumps({"type": "timeskip"}))
                events = await collect_until_quiet(ws, quiet=12)
                if not any(e.get("type") == "time" for e in events):
                    errors.append(f"round {i + 1}: timeskip time event missing")
                else:
                    print("timeskip events", len(events))

            all_events.extend(events)
            for event in events:
                if event.get("type") == "error" and event.get("code") not in {"money_not_enough"}:
                    errors.append(f"round {i + 1}: websocket error {event}")

    async with httpx.AsyncClient(timeout=180) as c:
        cards_final = await api_get(c, token, f"/api/rooms/{rid}/cards")
        scene_log = await api_get(c, token, f"/api/rooms/{rid}/scene-log")
        messages = await api_get(c, token, f"/api/rooms/{rid}/messages")

    final_npcs = [n for n in cards_final["npcs"] if n["id"] != 0]
    npc_names = {n["name"] for n in final_npcs}
    target_final = next((n for n in final_npcs if n["id"] == target["id"]), None)
    player_stats = cards_final["players"][0].get("stats") or {}
    seqs = [int(m["seq"]) for m in messages]
    ai_messages = [m for m in messages if m.get("author_type") == "ai"]
    label_errors = bad_ai_labels(ai_messages, npc_names)
    logs = scene_log.get("logs") or {}
    log_entries = [entry for entries in logs.values() for entry in entries]
    offscreen_entries = [e for e in log_entries if e.get("kind") == "offscreen"]
    scene_unlocks = [e for e in log_entries if e.get("kind") == "scene_unlock"]
    npc_moves = [e for e in log_entries if e.get("kind") == "npc_move"]

    checks = {
        "seq_strictly_increasing": strictly_increasing(seqs),
        "messages_persisted": len(messages) >= ROUNDS,
        "target_scene_present": bool(target_final and target_final.get("scene")),
        "stats_present": bool(player_stats) and "金钱" in player_stats,
        "scene_logs_present": bool(log_entries),
        "offscreen_or_world_events": bool(offscreen_entries or scene_unlocks or npc_moves),
        "speaker_labels_clean": not label_errors,
        "no_runtime_errors": not errors,
    }
    print("\n=== summary ===")
    print("checks:", json.dumps(checks, ensure_ascii=False))
    print("target_scene:", target_final.get("scene") if target_final else None)
    print("money:", player_stats.get("金钱"), "states:", player_stats.get("状态"))
    print(
        "logs:",
        {
            "all": len(log_entries),
            "offscreen": len(offscreen_entries),
            "scene_unlock": len(scene_unlocks),
            "npc_move": len(npc_moves),
        },
    )
    if errors:
        print("errors:")
        for err in errors[:12]:
            print(" -", err)
    if label_errors:
        print("label errors:")
        for err in label_errors[:12]:
            print(" -", err)

    if all(checks.values()):
        print("RESULT: ✅ 沙盒长跑压测通过")
        return 0
    print("RESULT: ⚠️ 沙盒长跑压测发现问题")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
