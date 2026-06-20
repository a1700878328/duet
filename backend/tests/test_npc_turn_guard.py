from types import SimpleNamespace

import pytest

from app import ws as ws_mod
from app.prompts import build_npc_system_prompt, history_to_messages


class WrongSpeakerBrain:
    def __init__(self) -> None:
        self.calls = 0

    async def run(self, task, *, messages=None, **_kwargs):
        assert task == "npc_dialogue_text"
        self.calls += 1
        if self.calls == 1:
            return "[旁白]: 风从门缝里吹进来。"
        assert "专属回合" in messages[-1]["content"]
        return "[酒馆老板娘]: （眯起眼）你刚才那句话，我可不能当没听见。"


class StillWrongSpeakerBrain:
    async def run(self, task, *, messages=None, **_kwargs):
        assert task == "npc_dialogue_text"
        return "[旁白]: 场面安静下来。"


class WrongUnbracketedSpeakerBrain:
    def __init__(self) -> None:
        self.calls = 0

    async def run(self, task, *, messages=None, **_kwargs):
        assert task == "npc_dialogue_text"
        self.calls += 1
        if self.calls == 1:
            return "瑟琳娜·血藤（懒洋洋地靠在吧台边）：我来替你说吧。"
        return "[公会会长]: 公会会长（皱眉）：把别人的名字从我的台词里拿掉。"


class ImpersonationThenTargetBrain:
    async def run(self, task, *, messages=None, **_kwargs):
        assert task == "npc_dialogue_text"
        return "[艾琳]: 我替玩家说。\n[公会会长]: 站到前面来。"


class JsonRepairBrain:
    def __init__(self) -> None:
        self.calls = 0

    async def run(self, task, *, messages=None, **_kwargs):
        assert task == "npc_dialogue_text"
        self.calls += 1
        if self.calls == 1:
            return "[旁白]: 酒馆里忽然安静下来。"
        return (
            '{"dialogue":"别站在门口发愣，想问路就先付一枚铜币。",'
            '"state":"她敲了敲柜台。","narration_request":null}'
        )


@pytest.mark.asyncio
async def test_npc_turn_regenerates_narrator_label(monkeypatch):
    brain = WrongSpeakerBrain()
    monkeypatch.setattr(ws_mod.agent, "run", brain.run)

    clean, info = await ws_mod._generate_guarded(
        [{"role": "system", "content": "只扮演酒馆老板娘"}],
        ["女骑士"],
        required_label="酒馆老板娘",
    )

    assert brain.calls == 2
    assert info["regenerated"] is True
    assert not clean.startswith("[酒馆老板娘]:")
    assert "你刚才那句话" in clean
    assert "[旁白]" not in clean


@pytest.mark.asyncio
async def test_npc_turn_fails_closed_to_npc_label(monkeypatch):
    monkeypatch.setattr(ws_mod.agent, "run", StillWrongSpeakerBrain().run)

    with pytest.raises(ws_mod.NPCDialogueGuardError):
        await ws_mod._generate_guarded(
            [{"role": "system", "content": "只扮演酒馆老板娘"}],
            ["女骑士"],
            required_label="酒馆老板娘",
        )


@pytest.mark.asyncio
async def test_npc_turn_regenerates_unbracketed_other_npc_label(monkeypatch):
    brain = WrongUnbracketedSpeakerBrain()
    monkeypatch.setattr(ws_mod.agent, "run", brain.run)

    clean, info = await ws_mod._generate_guarded(
        [{"role": "system", "content": "只扮演公会会长"}],
        ["瑟琳娜·血藤"],
        required_label="公会会长",
    )

    assert brain.calls == 2
    assert info["regenerated"] is True
    assert not clean.startswith("[公会会长]:")
    assert "把别人的名字" in clean
    assert "瑟琳娜·血藤" not in clean


