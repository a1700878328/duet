"""Scene -> Anima/NTRMix prompt builder.

This intentionally follows the local Anima/NTRMix consistency tutorial instead
of asking an LLM to freely rewrite the scene. The active ComfyUI API prompt
already supplies the quality prefix, so this module returns only the runtime
character/scene tags for node 54 plus extra negatives.
"""

from __future__ import annotations

import re
from typing import Any

_NSFW_PREFIX = "nsfw, explicit, adult"
_SFW_PREFIX = "sfw"
_FACE_ANCHOR = "colored eyelashes, jitome, smile, blush, open mouth, sweat"
_CAMERA_ANCHOR = "cowboy shot, from side, looking at viewer"
_BASE_NEGATIVE = (
    "worst quality, low quality, score_1, score_2, score_3, artist name, "
    "blurry, jpeg artifacts, lowres, censor, bad anatomy, bad hands, extra fingers, "
    "extra limbs, watermark, signature, deformed face, asymmetrical eyes"
)
_DUO_NEGATIVE_EXTRA = (
    ", duplicate character, unwanted crowd, extra person, third person, "
    "merged faces, fused bodies, same face, identical twins, "
    "wrong hair color, wrong eye color"
)
_MULTI_NEGATIVE_EXTRA = (
    ", duplicate character, unwanted crowd, merged faces, fused bodies, "
    "same face, identical twins, wrong hair color, wrong eye color"
)
_BOY_RE = re.compile(r"\b(1boy|boy|male|man|young man|少年|男人|男性|男)\b", re.I)
_GIRL_RE = re.compile(
    r"\b(1girl|girl|female|woman|young woman|少女|女人|女性|女)\b", re.I
)


def _clean(text: Any, limit: int = 360) -> str:
    out = re.sub(r"\s+", " ", str(text or "")).strip().strip('"')
    return out[:limit].strip(" ,")


def _split_character(note: str) -> tuple[str, str]:
    text = _clean(note)
    if ":" in text:
        name, desc = text.split(":", 1)
        return _clean(name, 80), _clean(desc)
    if "：" in text:
        name, desc = text.split("：", 1)
        return _clean(name, 80), _clean(desc)
    return "", text


def _gender_tag(text: str) -> str:
    if _BOY_RE.search(text):
        return "1boy"
    if _GIRL_RE.search(text):
        return "1girl"
    return "1girl"


def _face_anchor_for(desc: str) -> str:
    lower = desc.lower()
    parts: list[str] = []
    if "colored eyelashes" not in lower:
        parts.append("colored eyelashes")
    if not any(
        x in lower for x in ("jitome", "wide-eyed", "sharp eyes", "sleepy eyes")
    ):
        parts.append("jitome")
    if not any(x in lower for x in ("smile", "expressionless", "angry", "crying")):
        parts.append("smile")
    if "blush" not in lower:
        parts.append("blush")
    if not any(x in lower for x in ("open mouth", "closed mouth", "parted lips")):
        parts.append("open mouth")
    if "sweat" not in lower:
        parts.append("sweat")
    return ", ".join(parts)


def _scene_anchor(scene_text: str, *, two_person: bool) -> str:
    scene = _clean(scene_text, 260)
    if not scene:
        scene = "simple roleplay scene, clear background"
    shot = "medium shot" if two_person else _CAMERA_ANCHOR
    return (
        f"{shot}, simple background, cinematic anime lighting, clean anime line art, "
        f"polished cel shading, scene context: {scene}"
    )


def _single_prompt(scene_text: str, appearances: list[str], *, nsfw: bool) -> str:
    name, desc = _split_character(appearances[0] if appearances else "")
    subject = _gender_tag(desc)
    identity = name or "original anime character"
    face = _face_anchor_for(desc)
    parts = [
        _NSFW_PREFIX if nsfw else _SFW_PREFIX,
        subject,
        "solo",
        identity,
        desc,
        face or _FACE_ANCHOR,
        _scene_anchor(scene_text, two_person=False),
    ]
    return ", ".join(p for p in parts if p)


def _duo_prompt(scene_text: str, appearances: list[str], *, nsfw: bool) -> str:
    chars = [_split_character(a) for a in appearances if _clean(a)][:4]
    if len(chars) < 2:
        return _single_prompt(scene_text, appearances, nsfw=nsfw)

    count = len(chars)
    desc_blob = " ".join(desc for _, desc in chars)
    if all(not _BOY_RE.search(desc) for _, desc in chars):
        count_tag = f"{count}girls" if count == 2 else f"{count}girls"
    elif all(not _GIRL_RE.search(desc) for _, desc in chars):
        count_tag = f"{count}boys" if count == 2 else f"{count}boys"
    else:
        count_tag = f"{count} characters"

    parts = [
        _NSFW_PREFIX if nsfw else _SFW_PREFIX,
        count_tag,
        f"exactly {count} characters",
        "duo" if count == 2 else "group",
        "no other people",
    ]
    labels = ["left character", "right character", "center character", "rear character"]
    for idx, (name, desc) in enumerate(chars):
        label = labels[idx] if idx < len(labels) else f"character {idx + 1}"
        identity = f"{label}, {name}" if name else label
        face = _face_anchor_for(desc)
        parts.append(f"{identity}, {desc}, {face or _FACE_ANCHOR}")

    parts.extend(
        [
            "different hairstyles",
            "different hair colors" if "hair" in desc_blob.lower() else "",
            "different outfits",
            "different expressions",
            "separate faces",
            "separate bodies",
            "clear character separation",
            "standing close together" if count == 2 else "all characters visible",
            _scene_anchor(scene_text, two_person=True),
        ]
    )
    return ", ".join(p for p in parts if p)


def build_scene_prompt_sync(
    scene_text: str,
    appearances: list[str],
    *,
    nsfw: bool,
    two_person: bool,
) -> dict[str, str]:
    positive = (
        _duo_prompt(scene_text, appearances, nsfw=nsfw)
        if two_person and len(appearances) >= 2
        else _single_prompt(scene_text, appearances, nsfw=nsfw)
    )
    negative = _BASE_NEGATIVE
    if two_person and len(appearances) == 2:
        negative += _DUO_NEGATIVE_EXTRA
    elif two_person and len(appearances) > 2:
        negative += _MULTI_NEGATIVE_EXTRA
    return {"positive": positive, "negative": negative}


async def build_scene_prompt(
    scene_text: str,
    appearances: list[str],
    *,
    nsfw: bool,
    two_person: bool,
    brain: Any = None,
) -> dict[str, str]:
    """Build the deterministic Anima/NTRMix prompt.

    ``brain`` is accepted for API compatibility with the previous LLM-backed
    implementation, but is intentionally unused.
    """
    return build_scene_prompt_sync(
        scene_text,
        appearances,
        nsfw=nsfw,
        two_person=two_person,
    )
