"""Pydantic v2 structured game-data models.

Replaces the loose ``dict[str, Any]`` in ``RoomMember.stats`` with typed schemas
so every stat change is validated. AI-produced deltas are still the primary
source of changes, but they pass through these models for sanitisation.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class StatusEffect(BaseModel):
    """A named status with duration/severity mechanics."""

    id: str = ""
    name: str = ""
    group: str = ""  # 监禁/怀孕/诅咒/契约/标记/债务
    source: str = ""  # 来源 NPC/怪物名
    days: int = 0
    severity: int = 1  # 1-5
    effects: dict[str, int] = Field(default_factory=dict)  # {属性: 修正值}
    escape_dc: int = 0  # 逃脱难度（监禁类用）
    description: str = ""


class Item(BaseModel):
    """A single inventory item with category, quantity, and optional effects."""

    id: str = ""
    name: str = ""
    type: str = "素材"  # 武器/防具/消耗品/任务道具/贵重品/素材
    quantity: int = 1
    description: str = ""
    equippable: bool = False
    usable: bool = False
    effects: dict[str, int] = Field(default_factory=dict)
    icon: str = ""


class CharacterSheet(BaseModel):
    """Full typed stat block stored as JSON in ``RoomMember.stats``."""

    # ── 基础属性 ──
    职业: str = "冒险者"
    冒险者等级: str = "E"
    等级: int = 1
    经验: int = 0
    力量: int = 10
    敏捷: int = 10
    智力: int = 10
    意志: int = 10
    金钱: int = 100
    负债: int = 0

    # ── 淫乱向开发 ──
    淫乱: int = 0
    欲望: int = 0
    阴道开发: int = 0
    阴道经验: int = 0
    口腔开发: int = 0
    口腔经验: int = 0
    胸部开发: int = 0
    胸部经验: int = 0
    菊穴开发: int = 0
    菊穴经验: int = 0
    高潮经验: int = 0
    露出癖: int = 0
    露出经验: int = 0
    受虐狂: int = 0
    受虐经验: int = 0
    精液中毒: int = 0
    精液经验: int = 0
    百合经验: int = 0
    自慰经验: int = 0

    # ── 结构化子对象 ──
    物品栏: list[Item] = Field(default_factory=list)
    状态: list[StatusEffect] = Field(default_factory=list)
    好感度: dict[str, int] = Field(default_factory=dict)

    # ── 兼容旧格式的降级字段 ──
    物品: list[str] = Field(default_factory=list, description="旧版字符串物品列表")
    # Status effects also stored as strings in a list for backward compat
    _raw_states: list[str] = []

    def model_post_init(self, __context: Any) -> None:
        """Backfill legacy fields from structured data."""
        if not self.物品:
            self.物品 = [i.name for i in self.物品栏]
        if not self.好感度:
            self.好感度 = {}


# ── Helper functions ──


def parse_stats(data: dict[str, Any] | None) -> CharacterSheet:
    """Parse a raw stats dict into a validated CharacterSheet.

    Handles both new structured and legacy flat formats gracefully:
    - ``物品`` list of strings → promoted to ``物品栏`` Items
    - ``状态`` list of strings → promoted to ``状态`` StatusEffects
    - Unknown keys are discarded (instead of silently kept).
    """
    if not data:
        return CharacterSheet()

    cleaned: dict[str, Any] = {}

    # Copy known scalar fields (skip known sub-objects)
    KNOWN_FIELDS = set(CharacterSheet.model_fields.keys()) - {
        "物品栏",
        "状态",
        "好感度",
        "物品",
    }
    for k in KNOWN_FIELDS:
        v = data.get(k)
        if v is not None:
            cleaned[k] = int(v) if not isinstance(v, int) else v

    # 物品栏 — promote from legacy string list
    legacy_items = data.get("物品") or []
    if legacy_items and not data.get("物品栏"):
        seen: dict[str, int] = {}
        for name in legacy_items:
            name = str(name).strip()
            if name:
                seen[name] = seen.get(name, 0) + 1
        cleaned["物品栏"] = [Item(name=n, quantity=q) for n, q in seen.items()]

    # 状态 — promote from legacy string list
    legacy_states = data.get("状态") or []
    if legacy_states and not data.get("状态"):
        for s in legacy_states:
            if s:
                cleaned["状态"].append(_parse_state_string(str(s)))

    # 好感度
    cleaned["好感度"] = dict(data.get("好感度") or {})

    return CharacterSheet(**cleaned)


def sheet_to_flat(sheet: CharacterSheet) -> dict[str, Any]:
    """Convert a CharacterSheet back to a flat dict for JSON storage.

    Includes both structured fields and legacy-compatible flat collections.
    """
    raw = sheet.model_dump(exclude={"物品栏", "状态", "物品", "_raw_states"})
    raw["物品"] = [i.name for i in sheet.物品栏 for _ in range(i.quantity)]
    raw["状态"] = [_status_to_legacy(s) for s in sheet.状态]
    raw["好感度"] = dict(sheet.好感度)
    return raw


def _status_to_legacy(s: StatusEffect) -> str:
    """Convert a StatusEffect back to legacy string format, e.g. '监禁:哥布林 5'."""
    if s.days > 0:
        return f"{s.id} {s.days}"
    return s.id


def status_from_legacy(text: str) -> StatusEffect:
    """Parse a legacy status string like '监禁:哥布林 5' into a StatusEffect."""
    return _parse_state_string(text)


def _parse_state_string(text: str) -> StatusEffect:
    """Parse '监禁:哥布林 5' → StatusEffect(id='监禁:哥布林', days=5)."""
    import re

    text = text.strip()
    m = re.search(r"(\d+)", text)
    days = int(m.group(1)) if m else 0
    clean_id = re.sub(r"\s*\d+\s*$", "", text).strip()
    # Infer group from prefix
    group = ""
    for prefix in ("监禁", "怀孕", "契约", "诅咒", "标记"):
        if clean_id.startswith(prefix):
            group = prefix
            break
    if not group and "负债" in clean_id:
        group = "债务"
    return StatusEffect(
        id=clean_id,
        name=clean_id,
        group=group,
        days=days,
        description=clean_id,
    )
