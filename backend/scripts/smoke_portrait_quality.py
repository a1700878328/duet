"""Generate one portrait through the app's current portrait path."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.imagegen.portrait import generate_portrait


async def main() -> None:
    result = await generate_portrait(
        (
            "silver hair, long hair, violet eyes, colored eyelashes, "
            "half-closed eyes, faint smile, blush, parted lips, "
            "fantasy priestess robe, cleric vestments, holy symbol, staff, "
            "upper body, cathedral interior, soft warm light"
        ),
        name="test priestess",
        persona="dangerous dark priestess wearing cleric vestments",
        nsfw=True,
        seed=26061801,
    )
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