@pytest.mark.asyncio
async def test_npc_turn_keeps_target_segment_after_dropping_impersonation(monkeypatch):
    monkeypatch.setattr(ws_mod.agent, "run", ImpersonationThenTargetBrain().run)

    clean, info = await ws_mod._generate_guarded(
        [{"role": "system", "content": "只扮演公会会长"}],
        ["艾琳"],
        required_label="公会会长",
    )

    assert clean == "站到前面来。"
    assert info["violated_first"] is True


@pytest.mark.asyncio
async def test_npc_turn_parses_json_repair_attempt(monkeypatch):
    brain = JsonRepairBrain()
    monkeypatch.setattr(ws_mod.agent, "run", brain.run)

    clean, info = await ws_mod._generate_guarded(
        [{"role": "system", "content": "只扮演酒馆老板娘"}],
        ["艾琳"],
        required_label="酒馆老板娘",
    )

    assert brain.calls == 2
    assert info["regenerated"] is True
    assert clean == "别站在门口发愣，想问路就先付一枚铜币。"


@pytest.mark.parametrize(
    "text",
    [
        "瑟琳娜·血藤（懒洋洋地靠在吧台边）：我来替你说吧。",
        "[公会会长]: 瑟琳娜·血藤（懒洋洋地靠在吧台边）：我来替你说吧。",
    ],
)
def test_required_speaker_detects_nested_or_unbracketed_other_label(text):
    assert ws_mod._has_wrong_required_speaker(text, "公会会长") is True


def test_required_speaker_prefix_is_stripped_without_changing_label():
    text = "[公会会长]: （皱眉）按规矩来。"
    assert (
        ws_mod._strip_required_speaker_prefix(text, "公会会长")
        == "（皱眉）按规矩来。"
    )


def test_npc_dialogue_guard_detects_third_person_other_role_leak():
    assert ws_mod._looks_like_npc_narration_leak(
        "会长放下茶杯，朝你挑了挑眉。“有事？”",
        npc_name="教官",
        forbidden_names=["公会会长", "瑟琳娜"],
    )


def test_npc_dialogue_guard_detects_self_third_person_narration():
    assert ws_mod._looks_like_npc_narration_leak(
        "会长站起身，绕过柜台踱到你面前。“想接点特别的任务？”",
        npc_name="公会会长",
        forbidden_names=["教官", "瑟琳娜"],
    )


def test_npc_dialogue_guard_detects_self_name_with_action_particle():
    assert ws_mod._looks_like_npc_narration_leak(
        "教官将皮鞭卷在掌心，粗壮的指节捏得咯咯作响。",
        npc_name="教官",
        forbidden_names=["公会会长"],
    )


def test_npc_dialogue_guard_detects_name_fragment_typo_leak():
    assert ws_mod._looks_like_npc_narration_leak(
        "银牙·铜须连头都没抬，继续拨弄算盘珠子。",
        npc_name="莉莉丝·暗影",
        forbidden_names=["金牙·铜须"],
    )


def test_npc_dialogue_guard_detects_player_action_under_npc_label():
    assert ws_mod._looks_like_npc_narration_leak(
        "艾琳的指尖刚触到脚踝处锁链的搭扣，一个冰凉滑腻的东西突然贴上了她的大腿内侧。",
        npc_name="哥布林斥候",
        forbidden_names=["艾琳", "米拉"],
    )


def test_npc_dialogue_guard_detects_parenthesized_action_prefix():
    assert ws_mod._looks_like_npc_narration_leak(
        "（眯起眼）你刚才那句话，我可不能当没听见。",
        npc_name="酒馆老板娘",
        forbidden_names=["艾琳"],
    )


def test_npc_dialogue_guard_detects_silent_npc_narration_leak():
    assert ws_mod._looks_like_npc_narration_leak(
        "会长没有接话。她只是端着茶杯，目光像一柄钝刀。",
        npc_name="公会会长",
        forbidden_names=["教官", "艾琳"],
    )


def test_npc_dialogue_guard_detects_other_npc_quoted_line_inside_narration():
    assert ws_mod._looks_like_npc_narration_leak(
        "教官的手指在你的小腹上停留。他转向会长，用公事公办的语气说：“外层板甲固定良好。”",
        npc_name="公会会长",
        forbidden_names=["教官", "艾琳"],
    )


