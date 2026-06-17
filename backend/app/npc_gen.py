"""据世界卡 AI 生成 NPC 角色卡名册（Phase B）—— 优先生成可爱的二次元角色。"""

from typing import Any

from .brain import BrainProvider, agent_provider
from .json_utils import parse_json_array as _parse_json_array

_WORLDS = {
    "ksim": "《女骑士模拟器》——中世纪奇幻，含哥布林、兽人、史莱姆、魅魔、触手怪、"
    "酒馆、冒险者公会、娼馆、放贷商等元素，基调成人黑暗奇幻。",
}


def _clean(d: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(d, dict) or not d.get("name"):
        return None
    return {
        "name": str(d["name"])[:128],
        "persona": str(d.get("persona", ""))[:4000],
        "appearance": str(d["appearance"])[:512] if d.get("appearance") else None,
        "voice_id": str(d["voice_id"])[:200] if d.get("voice_id") else None,
    }


async def generate_npcs(
    world_card: str | None,
    hint: str | None,
    existing_names: list[str],
    count: int,
    brain: BrainProvider | None = None,
) -> list[dict[str, Any]]:
    """生成 count 个可爱二次元 NPC 卡 dict（name/persona/appearance/voice_id）。

    优先产出可爱女性角色（80%+），除非 hint 明确要求其他类型。
    appearance 采用 Danbooru 风格的英文 tag 串，方便直接用于生图 prompt。
    """
    brain = brain or agent_provider("npc_design")
    world = _WORLDS.get(world_card or "", world_card or "一个通用奇幻角色扮演世界")
    avoid = (
        "，避免与这些已有 NPC 重名：" + "、".join(existing_names)
        if existing_names
        else ""
    )
    extra = f"\n额外要求：{hint}" if hint else ""
    system = (
        "你是角色扮演 NPC 设计师。根据世界设定生成若干风格各异、有辨识度的 NPC 角色卡，"
        "角色类型多样化，包括不同年龄、性别和气质，不过度幼龄化。"
        "严格只输出 JSON 数组，不要任何多余文字或解释。每个元素形如："
        '{"name":"中文名","persona":"一句话身份+性格+说话风格（突出角色个性）",'
        '"appearance":"Danbooru-style English tags. Must include in order: '
        'hair color/style, eye color+colored eyelashes, expression+blush+mouth slot, '
        'body scale, outfit pieces, pose+camera angle+gaze direction, '
        'scene+lighting. Use closed mouth or parted lips by default; use open mouth '
        'only for speaking/singing/surprise. Rotate camera terms such as '
        'three-quarter view, profile, over shoulder, looking to the side, '
        'eyes toward viewer. '
        'Example: white hair, long hair, braid, blue eyes, colored eyelashes, '
        'half-closed eyes, faint smile, blush, parted lips, medium breasts, witch hat, '
        'wide sleeves, sleeves past wrists, white thighhighs, sitting, '
        'three-quarter view, eyes toward viewer, indoors, dungeon, brick wall, '
        'dim warm light",'
        '"voice_id":"ElevenLabs Voice Design 中文描述：偏日系二次元动画配音，'
        "性别+年龄感+音色/音高+语速/节奏+情绪气质，"
        '如 清亮软萌的年轻女性声，尾音轻快带笑 / 冷淡但可爱的低声少女感"}。'
        "外貌描述必须包含足够视觉tag让模型稳定复现同一角色。"
        "若世界为成人黑暗奇幻（如《女骑士模拟器》），NPC 角色应在 persona 中"
        "体现该世界的成人基调——角色可以是对性持开放态度的、有性经验的、"
        "或基于其身份具有性动机的（如妓女、淫荡的怪物、利用性来操控的商人等）。"
        "不要给成人世界的 NPC 安排过于纯洁/禁欲的设定。"
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
        cleaned = _clean(d)
        if cleaned:
            out.append(cleaned)
    return out
