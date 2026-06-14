"""ksim 游戏层：角色属性/经验/状态（AI 判定增量）。

数值 schema 取自世界卡抽取的术语表。裁判每回合后看剧情吐出增量。
"""

import json
from typing import Any

from .brain import BrainProvider, default_provider

# 数值字段（int）。基础属性 + 淫乱向经验/开发。
NUMERIC_FIELDS: tuple[str, ...] = (
    "等级", "经验", "力量", "敏捷", "智力", "意志", "金钱", "支出",
    "淫乱", "欲望",
    "阴道开发", "阴道经验", "口腔开发", "口腔经验",
    "胸部开发", "胸部经验", "菊穴开发", "菊穴经验",
    "高潮经验", "露出癖", "露出经验", "受虐狂", "受虐经验",
    "精液中毒", "精液经验", "百合经验", "自慰经验",
)


def default_stats(job: str = "冒险者") -> dict[str, Any]:
    """新角色起始属性表。"""
    base: dict[str, Any] = {
        "职业": job,
        "冒险者等级": "E",
        "等级": 1,
        "经验": 0,
        "力量": 10,
        "敏捷": 10,
        "智力": 10,
        "意志": 10,
        "金钱": 100,
        "支出": 0,
    }
    for f in NUMERIC_FIELDS:
        base.setdefault(f, 0)
    base["状态"] = []
    base["好感度"] = {}
    return base


def apply_delta(stats: dict[str, Any], delta: dict[str, Any]) -> dict[str, Any]:
    """把裁判增量应用到属性表（纯函数，返回新表）。"""
    out = json.loads(json.dumps(stats))  # deep copy
    out.setdefault("状态", [])
    out.setdefault("好感度", {})
    for key, val in delta.items():
        if key in {"状态_add", "状态_del", "好感度"}:
            continue
        if isinstance(val, (int, float)):
            out[key] = int(out.get(key, 0) or 0) + int(val)
    for s in delta.get("状态_add", []) or []:
        s = str(s).strip()
        if s and s not in out["状态"]:
            out["状态"].append(s)
    for s in delta.get("状态_del", []) or []:
        s = str(s).strip()
        out["状态"] = [x for x in out["状态"] if x != s and not x.startswith(s)]
    for name, dv in (delta.get("好感度") or {}).items():
        if isinstance(dv, (int, float)):
            out["好感度"][str(name)] = int(out["好感度"].get(str(name), 0)) + int(dv)
    # 简单升级：每 100×等级 经验升一级。
    while out.get("经验", 0) >= 100 * out.get("等级", 1):
        out["经验"] -= 100 * out["等级"]
        out["等级"] = out.get("等级", 1) + 1
    return out


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


_JUDGE_SYS = (
    "你是《女骑士模拟器》的数值裁判。根据**本回合刚发生的剧情**，判定主角的"
    "属性/经验/状态/好感度变化。**只输出 JSON 增量**，没有变化就输出 {}。\n"
    "数值字段用中文名（经验/金钱/力量/意志/淫乱/欲望/口腔经验/阴道经验/胸部经验/"
    "菊穴经验/高潮经验/露出经验/受虐经验/精液经验/百合经验/各种开发…），值为整数增量。\n"
    '状态用 "状态_add"/"状态_del"(字符串数组,如 "监禁:哥布林 5"/"露宿街头")，'
    '好感度用 "好感度":{"NPC名":增量}。形如：'
    '{"经验":10,"淫乱":1,"口腔经验":3,'
    '"状态_add":["监禁:哥布林 5"],"好感度":{"会长":2}}\n'
    "原则：贴合本回合实际发生的事，克制、别乱给；平淡对话多数返回 {}。"
)


async def judge_stat_delta(
    scene_text: str,
    current_stats: dict[str, Any],
    brain: BrainProvider | None = None,
) -> dict[str, Any]:
    """裁判：看本回合剧情，吐出属性增量 dict（可空）。"""
    brain = brain or default_provider()
    lv = current_stats.get("等级")
    lewd = current_stats.get("淫乱")
    money = current_stats.get("金钱")
    user = (
        f"主角当前关键属性：等级{lv} 淫乱{lewd} 金钱{money}。\n"
        f"本回合剧情：\n{scene_text}"
    )
    raw = await brain.complete(
        [{"role": "system", "content": _JUDGE_SYS}, {"role": "user", "content": user}]
    )
    return _parse_obj(raw)
