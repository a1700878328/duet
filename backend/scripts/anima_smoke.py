# /// script
# requires-python = ">=3.13"
# dependencies = ["httpx"]
# ///
"""Anima DiT multi-person live smoke.

Run from backend/ with: PYTHONUTF8=1 uv run python scripts/anima_smoke.py

1) one multi-person gen (random seed) -> assert PNG > 50KB
2) same prompt + same fixed seed, twice -> report byte-equality (determinism)
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.imagegen.anima import generate_anima  # noqa: E402

MULTI = (
    "2 characters, a female knight in silver armor with long blonde hair on the "
    "left, and a horned succubus with purple hair and red eyes on the right, "
    "tavern interior, talking, anime style, masterpiece"
)


def _bytes_of(res: dict) -> int:
    p = res.get("path")
    return Path(p).stat().st_size if p and Path(p).exists() else 0


async def main() -> None:
    print("=== gen 1: multi-person, landscape, random seed ===")
    r1 = await generate_anima(MULTI, landscape=True)
    print("result:", r1)
    if r1.get("error"):
        print("FAIL gen1:", r1["error"])
        return
    n1 = _bytes_of(r1)
    print(f"path={r1['path']}  bytes={n1}")
    assert n1 > 50_000, f"PNG too small: {n1} bytes"
    print("OK gen1: PNG > 50KB")

    print("\n=== seed determinism: same prompt + fixed seed=424242, twice ===")
    a = await generate_anima(MULTI, landscape=True, seed=424242)
    b = await generate_anima(MULTI, landscape=True, seed=424242)
    if a.get("error") or b.get("error"):
        print("FAIL determinism:", a.get("error"), b.get("error"))
        return
    ba = Path(a["path"]).read_bytes()
    bb = Path(b["path"]).read_bytes()
    print(f"a={a['path']} ({len(ba)} B)")
    print(f"b={b['path']} ({len(bb)} B)")
    identical = ba == bb
    print(f"byte-identical: {identical}")
    if not identical:
        print(f"size delta: {abs(len(ba) - len(bb))} B (smaller = more consistent)")


if __name__ == "__main__":
    asyncio.run(main())
