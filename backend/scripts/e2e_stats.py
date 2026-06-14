# /// script
# requires-python = ">=3.13"
# dependencies = ["httpx", "websockets"]
# ///
"""属性系统接入 e2e：玩家行动 → 裁判判定数值变化 → 广播 + 持久化。"""

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
        tok = await reg_or_login(c, "stest", "pw_s_123", "属测")
        h = {"Authorization": f"Bearer {tok}"}
        rid = (await c.post(f"{BASE}/api/rooms", headers=h, json={"name": "属性房", "character_name": "艾琳", "world_card": "ksim"})).json()["id"]
        npcs = (await c.post(f"{BASE}/api/rooms/{rid}/npcs/generate", headers=h, json={"count": 2})).json()
        cards0 = (await c.get(f"{BASE}/api/rooms/{rid}/cards", headers=h)).json()
        st0 = cards0["players"][0]["stats"]
        print("起始属性:", {k: st0[k] for k in ("等级", "淫乱", "口腔经验", "金钱")}, "| 有stats字段:", st0 is not None)

        async with websockets.connect(f"{WS}/ws/rooms/{rid}?token={tok}") as ws:
            while True:
                if json.loads(await asyncio.wait_for(ws.recv(), 10))["type"] == "history":
                    break
            await ws.send(json.dumps({"type": "say", "content": "艾琳被哥布林按住，被迫为它口交，口腔被反复侵犯，又被夺走了一袋金币。"}))
            await asyncio.wait_for(ws.recv(), 10)
            print("推进（导演拍 + 裁判）...")
            await ws.send(json.dumps({"type": "advance"}))
            loop = asyncio.get_event_loop(); end = loop.time() + 120
            stats_evt = None
            while loop.time() < end:
                try:
                    m = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
                except TimeoutError:
                    break
                if m["type"] == "stats":
                    stats_evt = m
                    break

        if stats_evt:
            print("收到 stats 广播 delta:", json.dumps(stats_evt["delta"], ensure_ascii=False))
        cards1 = (await c.get(f"{BASE}/api/rooms/{rid}/cards", headers=h)).json()
        st1 = cards1["players"][0]["stats"]
        changed = {k: (st0.get(k), st1.get(k)) for k in st1 if st1.get(k) != st0.get(k)}
        print("持久化后变化:", json.dumps(changed, ensure_ascii=False))
        ok = stats_evt is not None and bool(changed)
        print("RESULT:", "✅ 属性系统接入通过 — 行动→裁判判定→广播+持久化" if ok else "⚠️ 未变化(裁判可能判空)")
        return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