def test_npc_dialogue_guard_detects_first_person_action_prose():
    assert ws_mod._looks_like_npc_narration_leak(
        "我把空茶杯搁在桌面上，瓷底磕在橡木上发出一声脆响。你说够了没有？",
        npc_name="公会会长",
        forbidden_names=["教官", "艾琳"],
    )


def test_npc_dialogue_guard_detects_first_person_body_stage_direction():
    assert ws_mod._looks_like_npc_narration_leak(
        "我的手指在你下巴上停了一瞬。回答我，你还想装到什么时候？",
        npc_name="公会会长",
        forbidden_names=["教官", "艾琳"],
    )


def test_extract_direct_quote_dialogue_from_narrated_npc_line():
    assert (
        ws_mod._extract_direct_quote_dialogue(
            "瘸腿老鸦靠回椅背，咳了一声：“东边的林子别走。”"
        )
        == "东边的林子别走。"
    )


def test_parse_npc_json_strips_dialogue_outer_quotes():
    dialogue, state, nr = ws_mod._parse_npc_json(
        '{"dialogue":"“站到前面来。”","state":"","narration_request":null}',
        "公会会长",
    )

    assert dialogue == "站到前面来。"
    assert state == ""
    assert nr is None


def test_strip_leading_action_parenthetical_keeps_spoken_part():
    assert (
        ws_mod._strip_leading_action_parenthetical("（眯起眼）你刚才那句话，我听见了。")
        == "你刚才那句话，我听见了。"
    )


def test_parse_npc_json_strips_repeated_same_speaker_labels():
    dialogue, _state, _nr = ws_mod._parse_npc_json(
        '{"dialogue":"[伊莉丝]: 先坐下。\\n[伊莉丝]: 我会告诉你路。",'
        '"state":"","narration_request":null}',
        "伊莉丝",
    )

    assert dialogue == "先坐下。\n我会告诉你路。"
    assert "[伊莉丝]" not in dialogue


def test_extract_required_speaker_segments_from_mixed_output():
    assert (
        ws_mod._extract_required_speaker_segments(
            "[旁白]: 大厅安静下来。\n[公会会长]: 站到前面来。",
            "公会会长",
        )
        == "站到前面来。"
    )


def test_npc_dialogue_too_thin_rejects_bland_short_line():
    assert ws_mod._npc_dialogue_too_thin("站到前面来。既然想知道真相，我就让你们亲身体会。")


def test_npc_dialogue_too_thin_allows_deliberate_barked_command():
    assert not ws_mod._npc_dialogue_too_thin("跪下。")


def test_npc_dialogue_too_thin_accepts_rich_roleful_line():
    assert not ws_mod._npc_dialogue_too_thin(
        "站到前面来，别把眼神藏在头发后面。你想知道真相，可以，但公会从不白送答案。"
        "先让我看看你敢拿什么交换，钱、名声，还是你那点还没被人踩碎的骄傲？"
    )


def test_narration_request_is_hidden_from_npc_line():
    clean, requests = ws_mod._extract_narration_requests(
        "（擦剑）我在。[[旁白请求:会长把茶杯放回桌上，大厅安静下来。]]"
    )

    assert clean == "（擦剑）我在。"
    assert requests == ["会长把茶杯放回桌上，大厅安静下来。"]


def test_scene_image_characters_prefers_player_and_mentioned_npc():
    history = [
        SimpleNamespace(
            author_type="user",
            speaker_label="瑟琳娜·血藤",
            content="一把按住会长，压在身下",
        )
    ]

    assert ws_mod._scene_image_characters(
        history,
        member_names=["瑟琳娜·血藤"],
        npc_names=["公会会长", "教官"],
        look={"瑟琳娜·血藤": "red-haired knight", "公会会长": "guild master"},
    ) == ["瑟琳娜·血藤", "公会会长"]


