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
_FACE_ANCHOR = "colored eyelashes, half-closed eyes, faint smile, blush, parted lips"
_BASE_NEGATIVE = (
    "worst quality, low quality, score_1, score_2, score_3, artist name, "
    "blurry, jpeg artifacts, lowres, censor, bad anatomy, bad hands, extra fingers, "
    "extra limbs, watermark, signature, deformed face, asymmetrical eyes, "
    "plain white background, blank background, empty background, studio backdrop, "
    "front view, symmetrical composition, passport photo, id photo, straight-on, "
    "wide open mouth, shouting, yelling"
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


def _face_anchor_for(desc: str, action_desc: str = "") -> str:
    lower = f"{desc.lower()} {action_desc.lower()}"
    parts: list[str] = []
    if "colored eyelashes" not in lower:
        parts.append("colored eyelashes")
    if not any(
        x
        in lower
        for x in (
            "jitome",
            "wide-eyed",
            "sharp eyes",
            "sleepy eyes",
            "half-closed eyes",
        )
    ):
        parts.append("half-closed eyes")
    if not any(x in lower for x in ("smile", "laughing", "cheerful")):
        if any(
            x in lower
            for x in ("expressionless", "no smile", "serious", "angry", "crying")
        ):
            parts.append("expressionless")
        else:
            parts.append("faint smile")
    if "blush" not in lower:
        parts.append("blush")
    if not any(
        x in lower
        for x in (
            "open mouth",
            "closed mouth",
            "parted lips",
            "small open mouth",
        )
    ):
        parts.append("parted lips")
    return ", ".join(parts)


def _location_background(scene_text: str) -> str:
    if "冒险者公会" in scene_text or "公会" in scene_text:
        return (
            "adventurer guild hall interior, wooden reception counter, quest board, "
            "warm lamplight, background adventurers, fantasy guild props"
        )
    if "酒馆" in scene_text:
        return (
            "fantasy tavern interior, wooden bar counter, tables, bottles, smoky warm "
            "lamplight, lively background"
        )
    if "森林" in scene_text:
        return (
            "deep fantasy forest background, trees, moss, dappled sunlight, dirt path, "
            "environmental depth"
        )
    if "洞窟" in scene_text or "洞穴" in scene_text:
        return (
            "dark cave interior, wet stone, crystals, torchlight, shadowy depth, "
            "dungeon atmosphere"
        )
    if "借贷" in scene_text or "商店" in scene_text:
        return (
            "fantasy moneylender shop interior, counter, ledgers, coins, contract "
            "papers, dim luxurious lighting"
        )
    if "青楼" in scene_text or "娼馆" in scene_text:
        return (
            "fantasy red-light district interior, red lanterns, silk curtains, ornate "
            "wooden screens, warm moody lighting"
        )
    return "detailed fantasy environment background, cinematic depth, visible setting"


def _scene_anchor(scene_text: str, *, two_person: bool) -> str:
    scene = _clean(scene_text, 260)
    if not scene:
        scene = "roleplay scene with a visible fantasy environment"
    shot = (
        "medium two-shot, interactive composition"
        if two_person
        else "medium shot, character interacting with the environment"
    )
    background = _location_background(scene_text)
    return (
        f"{shot}, {background}, cinematic anime lighting, clean anime line art, "
        f"polished cel shading, scene context: {scene}"
    )


def _single_prompt(
    scene_text: str, appearances: list[str], *, nsfw: bool, action_desc: str = ""
) -> str:
    name, desc = _split_character(appearances[0] if appearances else "")
    subject = _gender_tag(desc)
    identity = name or "original anime character"
    face = _face_anchor_for(desc, action_desc)
    parts = [
        _NSFW_PREFIX if nsfw else _SFW_PREFIX,
        subject,
        "solo",
        identity,
        desc,
        face or _FACE_ANCHOR,
    ]
    if action_desc:
        parts.append(action_desc)
    parts.append(_scene_anchor(scene_text, two_person=False))
    return ", ".join(p for p in parts if p)


def _duo_prompt(
    scene_text: str, appearances: list[str], *, nsfw: bool, action_desc: str = ""
) -> str:
    chars = [_split_character(a) for a in appearances if _clean(a)][:4]
    if len(chars) < 2:
        return _single_prompt(
            scene_text, appearances, nsfw=nsfw, action_desc=action_desc
        )

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
        face = _face_anchor_for(desc, action_desc)
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
        ]
    )
    if action_desc:
        parts.append(action_desc)
    parts.append(
        "standing close together" if count == 2 else "all characters visible",
    )
    parts.append(_scene_anchor(scene_text, two_person=True))
    return ", ".join(p for p in parts if p)


def build_scene_prompt_sync(
    scene_text: str,
    appearances: list[str],
    *,
    nsfw: bool,
    two_person: bool,
    action_desc: str = "",
) -> dict[str, str]:
    positive = (
        _duo_prompt(scene_text, appearances, nsfw=nsfw, action_desc=action_desc)
        if two_person and len(appearances) >= 2
        else _single_prompt(scene_text, appearances, nsfw=nsfw, action_desc=action_desc)
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
    action_desc: str = "",
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
        action_desc=action_desc,
    )
