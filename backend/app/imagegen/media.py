"""Media paths and persistence helpers for generated images."""

from __future__ import annotations

import uuid
from pathlib import Path

MEDIA_DIR = Path(__file__).resolve().parents[1] / "media" / "generated"
MEDIA_URL_PREFIX = "/media/generated"


def save_png(image_bytes: bytes) -> tuple[str, Path]:
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}.png"
    path = MEDIA_DIR / name
    path.write_bytes(image_bytes)
    return name, path
