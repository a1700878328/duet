"""Character-portrait (立绘/avatar) generation for duet (Phase E).

Wraps the Anima path with portrait framing so a character card's natural-language
appearance becomes a consistent cute upper-body avatar. Portrait orientation only
(832x1216, ``landscape=False``).
"""

from __future__ import annotations

import re
from typing import Any

from .anima import generate_anima

# Tag-soup style portrait framing. Subject tags are inferred per card so male and
# monster presets do not inherit the female protagonist framing. @ntrmixstyle +
# quality tags are prepended by _with_anima_style_prefix() inside generate_anima().
PORTRAIT_FRAMING_BASE = (
    "anime character portrait, premium character card art, expressive face, "
    "charming eyes, clean line art, polished cel shading, vibrant anime coloring, "
    "detailed outfit, detailed accessories, detailed hair, detailed eyes"
)
PORTRAIT_FRAMING_VARIANTS = (
    (
        "upper body, three-quarter view, eyes toward viewer, closed mouth, "
        "clean anime character sheet, simple background, soft rim light, "
        "clear silhouette"
    ),
    (
        "upper body, three-quarter view, looking to the side, half-closed eyes, "
        "faint smile, parted lips, game character portrait, polished illustration, "
        "sharp face detail"
    ),
    (
        "close-up, profile, looking to the side, calm expression, closed mouth, "
        "slice of life anime still, natural lighting, soft background"
    ),
    (
        "cowboy shot, over shoulder, looking back, dynamic pose, "
        "mischievous smile, small open mouth, anime key visual, "
        "cinematic composition, dramatic lighting"
    ),
)
PORTRAIT_NEGATIVE = (
    "open mouth, wide open mouth, shouting, yelling, "
    "plain white background, sticker, flat icon, chibi, super deformed, "
    "cropped head, cropped face, out of frame, bad face, asymmetrical eyes, "
    "photorealistic, realistic, 3d render, cgi, semi-realistic, plastic skin, "
    "stern face, emotionless face, angry glare, intimidating expression, "
    "front view, symmetrical composition, passport photo, id photo, straight-on, "
    "lowres, worst quality, ugly, distorted face, bad hands"
)
MALE_VISUAL_NOVEL_STYLE = (
    "handsome visual novel male lead, otome game male character, attractive "
    "adult anime man, refined face, clean charming expression"
)
MALE_VISUAL_NOVEL_NEGATIVE = (
    "shota, child, childlike, young child, baby face, scary face, horror, "
    "grotesque, ugly brute, overly rugged, old man"
)
MALE_MONSTER_VISUAL_STYLE = (
    "attractive adult anime monster man, visual novel fantasy villain, stylish "
    "non-human features, expressive charming face, cool character design"
)
MALE_MONSTER_NEGATIVE = (
    "mascot, cute child, chibi goblin, ugly monster, horror monster, "
    "deformed tusks, distorted jaw, grotesque brute"
)
EXPRESSION_TAGS = "expression matching personality, varied gaze, natural mouth shape"

_MONSTER_MARKERS = (
    "goblin",
    "orc",
    "slime",
    "tentacle",
    "demon lord",
    "monster",
    "creature",
    "哥布林",
    "兽人",
    "史莱姆",
    "触手",
    "魔王",
)
_MALE_MARKERS = (
    "1boy",
    "male",
    "man",
    "boy",
    "男性",
    "男人",
    "男",
    "教官",
    "商人",
)
_FEMALE_MARKERS = (
    "1girl",
    "female",
    "woman",
    "girl",
    "女性",
    "女人",
    "女",
    "少女",
    "老板娘",
    "会长",
)


def _has_marker(text: str, markers: tuple[str, ...]) -> bool:
    for marker in markers:
        if marker.isascii() and marker.isalpha():
            if re.search(rf"(?<![a-z]){re.escape(marker)}(?![a-z])", text):
                return True
        elif marker in text:
            return True
    return False


def _subject_tags(name: str, appearance: str, persona: str) -> str:
    primary = f"{name} {appearance}".lower()
    all_text = f"{primary} {persona}".lower()
    primary_is_monster = _has_marker(primary, _MONSTER_MARKERS)
    primary_is_male = _has_marker(primary, _MALE_MARKERS)
    primary_is_female = _has_marker(primary, _FEMALE_MARKERS)
    all_is_monster = _has_marker(all_text, _MONSTER_MARKERS)
    all_is_male = _has_marker(all_text, _MALE_MARKERS)
    all_is_female = _has_marker(all_text, _FEMALE_MARKERS)

    if primary_is_monster and primary_is_male and not primary_is_female:
        return "1boy, solo, adult monster man portrait"
    if _has_marker(primary, _MALE_MARKERS):
        return "1boy, solo"
    if _has_marker(primary, _FEMALE_MARKERS):
        return "1girl, solo"
    if primary_is_monster:
        return "solo, monster portrait"
    if all_is_monster and all_is_male and not all_is_female:
        return "1boy, solo, adult monster man portrait"
    if all_is_male:
        return "1boy, solo"
    if all_is_female:
        return "1girl, solo"
    if all_is_monster:
        return "solo, monster portrait"
    return "1girl, solo"


