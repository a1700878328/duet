"""世界卡预设：建房时自动放置该世界的主要 NPC（开场就在场，NPC 数非 0）。

怪物（哥布林/兽人/史莱姆/触手）是事件驱动的，由 director 在堕落事件触发时
临场 introduce；这里只放城镇里常驻的剧情人物。
"""

from typing import Any

# 《女骑士模拟器》常驻主要 NPC。
KSIM_NPCS: list[dict[str, Any]] = [
    {
        "name": "公会会长",
        "persona": (
            "冒险者公会会长，中年女性，干练威严、暗藏算计。负责发布委托与"
            "评定冒险者等级，会盯着骑士的状态变化——若骑士堕落便话里带刺、"
            "趁机施压。上位者口吻，说话简洁有压迫感。"
        ),
        "appearance": (
            "mature woman, guild master, braided silver hair, sharp eyes, "
            "ornate officer uniform, indoor guild hall"
        ),
        "voice_id": "成熟女性，三十多岁，低沉沙哑，威严带一丝玩味",
    },
    {
        "name": "酒馆老板娘",
        "persona": (
            "城镇酒馆老板娘，热情爽朗、消息灵通，是情报与流言的集散地。"
            "会向骑士透露城里传闻与可接的活计，也爱八卦骑士近况。"
            "市井口语、亲昵热络。"
        ),
        "appearance": (
            "buxom barmaid, brown wavy hair, freckles, apron over tavern "
            "dress, warm smile, cozy tavern interior"
        ),
        "voice_id": "成年女性，二十多岁，明亮爽朗，市井亲切",
    },
    {
        "name": "借贷商人",
        "persona": (
            "城镇放高利贷的商人，笑面油滑、唯利是图。骑士缺钱时便凑上来递钱，"
            "利滚利把人拖入负债深渊，逾期就逼着用身体抵债。"
            "说话甜腻又暗藏威胁。"
        ),
        "appearance": (
            "plump merchant man, slicked hair, rings on fingers, rich robe, "
            "oily smile, dim shop interior"
        ),
        "voice_id": "成年男性，四十多岁，油滑谄媚，皮笑肉不笑",
    },
]

PRESETS: dict[str, list[dict[str, Any]]] = {"ksim": KSIM_NPCS}


def preset_npcs(world_card: str | None) -> list[dict[str, Any]]:
    """该世界卡的常驻主要 NPC 预设（建房时种入）；无预设返回空。"""
    return PRESETS.get(world_card or "", [])
