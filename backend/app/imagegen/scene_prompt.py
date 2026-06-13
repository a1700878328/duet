"""Scene -> SDXL/Danbooru prompt synthesizer (DeepSeek brain).

Converts a recent Chinese RP scene into ENGLISH Danbooru tags. Returns STRICT
JSON: single -> {"positive","negative"}; duo -> {"global","left","right","negative"}.
Import-safe: no module-level API/GPU; the provider is built lazily inside the call.
"""

from __future__ import annotations

import json
import re
from typing import Any

_QUALITY_TAGS = "masterpiece, best quality, highly detailed, sharp focus"
_NSFW_TAGS = "nsfw, explicit, uncensored, detailed skin"
_SFW_TAGS = "sfw, safe, tasteful"
_BASE_NEGATIVE = (
    "worst quality, low quality, bad anatomy, bad hands, extra fingers, "
    "missing fingers, watermark, text, signature, jpeg artifacts, blurry"
)

_SINGLE_SYS = """You are an SDXL prompt engineer for an anime illustration model.
Convert the user's Chinese roleplay scene + character appearance notes into a
single English Danbooru-tag prompt. Rules:
- Output ONLY tags, comma-separated, lowercase, no sentences.
- Start with subject count (1girl / 1boy / etc.), then character appearance,
  then pose/expression/clothing, then setting/lighting/composition.
- Weave EACH given appearance note (hair color, eye color, outfit) verbatim into
  the tags for character consistency. Do NOT invent or change hair/eye colors.
- {rating_rule}
- Quality tags are added by the system; do not repeat them.
Respond with STRICT JSON only: {{"positive": "...", "negative": "..."}}
The "negative" field is for extra scene-specific negatives (may be empty)."""

_DUO_SYS = """You are an SDXL prompt engineer for an anime illustration model using
regional prompting (left/right split). Convert the Chinese roleplay scene + the two
characters' appearance notes into THREE English Danbooru-tag prompts. Rules:
- Output ONLY tags, comma-separated, lowercase, no sentences.
- "global": shared scene — count (2girls / couple / etc.), setting, lighting,
  composition, interaction. No per-character hair/eye colors here.
- "left": FIRST character only — their appearance note + pose/expression/clothing.
- "right": SECOND character only — their appearance note + pose/expression/clothing.
- Weave EACH appearance note verbatim into its region (first->left, second->right).
  Do NOT invent or change hair/eye colors.
- {rating_rule}
- Quality tags are added by the system; do not repeat them.
Respond with STRICT JSON only:
{{"global": "...", "left": "...", "right": "...", "negative": "..."}}
The "negative" field is for extra scene-specific negatives (may be empty)."""


def _rating_rule(nsfw: bool) -> str:
    if nsfw:
        return "This is an explicit NSFW scene; include appropriate explicit tags."
    return "Keep it strictly SFW; no nudity or explicit tags."


def _extract_json(raw: str) -> dict[str, Any]:
    """Strip ``` fences, fall back to the first {...} block, parse JSON."""
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return {}


def _clean(tag_str: str) -> str:
    return ", ".join(t.strip() for t in str(tag_str).split(",") if t.strip())


def _user_msg(scene_text: str, appearances: list[str], *, two_person: bool) -> str:
    if two_person:
        notes = (
            "\n".join(f"- character {i + 1}: {a}" for i, a in enumerate(appearances))
            or "- (no appearance notes provided)"
        )
        label = "Two-character appearance notes (order = left, right):"
    else:
        notes = "\n".join(f"- {a}" for a in appearances) or "- (no appearance notes)"
        label = "Character appearance notes:"
    return f"Scene (Chinese):\n{scene_text}\n\n{label}\n{notes}"


async def build_scene_prompt(
    scene_text: str,
    appearances: list[str],
    *,
    nsfw: bool,
    two_person: bool,
    brain: Any = None,
) -> dict[str, str]:
    """Synthesize an SDXL prompt from an RP scene via the brain (DeepSeek).

    Returns single -> {"positive","negative"} or duo ->
    {"global","left","right","negative"}. Quality + rating tags are baked in.
    """
    if brain is None:
        from app.brain import default_provider

        brain = default_provider()

    sys_tmpl = _DUO_SYS if two_person else _SINGLE_SYS
    system = sys_tmpl.format(rating_rule=_rating_rule(nsfw))
    user = _user_msg(scene_text, appearances, two_person=two_person)

    # Deterministic-ish: low temperature for stable tagging.
    try:
        brain.temperature = 0.2
    except Exception:
        pass

    raw = await brain.complete(
        [{"role": "system", "content": system}, {"role": "user", "content": user}]
    )
    data = _extract_json(raw)

    rating = _NSFW_TAGS if nsfw else _SFW_TAGS
    quality = f"{_QUALITY_TAGS}, {rating}"
    extra_neg = _clean(data.get("negative", ""))
    negative = f"{_BASE_NEGATIVE}, {extra_neg}" if extra_neg else _BASE_NEGATIVE

    if two_person:
        g = _clean(data.get("global", ""))
        return {
            "global": f"{quality}, {g}" if g else quality,
            "left": _clean(data.get("left", "")),
            "right": _clean(data.get("right", "")),
            "negative": negative,
        }

    pos = _clean(data.get("positive", ""))
    return {
        "positive": f"{quality}, {pos}" if pos else quality,
        "negative": negative,
    }
