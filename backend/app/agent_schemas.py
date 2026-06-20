"""Output schemas for named agent tasks.

These are intentionally lightweight: the app still owns domain-specific
coercion, but each task now returns a stable shape before call sites use it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentSchema:
    kind: type[Any]
    defaults: dict[str, Any] = field(default_factory=dict)
    required: tuple[str, ...] = ()
    item_schema: AgentSchema | None = None
    normalizer: Callable[[Any], Any] | None = None

    def validate(self, value: Any) -> Any:
        if self.kind is dict:
            if not isinstance(value, dict):
                value = {}
            out = {**self.defaults, **value}
            for key in self.required:
                if key not in out:
                    out[key] = self.defaults.get(key)
            value = out
        elif self.kind is list:
            if not isinstance(value, list):
                value = []
            if self.item_schema is not None:
                value = [
                    self.item_schema.validate(item)
                    for item in value
                    if isinstance(item, self.item_schema.kind)
                ]
        if self.normalizer is not None:
            value = self.normalizer(value)
        return value


JSON_OBJECT = AgentSchema(dict)
JSON_ARRAY = AgentSchema(list)

CHARACTER_DESIGN_SCHEMA = AgentSchema(
    dict,
    defaults={"name": "", "persona": "", "appearance": None, "voice_id": None},
    required=("name", "persona", "appearance", "voice_id"),
)

SCENE_PROMPT_SCHEMA = AgentSchema(
    dict,
    defaults={
        "scene_intent": "",
        "pose_relation": "",
        "core_action": "",
        "camera": "",
        "style": "",
        "character_locks": [],
        "must_include": [],
        "must_avoid": [],
        "positive": "",
        "negative": "",
        "composition": "",
    },
    required=("positive", "negative", "composition"),
)

NPC_DIALOGUE_SCHEMA = AgentSchema(
    dict,
    defaults={"dialogue": "", "state": "", "narration_request": None},
    required=("dialogue", "state", "narration_request"),
)

NPC_IMPULSE_SCHEMA = AgentSchema(
    dict,
    defaults={"speak": False, "urgency": 0, "reason": ""},
    required=("speak", "urgency", "reason"),
)

DIRECTOR_SCHEMA = AgentSchema(
    dict,
    defaults={
        "narration": None,
        "acts": [],
        "introduce": [],
        "time_jump": None,
        "time_advance_steps": 0,
        "time_reason": None,
        "unlock_scenes": [],
    },
)
