# /// script
# requires-python = ">=3.13"
# dependencies = ["httpx", "websockets"]
# ///
"""NSFW ending e2e probe.

Runs a ksim room through a real adult-dark scenario using only normal websocket
player actions. No database/stat injection is used. The script prints structural
results only; it intentionally avoids dumping explicit generated prose.
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


async def reg_or_login(c: httpx.AsyncClient, username: str) -> dict[str, Any]:
    body = {
        "username": username,
        "password": "pw_nsfw_ending_123",
        "display_name": "NSFW结局测试",
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


async def wait_for(
    ws,
    types: set[str],
    *,
    timeout: float = 140,
    speaker: str | None = None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    loop = asyncio.get_event_loop()
    end = loop.time() + timeout
    while loop.time() < end:
        try:
            msg = json.loads(await asyncio.wait_for(ws.recv(), end - loop.time()))
        except TimeoutError:
            break
        events.append(msg)
        if msg.get("type") not in types:
            continue
        if speaker and msg.get("speaker_label") != speaker:
            continue
        return msg, events
    return None, events


async def collect_until_idle(ws, *, timeout: float = 160) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    loop = asyncio.get_event_loop()
    end = loop.time() + timeout
    saw_busy = False
    while loop.time() < end:
        try:
            msg = json.loads(await asyncio.wait_for(ws.recv(), 12))
        except TimeoutError:
            break
        events.append(msg)
        if msg.get("type") == "ai_status":
            saw_busy = saw_busy or msg.get("busy") is True
            if saw_busy and msg.get("busy") is False:
                break
        if msg.get("type") == "ending":
            more = await drain(ws, seconds=3)
            events.extend(more)
            break
    return events


async def drain(ws, *, seconds: float = 2) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    end = asyncio.get_event_loop().time() + seconds
    while asyncio.get_event_loop().time() < end:
        try:
            events.append(json.loads(await asyncio.wait_for(ws.recv(), 0.5)))
        except TimeoutError:
            break
    return events


def event_messages(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        e["message"]
        for e in events
        if e.get("type") == "message" and isinstance(e.get("message"), dict)
    ]


def npc_label_errors(messages: list[dict[str, Any]], npc_names: set[str]) -> list[str]:
    errors: list[str] = []
    for msg in messages:
        if msg.get("author_type") != "ai":
            continue
        label = msg.get("speaker_label") or ""
        text = (msg.get("content") or "").strip()
        if label in {"旁白", "系统", "场景图"}:
            continue
        if label not in npc_names:
            errors.append(f"unknown ai speaker={label}")
        if text.startswith("[旁白]") or text == "（……）":
            errors.append(f"bad npc content speaker={label}")
        if "[旁白]:" in text or "[NPC]:" in text or "[AI]:" in text:
            errors.append(f"leaky label speaker={label}")
    return errors


async def main() -> int:
    username = f"nsfw_ending_{int(time.time())}"
    all_events: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=180) as c:
        auth = await reg_or_login(c, username)
        token = auth["token"]
        headers = {"Authorization": f"Bearer {token}"}
        room = (
            await c.post(
                f"{BASE}/api/rooms",
                headers=headers,
                json={
                    "name": "NSFW结局链路测试",
                    "character_name": "艾琳",
                    "world_card": "ksim",
                },
            )
        )
        room.raise_for_status()
        rid = room.json()["id"]
        cards = await api_get(c, token, f"/api/rooms/{rid}/cards")
        npcs = [n for n in cards["npcs"] if n.get("id") and n.get("active")]
        if not npcs:
            print("FAIL: no NPCs in ksim room")
            return 2
        target = npcs[0]
        npc_names = {n["name"] for n in npcs}
        print(f"room={rid} target_npc={target['name']}")

    async with websockets.connect(f"{WS}/ws/rooms/{rid}?token={token}") as ws:
        history, events = await wait_for(ws, {"history"}, timeout=20)
        all_events.extend(events)
        if history is None:
            print("FAIL: websocket history missing")
            return 3
        all_events.extend(await collect_until_idle(ws, timeout=40))

        beats = [
            ("say", "艾琳注意到这个世界的成人黑暗规则正在逼近，询问在场者哪里最危险。"),
            ("advance", ""),
            ("goto_scene", "森林小路"),
            ("say", "艾琳独自沿着森林小路深入，寻找那些失踪冒险者留下的线索。"),
            ("advance", ""),
            ("goto_scene", "哥布林巢穴"),
            ("say", "艾琳在巢穴深处遭遇伏击，尝试抵抗但逐渐失去主动权。"),
            ("advance", ""),
            ("say", "艾琳被困在巢穴里，挣扎着寻找逃脱机会，但局势继续恶化。"),
            ("timeskip", ""),
            ("say", "时间继续流逝，艾琳的处境变得更加糟糕，她仍试图保持清醒。"),
        ]
        ending_event = None
        stats_events: list[dict[str, Any]] = []
        for index, (kind, content) in enumerate(beats, start=1):
            print(f"beat {index}: {kind}")
            if kind == "say":
                await ws.send(json.dumps({"type": "say", "content": content}, ensure_ascii=False))
            elif kind == "advance":
                await ws.send(json.dumps({"type": "advance"}, ensure_ascii=False))
            elif kind == "goto_scene":
                await ws.send(json.dumps({"type": "goto_scene", "scene": content}, ensure_ascii=False))
            elif kind == "timeskip":
                await ws.send(json.dumps({"type": "timeskip"}, ensure_ascii=False))
            events = await collect_until_idle(ws)
            all_events.extend(events)
            for msg in events:
                if msg.get("type") == "stats":
                    stats_events.append(msg)
                if msg.get("type") == "ending":
                    ending_event = msg
            if ending_event is not None:
                break

        await ws.send(json.dumps({"type": "advance", "npc_id": target["id"]}))
        npc_done, events = await wait_for(
            ws, {"ai_done", "error"}, speaker=target["name"], timeout=160
        )
        all_events.extend(events)
        if npc_done is None or npc_done.get("type") != "ai_done":
            print("FAIL: explicit NPC turn did not finish")
            return 4
        all_events.extend(await collect_until_idle(ws))
        for day in range(1, 12):
            if ending_event is not None:
                break
            print(f"imprisonment tick {day}: timeskip")
            await ws.send(json.dumps({"type": "timeskip"}, ensure_ascii=False))
            events = await collect_until_idle(ws, timeout=180)
            all_events.extend(events)
            for msg in events:
                if msg.get("type") == "stats":
                    stats_events.append(msg)
                if msg.get("type") == "ending":
                    ending_event = msg
                    break

    async with httpx.AsyncClient(timeout=60) as c:
        cards_final = await api_get(c, token, f"/api/rooms/{rid}/cards")
    final_stats = cards_final["players"][0]["stats"]
    label_errors = npc_label_errors(event_messages(all_events), npc_names)

    checks = {
        "npc_turn_ok": npc_done is not None and npc_done.get("speaker_label") == target["name"],
        "stats_events_seen": len(stats_events) > 0,
        "ending_event_seen": ending_event is not None,
        "npc_labels_clean": not label_errors,
    }
    print("checks:", json.dumps(checks, ensure_ascii=False))
    print("ending_event:", ending_event.get("name") if ending_event else None)
    print(
        "final_stats:",
        json.dumps(
            {
                "淫乱": final_stats.get("淫乱"),
                "意志": final_stats.get("意志"),
                "状态": final_stats.get("状态"),
            },
            ensure_ascii=False,
        ),
    )
    if label_errors:
        print("label_errors:", json.dumps(label_errors, ensure_ascii=False))
    ok = all(checks.values())
    print("RESULT:", "✅ NSFW 结局链路通过" if ok else "⚠️ NSFW 结局链路存在问题")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
