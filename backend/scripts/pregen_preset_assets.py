"""Pre-generate default portraits and role voice references for world presets.

Run from ``backend``:

    uv run python scripts/pregen_preset_assets.py --world ksim

The script writes ``app/preset_asset_manifest.json`` after every character so
new rooms can load generated media immediately. Generated media files live under
``app/media`` and are intentionally git-ignored local artifacts.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.imagegen.anima import char_seed
from app.imagegen.portrait import generate_portrait
from app.preset_assets import MANIFEST_PATH, preset_asset_key
from app.rooms import _PROTAGONIST_CARDS, _design_and_write_voice
from app.world_presets import PRESETS, hidden_initial_npc_names, preset_npcs


def _load_manifest() -> dict[str, Any]:
    if not MANIFEST_PATH.exists():
        return {"version": 1, "assets": {}}
    try:
        data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except Exception:
        data = {"version": 1, "assets": {}}
    if not isinstance(data, dict):
        data = {"version": 1, "assets": {}}
    if not isinstance(data.get("assets"), dict):
        data["assets"] = {}
    data.setdefault("version", 1)
    return data


def _save_manifest(data: dict[str, Any]) -> None:
    MANIFEST_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _with_prompt_edits(
    base: str | None,
    *,
    override: str | None,
    prefix: str | None,
    suffix: str | None,
) -> str | None:
    if override:
        return override.strip()
    parts = [prefix, base, suffix]
    text = ", ".join(str(p).strip() for p in parts if str(p or "").strip())
    return text or None


def _cards_for_world(
    world: str, *, include_hidden: bool, names: set[str] | None
) -> list[tuple[str, dict[str, Any]]]:
    cards: list[tuple[str, dict[str, Any]]] = []
    protagonist = _PROTAGONIST_CARDS.get(world)
    if protagonist is not None:
        cards.append(("protagonist", protagonist.model_dump(exclude_none=True)))

    if include_hidden:
        npcs = list(PRESETS.get(world, []))
    else:
        npcs = preset_npcs(world)
    hidden = hidden_initial_npc_names(world)
    for npc in npcs:
        card = dict(npc)
        if card.get("name") in hidden:
            card.setdefault("asset_note", "hidden-initial-form")
        cards.append(("npc", card))

    if names:
        cards = [(kind, card) for kind, card in cards if str(card.get("name")) in names]
    return cards


async def _generate_card(
    *,
    world: str,
    kind: str,
    card: dict[str, Any],
    manifest: dict[str, Any],
    force_image: bool,
    force_voice: bool,
    skip_image: bool,
    skip_voice: bool,
    candidate_only: bool,
    appearance_override: str | None,
    appearance_prefix: str | None,
    appearance_suffix: str | None,
    persona_override: str | None,
    nsfw_image: bool,
) -> None:
    name = str(card.get("name") or "").strip()
    if not name:
        return
    key = preset_asset_key(world, kind, name)
    assets = manifest.setdefault("assets", {})
    asset = assets.setdefault(key, {})
    print(f"\n[{kind}] {name}")

    if not skip_image and (candidate_only or force_image or not asset.get("avatar_url")):
        appearance = _with_prompt_edits(
            card.get("appearance") or name or "1person",
            override=appearance_override,
            prefix=appearance_prefix,
            suffix=appearance_suffix,
        )
        persona = _with_prompt_edits(
            card.get("persona"),
            override=persona_override,
            prefix=None,
            suffix=None,
        )
        result = await generate_portrait(
            appearance or name or "1person",
            name=name,
            persona=persona,
            nsfw=nsfw_image,
            seed=char_seed(0, f"{world}:{kind}:{name}"),
            mode="reference",
        )
        if result.get("url"):
            if candidate_only:
                print(f"  candidate image: {result['url']}")
            else:
                asset["avatar_url"] = result["url"]
                print(f"  image: {result['url']}")
        else:
            print(f"  image failed: {result.get('error', 'unknown error')}")
    else:
        print("  image: cached/skipped")

    has_voice = asset.get("voice_id") and asset.get("voice_ref_url")
    if not skip_voice and (force_voice or not has_voice):
        try:
            voice_id, ref_url, ref_text = await _design_and_write_voice(
                room_id=0,
                owner_key=f"preset:{world}:{kind}",
                name=name,
                persona=card.get("persona"),
                appearance=card.get("appearance"),
                voice_id=card.get("voice_id"),
            )
        except Exception as exc:
            print(f"  voice failed: {exc}")
        else:
            asset["voice_id"] = voice_id
            asset["voice_ref_url"] = ref_url
            asset["voice_ref_text"] = ref_text
            print(f"  voice: {ref_url}")
    else:
        print("  voice: cached/skipped")

    if candidate_only:
        return
    if not asset:
        assets.pop(key, None)
    _save_manifest(manifest)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--world", default="ksim")
    parser.add_argument("--include-hidden", action="store_true")
    parser.add_argument("--name", action="append", default=[])
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--force-image", action="store_true")
    parser.add_argument("--force-voice", action="store_true")
    parser.add_argument("--skip-image", action="store_true")
    parser.add_argument("--skip-voice", action="store_true")
    parser.add_argument(
        "--candidate-only",
        action="store_true",
        help="Generate media and print URLs without writing the manifest.",
    )
    parser.add_argument("--appearance-override", default=None)
    parser.add_argument("--appearance-prefix", default=None)
    parser.add_argument("--appearance-suffix", default=None)
    parser.add_argument("--persona-override", default=None)
    parser.add_argument(
        "--nsfw-image",
        action="store_true",
        help="Generate preset default images with NSFW portrait prompting. Defaults to SFW.",
    )
    args = parser.parse_args()

    names = {str(n).strip() for n in args.name if str(n).strip()} or None
    cards = _cards_for_world(args.world, include_hidden=args.include_hidden, names=names)
    if args.limit > 0:
        cards = cards[: args.limit]
    manifest = _load_manifest()
    print(f"Manifest: {MANIFEST_PATH}")
    print(f"Cards: {len(cards)}")

    for kind, card in cards:
        await _generate_card(
            world=args.world,
            kind=kind,
            card=card,
            manifest=manifest,
            force_image=args.force_image,
            force_voice=args.force_voice,
            skip_image=args.skip_image,
            skip_voice=args.skip_voice,
            candidate_only=args.candidate_only,
            appearance_override=args.appearance_override,
            appearance_prefix=args.appearance_prefix,
            appearance_suffix=args.appearance_suffix,
            persona_override=args.persona_override,
            nsfw_image=args.nsfw_image,
        )

    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
