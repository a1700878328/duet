"""据世界卡 AI 生成「玩家角色」候选草稿（强制选角 onboarding）。

与 npc_gen 平行：npc_gen 生成 NPC 名册，本模块生成供玩家本人挑选的
PLAYER 角色草稿（含英文视觉tag外貌描述 + 中文声音设计），不持久化——
选中后由前端走既有 PUT /me-card 写回。
"""

from typing import Any

from .brain import BrainProvider, default_provider
from .json_utils import parse_json_array as _parse_json_array

_WORLDS = {
    "ksim": "《女骑士模拟器》——中世纪奇幻，含哥布林、兽人、史莱姆、魅魔、触手怪、"
    "酒馆、冒险者公会、娼馆、放贷商等元素，基调成人黑暗奇幻。",
}


def _clean_drafts(raw: str, count: int) -> list[dict[str, Any]]:
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
                    "voice_id": str(d["voice_id"])[:200] if d.get("voice_id") else None,
                }
            )
    return out


async def generate_character_options(
    world_card: str | None,
    hint: str | None,
    count: int,
    brain: BrainProvider | None = None,
) -> list[dict[str, Any]]:
    """生成 count 个玩家角色草稿 dict（name/persona/appearance/voice_id）。

    若给定 ``hint``（玩家自我描述），围绕该描述生成 count 个候选变体。
    """
    brain = brain or default_provider()
    try:
        brain.temperature = 0.7
        brain.max_tokens = max(getattr(brain, "max_tokens", 800), 1600)
    except Exception:
        pass
    world = _WORLDS.get(world_card or "", world_card or "一个通用奇幻角色扮演世界")

    if hint:
        task = (
            f"玩家提供了一句自我描述，请围绕它生成 {count} 个完整、可直接游玩的"
            "玩家角色候选。每个候选都要忠实贴合该描述，但在职业细节、性格侧重、"
            "外貌辨识度或声音气质上做出明显差异，供玩家挑选。"
            f"玩家的自我描述：{hint}"
        )
    else:
        task = f"生成 {count} 个风格各异、适合玩家代入的玩家角色，差异要明显。"

    system = (
        "你是角色扮演角色设计师。为玩家设计有特色、有辨识度的角色卡，"
        "扎根于给定的世界设定。角色要有鲜明的个性特征和视觉辨识度，"
        "避免模板化。默认产出年轻到成年区间，不过度幼龄化。"
        "严格只输出 JSON 数组，不要任何多余文字或解释。"
        "每个元素形如："
        '{"name":"中文名","persona":"一句话身份+性格+说话风格（突出角色独特个性）",'
        '"appearance":"Danbooru-style English tags. Must include in order: '
        'hair color/style, eye color+colored eyelashes, expression+blush+mouth slot, '
        'body scale, outfit pieces, pose+camera angle+gaze direction, '
        'scene+lighting. Use closed mouth or parted lips by default; use open mouth '
        'only for speaking/singing/surprise. Rotate camera terms such as '
        'three-quarter view, profile, over shoulder, looking to the side, '
        'eyes toward viewer. '
        'Example: black hair, hime cut, red eyes, colored eyelashes, '
        'calm smile, blush, closed mouth, medium breasts, military uniform, '
        'black gloves, thighhighs, standing, three-quarter view, eyes toward viewer, '
        'indoors, barracks room, dim candlelight", '
        '"voice_id":"ElevenLabs Voice Design 中文描述：偏日系二次元动画配音，'
        "性别+年龄感+音色/音高+语速/节奏+情绪气质，"
        '如 清亮软萌的年轻女性声，尾音轻快带笑 / 冷淡但可爱的低声少女感"}。'
        "外貌描述必须包含足够多视觉tag让模型能稳定复现同一个角色。"
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

    out = _clean_drafts(raw, count)
    if out:
        return out

    retry_system = (
        system + "\n上一次输出没有被 JSON 解析器接受。现在必须只输出合法 JSON 数组，"
        "不要 Markdown，不要解释，不要前后缀。"
    )
    retry_user = (
        f"{user}\n\n必须输出恰好 {count} 个元素。示例格式："
        '[{"name":"艾琳","persona":"年轻女骑士，认真寡言，说话简短",'
        '"appearance":"1girl, short blonde hair, blue eyes, '
        'worn steel armor, red cloak",'
        '"voice_id":"年轻女性，清澈冷静，语速偏慢"}]'
    )
    raw = (
        await brain.complete(
            [
                {"role": "system", "content": retry_system},
                {"role": "user", "content": retry_user},
            ]
        )
    ).strip()
    return _clean_drafts(raw, count)
