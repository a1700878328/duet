import pytest

from app.imagegen.anima import (
    build_anima_regional_ipadapter_workflow,
    build_anima_workflow,
    build_baobao_anima_workflow,
)
from app.imagegen import anima as anima_mod
from app.imagegen.portrait import build_portrait_prompt
from app.imagegen import portrait as portrait_mod
from app.imagegen.scene_prompt import build_scene_prompt_sync


def test_anima_workflow_creates_valid_graph() -> None:
    graph = build_anima_workflow("A high-quality anime portrait.")

    assert graph["1"]["class_type"] == "AnimaBoosterLoader"
    assert graph["9"]["class_type"] == "KSampler"


def test_anima_workflow_can_add_teacache_and_upscale() -> None:
    graph = build_anima_workflow(
        "A high-quality anime scene.",
        width=512,
        height=768,
        upscale=True,
    )

    assert graph["16"]["class_type"] == "AnimaTeaCache"
    assert graph["2"]["inputs"]["model"] == ["16", 0]
    assert graph["20"]["class_type"] == "UpscaleModelLoader"
    assert graph["21"]["class_type"] == "ImageUpscaleWithModel"
    assert graph["22"]["class_type"] == "ImageScale"
    assert graph["22"]["inputs"]["width"] == 1024
    assert graph["22"]["inputs"]["height"] == 1536
    assert graph["11"]["inputs"]["images"] == ["22", 0]


def test_anima_workflow_uses_baobao_two_pass_quality_chain() -> None:
    graph = build_anima_workflow("A high-quality anime scene.")

    assert graph["9"]["inputs"]["steps"] == 30
    assert graph["9"]["inputs"]["cfg"] == 4.0
    assert graph["9"]["inputs"]["sampler_name"] == "er_sde"
    assert graph["9"]["inputs"]["scheduler"] == "beta57"
    assert graph["23"]["class_type"] == "LoraLoaderModelOnly"
    assert graph["23"]["inputs"]["model"] == ["2", 0]
    assert graph["23"]["inputs"]["lora_name"] == "ntrmix_style_anima_b1_v1.safetensors"
    assert graph["23"]["inputs"]["strength_model"] == 1.0
    assert graph["9"]["inputs"]["model"] == ["23", 0]
    assert graph["17"]["class_type"] == "VAEEncode"
    assert graph["18"]["class_type"] == "KSampler"
    assert graph["18"]["inputs"]["steps"] == 8
    assert graph["18"]["inputs"]["cfg"] == 4.0
    assert graph["18"]["inputs"]["sampler_name"] == "euler"
    assert graph["18"]["inputs"]["scheduler"] == "kl_optimal"
    assert graph["18"]["inputs"]["denoise"] == 0.4
    assert graph["19"]["class_type"] == "VAEDecode"
    assert graph["11"]["inputs"]["images"] == ["19", 0]


def test_baobao_workflow_ports_reference_t2i_path() -> None:
    graph = build_baobao_anima_workflow(
        "A blonde knight in a tavern.",
        width=1024,
        height=1024,
        seed=123,
    )

    assert graph["159"]["class_type"] == "WJILatentPreset"
    assert graph["159"]["inputs"]["自定义宽"] == 1024
    assert graph["159"]["inputs"]["自定义高"] == 1024
    assert graph["68"]["class_type"] == "CR Text"
    assert "@ntrmixstyle" in graph["68"]["inputs"]["text"]
    assert "score_9" in graph["68"]["inputs"]["text"]
    assert graph["3"]["class_type"] == "LoraLoaderModelOnly"
    assert graph["3"]["inputs"]["model"] == ["60", 0]
    assert graph["3"]["inputs"]["lora_name"] == "ntrmix_style_anima_b1_v1.safetensors"
    assert graph["3"]["inputs"]["strength_model"] == 1.0
    assert graph["73"]["class_type"] == "Text Concatenate"
    assert graph["57"]["inputs"]["model"] == ["3", 0]
    assert graph["57"]["inputs"]["steps"] == 30
    assert graph["57"]["inputs"]["cfg"] == 4.0
    assert graph["57"]["inputs"]["sampler_name"] == "er_sde"
    assert graph["57"]["inputs"]["scheduler"] == "beta57"
    assert graph["169"]["class_type"] == "SaveImage"
    assert graph["169"]["inputs"]["images"] == ["64", 0]
    assert "164" not in graph
    assert "180" not in graph


