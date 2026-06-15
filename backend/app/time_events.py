# ruff: noqa: E501 — event text strings are naturally long Chinese

"""Time-driven event system: scene + time-slot → random encounter/find/nothing.

Each time the room clock advances, _trigger_time_events rolls on a weighted table
keyed by (current_scene, time_phase). Hit events broadcast to the room so the AI
can narrate the outcome naturally. Encounters also introduce the NPC on the fly.
"""

from __future__ import annotations

import random
from typing import Any

from .models import NpcCard

# Weighted event table. Key = "scene_name" or "scene_name@time_phase".
# Where time_phase matches TIME_PHASES: 清晨/上午/正午/下午/黄昏/夜晚/深夜.
# "scene_name@any" matches any time; "scene_name@夜晚" only matches that phase.
# Events with higher weight are more likely to be picked.
_EVENT_TABLE: dict[str, list[dict[str, Any]]] = {
    # ── 森林 ──
    "森林@any": [
        {
            "type": "encounter",
            "npc_name": "哥布林",
            "npc_persona": "森林里成群出没的哥布林，矮小猥琐、欺软怕硬。以袭击落单女冒险者为乐。",
            "weight": 40,
            "text": "树丛中传来窸窣声响和粗鄙的窃笑声——有东西在盯着你。",
        },
        {
            "type": "encounter",
            "npc_name": "兽人",
            "npc_persona": "高大凶猛的兽人战士，视强奸为战利品和荣誉的象征。",
            "weight": 20,
            "text": "沉重的脚步声由远及近，地面都在微微震动——是兽人巡逻队。",
        },
        {
            "type": "find",
            "item": "药草",
            "quantity": 1,
            "weight": 15,
            "text": "你在一棵老树根下发现了一丛散发着清香的药草。",
        },
        {
            "type": "find",
            "item": "野兽的皮毛",
            "quantity": 1,
            "weight": 10,
            "text": "路边有一具被啃食过的野兽尸体，皮毛还算完整，可以剥下来卖钱。",
        },
        {"type": "nothing", "weight": 15},
    ],
    "森林@夜晚": [
        {
            "type": "encounter",
            "npc_name": "哥布林",
            "npc_persona": "夜晚的哥布林更加大胆残暴，成群结队地狩猎落单的猎物。",
            "weight": 50,
            "text": "黑暗中亮起十几双红色眼睛，伴随着淫邪的笑声——哥布林群从四面八方围了上来！",
        },
        {
            "type": "encounter",
            "npc_name": "触手怪",
            "npc_persona": "潜伏在暗处的触手怪物，专门捕捉独行的女冒险者拖入巢穴。",
            "weight": 25,
            "text": "一根湿滑黏腻的触手无声无息地从暗处卷向你的脚踝。",
        },
        {"type": "nothing", "weight": 25},
    ],
    # ── 洞窟 ──
    "洞窟@any": [
        {
            "type": "encounter",
            "npc_name": "史莱姆",
            "npc_persona": "洞窟深处的粘液怪物，体表分泌强力催情粘液。",
            "weight": 35,
            "text": "前方的通道被一团半透明的果冻状物体堵住了——是史莱姆。空气中弥漫着一股甜腻的气味。",
        },
        {
            "type": "encounter",
            "npc_name": "哥布林法师",
            "npc_persona": "哥布林族群中的施法者，用催眠魔法玩弄猎物。",
            "weight": 25,
            "text": "洞穴深处传来古怪的吟唱声，空气中泛起扭曲的波纹——哥布林法师在这里设下了埋伏。",
        },
        {
            "type": "encounter",
            "npc_name": "触手怪",
            "npc_persona": "洞窟深处的触手怪物，触手分泌麻痹毒液和催情体液。",
            "weight": 20,
            "text": "你踩到了什么湿滑的东西——低头一看，无数根触手正从地面的缝隙中涌出。",
        },
        {
            "type": "find",
            "item": "矿石",
            "quantity": 2,
            "weight": 10,
            "text": "洞壁上裸露着品质不错的矿石，敲几块带回去能卖个好价钱。",
        },
        {"type": "nothing", "weight": 10},
    ],
    # ── 城镇 ──
    "城镇@any": [
        {
            "type": "social",
            "text": "街上的行人来来往往，几个冒险者正在公告栏前讨论着什么。",
            "weight": 50,
        },
        {
            "type": "social",
            "npc_name": "借贷商人",
            "npc_persona": "放高利贷的商人，眼睛总是在女冒险者的身上和钱袋之间来回扫视。",
            "weight": 20,
            "text": "路边的阴影里，一个油腻的声音叫住了你——是借贷商人，他笑眯眯地打量着你。",
        },
        {
            "type": "find",
            "item": "零钱袋",
            "quantity": 1,
            "weight": 10,
            "text": "地上有一个被遗忘的零钱袋，打开一看，里面有几枚银币。",
        },
        {"type": "nothing", "weight": 20},
    ],
    "城镇@夜晚": [
        {
            "type": "social",
            "text": "夜晚的城镇褪去了白天的喧嚣，酒馆的灯光和笑闹声从街角飘来。",
            "weight": 40,
        },
        {
            "type": "encounter",
            "npc_name": "酒馆老板娘",
            "npc_persona": "夜晚的酒馆老板娘更加放得开，眼神在昏暗的灯光下晦暗不明。",
            "weight": 30,
            "text": "酒馆的门半掩着，老板娘靠在门框上，朝你招了招手——她似乎有话要单独对你说。",
        },
        {"type": "nothing", "weight": 30},
    ],
    # ── 酒馆 ──
    "酒馆@any": [
        {
            "type": "social",
            "text": "酒馆里人声鼎沸，麦酒和汗水的味道混在一起。有人在角落里低声交谈着什么。",
            "weight": 60,
        },
        {
            "type": "social",
            "npc_name": "酒馆老板娘",
            "npc_persona": "消息灵通的酒馆老板娘，眼睛和耳朵从不放过任何有价值的信息。",
            "weight": 30,
            "text": "老板娘擦着杯子走过来，压低声音说有好消息——或者至少是好买卖。",
        },
        {"type": "nothing", "weight": 10},
    ],
    # ── 青楼街 ──
    "青楼街@夜晚": [
        {
            "type": "social",
            "npc_name": "娼馆老板",
            "npc_persona": "青楼街的女老板，永远挂着亲切的微笑计算你的价值。",
            "weight": 40,
            "text": "灯笼映照的青石路上，娼馆老板的扇子轻轻搭在了你的肩头。",
        },
        {
            "type": "social",
            "text": "街道两旁传来暧昧的笑声和细碎的呻吟，几家娼馆的灯笼在夜风中摇曳。",
            "weight": 40,
        },
        {"type": "nothing", "weight": 20},
    ],
    # ── 冒险者公会 ──
    "冒险者公会@any": [
        {
            "type": "social",
            "text": "公会大厅里一如既往地忙碌，有几个陌生面孔的冒险者正在柜台前填写委托单。",
            "weight": 60,
        },
        {
            "type": "social",
            "text": "大厅角落的桌边，两个冒险者正在低声争执着什么——似乎与某张委托单有关。",
            "weight": 30,
        },
        {"type": "nothing", "weight": 10},
    ],
}

