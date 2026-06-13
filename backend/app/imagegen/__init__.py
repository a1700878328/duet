"""NSFW image-generation module for duet (SP-5).

Local async port of the .102 rp_system ComfyUI pipeline with its anti-hallucination
guards intact. Public surface:

    from app.imagegen import generate_single, generate_duo

registry/guard primitives are also re-exported for tests and wiring.
"""

from __future__ import annotations

from .guard import (
    PoisonedPromptError,
    UnverifiedNamedCharacter,
    assert_no_poisoned_colors,
    assert_workflow_safe,
)
from .registry import (
    UnverifiedCharacter,
    build_character_prompt,
    resolve,
)
from .service import generate_duo, generate_single

__all__ = [
    "generate_single",
    "generate_duo",
    "resolve",
    "build_character_prompt",
    "UnverifiedCharacter",
    "PoisonedPromptError",
    "UnverifiedNamedCharacter",
    "assert_no_poisoned_colors",
    "assert_workflow_safe",
]
