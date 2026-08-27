"""Every database read and write the app performs, in one place.

Nothing above this module builds a query. The endpoints call these functions,
which means persistence can never accidentally become half-implemented in a
route handler — and a failure to save is handled here, once, rather than in
every caller.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import asdict
from datetime import datetime, timezone as tz

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from .models import ChatMessage, ChatRun, ChatSession
from .pricing import estimate_cost

log = logging.getLogger("chatbot.store")

TITLE_MAX = 60


# ── helpers ────────────────────────────────────────────────────────────────


def as_uuid(value: str | uuid.UUID | None) -> uuid.UUID | None:
    """Parse an id from the wire. Returns None for anything unusable.

    Callers treat None as "not found" rather than raising, because a stale id
    in localStorage is a normal thing for a browser to send, not an error.
    """
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def title_from(text: str) -> str:
    """First line of the opening question, trimmed to fit a sidebar row."""
    line = " ".join(text.strip().split())
    if not line:
        return "New chat"
    return line if len(line) <= TITLE_MAX else line[: TITLE_MAX - 1].rstrip() + "…"


# ── sessions ───────────────────────────────────────────────────────────────


def create_session(db: Session, *, title: str = "New chat", **fields) -> ChatSession:
    session = ChatSession(title=title, **fields)
    db.add(session)
    db.flush()  # populate id/created_at without ending the transaction
    return session


def get_session(db: Session, session_id: str | uuid.UUID) -> ChatSession | None:
    """The session row alone — no transcript. This is the hot path."""
    sid = as_uuid(session_id)
    return db.get(ChatSession, sid) if sid else None


def get_session_full(db: Session, session_id: str | uuid.UUID) -> ChatSession | None:
    """The session with its transcript and metrics, for reopening it.

    Eager-loads in three queries instead of one per message: without the
    `ChatMessage.run` hop, rendering a 100-turn conversation would issue 100
    extra selects to fetch each turn's cost.
    """
    sid = as_uuid(session_id)
    if not sid:
        return None
    return db.execute(
        select(ChatSession)
        .where(ChatSession.id == sid)
        .options(
            selectinload(ChatSession.messages).selectinload(ChatMessage.run),
            selectinload(ChatSession.runs),
        )
    ).scalar_one_or_none()


def list_sessions(
    db: Session, *, include_archived: bool = False, limit: int = 100, offset: int = 0
) -> list[dict]:
    """Sidebar rows: the session plus its counts and totals, in one query.

    Aggregated in SQL rather than by loading the messages, so listing 100
    conversations costs one round-trip and never touches a message body.
    """
    msg_counts = (
        select(
            ChatMessage.session_id.label("sid"),
            func.count(ChatMessage.id).label("message_count"),
        )
        # Failed turns are kept for debugging but are not conversation, so
        # the sidebar count matches what you actually see in the transcript.
        .where(ChatMessage.incomplete.is_(False))
        .group_by(ChatMessage.session_id)
        .subquery()
    )
    run_totals = (
        select(
            ChatRun.session_id.label("sid"),
            func.count(ChatRun.id).label("run_count"),
            func.coalesce(func.sum(ChatRun.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(ChatRun.output_tokens), 0).label("output_tokens"),
            func.sum(ChatRun.cost_usd).label("cost_usd"),
        )
        .group_by(ChatRun.session_id)
        .subquery()
    )

    stmt = (
        select(
            ChatSession,
            func.coalesce(msg_counts.c.message_count, 0),
            func.coalesce(run_totals.c.run_count, 0),
            func.coalesce(run_totals.c.input_tokens, 0),
            func.coalesce(run_totals.c.output_tokens, 0),
            run_totals.c.cost_usd,
        )
        .outerjoin(msg_counts, msg_counts.c.sid == ChatSession.id)
        .outerjoin(run_totals, run_totals.c.sid == ChatSession.id)
        # Never-used sessions have no last_message_at; fall back to created_at
        # so a brand-new chat still sorts to the top.
        .order_by(
            func.coalesce(ChatSession.last_message_at, ChatSession.created_at).desc()
        )
        .limit(limit)
        .offset(offset)
    )
    if not include_archived:
        stmt = stmt.where(ChatSession.archived.is_(False))

    rows = []
    for session, n_msg, n_run, tok_in, tok_out, cost in db.execute(stmt).all():
        rows.append(
            {
                "session": session,
                "message_count": n_msg,
                "run_count": n_run,
                "input_tokens": tok_in,
                "output_tokens": tok_out,
                "cost_usd": float(cost) if cost is not None else None,
            }
        )
    return rows


def update_session(db: Session, session: ChatSession, **fields) -> ChatSession:
    for key, value in fields.items():
        if value is not None and hasattr(session, key):
            setattr(session, key, value)
    db.flush()
    return session


def delete_session(db: Session, session: ChatSession) -> None:
    # Messages and runs go with it — ON DELETE CASCADE in the schema.
    db.delete(session)


def delete_all_sessions(db: Session, *, archived_only: bool = False) -> int:
    stmt = delete(ChatSession)
    if archived_only:
        stmt = stmt.where(ChatSession.archived.is_(True))
    return db.execute(stmt).rowcount or 0


def touch(db: Session, session: ChatSession) -> None:
    session.last_message_at = datetime.now(tz.utc)
    db.flush()


# ── messages ───────────────────────────────────────────────────────────────


def next_seq(db: Session, session_id: uuid.UUID) -> int:
    """The next free slot in a conversation.

    Computed from the table rather than from len(messages) on the client, so
    two tabs posting to the same session cannot both claim the same position
    — the unique constraint would reject the second one either way.
    """
    current = db.execute(
        select(func.max(ChatMessage.seq)).where(ChatMessage.session_id == session_id)
    ).scalar()
    return 0 if current is None else current + 1


def add_message(
    db: Session,
    session: ChatSession,
    *,
    role: str,
    content: str = "",
    seq: int | None = None,
    **fields,
) -> ChatMessage:
    message = ChatMessage(
        session_id=session.id,
        seq=next_seq(db, session.id) if seq is None else seq,
        role=role,
        content=content,
        **fields,
    )
    db.add(message)
    session.last_message_at = datetime.now(tz.utc)

    # First real question names the conversation.
    if role == "user" and session.title in ("", "New chat") and content.strip():
        session.title = title_from(content)

    db.flush()
    return message


def sync_history(db: Session, session: ChatSession, history: list[dict]) -> None:
    """Store any messages from the client that we have not saved yet.

    The frontend sends the whole conversation on every turn (LLM APIs are
    stateless), so this reconciles that view with ours: it appends what is
    missing and leaves what is already there alone. That is what makes an
    older conversation, or one started before the database existed, land in
    Postgres the first time it is used again.

    Matching is by content, not by counting rows. A turn that failed leaves an
    `incomplete` row behind that the client never replays, so the two views
    are already off by one — a positional match would then skip every later
    question. Comparing (role, content) walks past that correctly.
    """
    stored = (
        db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session.id)
            .order_by(ChatMessage.seq)
        )
        .scalars()
        .all()
    )
    # Failed turns are bookkeeping, not conversation: the client does not send
    # them back, so they must not be lined up against what it does send.
    real = [m for m in stored if not m.incomplete]

    # Walk both views together and stop at the first thing we do not have.
    start = 0
    while start < len(history) and start < len(real):
        item = history[start]
        row = real[start]
        if row.role != item.get("role") or row.content != item.get("content", ""):
            break
        start += 1

    for item in history[start:]:
        # seq is left to the table (max + 1) rather than to the loop index, so
        # appended rows land after any incomplete row instead of colliding
        # with it on the unique (session_id, seq) constraint.
        add_message(
            db,
            session,
            role=item.get("role", "user"),
            content=item.get("content", ""),
        )


def set_liked(db: Session, message_id: str | uuid.UUID, liked: bool) -> ChatMessage | None:
    mid = as_uuid(message_id)
    message = db.get(ChatMessage, mid) if mid else None
    if message:
        message.liked = liked
        db.flush()
    return message


# ── runs ───────────────────────────────────────────────────────────────────


def add_run(
    db: Session,
    session: ChatSession,
    metrics,
    *,
    message: ChatMessage | None = None,
) -> ChatRun:
    """Persist one turn's metrics. `metrics` is a `TurnMetrics` dataclass."""
    data = asdict(metrics)
    run = ChatRun(
        session_id=session.id,
        message_id=message.id if message else None,
        cost_usd=estimate_cost(
            data.get("model", ""), data.get("input_tokens", 0), data.get("output_tokens", 0)
        ),
        **{k: v for k, v in data.items() if hasattr(ChatRun, k)},
    )
    db.add(run)
    db.flush()
    return run


