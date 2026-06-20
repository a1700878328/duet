"""Character-portrait (立绘/avatar) generation for duet (Phase E).

Wraps the Anima path with portrait framing so a character card's natural-language
appearance becomes a consistent cute upper-body avatar. Portrait orientation only
(832x1216, ``landscape=False``).
"""

from __future__ import annotations

import re
from typing import Any

from ..agent_sdk import agent
from ..brain import BrainProvider
from .anima import generate_anima
from .quality import annotate_quality_result

PORTRAIT_NEGATIVE = (
    "wide open mouth, shouting, yelling, "
    "plain white background, white background, blank background, empty background, "
    "overexposed background, simple background, sticker, flat icon, chibi, super deformed, "
    "cropped head, cropped face, cropped body, badly cropped legs, out of frame, "
    "black border, black frame, letterbox, cinematic black bars, "
    "large black foreground shape, foreground object blocking character, "
    "boring standing pose, stiff front view, symmetrical passport pose, "
    "bad face, asymmetrical eyes, "
    "wrong hair color, wrong eye color, unrequested animal ears, unrequested crown, "
    "unrequested tiara, unrequested horns, unrequested tail, "
    "modern gun, firearm, pistol, rifle, handgun, assault rifle, "
    "photorealistic, realistic, 3d render, cgi, semi-realistic, plastic skin, "
    "passport photo, id photo, "
    "lowres, worst quality, ugly, distorted face, bad hands"
)
AVATAR_NEGATIVE_EXTRA = (
    "full body, feet visible, tiny face, distant character, character sheet, "
    "standing pose, action scene, large weapon covering face, busy background, "
    "wide shot, environmental shot"
)
REFERENCE_NEGATIVE_EXTRA = (
    "headshot, face portrait, extreme close-up, tiny character, distant character"
)

_NL_RE = re.compile(r"[一-鿿]")
_ESCAPED_CJK_RE = re.compile(r"\\u[4-9a-fA-F][0-9a-fA-F]{3}")
_GENDER_RE = re.compile(r"\b(1girl|1boy|girl|boy|woman|man|female|male)\b", re.I)
_COMPOSITION_RE = re.compile(
    r"\b(full body|cowboy shot|knees-up|thigh-up|headshot|portrait|bust portrait|"
    r"head-and-shoulders|close-up|closeup|dynamic pose|walking|sitting|"
    r"seated|from side|looking back|low angle|high angle|dutch angle|three-quarter view|"
    r"over shoulder|profile)\b",
    re.I,
)


def _is_natural_language(text: str) -> bool:
    """Contains Chinese → likely natural language, not Danbooru tags."""
    return bool(_NL_RE.search(text) or _ESCAPED_CJK_RE.search(text))


