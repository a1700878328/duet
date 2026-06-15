"""Pydantic v2 request/response schemas."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: str


class RegisterIn(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=4, max_length=256)
    display_name: str = Field(min_length=1, max_length=128)


class LoginIn(BaseModel):
    username: str
    password: str


class AuthOut(BaseModel):
    token: str
    user: UserOut


class MeOut(BaseModel):
    user: UserOut


class MemberOut(BaseModel):
    user_id: int
    display_name: str
    character_name: str
    appearance: str | None = None
    persona: str | None = None
    voice_id: str | None = None
    voice_ref_url: str | None = None
    voice_ref_text: str | None = None
    avatar_url: str | None = None
    stats: dict[str, Any] | None = None


class RoomOut(BaseModel):
    id: int
    name: str
    owner_id: int
    ai_mode: str
    world_card: str | None = None
    week: int = 1
    day: int = 1
    time_slot: int = 0
    time_label: str = "冒险第1周·第1天·清晨"
    current_scene: str = ""
    scene_options: list[str] = Field(default_factory=list)
    current_task: dict[str, Any] | None = None
    task_offers: list[dict[str, Any]] = Field(default_factory=list)
    members: list[MemberOut]


class RoomCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    character_name: str = Field(min_length=1, max_length=128)
    world_card: str | None = Field(default=None, max_length=32)
    appearance: str | None = Field(default=None, max_length=512)


class RoomJoinIn(BaseModel):
    character_name: str = Field(min_length=1, max_length=128)
    appearance: str | None = Field(default=None, max_length=512)


class MeCardUpdateIn(BaseModel):
    character_name: str | None = Field(default=None, max_length=128)
    persona: str | None = Field(default=None, max_length=4000)
    appearance: str | None = Field(default=None, max_length=512)
    voice_id: str | None = Field(default=None, max_length=200)
    avatar_url: str | None = Field(default=None, max_length=256)
    voice_ref_url: str | None = Field(default=None, max_length=256)
    voice_ref_text: str | None = Field(default=None, max_length=1000)
    reset_stats: bool = False


class UserCharacterCardIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    persona: str = Field(default="", max_length=4000)
    appearance: str | None = Field(default=None, max_length=512)
    voice_id: str | None = Field(default=None, max_length=200)
    voice_ref_url: str | None = Field(default=None, max_length=256)
    voice_ref_text: str | None = Field(default=None, max_length=1000)
    avatar_url: str | None = Field(default=None, max_length=256)
    source_world_card: str | None = Field(default=None, max_length=32)


class UserCharacterCardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    persona: str
    appearance: str | None = None
    voice_id: str | None = None
    voice_ref_url: str | None = None
    voice_ref_text: str | None = None
    avatar_url: str | None = None
    source_world_card: str | None = None
    created_at: datetime
    updated_at: datetime


class NpcCardIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    persona: str = Field(default="", max_length=4000)
    appearance: str | None = Field(default=None, max_length=512)
    voice_id: str | None = Field(default=None, max_length=200)


class NpcGenIn(BaseModel):
    count: int = Field(default=4, ge=1, le=6)
    hint: str | None = Field(default=None, max_length=500)


class NpcCardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    persona: str
    appearance: str | None = None
    voice_id: str | None = None
    voice_ref_url: str | None = None
    voice_ref_text: str | None = None
    avatar_url: str | None = None
    active: bool = True
    scene: str | None = None
    discovered: str | None = None
    created_by_ai: bool


class NpcActiveIn(BaseModel):
    active: bool


class CharOptionsIn(BaseModel):
    count: int = Field(default=3, ge=1, le=4)
    hint: str | None = Field(default=None, max_length=500)


class CharDraftOut(BaseModel):
    """A non-persisted player-character draft for in-room selection."""

    name: str
    persona: str
    appearance: str | None = None
    voice_id: str | None = None
    avatar_url: str | None = None


class TtsIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    voice_id: str | None = Field(default=None, max_length=200)
    voice_ref_url: str | None = Field(default=None, max_length=256)
    voice_ref_text: str | None = Field(default=None, max_length=1000)
    regenerate: bool = False


class TtsOut(BaseModel):
    url: str


class CardsOut(BaseModel):
    players: list[MemberOut]
    npcs: list[NpcCardOut]


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    room_id: int
    seq: int
    author_type: str
    author_user_id: int | None
    speaker_label: str
    content: str
    created_at: datetime


class SceneLogEntryOut(BaseModel):
    scene: str
    time_label: str
    speaker_label: str
    content: str
    kind: str = "scene"


class SceneLogOut(BaseModel):
    current_scene: str
    scenes: list[str] = Field(default_factory=list)
    logs: dict[str, list[SceneLogEntryOut]] = Field(default_factory=dict)


class HealthOut(BaseModel):
    status: str = "ok"
