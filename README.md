# Duet

Duet is a two-player collaborative AI roleplay prototype. It combines realtime chat, character cards, persistent rooms, world-state tracking, NPC agency, voice playback, and optional scene image generation into one playable vertical slice.

The current frontend supports Chinese and Japanese UI language switching from the login screen, room lobby, and in-room header. The Japanese option is intended for live studio demos.

## Highlights

- Two-player rooms with JWT auth, lobby updates, and room WebSocket sync.
- Character onboarding with saved account cards, world characters, protagonist cards, and AI-generated drafts.
- NPC and narrator turns with streaming responses and per-room sequencing.
- World-state panels for current scene, NPC distribution, recent events, risks, stats, inventory, and favorability.
- Optional voice and image generation hooks for richer demos.
- Lightweight Japanese UI option for the core demo flow.

## Tech Stack

- Frontend: React 18, Vite, TypeScript.
- Backend: FastAPI, async SQLAlchemy, SQLite, Pydantic v2.
- Realtime: WebSocket endpoints for rooms and lobby updates.
- AI provider: OpenAI-compatible chat completions, configured through backend environment variables.

## Quick Start

### Backend

```bash
cd backend
uv sync
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The backend health check is available at:

```text
http://127.0.0.1:8000/api/health
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open:

```text
http://127.0.0.1:5173
```

The Vite dev server proxies `/api`, `/ws`, and `/media` to `http://127.0.0.1:8000` by default. To point at another backend:

```bash
$env:DUET_BACKEND_TARGET="http://127.0.0.1:8000"
npm run dev
```

## Japanese Demo

1. Open the frontend.
2. Use the language dropdown in the top-right of the login card.
3. Select `日本語`.
4. Continue through login, room creation, room entry, chat, scene image generation, movement, and room status panels.

The setting is saved in browser local storage, so refreshes keep the selected language.

## Tests

Backend:

```bash
cd backend
uv run pytest -q
uv run ruff check .
```

Frontend:

```bash
cd frontend
npm run typecheck
npm run build
```

## Environment

Create `backend/.env` for provider settings when live AI calls are needed:

```env
DEEPSEEK_API_KEY=...
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-v4-flash
JWT_SECRET=change-me
```

Useful optional backend settings include `DB_URL`, `HISTORY_WINDOW`, and `ALLOW_LIVE_BRAIN`.

## GitHub Upload Checklist

```bash
git status
git add README.md frontend/src
git commit -m "Add Japanese demo language option"
git remote add origin <your-repo-url>
git push -u origin main
```

If the remote already exists, skip `git remote add origin`.

## Notes

Generated media, local databases, credentials, and cache directories should stay out of Git. Review `.gitignore` before pushing if you add new local output folders.
