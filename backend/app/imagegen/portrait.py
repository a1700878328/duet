"""Character-portrait (立绘/avatar) generation for duet (Phase E).

Wraps the Anima path with portrait framing so a character card's natural-language
appearance becomes a consistent cute upper-body avatar. Portrait orientation only
(832x1216, ``landscape=False``).
"""

from __future__ import annotations

from typing import Any

from .anima import generate_anima

# Tag-soup style portrait framing — matches the style of the ntrmix witch prompt
# that produces cute results. @ntrmixstyle + quality tags are prepended by
# _with_anima_style_prefix() inside generate_anima().
PORTRAIT_FRAMING = (
    "1girl, solo, anime upper body portrait, "
    "looking at viewer, centered, "
    "clean line art, polished cel shading, "
    "flat anime coloring, detailed outfit, soft rim light, "
    "detailed hair, detailed eyes, cinematic lighting, aesthetic"
)
PORTRAIT_NEGATIVE = (
    "plain white background, sticker, flat icon, chibi, super deformed, "
    "cropped head, cropped face, out of frame, bad face, asymmetrical eyes, "
    "photorealistic, realistic, 3d render, cgi, semi-realistic, plastic skin, "
    "stern face, emotionless face, angry glare, intimidating expression, "
    "lowres, worst quality, ugly, distorted face, bad hands"
)
EXPRESSION_TAGS = "expression matching personality, looking at viewer"


def build_portrait_prompt(
    appearance: str,
    *,
    name: str | None = None,
    persona: str | None = None,
    nsfw: bool = False,
) -> tuple[str, str]:
    """Build a tag-soup portrait prompt for a cute anime character portrait.

    The appearance/natural-language description is appended as-is, but the framing
    uses tag-soup style (matching the ntrmix LoRA's training data) for maximal
    cuteness and style adherence.
    """
    appearance = (appearance or "").strip()
    name = (name or "").strip()
    persona = (persona or "").strip()

    tags = [PORTRAIT_FRAMING, EXPRESSION_TAGS]
    if name:
        tags.append(name)
    if appearance:
        tags.append(appearance)
    if persona:
        tags.append(persona)

    positive = ", ".join(tags)
    if nsfw:
        positive = f"nsfw, explicit, {positive}"
    return positive, PORTRAIT_NEGATIVE


async def generate_portrait(
    appearance: str,
    *,
    name: str | None = None,
    persona: str | None = None,
    nsfw: bool = False,
    seed: int | None = None,
) -> dict[str, Any]:
    """Generate one cute upper-body avatar (立绘) from a free-text appearance.

    Uses the Anima DiT path with ntrmix LoRA. Returns
    ``{url,path,filename,prompt_id}`` on success or ``{error}`` on failure.
    """
    positive, negative = build_portrait_prompt(
        appearance, name=name, persona=persona, nsfw=nsfw
    )
    return await generate_anima(
        positive,
        negative,
        seed=seed,
        upscale=False,
        tile_refine=False,
        ipadapter_weight=0.48,
    )