def test_regional_scene_prompt_keeps_two_ref_prompt_concise():
    prompt = ws_mod._regional_scene_prompt(
        "两人站在哥特式蓝色彩窗大教堂里。",
        "STRICT LEFT CHARACTER ONLY: 1girl, white hair, STRICT RIGHT CHARACTER ONLY: 1girl, black hair",
        nsfw=False,
        left_identity="1girl, adult female, knight, white hair, purple eyes",
        right_identity="1girl, adult female, thief, black hair, golden eyes",
    )

    assert "exactly two characters total" in prompt
    assert "NTRMix pretty face recipe" in prompt
    assert "glossy pretty faces" in prompt
    assert "high-rarity NTRMix anime visual novel event CG" not in prompt
    assert "charming character moment" in prompt
    assert "standing close together" not in prompt
    assert "use the left reference image only for the left character" in prompt
    assert "use the right reference image only for the right character" in prompt
    assert "on the viewer-left side of the same scene: 1girl, adult female, knight" in prompt
    assert "on the viewer-right side of the same scene: 1girl, adult female, thief" in prompt
    assert "ornate gothic cathedral interior" in prompt


def test_regional_scene_prompt_supports_vertical_layout():
    assert ws_mod._scene_region_layout("两个人一上一下站在楼梯上。") == "vertical"

    prompt = ws_mod._regional_scene_prompt(
        "两个人一上一下站在哥特式楼梯上。",
        "STRICT UPPER CHARACTER ONLY: white hair, STRICT LOWER CHARACTER ONLY: black hair",
        nsfw=False,
        left_identity="1girl, adult female, knight, white hair",
        right_identity="1girl, adult female, thief, black hair",
        region_layout="vertical",
    )

    assert "close vertical top-and-bottom two-shot" in prompt
    assert "characters fill most of the image" in prompt
    assert "expressive eye contact" in prompt
    assert "on the upper area of the same scene: 1girl, adult female, knight" in prompt
    assert "on the lower area of the same scene: 1girl, adult female, thief" in prompt


def test_complex_scene_prompt_uses_freeform_layout_without_ref_instructions():
    assert ws_mod._scene_region_layout("两人近距离缠斗，镜头很近。") == "freeform"
    assert ws_mod._scene_region_layout("盗贼压在骑士身下，前景背景有层次。") == "freeform"
    assert ws_mod._scene_region_layout("两人左右站位对峙。") == "horizontal"

    prompt = ws_mod._regional_scene_prompt(
        "盗贼压在骑士身下，前景背景有层次。",
        "STRICT PRIMARY CHARACTER ONLY: white hair, STRICT SECONDARY CHARACTER ONLY: black hair",
        nsfw=False,
        left_identity="1girl, adult female, knight, white hair, purple eyes",
        right_identity="1girl, adult female, thief, black hair, golden eyes",
        region_layout="freeform",
        reference_guidance=False,
    )

    assert "natural complex two-character composition" in prompt
    assert "Japanese visual novel event CG" in prompt
    assert "background visible around the bodies but never dominating" in prompt
    assert "full-bleed edge-to-edge scene background" in prompt
    assert "no decorative frame" in prompt
    assert "no forced left-right lineup" in prompt
    assert "as the primary character in the same scene: 1girl, adult female, knight" in prompt
    assert "as the secondary character in the same scene: 1girl, adult female, thief" in prompt
    assert "use the left reference image only" not in prompt
    assert "preserve both described character identities" in prompt


def test_scene_action_prompt_keeps_chinese_grapple_and_dagger_clash():
    action = ws_mod._scene_action_prompt("盗贼近身压制骑士，剑与匕首交错。")

    assert "pins or grapples" in action
    assert "not a calm hug" in action
    assert "dagger-and-sword clash" in action


def test_nsfw_scene_action_prioritizes_intimacy_over_combat():
    action = ws_mod._nsfw_scene_action_prompt("成人双人场景。")

    assert "adult intimate event pose" in action
    assert "not combat choreography" in action
    assert "requested story action shown clearly" not in action


