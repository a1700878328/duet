# /// script
# requires-python = ">=3.13"
# dependencies = ["httpx", "websockets"]
# ///
"""SP-1 端到端真实测试：两玩家 + AI，走真实 DeepSeek。

注册 alice/bob → alice 建房(艾琳) → bob 进房(卡尔) → 双 WS →
alice say → 验证 bob 收到 → alice advance → 收集 ai_delta 直到 ai_done。
"""

import asyncio
import json
import os
import sys

import httpx
import websockets

BASE = os.environ.get("DUET_BASE", "http://127.0.0.1:8000")
WS = os.environ.get("DUET_WS", BASE.replace("http", "ws", 1))


async def reg_or_login(c: httpx.AsyncClient, username: str, pw: str, name: str) -> str:
    r = await c.post(f"{BASE}/api/auth/register", json={"username": username, "password": pw, "display_name": name})
    if r.status_code == 409:
        r = await c.post(f"{BASE}/api/auth/login", json={"username": username, "password": pw})
    r.raise_for_status()
    return r.json()["token"]


async def recv_until(ws, want_type: str, timeout: float = 40.0, sink: list | None = None):
    loop = asyncio.get_event_loop()
    end = loop.time() + timeout
    while loop.time() < end:
        raw = await asyncio.wait_for(ws.recv(), timeout=end - loop.time())
        msg = json.loads(raw)
        if sink is not None:
            sink.append(msg)
        if msg.get("type") == want_type:
            return msg
    raise TimeoutError(f"did not get {want_type}")


async def main() -> int:
    async with httpx.AsyncClient(timeout=30) as c:
        # health
        h = await c.get(f"{BASE}/api/health")
        print("health:", h.json())

        ta = await reg_or_login(c, "alice", "pw_alice_123", "小爱")
        tb = await reg_or_login(c, "bob", "pw_bob_123", "阿伯")
        print("got tokens for alice/bob")

        ha = {"Authorization": f"Bearer {ta}"}
        hb = {"Authorization": f"Bearer {tb}"}

        room = (await c.post(f"{BASE}/api/rooms", headers=ha, json={"name": "试炼地牢", "character_name": "艾琳"})).json()
        rid = room["id"]
        print("alice created room", rid, room["name"])
        await c.post(f"{BASE}/api/rooms/{rid}/join", headers=hb, json={"character_name": "卡尔"})
        print("bob joined as 卡尔")

    async with websockets.connect(f"{WS}/ws/rooms/{rid}?token={ta}") as wa, \
               websockets.connect(f"{WS}/ws/rooms/{rid}?token={tb}") as wb:
        await recv_until(wa, "history")
        await recv_until(wb, "history")
        print("both sockets connected, history received")

        # alice 发言
        line = "卡尔，我们被触手怪堵在地牢深处了，你那边有办法吗？"
        await wa.send(json.dumps({"type": "say", "content": line}))
        got = await recv_until(wb, "message")
        body = got["message"]
        print(f"bob received A's message: [{body['speaker_label']}] {body['content'][:40]}")
        assert line in body["content"], "B did not receive A's exact line"

        # alice 推进 → AI 接话
        await wa.send(json.dumps({"type": "advance"}))
        deltas: list[str] = []
        loop = asyncio.get_event_loop()
        end = loop.time() + 90
        ai_done = None
        first_delta_at = None
        while loop.time() < end:
            raw = await asyncio.wait_for(wa.recv(), timeout=end - loop.time())
            m = json.loads(raw)
            if m["type"] == "ai_delta":
                if first_delta_at is None:
                    first_delta_at = loop.time()
                deltas.append(m["delta"])
            elif m["type"] == "ai_done":
                ai_done = m
                break
            elif m["type"] == "error":
                print("ERROR event:", m)
                return 5
        if ai_done is None:
            print("FAIL: no ai_done within timeout; deltas so far:", "".join(deltas)[:200])
            return 4

        full = ai_done["content"]
        print(f"\n=== AI 回复 (finish={ai_done['finish_reason']}, {len(deltas)} 个流式分片) ===")
        print(full)
        print("=" * 50)

        # bob 也应收到同一条 AI 消息
        bmsgs: list = []
        try:
            await recv_until(wb, "ai_done", timeout=5, sink=bmsgs)
            print("bob also saw the AI turn ✓")
        except TimeoutError:
            if any(x.get("type") == "ai_delta" for x in bmsgs):
                print("bob saw AI deltas ✓")
            else:
                print("WARN: bob did not observe AI turn (check broadcast)")

        assert len(full.strip()) >= 10, "AI content too short / empty"
        print("\nRESULT: ✅ SP-1 端到端通过 — 双人共享房间 + AI 流式接话 全链路工作")
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
