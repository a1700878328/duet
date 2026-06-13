# /// script
# requires-python = ">=3.13"
# dependencies = ["httpx", "websockets"]
# ///
"""端到端：聊天里生图（单人 raw 路径）。

register → 建房(带外貌卡) → WS → say 场景 → {type:image} → 等图消息 → GET 验证图可达。
"""

import asyncio
import json
import os
import sys

import httpx
import websockets

BASE = os.environ.get("DUET_BASE", "http://127.0.0.1:8000")
WS = os.environ.get("DUET_WS", BASE.replace("http", "ws", 1))


async def reg_or_login(c: httpx.AsyncClient, u: str, pw: str, name: str) -> str:
    r = await c.post(f"{BASE}/api/auth/register", json={"username": u, "password": pw, "display_name": name})
    if r.status_code == 409:
        r = await c.post(f"{BASE}/api/auth/login", json={"username": u, "password": pw})
    r.raise_for_status()
    return r.json()["token"]


async def main() -> int:
    async with httpx.AsyncClient(timeout=30) as c:
        token = await reg_or_login(c, "imgtest", "pw_img_123", "图测")
        h = {"Authorization": f"Bearer {token}"}
        room = (
            await c.post(
                f"{BASE}/api/rooms",
                headers=h,
                json={
                    "name": "生图测试",
                    "character_name": "艾琳",
                    "appearance": "1girl, long silver hair, blue eyes, ornate plate armor",
                },
            )
        ).json()
        rid = room["id"]
        print("created room", rid, "members:", [(m["character_name"], m["appearance"]) for m in room["members"]])

    async with websockets.connect(f"{WS}/ws/rooms/{rid}?token={token}") as ws:
        # drain history
        while True:
            m = json.loads(await asyncio.wait_for(ws.recv(), 10))
            if m["type"] == "history":
                break
        await ws.send(json.dumps({"type": "say", "content": "艾琳握紧长剑，站在幽暗的地牢入口，火把映亮她的银甲。"}))
        await asyncio.wait_for(ws.recv(), 10)  # the say message echo

        print("requesting image (single, sfw)... 可能 30-90s")
        await ws.send(json.dumps({"type": "image", "nsfw": False}))

        loop = asyncio.get_event_loop()
        end = loop.time() + 150
        img_url = None
        pending_seen = False
        while loop.time() < end:
            m = json.loads(await asyncio.wait_for(ws.recv(), timeout=end - loop.time()))
            if m["type"] == "image_pending":
                pending_seen = True
                print("  image_pending received")
            elif m["type"] == "message" and m["message"]["author_type"] == "image":
                img_url = m["message"]["content"]
                print("  IMAGE message:", img_url)
                break
            elif m["type"] == "error" and m["code"] in {"image_failed", "image_busy"}:
                print("  ERROR:", m)
                return 5
        if not img_url:
            print("FAIL: no image within timeout")
            return 4

    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"{BASE}{img_url}")
        print(f"GET {img_url} -> {r.status_code} {r.headers.get('content-type')} {len(r.content)} bytes")
        ok = r.status_code == 200 and r.headers.get("content-type") == "image/png" and len(r.content) > 50000
    print(f"pending_seen={pending_seen}")
    if ok:
        print("RESULT: ✅ 聊天内生图端到端通过 — 场景图生成 + /media 可达")
        return 0
    print("RESULT: ❌ 图不可达或过小")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
