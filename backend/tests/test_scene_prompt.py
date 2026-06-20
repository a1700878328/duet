import pytest

import app.imagegen.scene_prompt as scene_prompt
from app.imagegen.scene_prompt import build_scene_prompt


async def _agent_failure(_task, **_kwargs):
    raise RuntimeError("agent unavailable")


@pytest.mark.asyncio
async def test_scene_prompt_uses_original_ntrmix_runtime_tags_only(monkeypatch) -> None:
    monkeypatch.setattr(scene_prompt.agent, "run", _agent_failure)
    prompt = await build_scene_prompt(
        "女骑士警惕地看向酒馆门口。",
        ["莉娜: blonde hair, blue eyes, silver armor"],
        nsfw=False,
        two_person=False,
    )

    assert "masterpiece" not in prompt["positive"]
    assert "@ntrmixstyle" not in prompt["positive"]
    assert "sfw, 1girl, solo" in prompt["positive"]
    assert "nsfw" not in prompt["positive"]
    assert "1girl, solo" in prompt["positive"]
    assert "莉娜" not in prompt["positive"]
    assert "blonde hair, blue eyes, silver armor" in prompt["positive"]
    assert "colored eyelashes" in prompt["positive"]
    assert "half-closed eyes" in prompt["positive"]
    assert "parted lips" in prompt["positive"]
    assert "open mouth" not in prompt["positive"]
    assert "fantasy tavern interior" in prompt["positive"]
    assert "simple background" not in prompt["positive"]
    assert "plain white background" in prompt["negative"]
    assert "passport photo" in prompt["negative"]
    assert "night city street" not in prompt["positive"]
    assert "fireworks" not in prompt["positive"]
    assert "explosion" not in prompt["positive"]


@pytest.mark.asyncio
async def test_scene_prompt_builds_duo_consistency_template(monkeypatch) -> None:
    monkeypatch.setattr(scene_prompt.agent, "run", _agent_failure)
    prompt = await build_scene_prompt(
        "两人在地下城入口短暂对峙。",
        [
            "艾莉丝: red hair, amber eyes, leather armor, sword at hip",
            "米拉: white hair, blue eyes, witch hat, wide sleeves",
        ],
        nsfw=False,
        two_person=True,
    )

    positive = prompt["positive"]
    negative = prompt["negative"]
    assert "exactly 2 characters" in positive
    assert "left character" in positive
    assert "right character" in positive
    assert "left character, 1girl, adult female" in positive
    assert "right character, 1girl, adult female" in positive
    assert "艾莉丝" not in positive
    assert "米拉" not in positive
    assert "different hairstyles" in positive
    assert "different hair colors" in positive
    assert "different outfits" in positive
    assert "separate faces" in positive
    assert "separate bodies" in positive
    assert "no other people" in positive
    assert "merged faces" in negative
    assert "same face" in negative
    assert "third person" in negative


@pytest.mark.asyncio
async def test_scene_prompt_rejects_mixed_chinese_ai_output(monkeypatch) -> None:
    async def mixed_chinese(_task, **_kwargs):
        return {
            "positive": "2girls, left character 银白发蓝眼, right character 黑发金眼",
            "negative": "",
        }

    monkeypatch.setattr(scene_prompt.agent, "run", mixed_chinese)
    prompt = await build_scene_prompt(
        "两人在地下城入口短暂对峙。",
        [
            "艾莉丝: silver-white hair, blue eyes, silver armor, sword at hip",
            "米拉: black hair, golden eyes, black robe, obsidian staff",
        ],
        nsfw=False,
        two_person=True,
    )

    assert "银白" not in prompt["positive"]
    assert "黑发" not in prompt["positive"]
    assert "silver-white hair" in prompt["positive"]
    assert "golden eyes" in prompt["positive"]


@pytest.mark.asyncio
async def test_scene_prompt_normalizes_identity_tags_and_blocks_side_margins(
    monkeypatch,
) -> None:
    monkeypatch.setattr(scene_prompt.agent, "run", _agent_failure)

    prompt = await build_scene_prompt(
        "两人在城堡走廊警戒。",
        [
            "骑士: silver-white hair, purple eyes, blue_cape, rune_sword",
            "盗贼: black_hair, golden_eyes, brown_skin, red_black_outfit, cat_theme",
        ],
        nsfw=False,
        two_person=True,
    )

    assert "black hair" in prompt["positive"]
    assert "golden eyes" in prompt["positive"]
    assert "dark red and black leather rogue outfit" in prompt["positive"]
    assert "cat theme" not in prompt["positive"]
    assert "cat ears" in prompt["negative"]
    assert "white side borders" in prompt["negative"]


@pytest.mark.asyncio
async def test_scene_prompt_keeps_structured_director_plan(monkeypatch) -> None:
    async def structured_scene(_task, **_kwargs):
        return {
            "scene_intent": "会长跨坐在玩家身上。",
            "pose_relation": "one woman straddling on top of the other in an above-and-below pose",
            "core_action": "hips pressed together, crotch rubbing is the main requested action",
            "camera": "close medium galgame CG, lower bodies visible enough to show the pose",
            "style": "vibrant 2D anime game CG",
            "character_locks": ["silver hair stays silver", "black dress stays black"],
            "must_include": ["straddling on top", "above-and-below pose"],
            "must_avoid": ["tea cup", "drinking tea", "touching chin"],
            "positive": "2girls, straddling, above-and-below pose, vibrant 2D anime game CG",
            "negative": "standing side by side",
            "composition": "Close above-and-below two-person composition.",
        }

    monkeypatch.setattr(scene_prompt.agent, "run", structured_scene)
    prompt = await build_scene_prompt(
        "会长骑在我身上蹭我的小穴。",
        [
            "会长: silver hair, blue eyes, black dress",
            "玩家: black hair, purple eyes, red outfit",
        ],
        nsfw=True,
        two_person=True,
    )

    assert "straddling on top" in prompt["pose_relation"]
    assert "crotch rubbing is the main requested action" in prompt["core_action"]
    assert "lower bodies visible" in prompt["camera"]
    assert "tea cup" in prompt["negative"]
    assert "touching chin" in prompt["negative"]


@pytest.mark.asyncio
async def test_scene_prompt_compacts_generic_style_filler(monkeypatch) -> None:
    async def generic_scene(_task, **_kwargs):
        return {
            "positive": (
                "2girls, high-rarity NTRMix anime visual novel event CG, "
                "premium story event still, finished full-color anime illustration, "
                "standing close in a gothic cathedral"
            ),
            "negative": "",
        }

    monkeypatch.setattr(scene_prompt.agent, "run", generic_scene)
    prompt = await build_scene_prompt(
        "两人在哥特式教堂里对视。",
        [
            "骑士: silver-white hair, purple eyes, blue armor",
            "会长: black hair, red eyes, black dress",
        ],
        nsfw=False,
        two_person=True,
    )

    assert "high-rarity NTRMix anime visual novel event CG" not in prompt["positive"]
    assert "premium story event still" not in prompt["positive"]
    assert "NTRMix pretty face recipe" in prompt["positive"]
    assert "colored eyelashes" in prompt["positive"]
    assert "Japanese visual novel event CG" in prompt["positive"]