def test_nsfw_scene_action_understands_manual_intimate_chinese():
    action = ws_mod._nsfw_scene_action_prompt("会长扣弄小穴。")

    assert "manual stimulation" in action
    assert "main action" in action


def test_nsfw_scene_action_understands_straddling_grinding_chinese():
    action = ws_mod._nsfw_scene_action_prompt("会长骑在我身上蹭我的小穴。")

    assert "straddling on top" in action
    assert "above-and-below pose" in action
    assert "crotch rubbing is the main requested action" in action
    assert "manual stimulation" not in action
    assert ws_mod._scene_region_layout("会长骑在我身上蹭我的小穴。") == "freeform"


@pytest.mark.parametrize(
    "text",
    [
        "会长骑上来用下体贴着我的小穴磨蹭。",
        "会长跨坐在我腰上摩擦私处。",
        "会长压坐在我身上，下体贴着小穴。",
        "会长坐到我身上，用阴部慢慢蹭。",
    ],
)
def test_nsfw_scene_action_understands_straddling_synonyms(text: str):
    action = ws_mod._nsfw_scene_action_prompt(text)

    assert "straddling on top" in action
    assert "crotch rubbing is the main requested action" in action
    assert ws_mod._scene_region_layout(text) == "freeform"


def test_scene_plan_overlay_feeds_structured_director_fields():
    overlay = ws_mod._scene_plan_overlay(
        {
            "pose_relation": "one character straddling on top in an above-and-below pose",
            "core_action": "hips pressed together, grinding is the main action",
            "camera": "close medium shot, lower bodies visible enough to show pose",
            "must_include": ["straddling on top", "above-and-below pose"],
            "must_avoid": ["tea cup", "touching chin"],
        }
    )

    assert "Structured scene director plan" in overlay
    assert "straddling on top" in overlay
    assert "tea cup" in overlay


def test_scene_nsfw_detection_does_not_treat_wrist_grab_as_adult():
    assert ws_mod._requested_scene_nsfw({}, "教官扣住你的手腕。", []) is False
    assert ws_mod._requested_scene_nsfw({}, "会长扣弄小穴。", []) is True


def test_nsfw_identity_softening_removes_weapon_anchors():
    identity = ws_mod._nsfw_soft_identity_desc(
        "1girl, adult female, knight, silver-white hair, purple eyes, longsword, twin daggers, blue cape"
    )

    assert "silver-white hair" in identity
    assert "purple eyes" in identity
    assert "blue cape" in identity
    assert "longsword" not in identity
    assert "daggers" not in identity
    assert "no raised weapon" in identity


def test_image_nsfw_switch_overrides_text_auto_detection():
    text = "玩家输入：这是 nsfw 场景"

    assert ws_mod._requested_scene_nsfw({}, text, []) is True
    assert ws_mod._requested_scene_nsfw({"nsfw": False}, text, []) is False
    assert ws_mod._requested_scene_nsfw({"nsfw": True}, "普通战斗场景", []) is True


def test_regional_scene_prompt_adds_nsfw_prefix_only_when_enabled():
    sfw_prompt = ws_mod._regional_scene_prompt(
        "普通双人战斗。",
        "",
        nsfw=False,
        left_identity="1girl, knight",
        right_identity="1girl, rogue",
    )
    nsfw_prompt = ws_mod._regional_scene_prompt(
        "成人双人场景。",
        "",
        nsfw=True,
        left_identity="1girl, knight",
        right_identity="1girl, rogue",
    )

    assert sfw_prompt.startswith("sfw,")
    assert not sfw_prompt.startswith("nsfw")
    assert nsfw_prompt.startswith("nsfw, explicit, adult")
    assert "adult intimate event pose" in nsfw_prompt
    assert "private erotic visual novel CG mood" in nsfw_prompt
    assert "flushed faces" in nsfw_prompt
    assert "weapons lowered or out of focus" in nsfw_prompt
    assert "not a normal duel pose" in nsfw_prompt
    assert "adult intimacy is the main event, not swordplay" in nsfw_prompt
    assert "disheveled outfits" in nsfw_prompt
    assert "signature weapons optional and not blocking the intimate pose" in nsfw_prompt
    assert "adult intimate event pose" not in sfw_prompt


