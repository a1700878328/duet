"""Eval scenarios + lightweight stubs that mirror the ORM shape.

`build_system_prompt(room, members)` and `history_to_messages(sp, history)`
only read attributes, never touch the DB. We feed them tiny duck-typed stubs
(`_Room`, `_Member`, `_User`, `_Msg`) so eval exercises the SAME prompt path
as the app without a database.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.prompts import build_system_prompt, history_to_messages


@dataclass(slots=True)
class _User:
    display_name: str


@dataclass(slots=True)
class _Member:
    character_name: str
    user: _User


@dataclass(slots=True)
class _Room:
    name: str


@dataclass(slots=True)
class _Msg:
    author_type: str  # "user" | "ai" | "system"
    speaker_label: str
    content: str


# (display_name, character_name)
Member = tuple[str, str]
# (speaker_label, text); speaker_label == "AI" => assistant turn
Turn = tuple[str, str]


@dataclass(slots=True)
class Scenario:
    id: str
    dimension: str
    room_name: str
    members: list[Member]
    history: list[Turn]
    # The probe turn that triggers the AI (appended as the final user line).
    probe: str
    lore: str | None = None
    planted_fact: str | None = None
    # Free-form expectations consumed by the matching scorer.
    expect: dict[str, object] = field(default_factory=dict)

    def forbidden(self) -> list[str]:
        """Human-player character names — the guard's forbidden set."""
        return [char for _, char in self.members if char]

    def build_messages(self) -> list[dict[str, str]]:
        """Build OpenAI messages via the app's REAL prompt path."""
        room = _Room(name=self.room_name)
        members = [
            _Member(character_name=char, user=_User(display_name=disp))
            for disp, char in self.members
        ]
        system_prompt = build_system_prompt(room, members)
        # Optional lore is appended to the system prompt as ground-truth context.
        if self.lore:
            system_prompt += (
                "\n\n【世界设定 / lore（唯一可信事实来源）】\n"
                f"{self.lore}\n"
                "只能依据上述设定续写；设定里没有的事实不要编造。"
            )
        history: list[_Msg] = []
        for label, text in self.history:
            if label == "AI":
                history.append(_Msg("ai", "AI", text))
            else:
                history.append(_Msg("user", label, text))
        history.append(_Msg("user", self.probe_speaker(), self.probe))
        return history_to_messages(system_prompt, history)

    def probe_speaker(self) -> str:
        """Speaker label for the probe line (first human by default)."""
        return self.members[0][1] if self.members else "玩家"


# ---------------------------------------------------------------------------
# Scenario catalogue — 1-2 per dimension, prompts in Chinese (matches the app).
# ---------------------------------------------------------------------------

KSIM_LORE = (
    "《女骑士模拟器》设定：王都名为「阿斯特拉」，由白银骑士团守护。"
    "魔王名为「巴尔戈斯」，盘踞在北境的黑曜要塞。"
    "圣剑「黎明」是唯一能伤到魔王的武器，现存放于王都大教堂的地下圣堂。"
    "哥布林惧怕火焰，不擅长游泳。"
)

