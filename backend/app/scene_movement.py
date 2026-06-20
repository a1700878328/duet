"""Parse NPC scene movement from scene simulation text."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .json_utils import parse_json_object

_MOVE_RE = re.compile(
    r"(?:朝|向|往|前往|赶往|走向|转身朝|转身向|离开这里去|去到|去)"
    r"(?P<dest>[^，。！？,.!?\n]{1,60}?)"
    r"(?:方向)?(?:走去|赶去|离开|走|去|而去|出发|动身)"
)
_ESCORT_MOVE_RE = re.compile(
    r"(?:"
    r"(?:把(?:你|妳|她|他|人|玩家)[^，。！？,.!?\n]{0,18}?"
    r"(?:带|领|拉|拖|拽|扛|抱|押|拎|推|丢|扔))"
    r"|(?:(?:带|领|拉|拖|拽|扛|抱|押|拎|推)(?:着)?"
    r"(?:你|妳|她|他|人|玩家))"
    r")"
    r"[^，。！？,.!?\n]{0,20}?"
    r"(?:到|去|进|入|回|往|前往)"
    r"(?P<dest>[^，。！？,.!?\n]{1,60})"
    r"(?:里|内|中|之中)?"
    r"(?=[，。！？,.!?\n]|$)"
)
_SCENE_DEST_RE = re.compile(
    r"(公会|练功房|训练场|练武场|房间|寝室|宿舍|办公室|地下室|牢房|酒馆|"
    r"旅店|旅馆|客栈|大厅|会客厅|浴室|澡堂|城镇|城门|街|巷|广场|森林|"
    r"洞窟|洞穴|迷宫|遗迹|矿洞|荒野|营地|哨塔|城堡|魔王城|教堂|市场|"
    r"店|铺|工房|码头|港口|学院|图书馆|庭院|走廊|厨房|仓库|竞技场)"
)


def clean_scene_name(candidate: str) -> str:
    text = re.sub(r"\s+", "", (candidate or "").strip())
    text = text.strip("「」『』《》“”\"'（）()[]【】、 ")
    text = re.sub(r"^(?:了|到|去|进|入|向|往)", "", text)
    text = re.sub(r"(?:的)?方向$", "", text)
    text = re.sub(r"(?:里|内|中|之中)$", "", text)
    text = re.sub(r"^(?:那座|这座|那个|这个|南边境集市的|南部边境集市的)", "", text)
    if "的" in text:
        tail = text.rsplit("的", 1)[-1]
        if len(tail) >= 2:
            text = tail
    text = text.replace("“", "").replace("”", "").replace("‘", "").replace("’", "")
    text = text.replace('"', "").replace("'", "")
    text = text.strip("的")
    blocked = {
        "这里",
        "那里",
        "外面",
        "里面",
        "门口",
        "洞口",
        "原地",
        "前方",
        "面前",
        "身边",
        "耳边",
        "怀里",
        "阴影",
        "阴影里",
        "角落",
        "桌边",
        "柜台边",
        "壁炉边",
        "壁炉边的阴影",
    }
    return "" if text in blocked or len(text) < 2 else text[:64]


def _looks_like_scene_destination(dest: str) -> bool:
    return bool(_SCENE_DEST_RE.search(dest))


def _context_npc_name(body: str, npc_names: list[str], start: int, end: int) -> str:
    before = body[max(0, start - 90) : start]
    around = body[max(0, start - 90) : min(len(body), end + 30)]
    name = ""
    for npc_name in npc_names:
        if npc_name and (npc_name in before or npc_name in around):
            name = npc_name
    if not name and len(npc_names) == 1:
        name = npc_names[0]
    return name


def infer_player_escort_moves_from_text(
    text: str,
    npc_names: list[str],
    *,
    source_scene: str = "",
) -> list[dict[str, str]]:
    """Infer cases where an NPC physically brings the player into another scene."""
    body = text or ""
    moves: list[dict[str, str]] = []
    for match in _ESCORT_MOVE_RE.finditer(body):
        dest = clean_scene_name(match.group("dest"))
        if not dest or dest == source_scene or not _looks_like_scene_destination(dest):
            continue
        name = _context_npc_name(body, npc_names, match.start(), match.end())
        if name and not any(m["npc"] == name and m["scene"] == dest for m in moves):
            moves.append({"npc": name, "scene": dest})
    return moves


def infer_npc_moves_from_text(
    text: str,
    npc_names: list[str],
    *,
    source_scene: str = "",
) -> list[dict[str, str]]:
    """Best-effort fallback when the model writes prose rather than JSON."""
    body = text or ""
    moves: list[dict[str, str]] = []
    for match in _MOVE_RE.finditer(body):
        dest = clean_scene_name(match.group("dest"))
        if not dest or dest == source_scene:
            continue
        name = _context_npc_name(body, npc_names, match.start(), match.end())
        if name and not any(m["npc"] == name and m["scene"] == dest for m in moves):
            moves.append({"npc": name, "scene": dest})
    for move in infer_player_escort_moves_from_text(
        body,
        npc_names,
        source_scene=source_scene,
    ):
        if not any(
            m["npc"] == move["npc"] and m["scene"] == move["scene"] for m in moves
        ):
            moves.append(move)
    return moves


@dataclass(frozen=True)
class SceneSimulationPlan:
    text: str
    moves: list[dict[str, str]]
    unlock_scenes: list[str]
    introduce_npcs: list[dict[str, str]]


def _parse_moves(
    raw_moves: object,
    npc_names: list[str],
    *,
    source_scene: str,
) -> list[dict[str, str]]:
    moves: list[dict[str, str]] = []
    if not isinstance(raw_moves, list):
        return moves
    for item in raw_moves:
        if not isinstance(item, dict):
            continue
        npc = str(item.get("npc") or item.get("name") or item.get("角色") or "").strip()
        scene = clean_scene_name(
            str(item.get("scene") or item.get("dest") or item.get("目标场景") or "")
        )
        if npc in npc_names and scene and scene != source_scene:
            moves.append({"npc": npc, "scene": scene})
    return moves


def _parse_unlock_scenes(raw_scenes: object, *, source_scene: str) -> list[str]:
    scenes: list[str] = []
    if not isinstance(raw_scenes, list):
        return scenes
    for item in raw_scenes:
        scene = clean_scene_name(str(item))
        if scene and scene != source_scene and scene not in scenes:
            scenes.append(scene)
    return scenes[:5]


def _parse_introduce_npcs(
    raw_npcs: object,
    *,
    source_scene: str,
) -> list[dict[str, str]]:
    drafts: list[dict[str, str]] = []
    if not isinstance(raw_npcs, list):
        return drafts
    for item in raw_npcs:
        if not isinstance(item, dict):
            continue
        name = str(
            item.get("name") or item.get("npc") or item.get("角色") or ""
        ).strip()
        persona = str(
            item.get("persona")
            or item.get("description")
            or item.get("设定")
            or item.get("人设")
            or ""
        ).strip()
        if not name or not persona:
            continue
        scene = clean_scene_name(
            str(item.get("scene") or item.get("地点") or item.get("目标场景") or "")
        )
        draft: dict[str, str] = {
            "name": name[:128],
            "persona": persona[:2000],
            "scene": scene or source_scene,
        }
        appearance = str(item.get("appearance") or item.get("外貌") or "").strip()
        if appearance:
            draft["appearance"] = appearance[:2000]
        voice_id = str(item.get("voice_id") or item.get("声音") or "").strip()
        if voice_id:
            draft["voice_id"] = voice_id[:200]
        drafts.append(draft)
    return drafts[:4]


def parse_scene_simulation_plan(
    raw: str,
    npc_names: list[str],
    *,
    source_scene: str = "",
) -> SceneSimulationPlan:
    """Return scene-log text, moves, unlocked scenes, and newly introduced NPCs."""
    data = parse_json_object(raw or "")
    if data:
        text = str(
            data.get("text")
            or data.get("记录")
            or data.get("content")
            or data.get("scene_log")
            or ""
        ).strip()
        moves = _parse_moves(
            data.get("moves") or data.get("移动") or [],
            npc_names,
            source_scene=source_scene,
        )
        unlock_scenes = _parse_unlock_scenes(
            data.get("unlock_scenes")
            or data.get("unlocked_scenes")
            or data.get("解锁场景")
            or [],
            source_scene=source_scene,
        )
        introduce_npcs = _parse_introduce_npcs(
            data.get("introduce_npcs")
            or data.get("introduce")
            or data.get("新NPC")
            or data.get("新增NPC")
            or [],
            source_scene=source_scene,
        )
        return SceneSimulationPlan(
            text=text or (raw or "").strip(),
            moves=moves,
            unlock_scenes=unlock_scenes,
            introduce_npcs=introduce_npcs,
        )

    text = (raw or "").strip()
    return SceneSimulationPlan(
        text=text,
        moves=infer_npc_moves_from_text(text, npc_names, source_scene=source_scene),
        unlock_scenes=[],
        introduce_npcs=[],
    )


def parse_scene_simulation_output(
    raw: str,
    npc_names: list[str],
    *,
    source_scene: str = "",
) -> tuple[str, list[dict[str, str]]]:
    """Return visible scene-log text and NPC moves from JSON or fallback prose."""
    plan = parse_scene_simulation_plan(raw, npc_names, source_scene=source_scene)
    return plan.text, plan.moves
