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
    player_state: str = "",
    scene: str = "",
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
        "你是角色扮演**导演**。根据当前场面，决定：这一拍由哪些现有 NPC 反应、"
        "是否引入新 NPC 登场、是否推进剧情时间。**只输出 JSON**，不要多余文字：\n"
        '{"acts": [按发言顺序的现有 NPC id 数组，0-3 个，只选此刻最该'
        '反应的；可空], '
        '"introduce": [{"name":"中文名","persona":"一句话身份+性格+说话风格",'
        '"appearance":"英文Danbooru外貌",'
        '"voice_id":"中文声音描述(性别+年龄+音色+语气)"}], '
        '"time_jump": null 或 '
        '"一句话:时间流逝+这段时间世界/相关NPC做了什么/局势变化"}\n'
        "原则：不要让所有 NPC 都说话，贴合当前对话选最相关的。"
        "introduce：剧情需要新角色出场时给（0-2 个；"
        "在场已有合适 NPC 或无需新人则空数组）；"
        "**若当前在场 NPC 为空且场景里该有人，就用 introduce 引入**。"
        "多数平稳推进时 introduce 为空、time_jump 为 null。\n"
        "【数值→剧情倾向，仿《女骑士模拟器》】结合下面玩家数值/状态，"
        "把剧情往合适方向推（选 acts/introduce/time_jump 时体现）："
        "负债/没钱→倾向引入借贷商/流落街头/卖春事件，钱越负越强；"
        "淫乱高→倾向被调教/堕落剧情，露出高→露出事件，欲望高→发情/自慰；"
        "状态'监禁:X'→强制推进该怪物的囚禁侵犯循环，直到逃脱或彻底沦陷；"
        "'怀孕:X'/'公共厕所'/'契约:娼妇'→推进对应堕落剧情；"
        "好感度高的 NPC 可深入互动。让世界对玩家处境做出游戏式反应。"
    )
    state_block = f"\n玩家数值/状态：{player_state}" if player_state else ""
    scene_block = f"\n当前场景：{scene}（只引入合此地的 NPC）" if scene else ""
    user = (
        f"世界：{world}\n真人玩家角色：{players}{scene_block}\n"
        f"在场 NPC：\n{roster}{state_block}\n\n"
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

    introduce: list[dict[str, Any]] = []
    for d in (data.get("introduce") or [])[:2]:
        if isinstance(d, dict) and d.get("name"):
            introduce.append(
                {
                    "name": str(d["name"])[:128],
                    "persona": str(d.get("persona", ""))[:4000],
                    "appearance": str(d["appearance"])[:512]
                    if d.get("appearance")
                    else None,
                    "voice_id": str(d["voice_id"])[:200]
                    if d.get("voice_id")
                    else None,
                }
            )

    return {"acts": acts, "introduce": introduce, "time_jump": time_jump}