def test_baobao_workflow_can_enable_original_ultratile_chain() -> None:
    graph = build_baobao_anima_workflow(
        "A blonde knight in a tavern.",
        width=1024,
        height=1024,
        seed=123,
        upscale=True,
        tile_refine=True,
    )

    assert graph["164"]["class_type"] == "easy imageScaleDownToSize"
    assert graph["161"]["class_type"] == "UpscaleModelLoader"
    assert graph["162"]["class_type"] == "ImageUpscaleWithModel"
    assert graph["165"]["class_type"] == "easy imageScaleDownToSize"
    assert graph["180"]["inputs"]["images"] == ["165", 0]
    assert graph["169"]["inputs"]["images"] == ["139", 0]
    assert "REFINED" in graph["169"]["inputs"]["filename_prefix"]


def test_baobao_workflow_builds_ntrmix_graph() -> None:
    graph = build_baobao_anima_workflow(
        "Two characters stand together.",
        width=1216,
        height=832,
        seed=123,
    )

    assert graph["3"]["inputs"]["lora_name"] == "ntrmix_style_anima_b1_v1.safetensors"
    assert graph["54"]["inputs"]["text"] == "Two characters stand together."
    assert all(
        n["class_type"] not in {"SolidMask", "MaskComposite"} for n in graph.values()
    )
    assert graph["57"]["inputs"]["model"] == ["3", 0]


def test_regional_ipadapter_keeps_public_ref_order_for_current_masks(
    monkeypatch,
) -> None:
    def fake_copy(path):
        return str(path)

    monkeypatch.setattr(anima_mod, "_copy_reference_to_comfy_input", fake_copy)

    graph = build_anima_regional_ipadapter_workflow(
        "left knight, right thief",
        reference_paths=["left_knight.png", "right_thief.png"],
        seed=123,
    )

    assert "left_knight" in graph["300"]["inputs"]["image"]
    assert "right_thief" in graph["301"]["inputs"]["image"]


def test_regional_ipadapter_can_swap_refs_for_alternate_mask_geometry(
    monkeypatch,
) -> None:
    def fake_copy(path):
        return str(path)

    monkeypatch.setattr(anima_mod, "_copy_reference_to_comfy_input", fake_copy)

    graph = build_anima_regional_ipadapter_workflow(
        "left knight, right thief",
        reference_paths=["left_knight.png", "right_thief.png"],
        seed=123,
        swap_refs=True,
    )

    assert "right_thief" in graph["300"]["inputs"]["image"]
    assert "left_knight" in graph["301"]["inputs"]["image"]


def test_regional_ipadapter_can_use_vertical_masks(monkeypatch) -> None:
    def fake_copy(path):
        return str(path)

    def fake_mask(side, *, width, height):
        return f"{side}_mask.png"

    monkeypatch.setattr(anima_mod, "_copy_reference_to_comfy_input", fake_copy)
    monkeypatch.setattr(anima_mod, "_region_mask_to_comfy_input", fake_mask)

    graph = build_anima_regional_ipadapter_workflow(
        "upper knight, lower thief",
        reference_paths=["upper_knight.png", "lower_thief.png"],
        seed=123,
        region_layout="vertical",
    )

    assert graph["302"]["inputs"]["image"] == "top_mask.png"
    assert graph["303"]["inputs"]["image"] == "bottom_mask.png"


def test_baobao_workflow_can_disable_ntrmix_for_clean_style() -> None:
    graph = build_baobao_anima_workflow(
        "A clean anime scene.",
        seed=123,
        use_ntrmix=False,
    )

    assert "4" not in graph
    assert "@ntrmixstyle" not in graph["68"]["inputs"]["text"]
    assert graph["57"]["inputs"]["model"] == ["60", 0]


def test_portrait_prompt_keeps_ai_prompt_and_adds_card_guards() -> None:
    positive, negative = build_portrait_prompt(
        "1girl, full body, silver hair, blue eyes, light armor, ornate cathedral",
        name="莉娜",
        persona="温柔但有点害羞的新人骑士",
    )

    assert "1girl" in positive
    assert "silver hair, blue eyes, light armor" in positive
    assert "full body" not in positive
    assert "close cowboy shot" in positive
    assert "NTRMix pretty face recipe" in positive
    assert "colored eyelashes" in positive
    assert "nsfw" not in positive  # nsfw flag not set
    assert "passport photo" in negative
    assert "headshot" in negative


