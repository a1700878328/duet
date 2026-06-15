"""Parse NPC scene movement from scene simulation text."""

from __future__ import annotations

import re

from .json_utils import parse_json_object

_MOVE_RE = re.compile(
    r"(?:朝|向|往|前往|赶往|走向|转身朝|转身向|离开这里去|去到|去)"
    r"(?P<dest>[^，。！？,.!?\n]{1,60}?)"
    r"(?:方向)?(?:走去|赶去|离开|走|去|而去|出发|动身)"
)


def clean_scene_name(candidate: str) -> str:
    text = re.sub(r"\s+", "", (candidate or "").strip())
    text = text.strip("「」『』《》“”\"'（）()[]【】、 ")
    text = re.sub(r"(?:的)?方向$", "", text)
    text = re.sub(r"^(?:那座|这座|那个|这个|南边境集市的|南部边境集市的)", "", text)
    if "的" in text:
        tail = text.rsplit("的", 1)[-1]
        if len(tail) >= 2:
            text = tail
    text = text.replace("“", "").replace("”", "").replace("‘", "").replace("’", "")
    text = text.replace('"', "").replace("'", "")
    blocked = {"这里", "那里", "外面", "里面", "门口", "洞口", "原地", "前方"}
    return "" if text in blocked or len(text) < 2 else text[:64]


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
        before = body[max(0, match.start() - 90) : match.start()]
        name = ""
        for npc_name in npc_names:
            if npc_name and npc_name in before:
                name = npc_name
        if not name and len(npc_names) == 1:
            name = npc_names[0]
        if name and not any(m["npc"] == name and m["scene"] == dest for m in moves):
            moves.append({"npc": name, "scene": dest})
    return moves


def parse_scene_simulation_output(
    raw: str,
    npc_names: list[str],
    *,
    source_scene: str = "",
) -> tuple[str, list[dict[str, str]]]:
    """Return visible scene-log text and NPC moves from JSON or fallback prose."""
    data = parse_json_object(raw or "")
    if data:
        text = str(
            data.get("text")
            or data.get("记录")
            or data.get("content")
            or data.get("scene_log")
            or ""
        ).strip()
        raw_moves = data.get("moves") or data.get("移动") or []
        moves: list[dict[str, str]] = []
        if isinstance(raw_moves, list):
            for item in raw_moves:
                if not isinstance(item, dict):
                    continue
                npc = str(
                    item.get("npc") or item.get("name") or item.get("角色") or ""
                ).strip()
                scene = clean_scene_name(
                    str(
                        item.get("scene")
                        or item.get("dest")
                        or item.get("目标场景")
                        or ""
                    )
                )
                if npc in npc_names and scene and scene != source_scene:
                    moves.append({"npc": npc, "scene": scene})
        return text or (raw or "").strip(), moves

    text = (raw or "").strip()
    return text, infer_npc_moves_from_text(text, npc_names, source_scene=source_scene)
