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
from .portrait import generate_portrait
from .registry import (
    UnverifiedCharacter,
    build_character_prompt,
    resolve,
)
from .scene_prompt import build_scene_prompt
from .service import (
    generate_duo,
    generate_raw_duo,
    generate_raw_single,
    generate_single,
)

__all__ = [
    "generate_single",
    "generate_duo",
    "generate_raw_single",
    "generate_raw_duo",
    "generate_portrait",
    "build_scene_prompt",
    "resolve",
    "build_character_prompt",
    "UnverifiedCharacter",
    "PoisonedPromptError",
    "UnverifiedNamedCharacter",
    "assert_no_poisoned_colors",
    "assert_workflow_safe",
]
