# /// script
# requires-python = ">=3.13"
# dependencies = ["httpx", "websockets"]
# ///
"""Phase C e2e：导演自动调度多 NPC + 叙事跳跃时间。"""

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


async def collect_beat(ws, quiet=25.0, hard=180.0):
    """收集一拍产生的所有消息，直到 quiet 秒无新事件。返回 ai_done 内容 + 普通消息内容。"""
    dones, msgs = [], []
    loop = asyncio.get_event_loop()
    hard_end = loop.time() + hard
    while loop.time() < hard_end:
        try:
            m = json.loads(await asyncio.wait_for(ws.recv(), timeout=quiet))
        except TimeoutError:
            break
        if m["type"] == "ai_done":
            dones.append(m["content"])
        elif m["type"] == "message" and m["message"]["author_type"] in {"ai", "system"}:
            msgs.append(m["message"]["content"])
        elif m["type"] == "error":
            print("  error:", m)
    return dones, msgs


async def main():
    async with httpx.AsyncClient(timeout=120) as c:
        token = await reg_or_login(c, "dirtest", "pw_dir_123", "导测")
        h = {"Authorization": f"Bearer {token}"}
        rid = (await c.post(f"{BASE}/api/rooms", headers=h, json={"name": "导演测试", "character_name": "艾琳", "world_card": "ksim"})).json()["id"]
        npcs = (await c.post(f"{BASE}/api/rooms/{rid}/npcs/generate", headers=h, json={"count": 4})).json()
        print("room", rid, "NPCs:", [n["name"] for n in npcs])

    async with websockets.connect(f"{WS}/ws/rooms/{rid}?token={token}") as ws:
        while True:
            if json.loads(await asyncio.wait_for(ws.recv(), 10))["type"] == "history":
                break
        await ws.send(json.dumps({"type": "say", "content": "艾琳大步走进喧闹的酒馆，扫视众人，高声问：谁知道去魔王城的路，我重金酬谢！"}))
        await asyncio.wait_for(ws.recv(), 10)

        print("\n=== 导演拍（advance 无 npc_id）===")
        await ws.send(json.dumps({"type": "advance"}))
        dones, _ = await collect_beat(ws)
        for d in dones:
            print("  •", d[:90])
        n_spoke = len(dones)

        print("\n=== 推进时间（timeskip）===")
        await ws.send(json.dumps({"type": "timeskip"}))
        dones2, msgs2 = await collect_beat(ws)
        jumped = any("⏳" in m for m in msgs2)
        for m in msgs2:
            print("  旁白:", m[:100])
        for d in dones2:
            print("  •", d[:90])

        print(f"\n导演拍NPC发言数={n_spoke} 时间跳跃出现={jumped}")
        if n_spoke >= 1 and jumped:
            print("RESULT: ✅ Phase C 通过 — 导演自动调度 NPC + 叙事跳跃时间")
            return 0
        print("RESULT: ⚠️ 部分未达预期(看上面)")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
