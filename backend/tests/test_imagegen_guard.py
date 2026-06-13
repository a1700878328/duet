"""Pure-logic tests for the color-poison guard. No ComfyUI / SSH access."""

from __future__ import annotations

import pytest

from app.imagegen.guard import (
    PoisonedPromptError,
    assert_no_poisoned_colors,
)

# 莉音/Rio is a registered prompt-only char whose wrong colors include
# "silver hair" / "blue eyes". Mixing her trigger with a wrong color must reject.
POISONED = (
    "masterpiece, tsukatsuki rio (blue archive), silver hair, blue eyes, "
    "classroom, simple background"
)
CLEAN = (
    "masterpiece, tsukatsuki rio (blue archive), black hair, red eyes, "
    "classroom, simple background"
)


def test_poisoned_prompt_rejected() -> None:
    with pytest.raises(PoisonedPromptError):
        assert_no_poisoned_colors([POISONED])


def test_clean_prompt_passes() -> None:
    assert_no_poisoned_colors([CLEAN])  # must not raise


def test_unrelated_prompt_passes() -> None:
    assert_no_poisoned_colors(
        ["masterpiece, scenery, mountains, blue sky, no characters"]
    )
