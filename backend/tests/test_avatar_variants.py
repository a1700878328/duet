import pytest
from httpx import ASGITransport, AsyncClient

from app import rooms as rooms_mod
from app.db import Base, engine
from app.main import app


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


async def _register(client: AsyncClient, username: str = "alice") -> str:
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


async def _room(client: AsyncClient, token: str) -> int:
    resp = await client.post(
        "/api/rooms",
        json={"name": "variants", "character_name": "Erin"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_member_avatar_generation_keeps_variants(monkeypatch, client):
    urls = iter(["/media/generated/a.png", "/media/generated/b.png"])

    async def fake_generate_portrait(*_args, **_kwargs):
        return {"url": next(urls)}

    monkeypatch.setattr(rooms_mod, "generate_portrait", fake_generate_portrait)

    token = await _register(client)
    headers = {"Authorization": f"Bearer {token}"}
    rid = await _room(client, token)

    first = await client.post(f"/api/rooms/{rid}/me-card/avatar", headers=headers)
    assert first.status_code == 200, first.text
    assert first.json()["avatar_url"] == "/media/generated/a.png"
    assert [v["url"] for v in first.json()["avatar_variants"]] == [
        "/media/generated/a.png"
    ]

    second = await client.post(f"/api/rooms/{rid}/me-card/avatar", headers=headers)
    assert second.status_code == 200, second.text
    assert second.json()["avatar_url"] == "/media/generated/b.png"
    assert [v["url"] for v in second.json()["avatar_variants"]] == [
        "/media/generated/b.png",
        "/media/generated/a.png",
    ]

    selected = await client.put(
        f"/api/rooms/{rid}/me-card/avatar/current",
        json={"avatar_url": "/media/generated/a.png"},
        headers=headers,
    )
    assert selected.status_code == 200, selected.text
    assert selected.json()["avatar_url"] == "/media/generated/a.png"
    assert {v["url"] for v in selected.json()["avatar_variants"]} == {
        "/media/generated/a.png",
        "/media/generated/b.png",
    }


@pytest.mark.asyncio
async def test_member_regenerated_voice_can_be_saved_to_library(monkeypatch, client):
    async def fake_design_and_write_voice(**_kwargs):
        return (
            "fish-clone:new-player-voice",
            "/media/audio/ref_new_player_voice.mp3",
            "别担心，我已经准备好了。这一次，就让我亲自来收尾吧。",
        )

    monkeypatch.setattr(
        rooms_mod, "_design_and_write_voice", fake_design_and_write_voice
    )

    token = await _register(client)
    headers = {"Authorization": f"Bearer {token}"}
    rid = await _room(client, token)

    regenerated = await client.post(f"/api/rooms/{rid}/me-card/voice", headers=headers)
    assert regenerated.status_code == 200, regenerated.text
    member = regenerated.json()
    assert member["voice_id"] == "fish-clone:new-player-voice"
    assert member["voice_ref_url"] == "/media/audio/ref_new_player_voice.mp3"
    assert member["voice_ref_text"].startswith("别担心")

    created = await client.post(
        "/api/me/character-cards",
        json={
            "name": member["character_name"],
            "persona": member["persona"] or "",
            "appearance": member["appearance"],
            "voice_id": "old-voice",
            "voice_ref_url": "/media/audio/old.mp3",
            "voice_ref_text": "旧语音",
            "avatar_url": member["avatar_url"],
            "avatar_variants": member["avatar_variants"],
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text

    saved = await client.put(
        f"/api/me/character-cards/{created.json()['id']}",
        json={
            "name": member["character_name"],
            "persona": member["persona"] or "",
            "appearance": member["appearance"],
            "voice_id": member["voice_id"],
            "voice_ref_url": member["voice_ref_url"],
            "voice_ref_text": member["voice_ref_text"],
            "avatar_url": member["avatar_url"],
            "avatar_variants": member["avatar_variants"],
        },
        headers=headers,
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["voice_id"] == "fish-clone:new-player-voice"
    assert saved.json()["voice_ref_url"] == "/media/audio/ref_new_player_voice.mp3"
    assert saved.json()["voice_ref_text"].startswith("别担心")


@pytest.mark.asyncio
async def test_member_voice_generation_keeps_card_when_audio_provider_fails(
    monkeypatch, client
):
    async def fake_design_and_write_voice(**_kwargs):
        raise rooms_mod.HTTPException(status_code=502, detail="provider down")

    async def fake_voice_metadata_for_card(**_kwargs):
        return "年轻女性，清亮柔软，日漫声优感", "你好，我已经准备好了。"

    monkeypatch.setattr(
        rooms_mod, "_design_and_write_voice", fake_design_and_write_voice
    )
    monkeypatch.setattr(
        rooms_mod, "_voice_metadata_for_card", fake_voice_metadata_for_card
    )

    token = await _register(client)
    headers = {"Authorization": f"Bearer {token}"}
    rid = await _room(client, token)

    regenerated = await client.post(f"/api/rooms/{rid}/me-card/voice", headers=headers)

    assert regenerated.status_code == 200, regenerated.text
    member = regenerated.json()
    assert member["voice_id"] == "年轻女性，清亮柔软，日漫声优感"
    assert member["voice_ref_text"] == "你好，我已经准备好了。"
    assert member["voice_ref_url"] is None


@pytest.mark.asyncio
async def test_npc_avatar_generation_keeps_variants(monkeypatch, client):
    urls = iter(["/media/generated/npc-a.png", "/media/generated/npc-b.png"])

    async def fake_generate_portrait(*_args, **_kwargs):
        return {"url": next(urls)}

    monkeypatch.setattr(rooms_mod, "generate_portrait", fake_generate_portrait)

    token = await _register(client)
    headers = {"Authorization": f"Bearer {token}"}
    rid = await _room(client, token)
    created = await client.post(
        f"/api/rooms/{rid}/npcs",
        json={"name": "Guide", "persona": "Helpful guide", "appearance": "woman"},
        headers=headers,
    )
    assert created.status_code == 200, created.text
    npc_id = created.json()["id"]

    await client.post(f"/api/rooms/{rid}/npcs/{npc_id}/avatar", headers=headers)
    second = await client.post(
        f"/api/rooms/{rid}/npcs/{npc_id}/avatar", headers=headers
    )
    assert second.status_code == 200, second.text
    assert [v["url"] for v in second.json()["avatar_variants"]] == [
        "/media/generated/npc-b.png",
        "/media/generated/npc-a.png",
    ]

    selected = await client.put(
        f"/api/rooms/{rid}/npcs/{npc_id}/avatar/current",
        json={"avatar_url": "/media/generated/npc-a.png"},
        headers=headers,
    )
    assert selected.status_code == 200, selected.text
    assert selected.json()["avatar_url"] == "/media/generated/npc-a.png"


@pytest.mark.asyncio
async def test_player_evolve_merges_persona_and_appearance(monkeypatch, client):
    class EvolveBrain:
        temperature = 0
        max_tokens = 0

        async def complete(self, _messages):
            return (
                '{"persona":"新人设：冷静但更自信的女骑士",'
                '"appearance":"blonde hair, blue eyes, colored eyelashes, '
                'confident smile, blush, closed mouth, silver armor, '
                'three-quarter view, eyes toward viewer"}'
            )

    async def fake_generate_portrait(*_args, **_kwargs):
        return {"url": "/media/generated/evolved.png"}

    monkeypatch.setattr(rooms_mod, "agent_provider", lambda _agent: EvolveBrain())
    monkeypatch.setattr(rooms_mod, "generate_portrait", fake_generate_portrait)

    token = await _register(client)
    headers = {"Authorization": f"Bearer {token}"}
    rid = await _room(client, token)

    evolved = await client.post(
        f"/api/rooms/{rid}/me-card/evolve",
        json={"persona_add": "经历战斗后变得更自信。"},
        headers=headers,
    )

    assert evolved.status_code == 200, evolved.text
    body = evolved.json()
    assert body["persona"] == "新人设：冷静但更自信的女骑士"
    assert "closed mouth" in body["appearance"]
    assert body["avatar_url"] == "/media/generated/evolved.png"


@pytest.mark.asyncio
async def test_evolve_routes_accept_put_and_npc_needs_no_body(monkeypatch, client):
    class TagBrain:
        temperature = 0
        max_tokens = 0

        async def complete(self, _messages):
            return "silver hair, green eyes, colored eyelashes, closed mouth"

    async def fake_generate_portrait(*_args, **_kwargs):
        return {"url": "/media/generated/evolved-npc.png"}

    monkeypatch.setattr(rooms_mod, "agent_provider", lambda _agent: TagBrain())
    monkeypatch.setattr(rooms_mod, "generate_portrait", fake_generate_portrait)

    token = await _register(client)
    headers = {"Authorization": f"Bearer {token}"}
    rid = await _room(client, token)
    created = await client.post(
        f"/api/rooms/{rid}/npcs",
        json={"name": "Guide", "persona": "Helpful guide", "appearance": "woman"},
        headers=headers,
    )
    npc_id = created.json()["id"]

    npc_evolved = await client.put(
        f"/api/rooms/{rid}/npcs/{npc_id}/evolve", headers=headers
    )
    player_evolved = await client.put(
        f"/api/rooms/{rid}/me-card/evolve",
        json={"persona_add": "补充一段新设定。"},
        headers=headers,
    )

    assert npc_evolved.status_code == 200, npc_evolved.text
    assert npc_evolved.json()["avatar_url"] == "/media/generated/evolved-npc.png"
    assert player_evolved.status_code == 200, player_evolved.text
