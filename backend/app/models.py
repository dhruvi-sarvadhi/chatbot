"""The tables. One conversation is a session; a session owns messages and runs.

Why three tables rather than one blob of JSON per conversation:

  sessions  — the thing you list in a sidebar. Cheap to query without ever
              touching the message text.
  messages  — the transcript, in order. `seq` is the position in the
              conversation, so replaying it never depends on clock skew.
  runs      — what one answer cost: tokens, timing split, tool calls, dollars.
              Separate from `messages` because the interesting queries are
              aggregates ("spend by model this week") and they should not have
              to scan message bodies to answer.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class ChatSession(Base):
    """One conversation thread."""

    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)

    # Auto-filled from the first user message, editable from the UI.
    title: Mapped[str] = mapped_column(String(200), default="New chat")

    # The settings this conversation was last answered with. Stored so
    # reopening a session restores the configuration that produced it.
    provider: Mapped[str | None] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(120))
    system_prompt: Mapped[str | None] = mapped_column(Text)
    effort: Mapped[str | None] = mapped_column(String(16))
    max_tokens: Mapped[int | None] = mapped_column(Integer)
    web_search: Mapped[bool] = mapped_column(Boolean, default=False)
    search_backend: Mapped[str | None] = mapped_column(String(24))

    # What the browser reported at the time — useful when reading back a
    # transcript that says "tomorrow".
    timezone: Mapped[str | None] = mapped_column(String(64))
    locale: Mapped[str | None] = mapped_column(String(32))

    archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    # Distinct from updated_at, which also moves when you just rename a chat.
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Loaded on demand, not eagerly: the only place that wants the whole
    # transcript is the detail endpoint, which asks for it explicitly. Making
    # these eager would have every chat turn — and every row of the sidebar —
    # pull its full message list in just to append one row.
    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessage.seq",
    )
    runs: Mapped[list["ChatRun"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatRun.created_at",
    )

    __table_args__ = (
        # The sidebar query: newest activity first, archived chats hidden.
        Index("ix_sessions_archived_last_message", "archived", "last_message_at"),
    )


class ChatMessage(Base):
    """One turn in the transcript — a user question or a model answer."""

    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )

    # Position in the conversation. Ordering by timestamp would be wrong the
    # moment two rows land in the same millisecond.
    seq: Mapped[int] = mapped_column(Integer, nullable=False)

    # "user" or "assistant". The UI's settings-changed markers are not stored:
    # the chat schema does not accept them, and they describe the panel rather
    # than the conversation.
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="")

    # The model's summarized reasoning, when it produced any.
    thinking: Mapped[str] = mapped_column(Text, default="")

    provider: Mapped[str | None] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(120))

    # "searching" / "searched:<backend>:<n>" — the web-lookup badge.
    search: Mapped[str | None] = mapped_column(String(120))
    # The agent loop, one entry per step. JSONB so it can be queried, not just
    # read back: e.g. which turns actually called a tool.
    trace: Mapped[list | None] = mapped_column(JSONB)

    liked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)

    # Wall-clock for this answer, and how much of it was spent reasoning.
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    thinking_ms: Mapped[int | None] = mapped_column(Integer)

    # True when the stream died before the answer finished, so the UI can say
    # so instead of showing a truncated reply as if it were complete.
    incomplete: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    session: Mapped[ChatSession] = relationship(back_populates="messages")
    run: Mapped["ChatRun | None"] = relationship(
        back_populates="message", uselist=False, cascade="all, delete-orphan"
    )

    __table_args__ = (
        # Two rows can never claim the same slot in a conversation.
        UniqueConstraint("session_id", "seq", name="uq_messages_session_seq"),
        Index("ix_messages_session_seq", "session_id", "seq"),
    )


class ChatRun(Base):
    """What one answer cost. Mirrors `TurnMetrics` from the provider layer."""

    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE")
    )

    provider: Mapped[str] = mapped_column(String(32), default="")
    model: Mapped[str] = mapped_column(String(120), default="")
    effort: Mapped[str] = mapped_column(String(16), default="")

    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    reasoning_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cached_tokens: Mapped[int] = mapped_column(Integer, default=0)

    model_requests: Mapped[int] = mapped_column(Integer, default=0)
    tool_calls: Mapped[int] = mapped_column(Integer, default=0)

    total_ms: Mapped[int] = mapped_column(Integer, default=0)
    model_ms: Mapped[int] = mapped_column(Integer, default=0)
    tool_ms: Mapped[int] = mapped_column(Integer, default=0)

    search_backend: Mapped[str] = mapped_column(String(24), default="")

    # Numeric, not float: money summed over thousands of rows should not drift.
    # None when the model is not in the pricing table — never a guessed zero.
    cost_usd: Mapped[float | None] = mapped_column(Numeric(12, 6))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    session: Mapped[ChatSession] = relationship(back_populates="runs")
    message: Mapped[ChatMessage | None] = relationship(back_populates="run")

    __table_args__ = (
        # "spend by model over time" reads this index and nothing else.
        Index("ix_runs_model_created", "model", "created_at"),
        Index("ix_runs_session_created", "session_id", "created_at"),
    )
