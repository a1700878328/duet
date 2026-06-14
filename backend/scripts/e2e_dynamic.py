# /// script
# requires-python = ">=3.13"
# dependencies = ["httpx", "websockets"]
# ///
"""动态登场 NPC：空房推进 → 导演引入新 NPC 并发言。"""

import asyncio
import json
import os
import sys

import httpx
import websockets

BASE = os.environ.get("DUET_BASE", "http://127.0.0.1:8000")
WS = os.environ.get("DUET_WS", BASE.replace("http", "ws", 1))


async def reg_or_login(c, u, pw, name):
    r = await c.post(f"{BASE}/api/auth/register", json={"username": u, "password": pw, "display_name": name})
    if r.status_code == 409:
        r = await c.post(f"{BASE}/api/auth/login", json={"username": u, "password": pw})
    r.raise_for_status()
    return r.json()["token"]


async def main():
    async with httpx.AsyncClient(timeout=120) as c:
        tok = await reg_or_login(c, "dyntest", "pw_dyn_123", "动测")
        h = {"Authorization": f"Bearer {tok}"}
        rid = (await c.post(f"{BASE}/api/rooms", headers=h, json={"name": "空房", "character_name": "艾琳", "world_card": "ksim"})).json()["id"]
        cards0 = (await c.get(f"{BASE}/api/rooms/{rid}/cards", headers=h)).json()
        print("room", rid, "起始 NPC 数:", len(cards0["npcs"]))

        async with websockets.connect(f"{WS}/ws/rooms/{rid}?token={tok}") as ws:
            while True:
                if json.loads(await asyncio.wait_for(ws.recv(), 10))["type"] == "history":
                    break
            await ws.send(json.dumps({"type": "say", "content": "艾琳推开嘎吱作响的酒馆木门，抖落肩头的雪，环视这间烟雾缭绕的屋子。"}))
            await asyncio.wait_for(ws.recv(), 10)
            print("推进（导演拍，空房应引入 NPC）...")
            await ws.send(json.dumps({"type": "advance"}))
            loop = asyncio.get_event_loop(); end = loop.time() + 120
            dones, cards_changed = [], False
            while loop.time() < end:
                try:
                    m = json.loads(await asyncio.wait_for(ws.recv(), timeout=25))
                except TimeoutError:
                    break
                if m["type"] == "ai_done": dones.append(m["content"])
                elif m["type"] == "cards_changed": cards_changed = True

        cards1 = (await c.get(f"{BASE}/api/rooms/{rid}/cards", headers=h)).json()
        print("推进后 NPC 数:", len(cards1["npcs"]), "| cards_changed事件:", cards_changed)
        for n in cards1["npcs"]:
            print(f"  + {n['name']} | {n['persona'][:30]} | 声音:{(n['voice_id'] or '')[:18]}")
        for d in dones:
            print("  说:", d[:90])

        ok = len(cards1["npcs"]) > 0 and len(dones) >= 1
        print("RESULT:", "✅ 动态登场通过 — 空房推进→导演引入NPC并发言" if ok else "⚠️ 未引入(看上面)")
        return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