_CN_TAG_MAP = (
    ("修女服", "nun habit"),
    ("修女", "nun"),
    ("白色头巾", "white headdress"),
    ("头巾", "headdress"),
    ("眼罩遮住双眼", "blindfold covering eyes"),
    ("眼罩", "black blindfold"),
    ("十字架", "cross necklace"),
    ("白金", "platinum blonde hair"),
    ("银灰色", "silver-gray"),
    ("银白色", "silver hair"),
    ("银发", "silver hair"),
    ("白发", "white hair"),
    ("黑色短发", "black short hair"),
    ("黑短发", "black short hair"),
    ("黑发", "black hair"),
    ("黑色", "black"),
    ("短发", "short hair"),
    ("长发", "long hair"),
    ("高马尾", "high ponytail"),
    ("马尾", "ponytail"),
    ("金色", "golden"),
    ("金眼", "golden eyes"),
    ("碧蓝色眼眸", "blue eyes"),
    ("碧蓝", "blue eyes"),
    ("紫色眼", "purple eyes"),
    ("紫瞳", "purple eyes"),
    ("蓝眼", "blue eyes"),
    ("红眼", "red eyes"),
    ("红色眼睛", "red eyes"),
    ("赤红", "red eyes"),
    ("翠绿色眼眸", "green eyes"),
    ("绿色眼眸", "green eyes"),
    ("绿眼", "green eyes"),
    ("白皙", "pale skin"),
    ("冷白", "pale skin"),
    ("小麦色肌肤", "tan skin"),
    ("小麦色皮肤", "tan skin"),
    ("小麦色", "tan skin"),
    ("温柔", "gentle expression"),
    ("克制", "reserved expression"),
    ("盲眼", "blindfolded"),
    ("贵族", "noble outfit"),
    ("礼服", "formal dress"),
    ("战斗礼服", "battle dress"),
    ("骑士", "knight"),
    ("女骑士", "female knight"),
    ("钢制骑士板甲", "steel plate armor"),
    ("骑士板甲", "knight plate armor"),
    ("板甲", "plate armor"),
    ("锁子甲", "chainmail"),
    ("蓝白配色", "blue and white outfit"),
    ("蓝色披风", "blue cape"),
    ("披风", "cape"),
    ("双手长剑", "two-handed sword"),
    ("长剑", "longsword"),
    ("狮鹫徽章", "griffin emblem"),
    ("徽章", "emblem"),
    ("盗贼", "rogue"),
    ("刺客", "assassin"),
    ("皮质紧身衣", "leather bodysuit"),
    ("皮甲", "leather armor"),
    ("护甲", "armor"),
    ("暗色披风", "dark cloak"),
    ("深棕色", "dark brown"),
    ("匕首", "daggers"),
    ("开锁工具", "lockpicks"),
    ("精灵族银币", "elven silver coin pendant"),
    ("银币", "silver coin pendant"),
    ("纤细", "slender body"),
    ("矫健", "agile body"),
    ("警觉", "alert expression"),
    ("危险", "dangerous aura"),
    ("黑红", "black and red outfit"),
    ("暗红", "dark red"),
    ("红宝石", "ruby jewelry"),
    ("吊坠", "pendant"),
    ("耳坠", "earrings"),
    ("剑", "sword"),
    ("武器", "weapon"),
)


def _cn_anchor_tags(text: str) -> str:
    tags: list[str] = []
    if ("挑染" in text or "一缕" in text) and any(x in text for x in ("银白", "白色", "银色")):
        tags.append("silver hair streak")
    for cn, tag in _CN_TAG_MAP:
        if cn in text and tag not in tags:
            tags.append(tag)
    if "麻花辫" in text and "side braid" not in tags:
        tags.append("side braid")
    if "黑色短发" in text and "black hair" not in tags:
        tags.insert(0, "black hair")
    if "短发" in text and "short hair" not in tags and "black short hair" not in tags:
        tags.append("short hair")
    if "长发" in text and "long hair" not in tags:
        tags.append("long hair")
    if "披散" in text and "hair down" not in tags:
        tags.append("hair down")
    if not tags:
        return ""
    return ", ".join(tags)


def _merge_tag_anchors(prompt: str, anchors: str) -> str:
    prompt = (prompt or "").strip(" ,")
    anchors = (anchors or "").strip(" ,")
    if not anchors:
        return prompt
    seen = {part.strip().lower() for part in prompt.split(",") if part.strip()}
    extras = [
        part.strip()
        for part in anchors.split(",")
        if part.strip() and part.strip().lower() not in seen
    ]
    if not extras:
        return prompt
    if not prompt:
        return ", ".join(extras)
    return f"{prompt}, {', '.join(extras)}"


def _fallback_cn_tags(text: str) -> str:
    tags: list[str] = [
        "1girl",
        "solo",
        "full body",
        "character illustration",
        "ornate detailed background",
    ]
    anchor_tags = _cn_anchor_tags(text)
    for tag in [part.strip() for part in anchor_tags.split(",") if part.strip()]:
        if tag not in tags:
            tags.append(tag)
    if "修女" in text and "nun habit" not in tags:
        tags.append("black nun habit")
    if "眼罩" in text and "blindfold covering eyes" not in tags:
        tags.append("blindfold covering eyes")
    tags.extend(
        [
            "colored eyelashes",
            "half-closed eyes",
            "faint smile",
            "closed mouth",
            "detailed outfit",
            "detailed accessories",
            "cinematic lighting",
            "full body or knees-up character card",
            "ornate costume design",
            "rich non-white background",
            "clean anime character illustration",
        ]
    )
    return ", ".join(dict.fromkeys(tags))


