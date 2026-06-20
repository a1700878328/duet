"""据世界卡 AI 生成「玩家角色」候选草稿（强制选角 onboarding）。

与 npc_gen 平行：npc_gen 生成 NPC 名册，本模块生成供玩家本人挑选的
PLAYER 角色草稿（含英文视觉tag外貌描述 + 中文声音设计），不持久化——
选中后由前端走既有 PUT /me-card 写回。
"""

from typing import Any

from .agent_sdk import agent
from .i18n import language_instruction, normalize_locale
from .json_utils import parse_json_array as _parse_json_array

_WORLDS = {
    "ksim": "《女骑士模拟器》——中世纪奇幻，含哥布林、兽人、史莱姆、魅魔、触手怪、"
    "酒馆、冒险者公会、娼馆、放贷商等元素，基调成人黑暗奇幻。",
}


def _clean_drafts(raw: str, count: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for d in _parse_json_array(raw)[:count]:
        cleaned = _clean_draft(d)
        if cleaned:
            out.append(cleaned)
    return out


def _clean_draft(d: Any) -> dict[str, Any]:
    if not isinstance(d, dict) or not d.get("name"):
        return {}
    return {
        "name": str(d["name"])[:128],
        "persona": str(d.get("persona", ""))[:4000],
        "appearance": str(d["appearance"])[:2000] if d.get("appearance") else None,
        "voice_id": str(d["voice_id"])[:200] if d.get("voice_id") else None,
    }


async def generate_character_options(
    world_card: str | None,
    hint: str | None,
    count: int,
    *,
    nsfw: bool = False,
    locale: str | None = None,
) -> list[dict[str, Any]]:
    """生成 count 个玩家角色草稿 dict（name/persona/appearance/voice_id）。

    All AI work goes through AgentSDK so prompt/task/schema behavior has one
    source of truth.
    """
    world_label = _WORLDS.get(world_card or "", world_card or "")
    locale = normalize_locale(locale)
    results: list[dict[str, Any]] = []
    for i in range(count):
        desc = hint or f"风格各异的玩家角色，第{i+1}个"
        if i > 0 and hint:
            desc = (
                f"{hint}（这是同一个角色的第{i+1}个诠释版本，必须保留玩家原始描述里的"
                "职业、服装、道具和所有视觉细节，完全一致；"
                "只在姓名、发型细节、表情气质、服装配色或氛围上做微小变化——"
                "像是同一个角色的不同插画师诠释）"
            )
        elif i > 0:
            desc = f"风格与前面不同的玩家角色，第{i+1}个"
        user = (
            f"NSFW：{'true' if nsfw else 'false'}\n"
            f"玩家描述：{desc}\n"
            "硬性要求：角色卡和外貌必须贴合玩家描述，不得改职业、发色、瞳色、"
            "服装、道具、种族、体型或核心气质。persona 写 4-7 句；appearance 写 250-700 字，"
            "必须有足够视觉细节供后续画图 AI 锁定角色。"
        )
        if locale == "ja-JP":
            user += (
                "\n输出语言：日本語。name は日本語のキャラクター名、persona は4-7文の自然な日本語、"
                "appearance は250-700字程度の自然な日本語、voice_id も日本語の声質説明にしてください。"
            )
        if not nsfw:
            user += (
                " NSFW=false 时必须服装完整，不得裸露胸部/生殖器，不得写裸体、"
                "全裸、无遮蔽、性行为、被绑裸体或纯成人特写。"
            )
        if world_label:
            user = f"世界设定：{world_label}\n{user}"
        user = f"{language_instruction(locale)}\n{user}"
        draft = await agent.run("character_design", input=user, locale=locale)
        if draft.get("name"):
            cleaned = _clean_draft(draft)
            if cleaned:
                results.append(cleaned)
    return results