def test_portrait_prompt_adds_nsfw_prefix_when_enabled() -> None:
    positive, _negative = build_portrait_prompt(
        "silver hair, blue eyes, light armor",
        name="莉娜",
        persona="温柔但有点害羞的新人骑士",
        nsfw=True,
    )

    assert positive.startswith("nsfw, explicit")
    assert "silver hair, blue eyes, light armor" in positive
    assert "cowboy shot" in positive
    assert "NTRMix pretty face recipe" in positive


def test_portrait_prompt_avatar_mode_is_face_first() -> None:
    positive, negative = build_portrait_prompt(
        "1girl, silver hair, blue eyes, light armor, ornate collar",
        name="莉娜",
        persona="温柔但有点害羞的新人骑士",
        mode="avatar",
    )

    assert "head-and-shoulders crop" in positive
    assert "face fills most of the frame" in positive
    assert "no standing pose" in positive
    assert "large expressive face" in positive
    assert "full body" in negative
    assert "distant character" in negative


def test_portrait_prompt_reference_mode_keeps_character_card_framing() -> None:
    positive, negative = build_portrait_prompt(
        "1girl, silver hair, blue eyes, light armor",
        name="莉娜",
        persona="温柔但有点害羞的新人骑士",
        mode="reference",
    )

    assert "head-and-shoulders crop" not in positive
    assert "NTRMix pretty face recipe" in positive
    assert "close cowboy shot" in positive
    assert "extreme close-up" in negative


def test_portrait_prompt_adds_gender_and_filters_unrequested_animal_theme() -> None:
    positive, _negative = build_portrait_prompt(
        "black_hair, short_hair, golden_eyes, cat_theme, red_black_outfit",
        name="黑羽盗贼米拉",
        persona="敏捷、狡黠、警惕的女盗贼",
    )

    assert "1girl" in positive
    assert "cat_theme" not in positive
    assert "golden eyes" in positive
    assert "red black outfit" in positive


def test_portrait_prompt_empty_appearance_returns_empty() -> None:
    positive, negative = build_portrait_prompt("")
    assert positive == ""
    assert "passport photo" in negative


@pytest.mark.asyncio
async def test_portrait_translation_never_falls_back_to_chinese(monkeypatch) -> None:
    async def empty_translate(*_args, **_kwargs):
        return ""

    monkeypatch.setattr(portrait_mod.agent, "run", empty_translate)

    tags = await portrait_mod._translate_to_tags(
        "黑色修女服，白色头巾，黑色眼罩遮住双眼，银灰色短发",
        player_input="戴眼罩的修女",
    )

    assert "修女" not in tags
    assert "nun" in tags
    assert "blindfold" in tags


@pytest.mark.asyncio
async def test_portrait_english_tags_reject_mixed_chinese_ai_output(monkeypatch) -> None:
    async def mixed_chinese_prompt(*_args, **_kwargs):
        return "1girl, solo, 白金长发，红色眼睛，黑红贵族战斗礼服"

    monkeypatch.setattr(portrait_mod.agent, "run", mixed_chinese_prompt)

    tags = await portrait_mod._english_portrait_tags(
        "白金长发，红色眼睛，黑红贵族战斗礼服，佩剑和红宝石耳坠",
        name="夜璃",
        persona="暗黑贵族剑士",
        nsfw=False,
        brain=None,
        player_input="不要白底，不要头像",
    )

    assert "白金" not in tags
    assert "红色" not in tags
    assert "platinum blonde hair" in tags
    assert "red eyes" in tags
    assert "black and red outfit" in tags


def test_scene_prompt_uses_location_background_not_blank_backdrop() -> None:
    prompt = build_scene_prompt_sync(
        "当前场景：冒险者公会\n瑟琳娜按住会长，柜台旁围着冒险者。",
        [
            "瑟琳娜: 1girl, red hair, knight",
            "公会会长: mature woman, silver braid, guild uniform",
        ],
        nsfw=False,
        two_person=True,
    )

    assert "adventurer guild hall interior" in prompt["positive"]
    assert "simple background" not in prompt["positive"]
    assert "plain white background" in prompt["negative"]
