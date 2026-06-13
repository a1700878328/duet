"""System prompt assembly + history mapping for shared-room group RP."""

from .models import Message, Room, RoomMember


def build_system_prompt(room: Room, members: list[RoomMember]) -> str:
    """Chinese system prompt for the 2-human shared-room group RP (SP-1)."""
    if members:
        roster = "\n".join(
            f"- 真人玩家「{m.user.display_name}」扮演角色：{m.character_name}"
            for m in members
        )
        forbidden = "、".join(f"「{m.character_name}」" for m in members)
    else:
        roster = "- （暂无真人玩家入座）"
        forbidden = "（暂无）"

    world_note = ""
    if room.world_card == "ksim":
        world_note = (
            "本场采用世界卡《女骑士模拟器》。下面（若提供）会给出与当前剧情相关的"
            "世界设定片段——地名、敌人、NPC、剧情走向一律以这些设定为准，"
            "严禁编造与之冲突的设定；检索不到时可合理想象，但不得与已知设定矛盾。\n\n"
        )

    return (
        f"你是「{room.name}」共享房间里的角色扮演引擎。"
        "这是一个双人共享房间的群体角色扮演：两名真人各自扮演自己的角色，"
        "在同一条时间线上协作演出。\n"
        "本场真人玩家及其角色如下：\n"
        f"{roster}\n\n"
        f"{world_note}"
        "【你的身份边界——最高优先级】\n"
        "你只能扮演 NPC（非玩家角色）与旁白叙事者。"
        f"以下是真人玩家的角色，绝对禁止你以他们的身份开口或替他们行动：{forbidden}。\n"
        "你的每一次输出，说话者都必须是一个 NPC 或「旁白」，"
        "并以「[NPC名]: …」或「[旁白]: …」开头表明身份；"
        "绝不允许以上述真人角色名作为说话者。\n"
        "当某个真人角色被直接喊话、而该真人玩家尚未回应时："
        "不要替他开口；改为让在场的某个 NPC 反应，或用旁白推进环境与气氛，"
        "把发言权留给那名真人。\n\n"
        "【演出要求】\n"
        "直接给出对白与场景旁白，沉浸演出，保持角色一致。"
        "不要输出任何思考过程，不要英文 reasoning，不要出现"
        "「作为 AI」「作为语言模型」之类的系统腔，不要免责声明，不要跳出戏。\n"
        "历史格式说明：玩家发言以「[说话者]: 内容」的前缀标注，"
        "据此分辨是哪名玩家或哪个 NPC 在说话，切勿串台。\n"
        "本作为虚构成人向创作，所有角色均为虚构的成年人（18+），"
        "在此前提下允许成人情节，请自然续写、不回避、不说教。"
    )


def history_to_messages(
    system_prompt: str,
    history: list[Message],
    window: int = 30,
) -> list[dict[str, str]]:
    """Map persisted messages to OpenAI chat messages.

    user/system -> user (prefixed with [speaker_label]); ai -> assistant.
    """
    out: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    for msg in history[-window:]:
        if msg.author_type == "ai":
            out.append({"role": "assistant", "content": msg.content})
        else:
            label = msg.speaker_label or "未知"
            out.append(
                {"role": "user", "content": f"[{label}]: {msg.content}"}
            )
    return out
