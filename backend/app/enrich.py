"""NPC 信息渐显：随剧情把"玩家逐渐了解到的"NPC 信息累积刷新。

区别于作者设定的 persona（喂提示词、玩家不一定知道），discovered 是从**已发生
对话**里浮现、玩家此刻确实了解到的信息（外貌、来历、关系、习惯、当下处境）。
越聊越详细。
"""

from .agent_sdk import agent


async def enrich_npc(
    name: str,
    persona: str,
    prior: str | None,
    recent_dialogue: str,
) -> str | None:
    """合并最近对话→更新「已了解」档案；无可更新或失败时返回 None。"""
    recent_dialogue = (recent_dialogue or "").strip()
    if not recent_dialogue:
        return None
    user = (
        f"NPC：{name}\n设定(persona,仅供你参考,玩家未必全知道)：{persona}\n\n"
        f"已有「已了解」信息：{prior or '（暂无）'}\n\n"
        f"最近对话片段：\n{recent_dialogue}"
    )
    out = await agent.run("npc_enrich", input=user)
    out = (out or "").strip()
    return out[:2000] or None
