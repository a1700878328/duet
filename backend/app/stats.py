"""ksim 游戏层：角色属性/经验/状态（AI 判定增量）。

数值 schema 取自世界卡抽取的术语表。裁判每回合后看剧情吐出增量。
"""

import json
import re
from typing import Any

from .brain import BrainProvider, default_provider
from .json_utils import parse_json_object as _parse_obj

# 数值字段（int）。基础属性 + 淫乱向经验/开发。
NUMERIC_FIELDS: tuple[str, ...] = (
    "等级",
    "经验",
    "力量",
    "敏捷",
    "智力",
    "意志",
    "金钱",
    "淫乱",
    "欲望",
    "阴道开发",
    "阴道经验",
    "口腔开发",
    "口腔经验",
    "胸部开发",
    "胸部经验",
    "菊穴开发",
    "菊穴经验",
    "高潮经验",
    "露出癖",
    "露出经验",
    "受虐狂",
    "受虐经验",
    "精液中毒",
    "精液经验",
    "百合经验",
    "自慰经验",
    "负债",
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
    }
    for f in NUMERIC_FIELDS:
        base.setdefault(f, 0)
    base["状态"] = []
    base["好感度"] = {}
    base["物品"] = []
    return base


def apply_delta(stats: dict[str, Any], delta: dict[str, Any]) -> dict[str, Any]:
    """把裁判增量应用到属性表（纯函数，返回新表）。"""
    out = json.loads(json.dumps(stats))  # deep copy
    out.setdefault("状态", [])
    out.setdefault("好感度", {})
    out.setdefault("物品", [])
    for key, val in delta.items():
        if key in {"状态_add", "状态_del", "好感度", "物品_add"}:
            continue
        if key == "支出":
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
    for item in delta.get("物品_add", []) or []:
        text = str(item).strip()
        if text:
            out["物品"].append(text[:120])
    # 简单升级：每 100×等级 经验升一级。
    while out.get("经验", 0) >= 100 * out.get("等级", 1):
        out["经验"] -= 100 * out["等级"]
        out["等级"] = out.get("等级", 1) + 1
    return out


MONTHLY_RENT = 60  # 月末食宿基础支出。


def monthend_settle(
    stats: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """月末结算：扣基础食宿 + 债务利息。返回(新表, 应用的增量)。"""
    rent = MONTHLY_RENT
    debt = int(stats.get("负债", 0) or 0)
    interest = 0
    if debt > 0:
        # 高利贷：月息 20%，最低 5
        interest = max(5, int(debt * 0.2))
    delta: dict[str, Any] = {"金钱": -rent, "负债": interest}
    after = int(stats.get("金钱", 0) or 0) - rent
    states = stats.get("状态") or []
    if after < 0 and not any("负债" in str(s) for s in states):
        delta["状态_add"] = ["负债"]
    return apply_delta(stats, delta), delta


def initial_stats_from_card(name: str, persona: str | None) -> dict[str, Any]:
    """Create distinct starting stats from a selected player character card."""
    text = f"{name} {persona or ''}".lower()
    stats = default_stats()
    templates: list[tuple[tuple[str, ...], dict[str, Any]]] = [
        (
            ("女骑士", "骑士", "铁壁", "圣骑", "重甲", "盾"),
            {
                "职业": "女骑士",
                "力量": 12,
                "敏捷": 8,
                "智力": 9,
                "意志": 13,
                "金钱": 120,
            },
        ),
        (
            ("盗贼", "刺客", "斥候", "游侠", "弓手", "潜行"),
            {"职业": "斥候", "力量": 8, "敏捷": 14, "智力": 10, "意志": 9, "金钱": 80},
        ),
        (
            ("法师", "魔女", "术士", "魔法", "炼金"),
            {"职业": "法师", "力量": 6, "敏捷": 9, "智力": 15, "意志": 12, "金钱": 90},
        ),
        (
            ("修女", "牧师", "圣女", "神官"),
            {"职业": "修女", "力量": 7, "敏捷": 8, "智力": 12, "意志": 14, "金钱": 70},
        ),
        (
            ("贵族", "大小姐", "千金", "富家"),
            {"职业": "贵族", "力量": 7, "敏捷": 8, "智力": 12, "意志": 10, "金钱": 220},
        ),
        (
            ("商人", "行商", "会计", "账房"),
            {"职业": "商人", "力量": 7, "敏捷": 9, "智力": 13, "意志": 10, "金钱": 180},
        ),
        (
            ("佣兵", "战士", "剑士", "武者"),
            {"职业": "佣兵", "力量": 13, "敏捷": 10, "智力": 8, "意志": 11, "金钱": 90},
        ),
        (
            ("奴隶", "贫民", "流浪", "乞丐", "逃亡"),
            {
                "职业": "流浪者",
                "力量": 8,
                "敏捷": 10,
                "智力": 9,
                "意志": 11,
                "金钱": 25,
            },
        ),
    ]
    for keys, patch in templates:
        if any(k in text for k in keys):
            stats.update(patch)
            return stats
    return stats


_CN_NUMBERS: dict[str, int] = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}
_PAYMENT_RE = re.compile(
    r"(?:给|送|递|交|支付|付|付给|掏出|抽出|拿出|摸出|丢给|扔给|放到|落在|塞给|打赏|小费)"
    r"[^。\n；;]{0,40}?"
    r"(?P<amount>\d+|[一二两三四五六七八九十])?"
    r"\s*(?:枚|个|块|枚小|小)?"
    r"(?P<unit>金币|金枚|银币|银枚|铜币|铜板|钱币|硬币|银|铜|金)"
)


