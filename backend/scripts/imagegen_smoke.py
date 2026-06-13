"""Smoke test: generate ONE single-character image and print the saved path.

Picks a registered LoRA character whose .safetensors is actually present in the
local loras dir (fail-closed if none), uses a benign SFW scene, and confirms a
non-zero PNG landed in app/media/generated/.

Run:  uv run python scripts/imagegen_smoke.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.imagegen.config import CHARACTER_LORAS  # noqa: E402
from app.imagegen.service import generate_single  # noqa: E402

LORAS_DIR = Path(r"C:\Users\a1700\Documents\ComfyUI\models\loras")

# Preferred registered chars (verified present earlier); falls back to scanning.
PREFERRED = ["堀北铃音", "佐仓爱里"]


def pick_char() -> str:
    for name in PREFERRED:
        entry = CHARACTER_LORAS.get(name)
        if entry and (LORAS_DIR / entry["file"]).exists():
            return name
    for name, entry in CHARACTER_LORAS.items():
        if (LORAS_DIR / entry["file"]).exists():
            return name
    raise SystemExit(
        "No registered LoRA file present in loras dir — cannot smoke test."
    )


async def main() -> int:
    char = pick_char()
    scene = "upper body, classroom, sitting at desk, gentle smile, simple background"
    print(f"Generating single image for: {char}")
    print(f"Scene: {scene}")
    result = await generate_single(char, scene, nsfw=False, seed=12345)

    if result.get("error"):
        print(f"FAILED: {result['error']}")
        return 1

    path = Path(result["path"])
    size = path.stat().st_size if path.exists() else 0
    print("OK")
    print(f"  character : {char}")
    print(f"  url       : {result['url']}")
    print(f"  path      : {result['path']}")
    print(f"  filename  : {result['filename']}")
    print(f"  prompt_id : {result['prompt_id']}")
    print(f"  bytes     : {size}")
    return 0 if size > 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