def _normalize_tag_output(text: str) -> str:
    text = re.sub(r"\s+", " ", text.strip().strip("\"'").strip(" ,"))
    if "," not in text and " " in text:
        tokens = [part for part in text.split(" ") if part]
        if len(tokens) >= 3 and all("_" in part or part.isascii() for part in tokens):
            return ", ".join(tokens)
    return text


def _gender_anchor(*texts: str | None) -> str:
    blob = " ".join(t or "" for t in texts).lower()
    if re.search(r"\b(1girl|girl|woman|female|lady)\b", blob) or any(
        x in blob for x in ("女", "少女", "女人", "女性", "女骑士", "女盗贼", "她")
    ):
        return "1girl"
    if re.search(r"\b(1boy|boy|man|male)\b", blob) or any(
        x in blob for x in ("男", "少年", "男人", "男性", "男骑士", "男盗贼", "他")
    ):
        return "1boy"
    return "1girl"


def _strip_unrequested_animal_terms(prompt: str, *context: str | None) -> str:
    blob = " ".join(item or "" for item in context).lower()
    allow_animal = any(x in blob for x in ("猫", "犬", "狼", "狐", "兔")) or any(
        re.search(pattern, blob)
        for pattern in (
            r"\bcat\b",
            r"\bdog\b",
            r"\bwolf\b",
            r"\bfox\b",
            r"\bbunny\b",
            r"\brabbit\b",
        )
    )
    if allow_animal:
        return prompt
    banned = {
        "cat_theme",
        "cat theme",
        "cat ears",
        "animal ears",
        "wolf ears",
        "fox ears",
        "bunny ears",
        "tail",
        "horns",
    }
    parts = [
        part.strip()
        for part in prompt.split(",")
        if part.strip() and part.strip().lower() not in banned
    ]
    return ", ".join(parts)


def _prompt_parts(prompt: str) -> list[str]:
    return [part.strip() for part in (prompt or "").split(",") if part.strip()]