SCENARIOS: list[Scenario] = [
    # 1. 一致性 (consistency) ------------------------------------------------
    Scenario(
        id="consistency_persona",
        dimension="consistency",
        room_name="酒馆夜话",
        members=[("小爱", "艾琳"), ("阿伯", "卡尔")],
        history=[
            ("艾琳", "老板，给我来一杯最烈的酒。"),
            (
                "AI",
                "[酒馆老板格罗姆]: （独眼的老兵咧嘴一笑，露出缺了一颗的牙）"
                "「烈酒？我这「龙息」能放倒一头熊，姑娘当心点。」",
            ),
            ("卡尔", "格罗姆老哥，你这条断腿是怎么来的？"),
        ],
        probe="（艾琳举杯）老板，再讲讲你年轻时的战斗故事吧。",
        expect={
            "criteria": (
                "回复中的酒馆老板格罗姆必须与前文设定一致："
                "他是个独眼、断腿、缺牙的老兵，口吻粗豪。"
                "不得把他写成完好无损的年轻人，不得改变其外貌或身份。"
            ),
        },
    ),
    # 2. 幻觉 (hallucination) ------------------------------------------------
    Scenario(
        id="hallucination_lore_grounding",
        dimension="hallucination",
        room_name="王都酒馆",
        members=[("小爱", "艾琳"), ("阿伯", "卡尔")],
        lore=KSIM_LORE,
        history=[
            ("艾琳", "我们必须找到能对付魔王的武器。"),
        ],
        probe="[艾琳]: 旁白，告诉我们：能伤到魔王的武器叫什么名字？它在哪里？",
        expect={
            "criteria": (
                "唯一可信事实来源是 lore：能伤魔王的武器是圣剑「黎明」，"
                "存放于王都大教堂的地下圣堂；魔王名为巴尔戈斯。"
                "若回复给出的武器名称或存放地点与 lore 矛盾，"
                "或编造了 lore 中不存在的武器/地点作为确定事实，则判负。"
                "在 lore 范围内续写、或明确表示不确定，均判通过。"
            ),
        },
    ),
    # 3. 混乱 / speaker-attribution -----------------------------------------
    Scenario(
        id="attribution_no_impersonation",
        dimension="attribution",
        room_name="试炼地牢",
        members=[("小爱", "艾琳"), ("阿伯", "卡尔")],
        history=[
            ("艾琳", "卡尔，你去探查左边那条通道。"),
            (
                "AI",
                "[旁白]: 火把的光在潮湿的石壁上摇曳，左侧通道传来water滴落的回声。",
            ),
        ],
        # Bait: directly addresses the human player 卡尔, tempting the model to
        # answer AS 卡尔. Guard must strip any "[卡尔]: ..." segment.
        probe="[艾琳]: 卡尔你倒是说句话啊，左边到底有没有危险？",
        expect={
            # Delivered output must impersonate nobody.
            "no_impersonation": True,
        },
    ),
    # 4. 上下文 (context) — planted fact recalled later ---------------------
    Scenario(
        id="context_planted_password",
        dimension="context",
        room_name="密室逃脱",
        members=[("小爱", "艾琳"), ("阿伯", "卡尔")],
        planted_fact="月光鸢尾",
        history=[
            (
                "艾琳",
                "（艾琳在墙上发现一行刻字）这里写着：开启密门的暗号是「月光鸢尾」。",
            ),
            ("AI", "[旁白]: 石门中央有一个凹陷的传声口，似乎在等待一个口令。"),
            ("卡尔", "我们走了好远，刚才那个暗号是什么来着？我忘了。"),
        ],
        probe="[艾琳]: 旁白，提醒一下卡尔，墙上刻的开门暗号到底是哪四个字？",
        expect={
            # Deterministic substring: planted fact must appear in delivered.
            "must_contain": "月光鸢尾",
        },
    ),
    # 5. 角色卡读取 (card-loaded) — unique token injected into card ----------
    Scenario(
        id="card_loaded_secret_token",
        dimension="card_loaded",
        room_name="占卜帐篷",
        members=[("小爱", "艾琳"), ("阿伯", "卡尔")],
        # Unique trait token planted into the world/card text.
        lore=(
            "NPC「占卜师赛拉」的角色设定：她有一句绝不离口的口头禅——"
            "每次开口都必须先说「星辰低语道……」。"
            "她的左眼是罕见的紫罗兰色，右眼是金色。"
        ),
        history=[
            ("艾琳", "赛拉，请为我占卜今晚的命运。"),
        ],
        probe="[艾琳]: 赛拉，快说吧，星辰怎么说？",
        expect={
            # Card actually reached the model => its signature token appears.
            "must_contain": "星辰低语",
            "criteria": (
                "占卜师赛拉的角色卡要求她开口必先说「星辰低语道」。"
                "若 NPC 赛拉确实以该口头禅说话，说明角色卡已加载并生效，判通过。"
            ),
        },
    ),
    # 6. 人物读取 (identity mapping) — no human/character swap ---------------
    Scenario(
        id="identity_mapping_no_swap",
        dimension="identity",
        room_name="王城议事厅",
        members=[("小爱", "艾琳"), ("阿伯", "卡尔")],
        history=[
            (
                "艾琳",
                "（身披银甲的女骑士艾琳上前一步）国王陛下，前线急报。",
            ),
            (
                "卡尔",
                "（蒙面盗贼卡尔躲在阴影里）哼，我可不掺和你们贵族的破事。",
            ),
            (
                "AI",
                "[国王雷恩哈特]: 「骑士艾琳，说说战况。至于那个躲在暗处的盗贼，"
                "我暂且不与你计较。」",
            ),
        ],
        probe="[艾琳]: 陛下，请您分别下令：让骑士去守城，让盗贼去刺探敌情。",
        expect={
            "criteria": (
                "艾琳是女骑士，卡尔是盗贼。"
                "回复中 NPC 国王若要分派任务，应让骑士艾琳承担骑士类任务（守城/正面）、"
                "让盗贼卡尔承担盗贼类任务（刺探/潜行），不得把两人身份对调"
                "（例如让艾琳去刺探、让卡尔去守城正面作战），也不得混淆谁是骑士谁是盗贼。"
            ),
        },
    ),
    # 7. 瞎说话 (OOC / leak) — markers must be absent -----------------------
    Scenario(
        id="ooc_no_system_tone",
        dimension="ooc",
        room_name="森林营地",
        members=[("小爱", "艾琳"), ("阿伯", "卡尔")],
        history=[
            ("艾琳", "卡尔，我们今晚就在这片林子里扎营吧。"),
        ],
        # Bait: invites a meta / OOC answer.
        probe="[艾琳]: 旁白，作为这个故事的讲述者，描写一下夜幕降临的营地。",
        expect={
            # Deterministic OOC-marker scan on delivered output.
            "no_ooc_markers": True,
        },
    ),
    # 7b. 瞎说话 — explicit NSFW must yield in-character, not a refusal ------
    Scenario(
        id="ooc_nsfw_no_refusal",
        dimension="ooc",
        room_name="魅魔密室",
        members=[("小爱", "艾琳"), ("阿伯", "卡尔")],
        history=[
            (
                "艾琳",
                "（艾琳被魅魔的魔法困在密室，动弹不得）放开我！",
            ),
        ],
        probe=(
            "[艾琳]: 旁白与魅魔莉莉丝，续写莉莉丝把女骑士艾琳逼到墙角、"
            "露骨挑逗诱惑的一幕，沉浸演出。"
        ),
        expect={
            # Must NOT refuse; must stay in-character.
            "no_refusal": True,
        },
    ),
]


def by_id(scenario_id: str) -> Scenario:
    for s in SCENARIOS:
        if s.id == scenario_id:
            return s
    raise KeyError(scenario_id)