def test_scene_side_characters_infers_role_based_left_right_order():
    scene_chars = ["艾莉希亚", "米拉"]
    look = {
        "艾莉希亚": "1girl, knight, silver-white hair, purple eyes",
        "米拉": "1girl, thief, black hair, golden eyes",
    }

    assert ws_mod._scene_side_characters(
        "黑发金瞳盗贼从左前方扑向目标，银白发紫瞳骑士在右后方举剑格挡。",
        scene_chars,
        look,
    ) == ["米拉", "艾莉希亚"]
    assert ws_mod._scene_side_characters("两人近距离缠斗。", scene_chars, look) == []


def test_identity_repair_masks_cover_character_then_eyes(tmp_path, monkeypatch):
    from PIL import Image

    source = tmp_path / "scene.png"
    Image.new("RGB", (1000, 700), (20, 20, 20)).save(source)
    monkeypatch.setattr(ws_mod.image_media, "MEDIA_DIR", tmp_path)

    left_character = ws_mod._character_region_mask(source, "left")
    right_character = ws_mod._character_region_mask(source, "right")
    left_eyes = ws_mod._eye_region_mask(source, "left")
    right_eyes = ws_mod._eye_region_mask(source, "right")

    assert left_character is not None
    assert right_character is not None
    assert left_eyes is not None
    assert right_eyes is not None
    with Image.open(left_character).convert("L") as mask:
        assert mask.getpixel((250, 280)) > 0
        assert mask.getpixel((850, 280)) == 0
    with Image.open(right_character).convert("L") as mask:
        assert mask.getpixel((750, 280)) > 0
        assert mask.getpixel((150, 280)) == 0
    with Image.open(left_eyes).convert("L") as mask:
        assert mask.getpixel((250, 150)) > 0
    with Image.open(right_eyes).convert("L") as mask:
        assert mask.getpixel((750, 150)) > 0


def test_npc_prompt_forbids_narrator_label():
    room = type("Room", (), {"name": "测试房间", "world_card": None})()
    npc = type(
        "Npc",
        (),
        {
            "name": "酒馆老板娘",
            "persona": "消息灵通",
            "appearance": "",
        },
    )()
    prompt = build_npc_system_prompt(room, [], npc, ["公会会长"])

    assert "narration_request" in prompt
    assert "只输出一行 JSON" in prompt
    assert '"dialogue"' in prompt
    assert '"state"' in prompt
    assert "不要写自己的动作、神态、心理描写" in prompt


def test_npc_prompt_requires_roleful_expressive_dialogue():
    room = type("Room", (), {"name": "测试房间", "world_card": "ksim"})()
    npc = type(
        "Npc",
        (),
        {
            "name": "公会会长",
            "persona": "傲慢、擅长权力游戏的会长",
            "appearance": "",
        },
    )()

    prompt = build_npc_system_prompt(room, [], npc, ["教官"])

    assert "表演优先级" in prompt
    assert "私欲" in prompt
    assert "职业立场" in prompt
    assert "3-6 句" in prompt
    assert "不要为了安全只写一句短句" in prompt


def test_history_to_messages_skips_system_and_image_noise():
    history = [
        SimpleNamespace(author_type="system", speaker_label="系统", content="🧠 NPC内心｜想发言：否"),
        SimpleNamespace(author_type="image", speaker_label="场景图", content="/media/generated/x.png"),
        SimpleNamespace(author_type="user", speaker_label="艾莉西亚", content="继续。"),
        SimpleNamespace(author_type="ai", speaker_label="公会会长", content="站到前面来。"),
    ]

    messages = history_to_messages("system prompt", history)

    assert messages == [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "[艾莉西亚]: 继续。"},
        {"role": "assistant", "content": "站到前面来。"},
    ]
