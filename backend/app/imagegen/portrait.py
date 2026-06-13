"""Character-portrait (立绘/avatar) generation for duet (Phase E).

Wraps ``generate_raw_single`` with portrait framing so a character card's
natural-language appearance becomes a consistent upper-body avatar. Portrait
orientation only (832x1216, ``landscape=False``). The poisoned-color guard is
inherited from ``generate_raw_single``.
"""

from __future__ import annotations

from typing import Any

from .service import generate_raw_single

PORTRAIT_FRAMING = (
    "solo, upper body, portrait, looking at viewer, "
    "face focus, simple background, high detail"
)
NEUTRAL_APPEARANCE = "1person, portrait, simple background"


async def generate_portrait(
    appearance: str,
    *,
    nsfw: bool = False,
    seed: int | None = None,
) -> dict[str, Any]:
    """Generate one upper-body avatar from a free-text appearance.

    Returns the ``generate_raw_single`` dict: ``{url,path,filename,prompt_id}``
    on success or ``{error}`` on failure.
    """
    appearance = (appearance or "").strip()
    if not appearance:
        positive = NEUTRAL_APPEARANCE
    else:
        positive = f"{appearance}, {PORTRAIT_FRAMING}"
    return await generate_raw_single(
        positive, nsfw=nsfw, landscape=False, seed=seed
    )
