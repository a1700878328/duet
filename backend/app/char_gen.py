"""据世界卡 AI 生成「玩家角色」候选草稿（强制选角 onboarding）。

与 npc_gen 平行：npc_gen 生成 NPC 名册，本模块生成供玩家本人挑选的
PLAYER 角色草稿（含英文视觉tag外貌描述 + 中文声音设计），不持久化——
选中后由前端走既有 PUT /me-card 写回。
"""

from typing import Any

from .brain import BrainProvider
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

    使用教程注入设计师确保 appearance 严格对齐 NTRMix 格式。
    """
    from .imagegen.tutorial_designer import design_character

    world_label = _WORLDS.get(world_card or "", world_card or "")
    results: list[dict[str, Any]] = []
    for i in range(count):
        desc = hint or f"风格各异的玩家角色，第{i+1}个"
        if i > 0 and hint:
            desc = f"{hint}（变体{i+1}：在职业、性格或外貌上与前一个角色有明显差异）"
        elif i > 0:
            desc = f"风格与前面不同的玩家角色，第{i+1}个"
        draft = await design_character(
            desc, world_card=world_label, brain=brain
        )
        if draft.get("name"):
            results.append(draft)
    return results
