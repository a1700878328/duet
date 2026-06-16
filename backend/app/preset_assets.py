"""Default generated media for world-card character presets.

The world preset files describe characters; this module attaches generated
artifacts (portrait URL, voice reference URL/text, provider voice id) from a
separate manifest. Keeping generated paths out of the preset definitions makes
it much harder for future handoffs to accidentally rewrite role logic.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ASSET_FIELDS = ("voice_id", "voice_ref_url", "voice_ref_text", "avatar_url")
MANIFEST_PATH = Path(__file__).with_name("preset_asset_manifest.json")

_cache: dict[str, dict[str, Any]] | None = None
_cache_mtime: float | None = None


def preset_asset_key(world_card: str | None, kind: str, name: str) -> str:
    world = (world_card or "").strip()
    return f"{world}:{kind}:{name.strip()}"


def load_preset_assets() -> dict[str, dict[str, Any]]:
    global _cache, _cache_mtime
    try:
        mtime = MANIFEST_PATH.stat().st_mtime
    except FileNotFoundError:
        _cache = {}
        _cache_mtime = None
        return {}
    if _cache is not None and _cache_mtime == mtime:
        return _cache
    try:
        raw = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except Exception:
        raw = {}
    assets = raw.get("assets") if isinstance(raw, dict) else {}
    if not isinstance(assets, dict):
        assets = {}
    normalized: dict[str, dict[str, Any]] = {}
    for key, value in assets.items():
        if isinstance(key, str) and isinstance(value, dict):
            normalized[key] = {
                field: value[field]
                for field in ASSET_FIELDS
                if isinstance(value.get(field), str) and value.get(field)
            }
    _cache = normalized
    _cache_mtime = mtime
    return normalized


def preset_asset_for(
    world_card: str | None, kind: str, name: str | None
) -> dict[str, Any]:
    if not name:
        return {}
    asset = load_preset_assets().get(preset_asset_key(world_card, kind, name))
    return dict(asset) if asset else {}


def apply_preset_assets(
    world_card: str | None, kind: str, card: dict[str, Any]
) -> dict[str, Any]:
    """Return a card dict with generated default assets attached.

    ``voice_id`` from the manifest intentionally overrides preset voice
    descriptions when a reference sample exists, because provider-native IDs
    are what make Eleven/Fish reuse the generated character voice.
    """

    out = dict(card)
    asset = preset_asset_for(world_card, kind, str(card.get("name") or ""))
    if not asset:
        return out
    has_reference = bool(asset.get("voice_ref_url") and asset.get("voice_ref_text"))
    for field in ASSET_FIELDS:
        value = asset.get(field)
        if not value:
            continue
        if field == "voice_id" and has_reference:
            out[field] = value
        elif not out.get(field):
            out[field] = value
    return out
