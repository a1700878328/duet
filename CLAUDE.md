# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Duet** — a 2-player collaborative AI roleplay game (SP-1 vertical slice). Two players share a room with AI-directed NPCs in a fantasy world. The backend drives narrative, NPC behavior, stat management, image generation (ComfyUI), and voice synthesis (ElevenLabs/Fish Audio). The frontend is a React + Vite SPA.

## Current Source-of-Truth Guardrails

Read this before making changes. These rules are here because a stale Claude plan once overwrote newer Codex work.

- Treat the current worktree and tests as source of truth. Do not restore behavior from `.claude/plans`, older chat summaries, old specs, or checkpoint memory without first verifying it in the current code.
- Historical docs under `docs/superpowers/specs/` are design context, not current UI requirements. If they conflict with current code/tests, update the docs or ask, but do not reintroduce removed controls.
- Do not re-add a global `R18` button, a global `让 AI 接话` button, a global `推进时间` button, or an NPC auto-play voice toggle. Current flow is per-NPC action, private God whisper, scene/time systems, manual TTS preview.
- `上帝` is the private control channel (`npc_id=0`), not a public NPC speaker. WebSocket `advance` must never silently fall back to God or a generic AI speaker when an invalid NPC id is sent.
- For `ksim`, initial visible preset NPCs exclude alternate/future forms. The hidden alternate form `魅魔化的会长` must not appear beside `公会会长` in the initial role list or card panel.
- Alternate forms should update the same NPC's `name/persona/appearance/avatar_url` and add an `avatar_variants` entry. Do not create a second always-on card for an alternate form.
- Default generated preset media lives in `app/preset_asset_manifest.json` and is produced by `scripts/pregen_preset_assets.py`. Do not hardcode generated room-local media paths into `world_presets.py`.
- Portrait revisions must be treated as candidates first: use `scripts/pregen_preset_assets.py --candidate-only` and get user approval before changing `app/preset_asset_manifest.json`. Do not overwrite liked default art such as the feminine 魔王/哥布林法师 style with global "mature/horror/monster" prompt changes.
- Confirmed KSim default portraits: `借贷商人` uses the otome-antagonist merchant portrait `9b75232...`, `教官` uses the visual-novel male-lead portrait `dea6c9e...`, and `武道家` uses the feminine martial-artist portrait `4ceca62...`.
- Male portrait generation should be attractive visual-novel/otome style, not horror, brute, or childlike. Keep this as a gentle male-only branch; do not apply it to female cards whose persona merely mentions men or the instructor.
- Voice reference lines for design/cloning should be short character lines, roughly 45-90 Chinese characters. Do not pad ElevenLabs previews to long samples or reintroduce mechanical filler like "保持角色本人".
- Character selection must preserve `voice_ref_url`, `voice_ref_text`, `avatar_url`, and `avatar_variants` when copying protagonist, world-role, generated, or account-library cards into the player card.

Minimum verification before handoff:

```bash
cd backend && uv run pytest -q
cd backend && uv run ruff check .
cd backend && uv run python scripts/verify_preset_assets.py --world ksim
cd frontend && npm run build
```

## Dev Commands

### Backend (Python 3.13+, uv)

```bash
cd backend
uv sync                          # install deps
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000   # run dev server
uv run pytest -q                 # run all tests (no live AI calls)
uv run pytest tests/test_sp1.py -q               # single test file
uv run pytest -k "test_name" -q                  # single test method
uv run ruff check .              # lint
uv run ruff format . --check     # format check
```

### Frontend (React + Vite + TypeScript)

```bash
cd frontend
npm install                      # install deps
npm run dev                      # dev server (port 5173, proxies /api and /ws to :8000)
npm run build                    # tsc -b && vite build
npm run typecheck                # tsc -b --noEmit
```

### E2E Scripts

```bash
cd backend && uv run python scripts/e2e_sp1.py         # full stack e2e
cd backend && uv run python scripts/e2e_director.py     # director/beat e2e
cd backend && uv run python scripts/e2e_stats.py        # stat system e2e
cd backend && uv run python scripts/e2e_image.py        # image gen e2e
cd backend && uv run python scripts/e2e_memory.py       # memory/RAG e2e
```

