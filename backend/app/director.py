"""导演（Phase C）：每拍决定哪些 NPC 反应 + 是否推进叙事时间。"""

import json
from typing import Any

from .brain import BrainProvider, default_provider
from .models import NpcCard, RoomMember


def _parse_obj(raw: str) -> dict[str, Any]:
    s = raw.strip()
    if s.startswith("```"):
        s = s.strip("`")
        nl = s.find("\n")
        if nl != -1 and s[:nl].strip().lower() in {"json", ""}:
            s = s[nl + 1 :]
    a, b = s.find("{"), s.rfind("}")
    if a != -1 and b != -1 and b > a:
        s = s[a : b + 1]
    try:
        data = json.loads(s)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


async def direct_beat(
    world_card: str | None,
    members: list[RoomMember],
    npcs: list[NpcCard],
    recent_scene: str,
    *,
    force_timeskip: bool = False,
    brain: BrainProvider | None = None,
) -> dict[str, Any]:
    """返回 {"acts": [npc_id...], "time_jump": str|None}。

    acts = 本拍应发言的 NPC（按顺序，0-3 个，只选最该反应的）。
    time_jump = 推进叙事时间时的一句话描述（流逝 + 这段时间世界/NPC 变化），否则 None。
    """
    brain = brain or default_provider()
    roster = "\n".join(f"  id={n.id} 「{n.name}」：{n.persona}" for n in npcs)
    players = "、".join(m.character_name for m in members) or "（无）"
    world = "《女骑士模拟器》" if world_card == "ksim" else (world_card or "通用奇幻")
    skip_note = (
        "本拍请**推进剧情时间**：给出 time_jump 描述时间流逝"
        "与这段时间内世界/各 NPC 的变化。"
        if force_timeskip
        else "通常 time_jump 为 null；只有剧情到了合适的停顿/过渡点才推进时间。"
    )
    system = (
        "你是角色扮演**导演**。根据当前场面，决定这一拍由哪些 NPC 反应、按什么顺序，"
        "以及是否推进剧情时间。**只输出 JSON**，不要多余文字：\n"
        '{"acts": [按发言顺序的 NPC id 数组，0 到 3 个，只选此刻最该反应的；'
        '安静场合可为空], "time_jump": null 或 '
        '"一句话：时间流逝 + 这段时间世界/相关 NPC 做了什么/局势变化"}\n'
        "不要让所有 NPC 都说话；贴合当前对话选最相关的。"
    )
    user = (
        f"世界：{world}\n真人玩家角色：{players}\n在场 NPC：\n{roster}\n\n"
        f"最近场面：\n{recent_scene or '（刚开场）'}\n\n{skip_note}"
    )
    raw = await brain.complete(
        [{"role": "system", "content": system}, {"role": "user", "content": user}]
    )
    data = _parse_obj(raw)
    valid_ids = {n.id for n in npcs}
    acts = [
        int(x)
        for x in (data.get("acts") or [])
        if isinstance(x, (int, str)) and str(x).isdigit() and int(x) in valid_ids
    ][:3]
    tj = data.get("time_jump")
    time_jump = tj.strip() if isinstance(tj, str) and tj.strip() else None
    return {"acts": acts, "time_jump": time_jump}
