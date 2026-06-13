"""LIVE smoke test for the long-term memory module (SP-4).

Hits DeepSeek (deepseek-chat) for fact extraction + fastembed for embedding +
local qdrant for storage — this is REAL, not mocked.

remember(scope) one RP exchange about 艾琳's sword 破晓 (a relic from her
father), then search the same scope for "艾琳的剑" and confirm the
破晓 / 父亲 fact is recalled.

Run:  PYTHONUTF8=1 uv run python scripts/memory_smoke.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.memory import store  # noqa: E402

SCOPE = "room_smoke"
USER = "艾琳：我的剑叫破晓，是父亲留给我的遗物。"
AI = "[旁白]：破晓在火光下泛着寒芒。"
QUERY = "艾琳的剑"


def main() -> int:
    print("== remember ==")
    print(f"  scope: {SCOPE}")
    print(f"  user : {USER}")
    print(f"  ai   : {AI}")
    store.remember(SCOPE, USER, AI)

    # If the store degraded to no-op, search() returns "" — surface that clearly.
    client = store._get_client()
    if client is None:
        print("\nFAILED: memory store unavailable (degraded to no-op).")
        return 1

    print("\n== stored memories (raw) ==")
    try:
        all_mem = client.get_all(filters={"user_id": SCOPE})
        items = all_mem.get("results", []) if isinstance(all_mem, dict) else all_mem
        if not items:
            print("  (none extracted)")
        for it in items:
            print(f"  - {str((it or {}).get('memory') or '').strip()}")
    except Exception as exc:
        print(f"  (get_all failed: {exc})")

    print("\n== recall ==")
    print(f"  query: {QUERY}")
    block = store.search(SCOPE, QUERY, k=4)
    print(block or "  (empty)")

    text = block or ""
    ok = ("破晓" in text) or ("父亲" in text)
    print("\n== result ==")
    print("  RECALL OK" if ok else "  RECALL FAILED: expected 破晓/父亲 fact")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
