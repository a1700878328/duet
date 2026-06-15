import pytest

from app.imagegen.scene_prompt import build_scene_prompt


class UnusedBrain:
    async def complete(self, messages):  # pragma: no cover - should not be called
        raise AssertionError("scene prompts should be deterministic")


@pytest.mark.asyncio
async def test_scene_prompt_uses_original_ntrmix_runtime_tags_only() -> None:
    prompt = await build_scene_prompt(
        "女骑士警惕地看向酒馆门口。",
        ["莉娜: blonde hair, blue eyes, silver armor"],
        nsfw=False,
        two_person=False,
        brain=UnusedBrain(),
    )

    assert "masterpiece" not in prompt["positive"]
    assert "@ntrmixstyle" not in prompt["positive"]
    assert "1girl, solo" in prompt["positive"]
    assert "莉娜" in prompt["positive"]
    assert "blonde hair, blue eyes, silver armor" in prompt["positive"]
    assert "colored eyelashes" in prompt["positive"]
    assert "jitome" in prompt["positive"]
    assert "cowboy shot, from side, looking at viewer" in prompt["positive"]
    assert "night city street" not in prompt["positive"]
    assert "fireworks" not in prompt["positive"]
    assert "explosion" not in prompt["positive"]


@pytest.mark.asyncio
async def test_scene_prompt_builds_duo_consistency_template() -> None:
    prompt = await build_scene_prompt(
        "两人在地下城入口短暂对峙。",
        [
            "艾莉丝: red hair, amber eyes, leather armor, sword at hip",
            "米拉: white hair, blue eyes, witch hat, wide sleeves",
        ],
        nsfw=False,
        two_person=True,
        brain=UnusedBrain(),
    )

    positive = prompt["positive"]
    negative = prompt["negative"]
    assert "exactly 2 characters" in positive
    assert "left character, 艾莉丝" in positive
    assert "right character, 米拉" in positive
    assert "different hairstyles" in positive
    assert "different hair colors" in positive
    assert "different outfits" in positive
    assert "separate faces" in positive
    assert "separate bodies" in positive
    assert "no other people" in positive
    assert "merged faces" in negative
    assert "same face" in negative
    assert "third person" in negative
