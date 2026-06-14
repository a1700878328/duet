"""Character-portrait (立绘/avatar) generation for duet (Phase E).

Wraps ``generate_raw_single`` with portrait framing so a character card's
natural-language appearance becomes a consistent upper-body avatar. Portrait
orientation only (832x1216, ``landscape=False``). The poisoned-color guard is
inherited from ``generate_raw_single``.
"""

from __future__ import annotations

from typing import Any

from .anima import generate_anima

PORTRAIT_FRAMING = (
    "solo, upper body, portrait, looking at viewer, "
    "face focus, simple background, high detail, anime style, masterpiece"
)
NEUTRAL_APPEARANCE = "1person, portrait, simple background"


async def generate_portrait(
    appearance: str,
    *,
    nsfw: bool = False,
    seed: int | None = None,
) -> dict[str, Any]:
    """Generate one upper-body avatar (立绘) from a free-text appearance.

    Uses the Anima DiT path. Returns ``{url,path,filename,prompt_id}`` on
    success or ``{error}`` on failure.
    """
    appearance = (appearance or "").strip()
    positive = f"{appearance}, {PORTRAIT_FRAMING}" if appearance else NEUTRAL_APPEARANCE
    if nsfw:
        positive = f"nsfw, {positive}"
    return await generate_anima(positive, seed=seed)
