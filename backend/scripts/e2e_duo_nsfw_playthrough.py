# /// script
# requires-python = ">=3.13"
# dependencies = ["httpx", "websockets"]
# ///
"""Two-player ksim NSFW playthrough probe.

This is intentionally a real playthrough probe:
- two real users join the same room
- both websocket clients send player actions
- movement/exploration/NPC turns/timeskip are normal room actions
- no database writes or stat injection are used

The script prints event summaries instead of dumping explicit generated prose.
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
MAX_TICKS = int(os.environ.get("DUET_DUO_NSFW_TICKS", "12"))


async def reg_or_login(
    c: httpx.AsyncClient, username: str, password: str, display_name: str
) -> str:
    r = await c.post(
        f"{BASE}/api/auth/register",
        json={"username": username, "password": password, "display_name": display_name},
    )
    if r.status_code == 409:
        r = await c.post(
            f"{BASE}/api/auth/login",
            json={"username": username, "password": password},
        )
    r.raise_for_status()
    return r.json()["token"]


async def api_get(c: httpx.AsyncClient, token: str, path: str) -> Any:
    r = await c.get(f"{BASE}{path}", headers={"Authorization": f"Bearer {token}"})
    r.raise_for_status()
    return r.json()


async def api_post(
    c: httpx.AsyncClient, token: str, path: str, body: dict[str, Any] | None = None
) -> httpx.Response:
    return await c.post(
        f"{BASE}{path}",
        headers={"Authorization": f"Bearer {token}"},
        json=body or {},
    )


async def api_put(
    c: httpx.AsyncClient, token: str, path: str, body: dict[str, Any]
) -> httpx.Response:
    return await c.put(
        f"{BASE}{path}",
        headers={"Authorization": f"Bearer {token}"},
        json=body,
    )


async def wait_for_history(ws, label: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    end = asyncio.get_event_loop().time() + 30
    while asyncio.get_event_loop().time() < end:
        msg = json.loads(await asyncio.wait_for(ws.recv(), end - asyncio.get_event_loop().time()))
        events.append(msg)
        if msg.get("type") == "history":
            return events
    raise TimeoutError(f"{label} did not receive history")


async def collect_one(ws, *, timeout: float = 150, quiet: float = 8.0) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    end = asyncio.get_event_loop().time() + timeout
    saw_busy = False
    while asyncio.get_event_loop().time() < end:
        try:
            msg = json.loads(await asyncio.wait_for(ws.recv(), quiet))
        except TimeoutError:
            break
        events.append(msg)
        if msg.get("type") == "ai_status":
            saw_busy = saw_busy or msg.get("busy") is True
            if saw_busy and msg.get("busy") is False:
                break
        if msg.get("type") == "ending":
            break
        if msg.get("type") == "message" and (msg.get("message") or {}).get("author_type") == "image":
            break
    return events


async def collect_both(wa, wb, *, timeout: float = 150) -> list[dict[str, Any]]:
    left, right = await asyncio.gather(
        collect_one(wa, timeout=timeout),
        collect_one(wb, timeout=timeout),
    )
    return left + right


async def request_scene_image(
    ws,
    wa,
    wb,
    *,
    prompt: str,
    characters: list[str],
) -> tuple[bool, list[dict[str, Any]]]:
    await ws.send(
        json.dumps(
            {
                "type": "image",
                "custom_prompt": prompt,
                "characters": characters,
                "nsfw": True,
            },
            ensure_ascii=False,
        )
    )
    events: list[dict[str, Any]] = []
    pending = False
    end = asyncio.get_event_loop().time() + 360
    sockets = [wa, wb]
    while asyncio.get_event_loop().time() < end:
        tasks = [asyncio.create_task(s.recv()) for s in sockets]
        done, pending_tasks = await asyncio.wait(
            tasks,
            timeout=12 if pending else 45,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending_tasks:
            task.cancel()
        if not done:
            break
        for task in done:
            msg = json.loads(task.result())
            events.append(msg)
            if msg.get("type") == "image_pending":
                pending = True
            if (
                msg.get("type") == "message"
                and (msg.get("message") or {}).get("author_type") == "image"
            ):
                return True, events
            if msg.get("type") == "error" and str(msg.get("code", "")).startswith("image"):
                return False, events
    return False, events


def event_messages(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        e["message"]
        for e in events
        if e.get("type") == "message" and isinstance(e.get("message"), dict)
    ]


def summarize_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    messages = event_messages(events)
    speakers = [
        m.get("speaker_label")
        for m in messages
        if m.get("author_type") in {"ai", "user", "system"}
    ]
    return {
        "messages": len(messages),
        "stats": sum(1 for e in events if e.get("type") == "stats"),
        "scenes": sum(1 for e in events if e.get("type") == "scene"),
        "ai_done": sum(1 for e in events if e.get("type") == "ai_done"),
        "ending": next((e.get("name") for e in events if e.get("type") == "ending"), None),
        "speakers": list(dict.fromkeys(str(s) for s in speakers if s))[:8],
    }


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
            errors.append(f"unknown_ai_speaker={label}")
        if text.startswith("[旁白]") or text == "（……）":
            errors.append(f"bad_npc_content={label}")
        if any(mark in text for mark in ("[旁白]:", "[NPC]:", "[AI]:")):
            errors.append(f"leaky_label={label}")
    return errors


async def main() -> int:
    stamp = int(time.time())
    async with httpx.AsyncClient(timeout=180) as c:
        ta = await reg_or_login(c, f"duo_nsfw_a_{stamp}", "pw_duo_nsfw", "玩家A")
        tb = await reg_or_login(c, f"duo_nsfw_b_{stamp}", "pw_duo_nsfw", "玩家B")
        ha = {"Authorization": f"Bearer {ta}"}
        hb = {"Authorization": f"Bearer {tb}"}
        card_a = {
            "name": "艾琳",
            "persona": "成年女骑士，谨慎但有保护欲，面对黑暗诱惑时会强撑理智。",
            "appearance": "adult female knight, silver white hair, purple eyes, ornate damaged armor, cloak",
            "appearance_tags": "1girl, adult female, silver white hair, purple eyes, ornate armor, cloak",
            "source_world_card": "ksim",
        }
        card_b = {
            "name": "米拉",
            "persona": "成年盗贼斥候，黑发金瞳，喜欢冒险和挑衅，会保护同伴但容易被危险吸引。",
            "appearance": "adult female rogue, black hair, golden eyes, leather armor, dagger, sly smile",
            "appearance_tags": "1girl, adult female, black hair, golden eyes, leather armor, dagger",
            "source_world_card": "ksim",
        }
        ca = await api_post(c, ta, "/api/me/character-cards", card_a)
        cb = await api_post(c, tb, "/api/me/character-cards", card_b)
        ca.raise_for_status()
        cb.raise_for_status()
        print(f"created_cards={ca.json()['name']},{cb.json()['name']}")
        room_resp = await c.post(
            f"{BASE}/api/rooms",
            headers=ha,
            json={
                "name": f"双人NSFW真实跑团 {stamp}",
                "character_name": "艾琳",
                "world_card": "ksim",
                "appearance": card_a["appearance"],
            },
        )
        room_resp.raise_for_status()
        rid = room_resp.json()["id"]
        join_resp = await c.post(
            f"{BASE}/api/rooms/{rid}/join",
            headers=hb,
            json={"character_name": "米拉", "appearance": card_b["appearance"]},
        )
        join_resp.raise_for_status()
        ua = await api_put(
            c,
            ta,
            f"/api/rooms/{rid}/me-card",
            {**card_a, "character_name": card_a["name"], "reset_stats": True},
        )
        ub = await api_put(
            c,
            tb,
            f"/api/rooms/{rid}/me-card",
            {**card_b, "character_name": card_b["name"], "reset_stats": True},
        )
        ua.raise_for_status()
        ub.raise_for_status()
        image_results: dict[str, Any] = {"avatar_a": None, "avatar_b": None, "npc_avatar": None}
        for key, token in (("avatar_a", ta), ("avatar_b", tb)):
            try:
                r = await api_post(c, token, f"/api/rooms/{rid}/me-card/avatar")
                image_results[key] = r.status_code if r.status_code != 200 else "ok"
            except Exception as exc:  # noqa: BLE001
                image_results[key] = type(exc).__name__
        cards = await api_get(c, ta, f"/api/rooms/{rid}/cards")
        npcs = [n for n in cards["npcs"] if n.get("id") and n.get("active")]
        npc_names = {n["name"] for n in npcs}
        if npcs:
            try:
                r = await api_post(c, ta, f"/api/rooms/{rid}/npcs/{npcs[0]['id']}/avatar")
                image_results["npc_avatar"] = r.status_code if r.status_code != 200 else "ok"
            except Exception as exc:  # noqa: BLE001
                image_results["npc_avatar"] = type(exc).__name__
        cards = await api_get(c, ta, f"/api/rooms/{rid}/cards")
        room_players = [p["character_name"] for p in cards["players"]]
        print(f"room={rid} players=艾琳,米拉 npcs={list(npc_names)[:5]}")
        print("room_players_after_setup:", json.dumps(room_players, ensure_ascii=False))
        print("portrait_results:", json.dumps(image_results, ensure_ascii=False))

    all_events: list[dict[str, Any]] = []
    async with websockets.connect(f"{WS}/ws/rooms/{rid}?token={ta}") as wa, websockets.connect(
        f"{WS}/ws/rooms/{rid}?token={tb}"
    ) as wb:
        all_events.extend(await wait_for_history(wa, "A"))
        all_events.extend(await wait_for_history(wb, "B"))
        all_events.extend(await collect_both(wa, wb, timeout=40))

        scene_image_ok, events = await request_scene_image(
            wa,
            wa,
            wb,
            prompt="双人进入冒险者公会前的角色亮相，展示艾琳和米拉的成人黑暗奇幻冒险氛围。",
            characters=["艾琳", "米拉"],
        )
        all_events.extend(events)
        print("scene_image_opening:", scene_image_ok)

        script = [
            ("A", "say", "艾琳压低声音问米拉：这个城镇里失踪的冒险者，是不是都和成人黑暗传闻有关？"),
            ("B", "say", "米拉点头，提议先去酒馆打听线索，再决定是否深入危险区域。"),
            ("A", "goto_scene", "酒馆"),
            ("B", "say", "米拉向吧台打听最近失踪者、借贷商和森林小路的传闻。"),
            ("A", "advance", ""),
            ("B", "goto_scene", "森林小路"),
            ("A", "say", "艾琳和米拉沿着森林小路探索，检查被遗弃的装备和可疑脚印。"),
            ("B", "advance", ""),
            ("A", "goto_scene", "哥布林巢穴"),
            ("B", "say", "米拉跟上艾琳，两人进入巢穴深处，准备面对伏击和失控风险。"),
            ("A", "say", "艾琳试图保护米拉撤退，但巢穴里的敌意越来越近，局势开始崩坏。"),
            ("B", "advance", ""),
            ("A", "image", "巢穴深处的双人危机画面，艾琳和米拉共同面对哥布林伏击。"),
        ]

        ending_name = None
        for index, (who, kind, content) in enumerate(script, start=1):
            ws = wa if who == "A" else wb
            print(f"step {index}: player={who} action={kind}")
            if kind == "say":
                await ws.send(json.dumps({"type": "say", "content": content}, ensure_ascii=False))
            elif kind == "advance":
                await ws.send(json.dumps({"type": "advance"}, ensure_ascii=False))
            elif kind == "goto_scene":
                await ws.send(json.dumps({"type": "goto_scene", "scene": content}, ensure_ascii=False))
            elif kind == "image":
                ok, events = await request_scene_image(
                    ws,
                    wa,
                    wb,
                    prompt=content,
                    characters=["艾琳", "米拉", *list(npc_names)[:1]],
                )
                print("  image:", ok)
                all_events.extend(events)
                summary = summarize_events(events)
                print("  summary:", json.dumps(summary, ensure_ascii=False))
                ending_name = summary["ending"] or ending_name
                continue
            events = await collect_both(wa, wb)
            all_events.extend(events)
            summary = summarize_events(events)
            print("  summary:", json.dumps(summary, ensure_ascii=False))
            ending_name = summary["ending"] or ending_name
            if ending_name:
                break

        image_attempts = 1
        image_successes = 1 if scene_image_ok else 0
        for day in range(1, MAX_TICKS + 1):
            if ending_name:
                break
            print(f"day {day}: captive play beat A")
            await wa.send(
                json.dumps(
                    {
                        "type": "say",
                        "content": (
                            "艾琳在哥布林巢穴里寻找逃脱机会，观察守卫间隙，"
                            "但被困处境和成人黑暗压力仍在持续。"
                        ),
                    },
                    ensure_ascii=False,
                )
            )
            events = await collect_both(wa, wb, timeout=180)
            all_events.extend(events)
            summary = summarize_events(events)
            print("  summary:", json.dumps(summary, ensure_ascii=False))
            ending_name = summary["ending"] or ending_name
            if ending_name:
                break

            print(f"day {day}: captive play beat B")
            await wb.send(
                json.dumps(
                    {
                        "type": "say",
                        "content": (
                            "米拉试图从另一侧制造动静，帮艾琳分散哥布林注意，"
                            "同时寻找能移动到出口或更深处的路线。"
                        ),
                    },
                    ensure_ascii=False,
                )
            )
            events = await collect_both(wa, wb, timeout=180)
            all_events.extend(events)
            summary = summarize_events(events)
            print("  summary:", json.dumps(summary, ensure_ascii=False))
            ending_name = summary["ending"] or ending_name
            if ending_name:
                break

            print(f"day {day}: NPC/world reaction")
            await (wa if day % 2 else wb).send(json.dumps({"type": "advance"}, ensure_ascii=False))
            events = await collect_both(wa, wb, timeout=180)
            all_events.extend(events)
            summary = summarize_events(events)
            print("  summary:", json.dumps(summary, ensure_ascii=False))
            ending_name = summary["ending"] or ending_name
            if ending_name:
                break

            if day in {1, 2, 4, 6}:
                print(f"day {day}: nsfw scene image")
                ok, events = await request_scene_image(
                    wa if day % 2 else wb,
                    wa,
                    wb,
                    prompt=(
                        "哥布林巢穴内的双人危机进展，强调成人黑暗奇幻氛围、"
                        "艾琳和米拉的处境变化、环境压迫感。"
                    ),
                    characters=["艾琳", "米拉", *list(npc_names)[:1]],
                )
                image_attempts += 1
                image_successes += 1 if ok else 0
                all_events.extend(events)
                summary = summarize_events(events)
                print("  image:", ok)
                print("  summary:", json.dumps(summary, ensure_ascii=False))
                ending_name = summary["ending"] or ending_name
                if ending_name:
                    break

            print(f"day {day}: overnight/timeskip")
            await (wa if day % 2 else wb).send(json.dumps({"type": "timeskip"}, ensure_ascii=False))
            events = await collect_both(wa, wb, timeout=180)
            all_events.extend(events)
            summary = summarize_events(events)
            print("  summary:", json.dumps(summary, ensure_ascii=False))
            ending_name = summary["ending"] or ending_name

    async with httpx.AsyncClient(timeout=60) as c:
        cards_final = await api_get(c, ta, f"/api/rooms/{rid}/cards")
    final_players = [
        {
            "name": p.get("character_name"),
            "淫乱": (p.get("stats") or {}).get("淫乱"),
            "意志": (p.get("stats") or {}).get("意志"),
            "状态": (p.get("stats") or {}).get("状态"),
        }
        for p in cards_final["players"]
    ]
    messages = event_messages(all_events)
    label_errors = npc_label_errors(messages, npc_names)
    checks = {
        "both_players_connected": True,
        "both_players_spoke": {"艾琳", "米拉"}.issubset(
            {m.get("speaker_label") for m in messages}
        ),
        "movement_seen": any(e.get("type") == "scene" for e in all_events),
        "npc_or_narrator_seen": any(
            m.get("author_type") == "ai" for m in messages
        ),
        "stats_seen": any(e.get("type") == "stats" for e in all_events),
        "ending_seen": ending_name is not None,
        "npc_labels_clean": not label_errors,
        "nsfw_images_used": image_attempts >= 3 and image_successes >= 2,
    }
    print("checks:", json.dumps(checks, ensure_ascii=False))
    print("ending:", ending_name)
    print("image_usage:", json.dumps({"attempts": image_attempts, "successes": image_successes}, ensure_ascii=False))
    print("final_players:", json.dumps(final_players, ensure_ascii=False))
    if label_errors:
        print("label_errors:", json.dumps(label_errors, ensure_ascii=False))
    ok = all(checks.values())
    print("RESULT:", "✅ 双人NSFW真实跑团到结局通过" if ok else "⚠️ 双人NSFW真实跑团未完整到结局")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
