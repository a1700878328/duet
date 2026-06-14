"""据世界卡 AI 生成「玩家角色」候选草稿（强制选角 onboarding）。

与 npc_gen 平行：npc_gen 生成 NPC 名册，本模块生成供玩家本人挑选的
PLAYER 角色草稿（含外貌 Danbooru 标签 + 中文声音设计），不持久化——
选中后由前端走既有 PUT /me-card 写回。
"""

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


async def generate_character_options(
    world_card: str | None,
    hint: str | None,
    count: int,
    brain: BrainProvider | None = None,
) -> list[dict[str, Any]]:
    """生成 count 个玩家角色草稿 dict（name/persona/appearance/voice_id）。

    若给定 ``hint``（玩家自我描述），把它扩写成 ONE 个完整角色（count 强制为 1）。
    """
    brain = brain or default_provider()
    world = _WORLDS.get(world_card or "", world_card or "一个通用奇幻角色扮演世界")

    if hint:
        count = 1
        task = (
            "玩家提供了一句自我描述，请把它扩写成 1 个完整、可直接游玩的玩家角色，"
            f"忠实贴合该描述。玩家的自我描述：{hint}"
        )
    else:
        task = f"生成 {count} 个风格各异、适合玩家代入的玩家角色，差异要明显。"

    system = (
        "你是角色扮演角色设计师。为玩家本人设计可代入的主角角色卡，"
        "扎根于给定的世界设定。严格只输出 JSON 数组，不要任何多余文字或解释。"
        "每个元素形如："
        '{"name":"中文名","persona":"一句话身份+性格+说话风格",'
        '"appearance":"英文 Danbooru 外貌标签",'
        '"voice_id":"一句话中文声音设计描述：性别+年龄+音色+语气，'
        '如 沙哑低沉的中年男声带着江湖气 / 清脆娇媚的少女声"}。'
        "appearance 必须是英文 Danbooru 标签且贴合角色；"
        "voice_id 要贴合角色，每个角色的声音各不相同。"
    )
    user = f"世界设定：{world}\n{task}"
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
