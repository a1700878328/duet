# /// script
# requires-python = ">=3.13"
# dependencies = ["httpx", "websockets"]
# ///
"""Phase B e2e：世界卡 AI 生成 NPC 名册 + 指定 NPC 各自发言。"""

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


async def advance_as(ws, npc_id):
    await ws.send(json.dumps({"type": "advance", "npc_id": npc_id}))
    end = asyncio.get_event_loop().time() + 90
    while asyncio.get_event_loop().time() < end:
        m = json.loads(await asyncio.wait_for(ws.recv(), timeout=end - asyncio.get_event_loop().time()))
        if m["type"] == "ai_done":
            return m["content"]
        if m["type"] == "error":
            return f"<error {m}>"
    return "<timeout>"


async def main():
    async with httpx.AsyncClient(timeout=120) as c:
        token = await reg_or_login(c, "npctest", "pw_npc_123", "群测")
        h = {"Authorization": f"Bearer {token}"}
        rid = (await c.post(f"{BASE}/api/rooms", headers=h, json={"name": "群像测试", "character_name": "艾琳", "world_card": "ksim"})).json()["id"]
        print("room", rid, "(world=ksim)")

        print("AI 生成 NPC 名册...")
        npcs = (await c.post(f"{BASE}/api/rooms/{rid}/npcs/generate", headers=h, json={"count": 3})).json()
        if not isinstance(npcs, list) or len(npcs) == 0:
            print("FAIL: 生成为空", npcs)
            return 4
        for n in npcs:
            print(f"  - [{n['id']}] {n['name']} | {n['persona'][:36]} | voice={n['voice_id']} | ai={n['created_by_ai']}")

    async with websockets.connect(f"{WS}/ws/rooms/{rid}?token={token}") as ws:
        while True:
            if json.loads(await asyncio.wait_for(ws.recv(), 10))["type"] == "history":
                break
        await ws.send(json.dumps({"type": "say", "content": "艾琳推开酒馆大门，环视四周，朗声道：有人能给我指条去魔王城的路吗？"}))
        await asyncio.wait_for(ws.recv(), 10)

        a = npcs[0]
        b = npcs[1]
        print(f"\n让 [{a['name']}] 接话...")
        ra = await advance_as(ws, a["id"])
        print(ra[:200])
        print(f"\n让 [{b['name']}] 接话...")
        rb = await advance_as(ws, b["id"])
        print(rb[:200])

        # 验证：各自以自己名字开口，且不串到对方/玩家
        a_ok = a["name"] in ra
        b_ok = b["name"] in rb
        no_player = "艾琳]" not in ra.replace(f"{a['name']}]", "") and "艾琳]" not in rb.replace(f"{b['name']}]", "")
        different = ra != rb
        print(f"\na以自名开口={a_ok} b以自名开口={b_ok} 不冒充玩家={no_player} 两NPC回复不同={different}")
        if a_ok and b_ok and no_player and different:
            print("RESULT: ✅ Phase B 通过 — 世界卡生成NPC名册 + 各NPC独立AI发言、不串台")
            return 0
        print("RESULT: ⚠️ 部分未达预期(看上面输出)")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