def message_count(db: Session, session_id: str | uuid.UUID) -> int:
    """Real turns in a conversation, counted in SQL rather than by loading."""
    return db.execute(
        select(func.count(ChatMessage.id)).where(
            ChatMessage.session_id == as_uuid(session_id),
            ChatMessage.incomplete.is_(False),
        )
    ).scalar_one()


def session_runs(db: Session, session_id: str | uuid.UUID) -> list[ChatRun]:
    """Every turn's cost for one conversation, oldest first."""
    return list(
        db.execute(
            select(ChatRun)
            .where(ChatRun.session_id == as_uuid(session_id))
            .order_by(ChatRun.created_at)
        ).scalars()
    )


def session_totals(db: Session, session_id: uuid.UUID) -> dict:
    row = db.execute(
        select(
            func.count(ChatRun.id),
            func.coalesce(func.sum(ChatRun.input_tokens), 0),
            func.coalesce(func.sum(ChatRun.output_tokens), 0),
            func.sum(ChatRun.cost_usd),
        ).where(ChatRun.session_id == session_id)
    ).one()
    return {
        "run_count": row[0],
        "input_tokens": row[1],
        "output_tokens": row[2],
        "cost_usd": float(row[3]) if row[3] is not None else None,
    }


def stats(db: Session) -> dict:
    """Everything-so-far analytics, plus a per-model breakdown."""
    totals = db.execute(
        select(
            func.count(ChatRun.id),
            func.coalesce(func.sum(ChatRun.input_tokens), 0),
            func.coalesce(func.sum(ChatRun.output_tokens), 0),
            func.coalesce(func.sum(ChatRun.reasoning_tokens), 0),
            func.coalesce(func.sum(ChatRun.cached_tokens), 0),
            func.coalesce(func.sum(ChatRun.tool_calls), 0),
            func.sum(ChatRun.cost_usd),
            func.coalesce(func.avg(ChatRun.total_ms), 0),
        )
    ).one()

    by_model = [
        {
            "model": model,
            "provider": provider,
            "runs": runs,
            "input_tokens": tok_in,
            "output_tokens": tok_out,
            "cost_usd": float(cost) if cost is not None else None,
            "avg_ms": int(avg_ms or 0),
        }
        for model, provider, runs, tok_in, tok_out, cost, avg_ms in db.execute(
            select(
                ChatRun.model,
                ChatRun.provider,
                func.count(ChatRun.id),
                func.coalesce(func.sum(ChatRun.input_tokens), 0),
                func.coalesce(func.sum(ChatRun.output_tokens), 0),
                func.sum(ChatRun.cost_usd),
                func.avg(ChatRun.total_ms),
            )
            .group_by(ChatRun.model, ChatRun.provider)
            .order_by(func.count(ChatRun.id).desc())
        ).all()
    ]

    return {
        "sessions": db.execute(select(func.count(ChatSession.id))).scalar_one(),
        "messages": db.execute(
            select(func.count(ChatMessage.id)).where(ChatMessage.incomplete.is_(False))
        ).scalar_one(),
        "runs": totals[0],
        "input_tokens": totals[1],
        "output_tokens": totals[2],
        "reasoning_tokens": totals[3],
        "cached_tokens": totals[4],
        "tool_calls": totals[5],
        "cost_usd": float(totals[6]) if totals[6] is not None else None,
        "avg_ms": int(totals[7] or 0),
        "by_model": by_model,
    }
