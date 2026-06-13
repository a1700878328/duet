"""FastAPI app entrypoint for Duet SP-1."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .db import init_db
from .rooms import router as rest_router
from .ws import router as ws_router

_FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Duet", version="0.1.0", lifespan=lifespan)

# Dev CORS — native shells / vite dev server hit this from other origins.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(rest_router)
app.include_router(ws_router)

# Generated media (生图/语音) — mounted before the SPA catch-all so /media wins.
_MEDIA_DIR = Path(__file__).resolve().parent / "media"
_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=_MEDIA_DIR), name="media")

# Built frontend: hashed assets via StaticFiles + SPA index fallback so client
# routes (/rooms/15 等) survive deep-link/refresh instead of 404-ing.
if _FRONTEND_DIST.is_dir():
    _ASSETS = _FRONTEND_DIST / "assets"
    if _ASSETS.is_dir():
        app.mount("/assets", StaticFiles(directory=_ASSETS), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> FileResponse:
        if full_path.startswith(("api/", "ws/", "media/")):
            raise HTTPException(status_code=404, detail="Not Found")
        candidate = _FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_FRONTEND_DIST / "index.html")
