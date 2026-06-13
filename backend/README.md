# Duet backend — SP-1

FastAPI backend for the 2-player collaborative AI roleplay vertical slice.
Stack: FastAPI + uvicorn, async SQLAlchemy 2 + aiosqlite, pydantic v2,
httpx, PyJWT (HS256), argon2.

## Setup

```bash
cd backend
uv sync
```

`.env` (already present) holds the DeepSeek provider config:

```
DEEPSEEK_API_KEY=...
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-v4-flash
```

Optional overrides: `JWT_SECRET`, `DB_URL` (default
`sqlite+aiosqlite:///./duet.db`), `HISTORY_WINDOW`, `ALLOW_LIVE_BRAIN`.

## Run

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

- `GET http://127.0.0.1:8000/api/health` → `{"status":"ok"}`
- If `../frontend/dist` exists it is served at `/` (tolerates absence).

## Test / lint

```bash
uv run pytest -q          # no live brain calls — brain is mocked
uv run ruff check .
```

## REST API (prefix `/api`, JWT Bearer)

| Method | Path | Body | Returns |
|--------|------|------|---------|
| GET  | `/api/health` | — | `{status:"ok"}` |
| POST | `/api/auth/register` | `{username,password,display_name}` | `{token,user}` |
| POST | `/api/auth/login` | `{username,password}` | `{token,user}` |
| GET  | `/api/me` | — | `{user}` |
| GET  | `/api/rooms` | — | `[{id,name,owner_id,ai_mode,members[]}]` |
| POST | `/api/rooms` | `{name,character_name}` | room (creator auto-joins) |
| POST | `/api/rooms/{id}/join` | `{character_name}` | room |
| GET  | `/api/rooms/{id}/messages?after_seq=0` | — | ordered messages |

`user = {id, username, display_name}`.
`member = {user_id, display_name, character_name}`.
`message = {id, room_id, seq, author_type, author_user_id, speaker_label, content, created_at}`.

## WebSocket `/ws/rooms/{room_id}?token=<jwt>`

Auth via query `token`; connection rejected (close 4401/4403) if the token is
invalid or the user is not a room member.

Client → server:
- `{"type":"say","content":str}`
- `{"type":"advance"}`
- `{"type":"typing","is_typing":bool}`

Server → client:
- on connect: `{"type":"history","messages":[...]}` then a `presence` broadcast
- `{"type":"message","message":{...}}`
- `{"type":"ai_delta","turn_id":str,"seq":int,"delta":str}`
- `{"type":"ai_done","turn_id":str,"seq":int,"content":str,"finish_reason":str}`
- `{"type":"presence","user_id":int,"display_name":str,"online":bool}`
- `{"type":"typing","user_id":int,"display_name":str,"is_typing":bool}`
- `{"type":"error","code":str,"detail":str}` (e.g. `ai_busy`, `ai_error`)

Per-room coordinator serialises seq allocation + persistence; only one AI turn
runs at a time (`advance` while busy → `error: ai_busy`).

## Brain provider (`app/brain.py`)

`BrainProvider` streams from an OpenAI-compatible `/chat/completions`. For the
thinking model `deepseek-v4-flash`, only `delta.content` is yielded;
`reasoning_content` is dropped. Swap to the Jetson Qwen fallback in one line:

```python
BrainProvider(
    api_key="...", base_url="http://192.168.1.102:8080/v1", model="qwen",
    extra_body={"chat_template_kwargs": {"enable_thinking": False}},
)
```
