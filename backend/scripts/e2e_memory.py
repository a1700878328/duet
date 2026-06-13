# /// script
# requires-python = ">=3.13"
# dependencies = ["httpx", "websockets"]
# ///
"""端到端：长期记忆。回合1 说事实→后台 mem0 抽取→回合2 问，验证 AI 记得。"""

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


async def turn(ws, line):
    await ws.send(json.dumps({"type": "say", "content": line}))
    await asyncio.wait_for(ws.recv(), 10)  # say echo
    await ws.send(json.dumps({"type": "advance"}))
    end = asyncio.get_event_loop().time() + 90
    while asyncio.get_event_loop().time() < end:
        m = json.loads(await asyncio.wait_for(ws.recv(), timeout=end - asyncio.get_event_loop().time()))
        if m["type"] == "ai_done":
            return m["content"]
        if m["type"] == "error":
            return f"<error {m}>"
    return "<timeout>"


async def main():
    async with httpx.AsyncClient(timeout=30) as c:
        token = await reg_or_login(c, "memtest", "pw_mem_123", "记测")
        h = {"Authorization": f"Bearer {token}"}
        rid = (await c.post(f"{BASE}/api/rooms", headers=h, json={"name": "记忆测试", "character_name": "艾琳"})).json()["id"]
        print("room", rid)

    async with websockets.connect(f"{WS}/ws/rooms/{rid}?token={token}") as ws:
        while True:
            if json.loads(await asyncio.wait_for(ws.recv(), 10))["type"] == "history":
                break
        r1 = await turn(ws, "我叫艾琳。我的剑名叫破晓，是父亲临终前留给我的遗物，我一直贴身带着。")
        print("\n回合1 AI:", r1[:120])
        print("\n等待后台 mem0 抽取记忆 (20s)...")
        await asyncio.sleep(20)
        r2 = await turn(ws, "（盗贼好奇地打量艾琳腰间的剑）这位骑士，你这把剑有什么来历吗？")
        print("\n回合2 AI:", r2)
        hit = any(k in r2 for k in ("破晓", "父亲", "遗物"))
        print("\nRESULT:", "✅ 记忆生效 — 跨回合记得剑的来历(破晓/父亲/遗物)" if hit else "❌ 未体现记忆(可能后台抽取慢或召回未命中)")
        return 0 if hit else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
