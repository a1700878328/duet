# /// script
# requires-python = ">=3.13"
# dependencies = ["httpx", "websockets"]
# ///
"""Measure real NPC answer rate without fallback dialogue.

Creates fresh ksim rooms and explicitly asks NPCs to speak. Counts only turns
where the requested NPC produces a valid ai_done. Errors and timeouts are real
failures; no database/stat injection is used.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from typing import Any

import httpx
import websockets

BASE = os.environ.get("DUET_BASE", "http://127.0.0.1:8000")
WS = os.environ.get("DUET_WS", BASE.replace("http", "ws", 1))
TRIALS = int(os.environ.get("DUET_NPC_RATE_TRIALS", "30"))
ROOMS = int(os.environ.get("DUET_NPC_RATE_ROOMS", "5"))
TURN_TIMEOUT = float(os.environ.get("DUET_NPC_RATE_TIMEOUT", "180"))
TRIGGER_AUTO = os.environ.get("DUET_NPC_RATE_TRIGGER_AUTO", "0") == "1"
NPCS_PER_ROOM = int(os.environ.get("DUET_NPC_RATE_NPCS_PER_ROOM", "999"))


async def reg_or_login(c: httpx.AsyncClient, username: str) -> str:
    body = {
        "username": username,
        "password": "pw_npc_rate_123",
        "display_name": "NPC率测",
    }
    r = await c.post(f"{BASE}/api/auth/register", json=body)
    if r.status_code == 409:
        r = await c.post(
            f"{BASE}/api/auth/login",
            json={"username": body["username"], "password": body["password"]},
        )
    r.raise_for_status()
    return r.json()["token"]


async def drain(ws, *, seconds: float = 2.0) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    end = asyncio.get_event_loop().time() + seconds
    while asyncio.get_event_loop().time() < end:
        try:
            events.append(json.loads(await asyncio.wait_for(ws.recv(), 0.5)))
        except TimeoutError:
            break
    return events


async def collect_until_idle(ws, *, quiet: float = 4.0, hard: float = 180.0) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    loop = asyncio.get_event_loop()
    end = loop.time() + hard
    saw_busy = False
    while loop.time() < end:
        try:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=quiet))
        except TimeoutError:
            break
        events.append(msg)
        if msg.get("type") == "ai_status":
            saw_busy = saw_busy or msg.get("busy") is True
            if saw_busy and msg.get("busy") is False:
                break
    return events


async def wait_history(ws) -> None:
    end = asyncio.get_event_loop().time() + 30
    while asyncio.get_event_loop().time() < end:
        msg = json.loads(await asyncio.wait_for(ws.recv(), end - asyncio.get_event_loop().time()))
        if msg.get("type") == "history":
            return
    raise TimeoutError("no history")


async def wait_target_turn(ws, npc: dict[str, Any]) -> tuple[str, dict[str, Any] | None, list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    end = asyncio.get_event_loop().time() + TURN_TIMEOUT
    npc_name = npc["name"]
    while asyncio.get_event_loop().time() < end:
        try:
            msg = json.loads(await asyncio.wait_for(ws.recv(), end - asyncio.get_event_loop().time()))
        except TimeoutError:
            break
        events.append(msg)
        if msg.get("type") == "ai_done" and msg.get("speaker_label") == npc_name:
            return "success", msg, events
        if msg.get("type") == "error" and msg.get("code") == "ai_busy":
            continue
        if msg.get("type") == "error" and msg.get("code") in {
            "npc_dialogue_failed",
            "npc_turn_failed",
            "ai_error",
        }:
            return "error", msg, events
    return "timeout", None, events


def classify_target_events(
    events: list[dict[str, Any]], npc: dict[str, Any]
) -> tuple[str | None, dict[str, Any] | None]:
    npc_name = npc["name"]
    for msg in events:
        if msg.get("type") == "ai_done" and msg.get("speaker_label") == npc_name:
            return "success", msg
        if msg.get("type") == "error" and msg.get("code") in {
            "npc_dialogue_failed",
            "npc_turn_failed",
            "ai_error",
        }:
            speaker = msg.get("speaker_label") or msg.get("npc_name")
            if not speaker or speaker == npc_name:
                return "error", msg
    return None, None


async def advance_when_idle(ws, npc_id: int) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for _ in range(4):
        events.extend(await collect_until_idle(ws, quiet=2.0, hard=180.0))
        await ws.send(json.dumps({"type": "advance", "npc_id": npc_id}))
        reply_events = await drain(ws, seconds=0.8)
        events.extend(reply_events)
        if not any(e.get("type") == "error" and e.get("code") == "ai_busy" for e in reply_events):
            return events
    return events


def invalid_content(text: str, npc_names: set[str], player_names: set[str]) -> list[str]:
    bad: list[str] = []
    stripped = (text or "").strip()
    if not stripped:
        bad.append("empty")
    if stripped == "（……）":
        bad.append("ellipsis")
    if stripped.startswith("[旁白]") or "[旁白]:" in stripped:
        bad.append("narrator_label")
    if re.match(r"^[（(][^）)\n]{1,80}[）)]", stripped):
        bad.append("action_prefix")
    for name in player_names:
        if f"[{name}]" in stripped or f"{name}:" in stripped or f"{name}：" in stripped:
            bad.append(f"player_label:{name}")
    for name in npc_names:
        if f"[{name}]" in stripped:
            bad.append(f"npc_label:{name}")
    return bad


async def main() -> int:
    stamp = int(time.time())
    username = f"npc_rate_{stamp}"
    successes = 0
    failures: list[dict[str, Any]] = []
    invalids: list[dict[str, Any]] = []
    total = 0
    async with httpx.AsyncClient(timeout=180) as c:
        token = await reg_or_login(c, username)
        headers = {"Authorization": f"Bearer {token}"}
        for room_index in range(ROOMS):
            if total >= TRIALS:
                break
            room_resp = await c.post(
                f"{BASE}/api/rooms",
                headers=headers,
                json={
                    "name": f"NPC回答率 {stamp}-{room_index}",
                    "character_name": "艾琳",
                    "world_card": "ksim",
                },
            )
            room_resp.raise_for_status()
            rid = room_resp.json()["id"]
            gen = await c.post(
                f"{BASE}/api/rooms/{rid}/npcs/generate",
                headers=headers,
                json={"count": 4},
            )
            gen.raise_for_status()
            cards = await c.get(f"{BASE}/api/rooms/{rid}/cards", headers=headers)
            cards.raise_for_status()
            data = cards.json()
            npcs = [n for n in data["npcs"] if n.get("id") and n.get("active")][
                :NPCS_PER_ROOM
            ]
            npc_names = {n["name"] for n in npcs}
            player_names = {p["character_name"] for p in data["players"]}
            print(f"room={rid} npcs={list(npc_names)[:8]}", flush=True)
            async with websockets.connect(f"{WS}/ws/rooms/{rid}?token={token}") as ws:
                await wait_history(ws)
                await drain(ws, seconds=4)
                if TRIGGER_AUTO:
                    await ws.send(
                        json.dumps(
                            {
                                "type": "say",
                                "content": "艾琳看向在场众人：谁愿意直接告诉我现在该往哪里走？",
                            },
                            ensure_ascii=False,
                        )
                    )
                    await collect_until_idle(ws, quiet=4.0, hard=180.0)
                for npc in npcs:
                    if total >= TRIALS:
                        break
                    total += 1
                    pre_events = await advance_when_idle(ws, npc["id"])
                    pre_status, pre_msg = classify_target_events(pre_events, npc)
                    if pre_status:
                        status, msg, events = pre_status, pre_msg, pre_events
                    else:
                        status, msg, events = await wait_target_turn(ws, npc)
                        events = pre_events + events
                    retry_count = sum(1 for e in events if e.get("type") == "error")
                    if status == "success" and msg is not None:
                        text = msg.get("content") or ""
                        bad = invalid_content(text, npc_names, player_names)
                        if bad:
                            invalids.append(
                                {
                                    "trial": total,
                                    "npc": npc["name"],
                                    "bad": bad,
                                    "text": text[:120],
                                }
                            )
                        else:
                            successes += 1
                        print(
                            f"{total:02d} OK npc={npc['name']} chars={len(text)} bad={bad or '-'}"
                            ,
                            flush=True,
                        )
                    else:
                        fail = {
                            "trial": total,
                            "npc": npc["name"],
                            "status": status,
                            "event": msg,
                            "events": len(events),
                            "errors_seen": retry_count,
                        }
                        failures.append(fail)
                        print(f"{total:02d} FAIL {json.dumps(fail, ensure_ascii=False)}", flush=True)
                    await collect_until_idle(ws, quiet=1.5, hard=180.0)

    valid_success = successes
    print("\nSUMMARY", flush=True)
    print(f"trials={total}", flush=True)
    print(f"valid_success={valid_success}", flush=True)
    print(f"invalid_success={len(invalids)}", flush=True)
    print(f"failures={len(failures)}", flush=True)
    rate = (valid_success / total * 100) if total else 0
    print(f"valid_answer_rate={rate:.1f}%", flush=True)
    if invalids:
        print("invalids:", json.dumps(invalids[:5], ensure_ascii=False), flush=True)
    if failures:
        print("failures:", json.dumps(failures[:8], ensure_ascii=False), flush=True)
    return 0 if total and not failures and not invalids else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