def _money_amount(raw_amount: str | None, unit: str) -> int:
    amount = 1
    if raw_amount:
        if raw_amount.isdigit():
            amount = int(raw_amount)
        else:
            amount = _CN_NUMBERS.get(raw_amount, 1)
    # 目前属性表只有抽象"金钱"，银币/铜板/金币都按玩家说出的枚数扣。
    # 后续若做币制换算，可以只改这里。
    _ = unit
    return max(0, min(amount, 10000))


def infer_payment_total(scene_text: str) -> int:
    """Extract concrete money the player line says was actually paid."""
    text = scene_text or ""
    total = 0
    for match in _PAYMENT_RE.finditer(text):
        total += _money_amount(match.group("amount"), match.group("unit"))
    return total


def infer_deterministic_delta(
    scene_text: str, current_stats: dict[str, Any]
) -> dict[str, Any]:
    """Hard rules for concrete resource changes that should not depend on LLM taste."""
    money_spent = infer_payment_total(scene_text)
    if money_spent <= 0:
        return {}
    current_money = int(current_stats.get("金钱", 0) or 0)
    return {
        "金钱": -money_spent,
        **({"状态_add": ["负债"]} if current_money - money_spent < 0 else {}),
    }


def _state_count(states: list[Any], prefix: str) -> int:
    """从状态文本（如 '监禁:哥布林 5'）取计数；只存在无数字记 1，无则 0。"""
    for s in states:
        if str(s).startswith(prefix):
            m = re.search(r"(\d+)", str(s))
            return int(m.group(1)) if m else 1
    return 0


def check_ending(stats: dict[str, Any]) -> str | None:
    """数值/状态跨阈值 → 触发结局（照《女骑士模拟器》解码条件）。无则 None。"""
    states = stats.get("状态") or []
    has = lambda p: any(p in str(s) for s in states)  # noqa: E731
    lewd = int(stats.get("淫乱", 0) or 0)
    int(stats.get("金钱", 0) or 0)
    debt = int(stats.get("负债", 0) or 0)
    will = int(stats.get("意志", 0) or 0)
    # 监禁类：被怪物囚禁到彻底沦陷
    if _state_count(states, "监禁:哥布林") >= 7 or (
        has("监禁:哥布林") and lewd >= 40 and will < 8
    ):
        return "哥布林的母狗"
    if _state_count(states, "监禁:兽人") >= 6 or (
        has("监禁:兽人") and lewd >= 50 and will < 6
    ):
        return "兽人的新娘"
    if _state_count(states, "监禁:触手") >= 4 or (has("监禁:触手") and lewd >= 60):
        return "触手的俘虏"
    # 怀孕类：被魔物产卵到屈服
    if has("怀孕:史莱姆") and lewd >= 50:
        return "史莱姆家族计划"
    if has("怀孕:触手") and lewd >= 55:
        return "魔物的母亲"
    # 债务类：卖身抵债到无法翻身
    if has("负债") and debt >= 500 and will < 6:
        return "奴隶娼妇"
    if has("负债") and debt >= 300 and lewd >= 50:
        return "娼馆里的女勇者"
    # 公共厕所：彻底放弃尊严
    if has("公共厕所") and lewd >= 50 and will < 5:
        return "肉便器的末路"
    # 实验耗材：被魔物反复侵犯到身体崩溃
    if has("契约:娼妇") and lewd >= 80 and will < 4:
        return "实验耗材"
    # 斗技场的败者
    if has("斗技场") and lewd >= 60 and will < 5:
        return "斗技场的败者"
    return None


def tick_imprisonment(stats: dict[str, Any]) -> dict[str, Any]:
    """监禁 tick：增加监禁天数 + 意志磨损 + 淫乱增长。返回 delta。"""
    states = stats.get("状态") or []
    delta: dict[str, Any] = {}
    for s in list(states):
        txt = str(s)
        for monster in ("哥布林", "兽人", "触手", "史莱姆"):
            prefix = f"监禁:{monster}"
            if txt.startswith(prefix):
                import re

                m = re.search(r"(\d+)", txt)
                cur_days = int(m.group(1)) if m else 1
                new_days = cur_days + 1
                delta["状态_del"] = delta.get("状态_del", []) + [txt]
                delta["状态_add"] = delta.get("状态_add", []) + [f"{prefix} {new_days}"]
                delta["意志"] = delta.get("意志", 0) - 1
                delta["淫乱"] = delta.get("淫乱", 0) + 1
                break
    return delta


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
    "若主角明确支付、交出、递出、花费金币/银币/铜币/钱币，金钱必须减少对应数量。"
)


async def judge_stat_delta(
    scene_text: str,
    current_stats: dict[str, Any],
    brain: BrainProvider | None = None,
    deterministic_text: str | None = None,
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
    delta = _parse_obj(raw)
    deterministic = infer_deterministic_delta(
        deterministic_text if deterministic_text is not None else scene_text,
        current_stats,
    )
    for key, val in deterministic.items():
        delta[key] = val
    return delta
