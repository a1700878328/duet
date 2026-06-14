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
    avatar_url: str | None = None
    stats: dict[str, Any] | None = None


class RoomOut(BaseModel):
    id: int
    name: str
    owner_id: int
    ai_mode: str
    world_card: str | None = None
    week: int = 1
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
    voice_id: str | None = Field(default=None, max_length=64)


class NpcCardIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    persona: str = Field(default="", max_length=4000)
    appearance: str | None = Field(default=None, max_length=512)
    voice_id: str | None = Field(default=None, max_length=64)


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
    avatar_url: str | None = None
    active: bool = True
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


class HealthOut(BaseModel):
    status: str = "ok"
