"""据世界卡 AI 生成 NPC 角色卡名册（Phase B）。"""

import json
from typing import Any

from .brain import BrainProvider, default_provider

_WORLDS = {
    "ksim": "《女骑士模拟器》——中世纪奇幻，含哥布林、兽人、史莱姆、魅魔、触手怪、"
    "酒馆、冒险者公会、娼馆、放贷商等元素，基调成人黑暗奇幻。",
}


def _parse_json_array(raw: str) -> list[Any]:
    s = raw.strip()
    if s.startswith("```"):
        s = s.strip("`")
        nl = s.find("\n")
        if nl != -1 and s[:nl].strip().lower() in {"json", ""}:
            s = s[nl + 1 :]
    a, b = s.find("["), s.rfind("]")
    if a != -1 and b != -1 and b > a:
        s = s[a : b + 1]
    try:
        data = json.loads(s)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


async def generate_npcs(
    world_card: str | None,
    hint: str | None,
    existing_names: list[str],
    count: int,
    brain: BrainProvider | None = None,
) -> list[dict[str, Any]]:
    """生成 count 个 NPC 卡 dict（name/persona/appearance/voice_id）。"""
    brain = brain or default_provider()
    world = _WORLDS.get(world_card or "", world_card or "一个通用奇幻角色扮演世界")
    avoid = (
        "，避免与这些已有 NPC 重名：" + "、".join(existing_names)
        if existing_names
        else ""
    )
    extra = f"\n额外要求：{hint}" if hint else ""
    system = (
        "你是角色扮演 NPC 设计师。根据世界设定生成若干风格各异、适合互动的 NPC 角色卡。"
        "严格只输出 JSON 数组，不要任何多余文字或解释。每个元素形如："
        '{"name":"中文名","persona":"一句话身份+性格+说话风格",'
        '"appearance":"英文 Danbooru 外貌标签",'
        '"voice_id":"一句话中文声音设计描述：性别+年龄+音色+语气，'
        '如 沙哑低沉的中年男声带着江湖气 / 清脆娇媚的少女声"}。'
        "voice_id 要贴合该角色，每个 NPC 的声音各不相同。"
    )
    user = f"世界设定：{world}{avoid}{extra}\n生成 {count} 个 NPC。"
    raw = (
        await brain.complete(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
        )
    ).strip()

    out: list[dict[str, Any]] = []
    for d in _parse_json_array(raw)[:count]:
        if isinstance(d, dict) and d.get("name"):
            out.append(
                {
                    "name": str(d["name"])[:128],
                    "persona": str(d.get("persona", ""))[:4000],
                    "appearance": str(d["appearance"])[:512]
                    if d.get("appearance")
                    else None,
                    "voice_id": str(d["voice_id"])[:64]
                    if d.get("voice_id")
                    else None,
                }
            )
    return out
