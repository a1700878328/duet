"""SQLAlchemy ORM models for SP-1.

Kept engine-agnostic: no SQLite-only types/SQL so a Postgres swap is trivial.
"""

from datetime import UTC, datetime

from sqlalchemy import (
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _now() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(default=_now)


class Room(Base):
    __tablename__ = "rooms"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    ai_mode: Mapped[str] = mapped_column(String(16), default="manual")
    # 世界卡：None=无设定；"ksim"=《女骑士模拟器》lore RAG。
    world_card: Mapped[str | None] = mapped_column(
        String(32), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(default=_now)

    members: Mapped[list["RoomMember"]] = relationship(
        back_populates="room", lazy="selectin"
    )


class RoomMember(Base):
    __tablename__ = "room_members"

    room_id: Mapped[int] = mapped_column(
        ForeignKey("rooms.id"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), primary_key=True
    )
    character_name: Mapped[str] = mapped_column(String(128))
    # 外貌卡：自然语言外貌（发色/瞳色/服装…），生图时织入 prompt 保一致。None=不指定。
    appearance: Mapped[str | None] = mapped_column(
        String(512), nullable=True, default=None
    )
    # 角色卡升级：性格/说话风格/背景（喂提示词），声音（per-玩家 TTS）。
    persona: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    voice_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, default=None
    )
    # 立绘：本地生图产出的头像 URL（/media/...）。None=未生成。
    avatar_url: Mapped[str | None] = mapped_column(
        String(256), nullable=True, default=None
    )
    joined_at: Mapped[datetime] = mapped_column(default=_now)

    room: Mapped["Room"] = relationship(back_populates="members")
    user: Mapped["User"] = relationship(lazy="selectin")


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("room_id", "seq", name="uq_message_room_seq"),
        Index("ix_message_room_seq", "room_id", "seq"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[int] = mapped_column(
        ForeignKey("rooms.id"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer)
    author_type: Mapped[str] = mapped_column(String(16))  # user | ai | system | image
    author_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    speaker_label: Mapped[str] = mapped_column(String(128))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class NpcCard(Base):
    """NPC 角色卡：AI 据世界卡生成 或 玩家手建/编辑。B 阶段用于各 NPC 独立发言。"""

    __tablename__ = "npc_cards"
    __table_args__ = (Index("ix_npc_card_room", "room_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    persona: Mapped[str] = mapped_column(Text, default="")
    appearance: Mapped[str | None] = mapped_column(
        String(512), nullable=True, default=None
    )
    voice_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, default=None
    )
    # 立绘：本地生图产出的头像 URL（/media/...）。None=未生成。
    avatar_url: Mapped[str | None] = mapped_column(
        String(256), nullable=True, default=None
    )
    # active=False 表示该 NPC 已被关闭/退出实时模拟（director 据此过滤）。
    active: Mapped[bool] = mapped_column(default=True)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    created_by_ai: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=_now)
