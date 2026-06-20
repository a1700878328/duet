"""据世界卡 AI 生成 NPC 角色卡名册（Phase B）—— 优先生成可爱的二次元角色。"""

from typing import Any

from .agent_sdk import agent

_WORLDS = {
    "ksim": "《女骑士模拟器》——中世纪奇幻，含哥布林、兽人、史莱姆、魅魔、触手怪、"
    "酒馆、冒险者公会、娼馆、放贷商等元素，基调成人黑暗奇幻。",
}

_FALLBACK_NPCS = [
    {
        "name": "露西亚",
        "persona": "边境酒馆的情报贩子，笑容甜美但心思很深，习惯用玩笑试探客人的底线。",
        "appearance": "adult woman, auburn hair, green eyes, tavern waitress outfit, sly smile, leather corset",
        "voice_id": "轻快狡黠的年轻女性声线，尾音上扬，像随时藏着一个秘密",
    },
    {
        "name": "雷蒙",
        "persona": "退役佣兵兼护卫，沉默寡言，讲究实际利益，开口时短促直接。",
        "appearance": "adult man, short dark hair, stubble, scarred face, worn chainmail, broad shoulders",
        "voice_id": "低沉沙哑的成年男性声线，语速慢，带疲惫的金属质感",
    },
    {
        "name": "伊芙",
        "persona": "流浪炼金术士，对魔物生态异常着迷，说话温柔却经常说出危险提案。",
        "appearance": "adult woman, silver bob hair, blue eyes, alchemist coat, glass vials, curious expression",
        "voice_id": "柔和理性的女性声线，吐字清晰，偶尔带兴奋的轻笑",
    },
    {
        "name": "黑鸦",
        "persona": "戴兜帽的地下信使，消息灵通但从不白给情报，说话像在讨价还价。",
        "appearance": "adult androgynous figure, black hooded cloak, amber eyes, messenger satchel, dagger belt",
        "voice_id": "中性偏低的神秘声线，压低嗓音，句尾干脆",
    },
]


def _clean(d: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(d, dict) or not d.get("name"):
        return None
    return {
        "name": str(d["name"])[:128],
        "persona": str(d.get("persona", ""))[:4000],
        "appearance": str(d["appearance"])[:2000] if d.get("appearance") else None,
        "voice_id": str(d["voice_id"])[:200] if d.get("voice_id") else None,
    }


def _fallback_cards(existing_names: list[str], count: int) -> list[dict[str, Any]]:
    existing = {name.strip() for name in existing_names if name}
    out: list[dict[str, Any]] = []
    index = 1
    while len(out) < count:
        base = _FALLBACK_NPCS[(index - 1) % len(_FALLBACK_NPCS)]
        card = dict(base)
        if card["name"] in existing or any(c["name"] == card["name"] for c in out):
            card["name"] = f"{base['name']}{index}"
        out.append(card)
        index += 1
    return out


async def generate_npcs(
    world_card: str | None,
    hint: str | None,
    existing_names: list[str],
    count: int,
) -> list[dict[str, Any]]:
    """生成 count 个可爱二次元 NPC 卡 dict（name/persona/appearance/voice_id）。

    优先产出可爱女性角色（80%+），除非 hint 明确要求其他类型。
    appearance 采用 Danbooru 风格的英文 tag 串，方便直接用于生图 prompt。
    """
    world = _WORLDS.get(world_card or "", world_card or "一个通用奇幻角色扮演世界")
    avoid = (
        "，避免与这些已有 NPC 重名：" + "、".join(existing_names)
        if existing_names
        else ""
    )
    extra = f"\n额外要求：{hint}" if hint else ""
    out: list[dict[str, Any]] = []
    prompts = [
        f"世界设定：{world}{avoid}{extra}\n生成 {count} 个 NPC。",
        (
            f"世界设定：{world}{avoid}{extra}\n"
            f"重新生成 {count} 个 NPC。必须输出合法 JSON 数组；"
            "每个元素都必须包含 name/persona/appearance/voice_id 四个字符串字段。"
        ),
    ]
    for user in prompts:
        result = await agent.run("npc_design", input=user)
        if not isinstance(result, list):
            continue
        for d in result:
            cleaned = _clean(d)
            if cleaned and cleaned["name"] not in {c["name"] for c in out}:
                out.append(cleaned)
            if len(out) >= count:
                return out
    if len(out) < count:
        out.extend(
            _fallback_cards(
                [*existing_names, *[card["name"] for card in out]],
                count - len(out),
            )
        )
    return out[:count]