## High-Level Architecture

```
┌─ Browser ──────────────────────────────┐
│  React SPA (vite)                       │
│  /auth → /rooms → /rooms/:id           │
│  useRoomSocket ←→ WebSocket (room)      │
└──────────────┬──────────────────────────┘
               │ HTTP REST + WebSocket
┌──────────────▼──── Backend ─────────────┐
│  FastAPI + async SQLAlchemy + aiosqlite  │
│  ┌─ REST Layer ──────────────────────┐  │
│  │  rooms.py (auth, CRUD, cards,     │  │
│  │    NPC, TTS, portraits)           │  │
│  └───────────────────────────────────┘  │
│  ┌─ WS Layer ───────────────────────┐  │
│  │  ws.py (coordinator, say/advance, │  │
│  │    streaming AI, stats/tasks)     │  │
│  └───────────────────────────────────┘  │
│  ┌─ Brain ───────────────────────────┐  │
│  │  brain.py (DeepSeek/Qwen adapter)   │  │
│  │  prompts.py (system prompts)      │  │
│  │  director.py (world beat judge)   │  │
│  │  npc_decision.py (NPC impulse)    │  │
│  └───────────────────────────────────┘  │
│  ┌─ Game Systems ─────────────────────┐ │
│  │  stats.py (attribute/delta/judge) │  │
│  │  timeflow.py (narrative clock)    │  │
│  │  tasks.py (quest system)          │  │
│  │  scene_logs.py (scene event log)  │  │
│  │  scene_movement.py (NPC travel)   │  │
│  └───────────────────────────────────┘  │
│  ┌─ Media ───────────────────────────┐  │
│  │  imagegen/ (ComfyUI SD pipeline)  │  │
│  │  voice.py (ElevenLabs/Fish Audio) │  │
│  └───────────────────────────────────┘  │
│  ┌─ Memory ──────────────────────────┐  │
│  │  memory.py (mem0ai integration)   │  │
│  │  lore.py (chromadb RAG)           │  │
│  └───────────────────────────────────┘  │
└──────────────────────────────────────────┘
```

### Backend Module Map

| Module | Role |
|--------|------|
| `app/main.py` | FastAPI entrypoint, lifespan, static file serving, SPA fallback |
| `app/db.py` | Async SQLAlchemy engine, session factory, additive migrations |
| `app/models.py` | ORM: User, Room, RoomMember, Message, NpcCard |
| `app/schemas.py` | Pydantic v2 request/response schemas |
| `app/config.py` | pydantic-settings from `.env` (DeepSeek, JWT, DB, ElevenLabs, Fish Audio) |
| `app/security.py` | Password hashing (argon2), JWT create/verify |
| `app/crud.py` | Shared data-access helpers (room_to_out, members, messages) |
| `app/rooms.py` | REST router: auth, rooms CRUD, character cards, NPC CRUD, TTS, portraits |
| `app/ws.py` | WebSocket router: per-room async coordinator, AI streaming, stats, scene moves |
| `app/brain.py` | `BrainProvider` — OpenAI-compatible streaming adapter (DeepSeek primary, Qwen fallback) |
| `app/prompts.py` | System prompt builders, history_to_messages conversion |
| `app/director.py` | `judge_world_beat` — world event referee (narratives, time jumps, scene changes) |
| `app/npc_decision.py` | `judge_npc_impulse` — per-NPC impulse to speak/react |
| `app/npc_gen.py` | AI NPC card generation for rooms |
| `app/char_gen.py` | Player-character draft generation (with portraits) |
| `app/stats.py` | RPG stat system (default stats, stat delta, judge, endings, month-end settle) |
| `app/timeflow.py` | Narrative clock (week/day/time_slot), time advancement, phases |
| `app/tasks.py` | Quest/task system (current task, offers, completion tracking) |
| `app/speaker_guard.py` | Sanitizes speaker labels in AI output |
| `app/enrich.py` | NPC card enrichment (AI-generated details) |
| `app/voice.py` | TTS provider abstraction (ElevenLabs + Fish Audio) |
| `app/lore.py` | ChromaDB-based lore RAG for world cards |
| `app/memory.py` | mem0ai-based character memory |
| `app/world_presets.py` | World card NPC presets, scene options, initial tasks ("ksim") |
| `app/scene_logs.py` | Scene event logs (append, load, metadata management) |
| `app/scene_movement.py` | NPC scene inference and movement from AI output |
| `app/json_utils.py` | JSON parsing helpers (extract from markdown code fences) |
| `app/imagegen/` | ComfyUI SD pipeline (character registry, guard, workflow builder, portrait, anima) |
| `app/media/` | Generated media storage (audio/, generated/) |

