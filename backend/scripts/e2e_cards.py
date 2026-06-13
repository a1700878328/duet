# /// script
# requires-python = ">=3.13"
# dependencies = ["httpx"]
# ///
"""Phase A 角色卡 API 烟测：玩家卡更新 + NPC 卡 CRUD + 列出。"""

import asyncio
import os
import sys

import httpx

BASE = os.environ.get("DUET_BASE", "http://127.0.0.1:8000")


async def main() -> int:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{BASE}/api/auth/register", json={"username": "cardtest", "password": "pw_card_123", "display_name": "卡测"})
        if r.status_code == 409:
            r = await c.post(f"{BASE}/api/auth/login", json={"username": "cardtest", "password": "pw_card_123"})
        token = r.json()["token"]
        h = {"Authorization": f"Bearer {token}"}

        rid = (await c.post(f"{BASE}/api/rooms", headers=h, json={"name": "卡测房", "character_name": "艾琳"})).json()["id"]
        print("room", rid)

        # 更新我的玩家卡
        me = (await c.put(f"{BASE}/api/rooms/{rid}/me-card", headers=h, json={
            "persona": "冷静果敢的女骑士，寡言但重情义。", "appearance": "long silver hair, blue eyes, plate armor", "voice_id": "knight_f1",
        })).json()
        print("me-card:", me["character_name"], "| persona:", me["persona"][:20], "| voice:", me["voice_id"])
        assert me["persona"].startswith("冷静") and me["voice_id"] == "knight_f1"

        # 建 NPC 卡
        npc = (await c.post(f"{BASE}/api/rooms/{rid}/npcs", headers=h, json={
            "name": "老酒保麦克", "persona": "酒馆老板，爱讲传闻，贪财但善良。", "appearance": "old bartender, bald, apron", "voice_id": "old_man1",
        })).json()
        nid = npc["id"]
        print("npc created:", nid, npc["name"], "ai?", npc["created_by_ai"])

        # 改 NPC 卡（玩家叫 NPC 改）
        await c.put(f"{BASE}/api/rooms/{rid}/npcs/{nid}", headers=h, json={
            "name": "老酒保麦克", "persona": "酒馆老板，其实是退役佣兵，深藏不露。", "appearance": "old bartender, scar, apron", "voice_id": "old_man1",
        })

        # 列出
        cards = (await c.get(f"{BASE}/api/rooms/{rid}/cards", headers=h)).json()
        print("cards: players=", len(cards["players"]), "npcs=", len(cards["npcs"]))
        npc0 = cards["npcs"][0]
        assert "退役佣兵" in npc0["persona"], "NPC 编辑未生效"
        assert cards["players"][0]["voice_id"] == "knight_f1"
        print("npc persona after edit:", npc0["persona"][:24])

        # 删
        await c.delete(f"{BASE}/api/rooms/{rid}/npcs/{nid}", headers=h)
        cards2 = (await c.get(f"{BASE}/api/rooms/{rid}/cards", headers=h)).json()
        assert len(cards2["npcs"]) == 0
        print("after delete npcs=", len(cards2["npcs"]))

    print("RESULT: ✅ Phase A 角色卡 API 全通（玩家卡升级 + NPC 卡 CRUD）")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