# Global cooldown: once an encounter NPC is introduced, don't re-introduce
# the same one within this many time steps.
_ENCOUNTER_COOLDOWN: dict[str, int] = {}
_COOLDOWN_TICKS = 7  # ~1 day before same NPC can re-encounter


def roll_time_event(scene: str, time_phase: str) -> dict[str, Any] | None:
    """Roll the weighted event table for (scene, time_phase). Returns event or None."""
    candidates: list[dict[str, Any]] = []

    # Collect matching entries from specific and generic keys
    for key, events in _EVENT_TABLE.items():
        if "@" in key:
            s, t = key.split("@", 1)
            if s == scene and (t == time_phase or t == "any"):
                candidates.extend(events)
        elif key == scene:
            candidates.extend(events)

    if not candidates:
        return None

    total_weight = sum(e.get("weight", 1) for e in candidates)
    roll = random.uniform(0, total_weight)
    cumulative = 0
    for e in candidates:
        cumulative += e.get("weight", 1)
        if roll <= cumulative:
            return e
    return candidates[-1]


def pick_event_encounter_npc(event: dict[str, Any], room_id: int) -> NpcCard | None:
    """Create a temporary NpcCard for an encounter event, respecting cooldown."""
    npc_name = event.get("npc_name")
    if not npc_name:
        return None
    cooldown_key = f"{room_id}:{npc_name}"
    if _ENCOUNTER_COOLDOWN.get(cooldown_key, 0) > 0:
        return None
    _ENCOUNTER_COOLDOWN[cooldown_key] = _COOLDOWN_TICKS
    return NpcCard(
        room_id=room_id,
        name=npc_name,
        persona=event.get("npc_persona", ""),
        active=True,
        created_by_ai=True,
    )


def tick_cooldowns() -> None:
    """Decrement all encounter cooldowns by 1."""
    for key in list(_ENCOUNTER_COOLDOWN):
        _ENCOUNTER_COOLDOWN[key] -= 1
        if _ENCOUNTER_COOLDOWN[key] <= 0:
            del _ENCOUNTER_COOLDOWN[key]


def load_event_table(data: list[dict[str, Any]] | None = None) -> None:
    """Replace the event table (for testing or world-card overrides)."""
    global _EVENT_TABLE
    if data is not None:
        _EVENT_TABLE.clear()
        for entry in data:
            _EVENT_TABLE[entry["key"]] = entry["events"]