def _dedupe_parts(parts: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for part in parts:
        key = re.sub(r"\s+", " ", part.strip().lower())
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(part.strip())
    return out


def _strip_mode_conflicting_parts(prompt: str, *, mode: str) -> str:
    """Remove AI-supplied framing that conflicts with the requested output type."""
    if mode == "avatar":
        banned = (
            "full body",
            "feet visible",
            "knees-up",
            "thigh-up",
            "cowboy shot",
            "walking",
            "sitting",
            "seated",
            "standing",
            "dynamic pose",
            "action pose",
            "character sheet",
            "wide shot",
            "environmental shot",
        )
    else:
        banned = (
            "headshot",
            "face portrait",
            "bust portrait",
            "extreme close-up",
            "passport photo",
            "id photo",
            "character sheet",
            "full body",
            "standing pose",
            "standing front view",
            "plain white background",
            "white background",
            "simple background",
        )
    kept = []
    for part in _prompt_parts(prompt):
        lower = part.lower()
        if any(term in lower for term in banned):
            continue
        kept.append(part)
    return ", ".join(kept)


def _has_reference_camera(prompt: str) -> bool:
    lower = prompt.lower()
    return any(
        term in lower
        for term in (
            "close cowboy shot",
            "cowboy shot",
            "knees-up",
            "thigh-up",
            "close medium shot",
            "from side",
            "looking back",
            "low angle",
            "dutch angle",
            "seated pose",
            "walking action pose",
            "three-quarter view",
        )
    )


def _portrait_composition_variant(prompt_variant: int | None, *, mode: str = "reference") -> str:
    avatar_variants = [
        (
            "beautiful NTRMix headshot avatar, tight head-and-shoulders crop, face fills most of the frame, "
            "large expressive face, "
            "only head neck and shoulders visible, eyes as the focal point, subtle ornate blurred background"
        ),
        (
            "close-up bust avatar portrait, three-quarter face, shoulders visible, no waist, no hands, "
            "elegant collar detail, soft rim light, character face fills the frame"
        ),
        (
            "profile icon avatar, face-first composition, cropped above the chest, clear hairstyle and eye color, "
            "clean readable silhouette, not a standing character illustration"
        ),
    ]
    reference_variants = [
        (
            "close cowboy shot, three-quarter view, dynamic pose, large character in frame, "
            "face and upper body are prominent, ornate environment wrapped closely behind the character"
        ),
        (
            "knees-up view, from side, looking back over shoulder, diagonal composition, "
            "flowing hair, cinematic rim light, expressive hand pose"
        ),
        (
            "low angle action pose, dramatic perspective, outfit moving, large expressive face, "
            "foreground accessory, character fills the image"
        ),
        (
            "thigh-up view, seated pose on ornate furniture or stone steps, relaxed but elegant posture, "
            "tilted camera angle"
        ),
        (
            "walking action pose, diagonal composition, close camera, visible floor shadows, "
            "environmental depth behind the character"
        ),
        (
            "close medium shot, dutch angle, expressive hand pose, detailed background architecture, "
            "character occupies most of the image"
        ),
    ]
    variants = avatar_variants if mode == "avatar" else reference_variants
    idx = 0 if prompt_variant is None else abs(int(prompt_variant)) % len(variants)
    return variants[idx]


async def _translate_to_tags(
    appearance: str,
    *,
    name: str | None = None,
    persona: str | None = None,
    brain: BrainProvider | None = None,
    player_input: str | None = None,
) -> str:
    """Translate natural language character description → Danbooru English tags via AI.

    ``player_input`` is the user's original prompt — used as highest-priority reference
    so the translation never drops user-requested details.
    Falls back to original text if translation fails.
    """
    # 保留简短描述，过长会导致 DeepSeek 返回空
    msg = f"角色外貌：{appearance[:300]}"
    if name:
        msg += f"\n角色名：{name}。"
    if persona:
        msg += f"\n人设：{persona[:200]}"
    if player_input:
        msg += f"\n玩家描述：{player_input[:200]}"
    prompts = [
        msg,
        msg,
        f"角色外貌：{appearance[:300]}",
        f"只把下面中文外貌翻译成英文绘图tag，逗号分隔：{appearance[:220]}",
    ]
    for input_msg in prompts:
        try:
            raw = (await agent.run(
                "image_prompt_translate",
                input=input_msg,
            ))
            raw = _normalize_tag_output(raw)[:1024]
            if raw and not _is_natural_language(raw):
                return raw
        except Exception:
            continue
    return _fallback_cn_tags(f"{player_input or ''} {appearance}")


async def _design_portrait_prompt(
    appearance: str,
    *,
    name: str | None = None,
    persona: str | None = None,
    player_input: str | None = None,
    nsfw: bool = False,
) -> str:
    msg = (
        f"角色名：{name or '未知'}\n"
        f"角色人设：{persona or '无'}\n"
        f"角色外貌：{appearance[:600]}\n"
        f"NSFW：{'true' if nsfw else 'false'}\n"
        f"玩家原始描述：{player_input or '无'}"
    )
    try:
        raw = await agent.run("portrait_prompt", input=msg)
    except Exception:
        return ""
    prompt = _normalize_tag_output(str(raw))[:1400]
    if not prompt or _is_natural_language(prompt):
        return ""
    return prompt


async def _english_portrait_tags(
    appearance: str,
    *,
    name: str | None,
    persona: str | None,
    nsfw: bool,
    brain: BrainProvider | None,
    player_input: str | None,
) -> str:
    if not _is_natural_language(appearance):
        return appearance
    anchors = _cn_anchor_tags(f"{player_input or ''} {appearance} {persona or ''}")
    designed_prompt = await _design_portrait_prompt(
        appearance,
        name=name,
        persona=persona,
        player_input=player_input,
        nsfw=nsfw,
    )
    if designed_prompt and not _is_natural_language(designed_prompt):
        return _merge_tag_anchors(designed_prompt, anchors)
    translated = await _translate_to_tags(
        appearance,
        name=name,
        persona=persona,
        brain=brain,
        player_input=player_input,
    )
    if translated and not _is_natural_language(translated):
        return _merge_tag_anchors(translated, anchors)
    return _fallback_cn_tags(f"{player_input or ''} {appearance}")


def build_portrait_prompt(
    appearance: str,
    *,
    name: str | None = None,
    persona: str | None = None,
    nsfw: bool = False,
    prompt_variant: int | None = None,
    mode: str = "reference",
) -> tuple[str, str]:
    """Final character-card prompt with guardrails against avatar-like crops."""
    appearance = (appearance or "").strip()
    if not appearance:
        return "", PORTRAIT_NEGATIVE
    positive = re.sub(
        r"^(?:(?:masterpiece|best\s*quality|score_[987]|@?ntrmixstyle),?\s*)+",
        "",
        appearance,
        flags=re.I,
    ).replace("_", " ").strip(" ,")
    positive = _strip_unrequested_animal_terms(positive, appearance, name, persona)
    positive = _strip_mode_conflicting_parts(positive, mode=mode)
    lower = positive.lower()
    prefix_parts: list[str] = []
    guards: list[str] = []
    if not _GENDER_RE.search(lower):
        prefix_parts.append(_gender_anchor(appearance, name, persona))
    if "solo" not in lower:
        prefix_parts.append("solo")
    if mode == "avatar":
        guards.append(_portrait_composition_variant(prompt_variant, mode="avatar"))
        guards.append(
            "avatar icon crop, tight face close-up, no full body, no knees, no thighs, "
            "no standing pose, no large empty background"
        )
    elif not _has_reference_camera(lower):
        guards.append(_portrait_composition_variant(prompt_variant, mode="reference"))
    if not any(tag in lower for tag in ("colored eyelashes", "jitome", "half-closed eyes", "sleepy eyes")):
        guards.append("colored eyelashes, jitome, half-closed eyes, glossy eyes")
    if not any(tag in lower for tag in ("parted lips", "closed mouth", "small smile", "faint smile", "smirk")):
        guards.append("parted lips, sly faint smile")
    if "blush" not in lower:
        guards.append("soft blush")
    if not any(tag in lower for tag in ("ornate", "detailed background", "cathedral", "interior", "dungeon", "tavern")):
        guards.append(
            "ornate detailed background, rich colored background, cinematic anime lighting, "
            "not a plain white background"
        )
    if not any(tag in lower for tag in ("detailed outfit", "intricate outfit", "ornate outfit", "detailed accessories")):
        guards.append(
            "intricate outfit, ornate costume design, detailed accessories, "
            "layered costume design"
        )
    guards.append(
        "NTRMix pretty face recipe, finished full-color anime character illustration, "
        "polished cel shading, crisp expressive eyes, detailed hair, natural hands, strong character appeal"
    )
    positive_parts = _dedupe_parts(prefix_parts + _prompt_parts(positive) + guards)
    positive = ", ".join(positive_parts)
    if nsfw and positive:
        positive = f"nsfw, explicit, {positive}"
    negative = (
        f"{PORTRAIT_NEGATIVE}, {AVATAR_NEGATIVE_EXTRA}"
        if mode == "avatar"
        else f"{PORTRAIT_NEGATIVE}, {REFERENCE_NEGATIVE_EXTRA}"
    )
    lower_final = positive.lower()
    if (
        "golden eyes" in lower_final
        or "gold eyes" in lower_final
        or "yellow eyes" in lower_final
        or "amber eyes" in lower_final
    ):
        negative = f"{negative}, red eyes, crimson eyes, purple eyes, blue eyes"
    elif "purple eyes" in lower_final:
        negative = f"{negative}, red eyes, golden eyes, yellow eyes, blue eyes"
    elif "blue eyes" in lower_final or "azure eyes" in lower_final:
        negative = f"{negative}, red eyes, purple eyes, golden eyes, yellow eyes"
    elif "red eyes" in lower_final or "crimson eyes" in lower_final:
        negative = f"{negative}, golden eyes, yellow eyes, purple eyes, blue eyes"
    if "black hair" in lower_final or "black short hair" in lower_final:
        negative = f"{negative}, white hair, silver hair, blonde hair, light hair"
    elif "blonde hair" in lower_final or "golden hair" in lower_final:
        negative = f"{negative}, black hair, white hair, silver hair"
    elif "silver hair" in lower_final or "white hair" in lower_final:
        negative = f"{negative}, black hair, blonde hair, brown hair"
    return positive, negative


async def generate_portrait(
    appearance: str,
    *,
    name: str | None = None,
    persona: str | None = None,
    nsfw: bool = False,
    seed: int | None = None,
    prompt_variant: int | None = None,
    brain: BrainProvider | None = None,
    player_input: str | None = None,
    mode: str = "reference",
    max_attempts: int = 2,
) -> dict[str, Any]:
    """Generate one cute upper-body avatar (立绘) from a free-text appearance.

    If appearance is natural language (contains Chinese), translates to Danbooru
    tags via AI first, then passes to ComfyUI/Anima DiT with ntrmix LoRA.
    ``player_input`` is the user's original prompt — passed to the translation AI
    as highest-priority reference so user-requested details are never dropped.
    Returns ``{url,path,filename,prompt_id,appearance_tags}`` on success
    or ``{error}`` on failure.
    """
    if appearance and _is_natural_language(appearance):
        appearance = await _english_portrait_tags(
            appearance,
            name=name,
            persona=persona,
            nsfw=nsfw,
            brain=brain,
            player_input=player_input,
        )
    positive, negative = build_portrait_prompt(
        appearance,
        name=name,
        persona=persona,
        nsfw=nsfw,
        prompt_variant=prompt_variant,
        mode=mode,
    )
    if positive and _is_natural_language(positive):
        translated = await _translate_to_tags(
            positive,
            name=name,
            persona=persona,
            brain=brain,
            player_input=player_input,
        )
        if translated and not _is_natural_language(translated):
            positive, negative = build_portrait_prompt(
                translated,
                name=name,
                persona=persona,
                nsfw=nsfw,
                prompt_variant=prompt_variant,
                mode=mode,
            )
        else:
            positive, negative = build_portrait_prompt(
                _fallback_cn_tags(f"{player_input or ''} {appearance}"),
                name=name,
                persona=persona,
                nsfw=nsfw,
                prompt_variant=prompt_variant,
                mode=mode,
            )
    if positive and _is_natural_language(positive):
        return {"error": "portrait prompt still contains Chinese after translation guard"}
    quality_kind = "avatar" if mode == "avatar" else "reference"
    last_result: dict[str, Any] = {}
    attempts = max(1, int(max_attempts or 1))
    for attempt in range(attempts):
        attempt_seed = None if seed is None else seed + attempt * 1009
        attempt_positive = positive
        if attempt:
            attempt_positive = (
                f"{positive}, alternate polished composition, stronger face appeal, "
                "rich colored background, no white void"
            )
        result = await generate_anima(
            attempt_positive,
            negative,
            seed=attempt_seed,
            upscale=True,
            tile_refine=True,
        )
        last_result = result
        if result.get("url"):
            result["appearance_tags"] = attempt_positive
            result = annotate_quality_result(result, kind=quality_kind)
            last_result = result
            if result.get("quality_ok", True):
                return result
    if last_result.get("url"):
        return {
            "error": "生成图片质量不达标，已重试但仍失败",
            "last_url": last_result.get("url"),
            "quality_reasons": last_result.get("quality_reasons", []),
        }
    return last_result
