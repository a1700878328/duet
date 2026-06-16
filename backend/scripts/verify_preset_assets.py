"""Verify default preset portraits and voice references.

Run from ``backend``:

    uv run python scripts/verify_preset_assets.py --world ksim

This is intentionally a local check: generated media lives under ``app/media``
and is ignored by git, so the script verifies the current machine's manifest
and files before handoff.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.preset_assets import MANIFEST_PATH, preset_asset_key
from app.rooms import _PROTAGONIST_CARDS
from app.world_presets import PRESETS, hidden_initial_npc_names, preset_npcs

REQUIRED_FIELDS = ("avatar_url", "voice_id", "voice_ref_url", "voice_ref_text")


def _load_manifest() -> dict[str, Any]:
    try:
        data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - script should print friendly errors
        raise SystemExit(f"failed to read manifest: {MANIFEST_PATH}: {exc}") from exc
    assets = data.get("assets") if isinstance(data, dict) else None
    if not isinstance(assets, dict):
        raise SystemExit(f"manifest has no assets object: {MANIFEST_PATH}")
    return assets


def _cards_for_world(
    world: str, *, include_hidden: bool
) -> list[tuple[str, str, bool]]:
    cards: list[tuple[str, str, bool]] = []
    protagonist = _PROTAGONIST_CARDS.get(world)
    if protagonist is not None:
        cards.append(("protagonist", protagonist.name, False))

    npcs = list(PRESETS.get(world, [])) if include_hidden else preset_npcs(world)
    hidden = hidden_initial_npc_names(world)
    for npc in npcs:
        name = str(npc.get("name") or "").strip()
        if name:
            cards.append(("npc", name, name in hidden))
    return cards


def _path_for_url(url: str) -> Path | None:
    if not url.startswith("/media/"):
        return None
    return BACKEND_DIR / "app" / Path(*url.removeprefix("/").split("/"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--world", default="ksim")
    parser.add_argument(
        "--visible-only",
        action="store_true",
        help="Check only initially visible preset NPCs, excluding hidden forms.",
    )
    parser.add_argument(
        "--no-file-check",
        action="store_true",
        help="Only check manifest fields, not local app/media files.",
    )
    args = parser.parse_args()

    assets = _load_manifest()
    cards = _cards_for_world(args.world, include_hidden=not args.visible_only)
    errors: list[str] = []

    for kind, name, hidden in cards:
        key = preset_asset_key(args.world, kind, name)
        asset = assets.get(key)
        label = f"{key}{' (hidden)' if hidden else ''}"
        if not isinstance(asset, dict):
            errors.append(f"{label}: missing manifest entry")
            continue
        for field in REQUIRED_FIELDS:
            value = asset.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{label}: missing {field}")
                continue
            if args.no_file_check or field not in {"avatar_url", "voice_ref_url"}:
                continue
            path = _path_for_url(value)
            if path is not None and not path.exists():
                errors.append(f"{label}: {field} file missing: {path}")

    if errors:
        print("Preset asset check failed:")
        for err in errors:
            print(f"- {err}")
        raise SystemExit(1)

    scope = "visible" if args.visible_only else "all"
    print(
        f"Preset asset check passed: world={args.world} "
        f"scope={scope} cards={len(cards)}"
    )


if __name__ == "__main__":
    main()
