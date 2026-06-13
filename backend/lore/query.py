"""CLI to eyeball lore retrieval: `python -m lore.query "<query>" [k]`."""

from __future__ import annotations

import sys

from app.lore import store


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) < 2:
        print('usage: python -m lore.query "<query>" [k]')
        raise SystemExit(2)
    query = sys.argv[1]
    k = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    out = store.search_formatted(query, k=k)
    print(out or "(no hits — is the store ingested?)")


if __name__ == "__main__":
    main()