def _male_role_style(name: str, appearance: str, persona: str) -> str:
    text = f"{name} {appearance} {persona}".lower()
    if not _has_marker(text, _MALE_MARKERS):
        return ""
    if _has_marker(text, ("goblin", "orc", "哥布林", "兽人")):
        role_tags = [MALE_MONSTER_VISUAL_STYLE]
        if _has_marker(text, ("goblin", "哥布林")):
            role_tags.append(
                "adult goblin rogue, wiry build, sharp sly grin, leather armor"
            )
        if _has_marker(text, ("orc", "兽人")):
            role_tags.append(
                "handsome orc warrior, strong athletic build, clean tusks, rugged charm"
            )
        return ", ".join(role_tags)
    role_tags = [MALE_VISUAL_NOVEL_STYLE]
    if _has_marker(text, ("教官", "instructor", "trainer", "mentor")):
        role_tags.append(
            "handsome mentor, confident smile, fitted training armor, broad shoulders"
        )
    if _has_marker(text, ("商人", "merchant", "moneylender", "借贷")):
        role_tags.append(
            "elegant otome antagonist, sly charming smile, ornate merchant outfit"
        )
    return ", ".join(role_tags)


def _portrait_variant(prompt_variant: int | None) -> str:
    idx = 0 if prompt_variant is None else int(prompt_variant)
    return PORTRAIT_FRAMING_VARIANTS[idx % len(PORTRAIT_FRAMING_VARIANTS)]


_EXPRESSION_VARIANTS = [
    ("half-closed eyes", "faint smile", "parted lips", "blush"),       # 柔和微笑
    ("sharp eyes", "smug smile", "closed mouth", "blush"),            # 强势自信
    ("sleepy eyes", "expressionless", "closed mouth", ""),            # 冷淡无表情
    ("wide-eyed", "bright smile", "small open mouth", "blush"),       # 元气开朗
    ("half-closed eyes", "gentle smile", "parted lips", ""),          # 温柔
    ("sharp eyes", "serious", "closed mouth", ""),                    # 认真严肃
]


def _inject_ntrmix_face(appearance: str, variant_idx: int = 0) -> str:
    """Inject face anchor tags with rotating expression defaults."""
    lower = appearance.lower()
    needed: list[str] = []
    if "colored eyelashes" not in lower:
        needed.append("colored eyelashes")
    eye_style, expr, mouth, blush = _EXPRESSION_VARIANTS[
        variant_idx % len(_EXPRESSION_VARIANTS)
    ]
    if not any(
        x in lower
        for x in ("jitome", "half-closed", "sharp eyes", "sleepy eyes", "wide-eyed")
    ):
        needed.append(eye_style)
    if not any(
        x in lower for x in ("smile", "expressionless", "angry", "crying", "serious")
    ):
        needed.append(expr)
    if blush and "blush" not in lower:
        needed.append("blush")
    if not any(
        x in lower
        for x in ("open mouth", "closed mouth", "parted lips", "small open mouth")
    ):
        needed.append(mouth)
    return f"{appearance}, {', '.join(needed)}" if needed else appearance


def build_portrait_prompt(
    appearance: str,
    *,
    name: str | None = None,
    persona: str | None = None,
    nsfw: bool = False,
    prompt_variant: int | None = None,
) -> tuple[str, str]:
    """Build a tag-soup portrait prompt for a cute anime character portrait.

    The appearance/natural-language description is appended as-is, but the framing
    rotates gaze, mouth shape, camera angle, and illustration style so regenerating
    a card does not collapse into the same front-facing open-mouth portrait.
    """
    appearance = (appearance or "").strip()
    name = (name or "").strip()
    persona = (persona or "").strip()
    variant_used = prompt_variant if prompt_variant is not None else 0
    # 注入 NTRMix 脸部锚点，表情/眼神/嘴型按 variant 轮换
    appearance = _inject_ntrmix_face(appearance, variant_used)

    subject_tags = _subject_tags(name, appearance, persona)
    tags = [subject_tags, PORTRAIT_FRAMING_BASE, _portrait_variant(variant_used)]
    male_style = (
        _male_role_style(name, appearance, persona)
        if subject_tags.startswith("1boy")
        else ""
    )
    if male_style:
        tags.append(male_style)
    if name:
        tags.append(name)
    if appearance:
        tags.append(appearance)
    if persona:
        tags.append(persona)

    positive = ", ".join(tags)
    if nsfw:
        positive = f"nsfw, explicit, {positive}"
    negative = PORTRAIT_NEGATIVE
    if male_style:
        negative = f"{negative}, {MALE_VISUAL_NOVEL_NEGATIVE}"
        if "monster man" in male_style:
            negative = f"{negative}, {MALE_MONSTER_NEGATIVE}"
    return positive, negative


async def generate_portrait(
    appearance: str,
    *,
    name: str | None = None,
    persona: str | None = None,
    nsfw: bool = False,
    seed: int | None = None,
    prompt_variant: int | None = None,
) -> dict[str, Any]:
    """Generate one cute upper-body avatar (立绘) from a free-text appearance.

    Uses the Anima DiT path with ntrmix LoRA. Returns
    ``{url,path,filename,prompt_id}`` on success or ``{error}`` on failure.
    """
    positive, negative = build_portrait_prompt(
        appearance,
        name=name,
        persona=persona,
        nsfw=nsfw,
        prompt_variant=prompt_variant if prompt_variant is not None else seed,
    )
    return await generate_anima(
        positive,
        negative,
        seed=seed,
        upscale=False,
        tile_refine=False,
        ipadapter_weight=0.48,
    )
