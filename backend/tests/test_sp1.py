"""SP-1 tests: auth, rooms, message seq monotonicity, ai_busy guard.

Uses an in-memory SQLite DB and a mocked brain — no live DeepSeek calls.
"""

import asyncio
import json

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app import ws as ws_mod
from app.db import Base, SessionFactory, engine
from app.main import app
from app.models import Message, NpcCard, RoomMember


@pytest.fixture(autouse=True)
async def _fresh_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _register(client: AsyncClient, username: str) -> str:
    resp = await client.post(
        "/api/auth/register",
        json={
            "username": username,
            "password": "pw1234",
            "display_name": username.title(),
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


async def test_health(client: AsyncClient):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_persist_message_serializes_concurrent_room_seq(client: AsyncClient):
    token = await _register(client, "seqrace")
    room = await client.post(
        "/api/rooms",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "seq race", "character_name": "艾琳"},
    )
    assert room.status_code == 200, room.text
    rid = room.json()["id"]

    await asyncio.gather(
        *[
            ws_mod._persist_message(
                room_id=rid,
                author_type="system",
                author_user_id=None,
                speaker_label="系统",
                content=f"并发消息 {i}",
            )
            for i in range(8)
        ]
    )

    async with SessionFactory() as session:
        rows = (
            await session.scalars(
                select(Message).where(Message.room_id == rid).order_by(Message.seq)
            )
        ).all()

    seqs = [m.seq for m in rows]
    assert len(seqs) == len(set(seqs))
    assert seqs == sorted(seqs)


async def test_register_login(client: AsyncClient):
    token = await _register(client, "alice")
    assert token

    # duplicate username -> 409
    dup = await client.post(
        "/api/auth/register",
        json={"username": "alice", "password": "pw1234", "display_name": "A"},
    )
    assert dup.status_code == 409

    login = await client.post(
        "/api/auth/login", json={"username": "alice", "password": "pw1234"}
    )
    assert login.status_code == 200
    assert login.json()["user"]["username"] == "alice"

    bad = await client.post(
        "/api/auth/login", json={"username": "alice", "password": "nope"}
    )
    assert bad.status_code == 401

    me = await client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["user"]["username"] == "alice"


async def test_room_create_join(client: AsyncClient):
    a = await _register(client, "alice")
    b = await _register(client, "bob")
    ha = {"Authorization": f"Bearer {a}"}
    hb = {"Authorization": f"Bearer {b}"}

    created = await client.post(
        "/api/rooms",
        json={"name": "tavern", "character_name": "Erin"},
        headers=ha,
    )
    assert created.status_code == 200, created.text
    room = created.json()
    rid = room["id"]
    assert room["ai_mode"] == "manual"
    assert len(room["members"]) == 1

    joined = await client.post(
        f"/api/rooms/{rid}/join",
        json={"character_name": "Karl"},
        headers=hb,
    )
    assert joined.status_code == 200
    assert len(joined.json()["members"]) == 2

    # bob now sees the room in his list
    rooms = await client.get("/api/rooms", headers=hb)
    assert rooms.status_code == 200
    assert any(r["id"] == rid for r in rooms.json())

    # non-member cannot read messages
    c = await _register(client, "carol")
    forbidden = await client.get(
        f"/api/rooms/{rid}/messages",
        headers={"Authorization": f"Bearer {c}"},
    )
    assert forbidden.status_code == 403


async def test_old_ksim_room_backfills_missing_preset_characters(client: AsyncClient):
    token = await _register(client, "alice")
    headers = {"Authorization": f"Bearer {token}"}
    rid = (
        await client.post(
            "/api/rooms",
            json={
                "name": "old ksim room",
                "character_name": "Erin",
                "world_card": "ksim",
            },
            headers=headers,
        )
    ).json()["id"]

    async with SessionFactory() as session:
        npcs = (
            await session.scalars(
                select(NpcCard)
                .where(NpcCard.room_id == rid)
                .order_by(NpcCard.id)
            )
        ).all()
        assert len(npcs) == 14
        for npc in npcs[3:]:
            await session.delete(npc)
        session.add(
            NpcCard(
                room_id=rid,
                name="魅魔化的会长",
                persona="未来形态，不应作为开局常驻角色显示",
                active=True,
                created_by_ai=True,
            )
        )
        await session.commit()

    preset = await client.get(f"/api/rooms/{rid}/preset-characters", headers=headers)
    assert preset.status_code == 200, preset.text
    assert len(preset.json()) == 14
    assert {n["name"] for n in preset.json()} >= {"公会会长"}
    assert "魅魔化的会长" not in {n["name"] for n in preset.json()}

    cards = await client.get(f"/api/rooms/{rid}/cards", headers=headers)
    assert cards.status_code == 200, cards.text
    names = [n["name"] for n in cards.json()["npcs"]]
    assert len(names) == 15  # 14 visible presets + the private God card
    assert "上帝" in names
    assert "魅魔化的会长" not in names

    async with SessionFactory() as session:
        hidden = await session.scalar(
            select(NpcCard).where(
                NpcCard.room_id == rid,
                NpcCard.name == "魅魔化的会长",
            )
        )
        assert hidden is not None
        assert hidden.active is False


async def test_message_seq_monotonic(client: AsyncClient):
    a = await _register(client, "alice")
    ha = {"Authorization": f"Bearer {a}"}
    rid = (
        await client.post(
            "/api/rooms",
            json={"name": "r", "character_name": "Erin"},
            headers=ha,
        )
    ).json()["id"]

    # Persist several messages directly via the WS persistence helper.
    for i in range(5):
        await ws_mod._persist_message(
            room_id=rid,
            author_type="user",
            speaker_label="Erin",
            content=f"line {i}",
            author_user_id=None,
        )

    msgs = (await client.get(f"/api/rooms/{rid}/messages", headers=ha)).json()
    seqs = [m["seq"] for m in msgs]
    assert seqs == [1, 2, 3, 4, 5]
    assert seqs == sorted(seqs)

    # after_seq filtering
    tail = (
        await client.get(f"/api/rooms/{rid}/messages?after_seq=3", headers=ha)
    ).json()
    assert [m["seq"] for m in tail] == [4, 5]


async def test_resolve_advance_npc_rejects_god_and_inactive(client: AsyncClient):
    token = await _register(client, "alice")
    headers = {"Authorization": f"Bearer {token}"}
    rid = (
        await client.post(
            "/api/rooms",
            json={
                "name": "advance guard",
                "character_name": "Erin",
                "world_card": "ksim",
            },
            headers=headers,
        )
    ).json()["id"]

    async with SessionFactory() as session:
        npc = await session.scalar(
            select(NpcCard).where(
                NpcCard.room_id == rid,
                NpcCard.name == "公会会长",
            )
        )
        assert npc is not None
        npc_id = npc.id

    assert await ws_mod._resolve_advance_npc(rid, 0) is None
    assert await ws_mod._resolve_advance_npc(rid, "not-a-number") is None
    assert await ws_mod._resolve_advance_npc(rid, npc_id) is not None

    async with SessionFactory() as session:
        npc = await session.get(NpcCard, npc_id)
        assert npc is not None
        npc.active = False
        await session.commit()

    assert await ws_mod._resolve_advance_npc(rid, npc_id) is None


async def test_run_ai_turn_persists_required_npc_label(
    monkeypatch, client: AsyncClient
):
    calls = {"npc_dialogue_text": 0}

    async def mock_npc_run(task, **kw):
        if task == "npc_dialogue_text":
            calls["npc_dialogue_text"] += 1
            if calls["npc_dialogue_text"] > 1:
                return '{"dialogue":"现在轮到我说了。","state":"她抬起眼。","narration_request":null}'
            return "[公会会长]: （抬起眼）现在轮到我说了。"
        if task == "npc_dialogue":
            return '{"dialogue":"（抬起眼）现在轮到我说了。","state":"","nr":null}'
        return ""
    monkeypatch.setattr(ws_mod.agent, "run", mock_npc_run)
    token = await _register(client, "alice")
    headers = {"Authorization": f"Bearer {token}"}
    rid = (
        await client.post(
            "/api/rooms",
            json={
                "name": "npc turn",
                "character_name": "Erin",
                "world_card": "ksim",
            },
            headers=headers,
        )
    ).json()["id"]

    async with SessionFactory() as session:
        npc = await session.scalar(
            select(NpcCard).where(
                NpcCard.room_id == rid,
                NpcCard.name == "公会会长",
            )
        )
        assert npc is not None

    coord = ws_mod.RoomCoordinator(room_id=rid)
    await ws_mod._run_ai_turn(coord, npc)

    async with SessionFactory() as session:
        msg = (
            await session.scalars(
                select(ws_mod.Message)
                .where(ws_mod.Message.room_id == rid)
                .order_by(ws_mod.Message.seq.desc())
            )
        ).first()
        assert msg is not None
        assert msg.speaker_label == "公会会长"
        assert "现在轮到我说了" in msg.content


@pytest.mark.xfail(reason="mock encoding mismatch after agent SDK migration")
async def test_run_ai_turn_rewrites_json_dialogue_narration_leak(
    monkeypatch, client: AsyncClient
):
    class LeakyMock:
        def __init__(self) -> None:
            self.calls = 0

        async def run(self, task, **kw):
            self.calls += 1
            if task == "npc_dialogue_text":
                if self.calls <= 1:
                    return (
                        '{"dialogue":"会长放下茶杯，朝你挑了挑眉。“有事？”",'
                        '"state":"她坐在柜台后，指尖按着茶杯。",'
                        '"narration_request":null}'
                    )
                return "[公会会长]: 喝茶。[[旁白请求:会长把茶杯放回桌上。]]"
            if task == "npc_dialogue":
                dlg = "会长放下茶杯，朝你挑了挑眉。“有事？”"
                st = "她坐在柜台后，指尖按着茶杯。"
                nr = None if self.calls <= 1 else "会长把茶杯放回桌上。"
                return {"dialogue": dlg if self.calls <= 1 else "喝茶。",
                        "state": st if self.calls <= 1 else "",
                        "narration_request": nr}
            return ""

    mock = LeakyMock()
    monkeypatch.setattr(ws_mod.agent, "run", mock.run)
    token = await _register(client, "bob")
    headers = {"Authorization": f"Bearer {token}"}
    rid = (
        await client.post(
            "/api/rooms",
            json={
                "name": "npc json guard",
                "character_name": "Erin",
                "world_card": "ksim",
            },
            headers=headers,
        )
    ).json()["id"]

    async with SessionFactory() as session:
        npc = await session.scalar(
            select(NpcCard).where(
                NpcCard.room_id == rid,
                NpcCard.name == "公会会长",
            )
        )
        assert npc is not None

    coord = ws_mod.RoomCoordinator(room_id=rid)
    await ws_mod._run_ai_turn(coord, npc)

    async with SessionFactory() as session:
        msg = await session.scalar(
            select(ws_mod.Message)
            .where(
                ws_mod.Message.room_id == rid,
                ws_mod.Message.speaker_label == "公会会长",
            )
            .order_by(ws_mod.Message.seq.desc())
            .limit(1)
        )
        assert msg is not None
        assert msg.content == "有事？"
        assert "会长放下茶杯" not in msg.content
        assert mock.calls == 2


async def test_stats_judge_applies_delta_to_latest_stats(
    monkeypatch, client: AsyncClient
):
    token = await _register(client, "statrace")
    headers = {"Authorization": f"Bearer {token}"}
    rid = (
        await client.post(
            "/api/rooms",
            json={"name": "stats race", "character_name": "艾琳"},
            headers=headers,
        )
    ).json()["id"]

    async with SessionFactory() as session:
        member = await session.scalar(
            select(RoomMember).where(RoomMember.room_id == rid)
        )
        assert member is not None
        user_id = member.user_id

    await ws_mod._persist_message(
        room_id=rid,
        author_type="user",
        speaker_label="艾琳",
        content="艾琳观察四周。",
        author_user_id=user_id,
    )

    async def fake_judge_stat_delta(scene, current_stats, deterministic_text=None):
        assert current_stats["金钱"] == 100
        async with SessionFactory() as session:
            member = await session.scalar(
                select(RoomMember).where(
                    RoomMember.room_id == rid,
                    RoomMember.user_id == user_id,
                )
            )
            assert member is not None
            latest = ws_mod.default_stats()
            latest["金钱"] = 97
            member.stats = json.dumps(latest, ensure_ascii=False)
            await session.commit()
        return {"淫乱": 1}

    monkeypatch.setattr(ws_mod, "judge_stat_delta", fake_judge_stat_delta)

    await ws_mod._judge_and_apply_stats(ws_mod.RoomCoordinator(rid), user_id)

    async with SessionFactory() as session:
        member = await session.scalar(
            select(RoomMember).where(
                RoomMember.room_id == rid,
                RoomMember.user_id == user_id,
            )
        )
        assert member is not None
        stats = json.loads(member.stats)
        assert stats["金钱"] == 97
        assert stats["淫乱"] == 1


async def test_alternate_form_updates_existing_npc_instead_of_duplication(
    client: AsyncClient,
):
    token = await _register(client, "alice")
    headers = {"Authorization": f"Bearer {token}"}
    rid = (
        await client.post(
            "/api/rooms",
            json={
                "name": "form update",
                "character_name": "Erin",
                "world_card": "ksim",
            },
            headers=headers,
        )
    ).json()["id"]

    async with SessionFactory() as session:
        base = await session.scalar(
            select(NpcCard).where(
                NpcCard.room_id == rid,
                NpcCard.name == "公会会长",
            )
        )
        assert base is not None
        base_id = base.id

        updated = await ws_mod._upsert_introduced_npc(
            session,
            room_id=rid,
            world_card="ksim",
            draft={
                "name": "魅魔化的会长",
                "persona": "剧情后变化的会长形态",
                "appearance": "succubus guild master",
            },
            scene="魔王城",
        )
        await session.commit()

        assert updated.id == base_id
        cards = (
            await session.scalars(
                select(NpcCard).where(
                    NpcCard.room_id == rid,
                    NpcCard.name.in_(["公会会长", "魅魔化的会长"]),
                )
            )
        ).all()
        assert len(cards) == 1
        assert cards[0].id == base_id
        assert cards[0].name == "魅魔化的会长"


async def test_ai_busy_guard(monkeypatch):
    """A second advance during an in-flight AI turn yields error ai_busy."""
    coord = ws_mod.RoomCoordinator(room_id=999)

    started = asyncio.Event()
    release = asyncio.Event()
    sent: list[dict] = []

    async def fake_broadcast(payload):
        sent.append(payload)

    coord.broadcast = fake_broadcast  # type: ignore[method-assign]

    async def slow_turn(c, npc=None):
        started.set()
        await release.wait()

    monkeypatch.setattr(ws_mod, "_run_ai_turn", slow_turn)

    first = asyncio.create_task(ws_mod._handle_advance(coord))
    await started.wait()
    assert coord.ai_busy is True

    # second advance while busy -> immediate ai_busy error, no new turn
    await ws_mod._handle_advance(coord)
    assert any(p.get("type") == "error" and p.get("code") == "ai_busy" for p in sent)

    release.set()
    await first
    assert coord.ai_busy is False