### Frontend Structure

| File | Role |
|------|------|
| `src/App.tsx` | React Router setup, RequireAuth wrapper |
| `src/lib/api.ts` | REST API client (fetch-based, JWT Bearer, 401 handling) |
| `src/lib/auth.tsx` | Auth context provider (token in sessionStorage) |
| `src/lib/types.ts` | TypeScript types matching backend schemas + WebSocket protocol |
| `src/lib/useRoomSocket.ts` | Room WebSocket hook (connect, reconnect, stream accumulation) |
| `src/lib/features.ts` | Feature flags (MEDIA_GENERATION_ENABLED, VOICE_GENERATION_ENABLED) |
| `src/pages/AuthPage.tsx` | Login/register page |
| `src/pages/RoomsPage.tsx` | Room lobby (list, create, join) |
| `src/pages/RoomPage.tsx` | Main game room (chat + all overlays) |
| `src/components/` | CardEditor, CardPanel, CharacterSelect, Composer, MessageBubble, RoomOverlays, StatsPanel |

### Frontend → Backend Communication

**REST API** (`/api/*`, JWT Bearer):
- Auth: register, login, me
- Rooms: list, create, join, delete
- Messages: fetch after_seq (polling fallback)
- Cards: get cards, update player card, create/edit NPC, generate NPCs
- Media: generate avatar, generate voice, TTS synthesis
- Scene log: fetch per-scene event logs

**WebSocket** (`/ws/rooms/{id}?token=<jwt>`):
- Client→Server: `say`, `polish_say`, `advance`, `timeskip`, `goto_scene`, `describe_scene`, `god_whisper`, `pay_npc`, `image`, `typing`
- Server→Client: `history`, `message`, `ai_delta`, `ai_done`, `presence`, `typing`, `stats`, `task_offer`, `task_state`, `week`, `time`, `scene`, `scene_logs_changed`, `say_draft`, `god_reply`, `image_pending`, `cards_changed`, `ai_status`, `error`

## Key Architecture Decisions

- **DeepSeek v4 Flash** is the primary AI provider (thinking model; `reasoning_content` is dropped). Swap to local Qwen via one-line config.
- **Image generation** uses a local ComfyUI instance with SD XL + character LoRAs. Pipeline: registry → guard (poison prompt check) → workflow builder → Comfy submission → wait.
- **Voice** supports ElevenLabs (Voice Design API) and Fish Audio S2-Pro. Auto-detected by `voice_id` prefix (`eleven:` / `fish:`).
- **Database** is SQLite via aiosqlite+SQLAlchemy, designed for easy Postgres swap (no SQLite-only types). Additive migrations in `db.py` for dev.
- **Stats system** uses a Chinese-named RPG sheet (等级/经验/金钱/状态/好感度) with AI-judged stat deltas on each beat.

## Testing

- Tests live in `backend/tests/`. Fixtures in `conftest.py` override `DB_URL` to a temp SQLite file and set `JWT_SECRET`.
- No live AI calls in tests (brain is mocked via env flag). E2E scripts under `scripts/` do live calls.
- Run `uv run pytest tests/test_sp1.py -q -k "test_name"` for targeted single tests.
- Some system tests (stats, timeflow, tasks, NPC decision) are deterministic with no AI dependency.
