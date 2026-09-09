"""Let the model read and write real Clarix projects and tasks.

Unlike `web_search`, every call here CHANGES SOMETHING in a live workspace, so
the design leans conservative in three specific ways:

1. **One tool, not eight.** The model picks an `action` rather than choosing
   between eight similarly-named tools. Fewer tools means fewer wrong picks,
   and the whole surface fits in one description the model actually reads.

2. **Never raises.** A tool that raises aborts the turn; a tool that returns
   "that failed because X" lets the model tell the user, or fix its arguments
   and try again. Every failure comes back as text.

3. **Says what to do next.** Clarix has two behaviours that a model will get
   wrong on its first attempt — statuses are numeric ids resolved PER PROJECT,
   and an assignee must already be on the project team. The error text names
   the fix rather than just reporting the code, because the model reads it.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from ..clarix_client import ClarixError, get_clarix_client, rows_of

log = logging.getLogger("chatbot")

# How many rows to hand back. The model pays for every one of these in input
# tokens on the NEXT request, so this is a cost control, not a limit of the API.
MAX_ROWS = 25

ACTIONS = [
    "list_projects",
    "get_project",
    "create_project",
    "list_tasks",
    "list_project_team",
    "create_task",
    "get_task",
    "update_task",
    "list_task_statuses",
    "list_users",
    "list_comments",
    "add_comment",
]


# What the model sees. Not documentation — it is the only thing the model reads
# when deciding whether and how to call this, so it names the two ordering
# constraints that otherwise cause a confident, wrong first attempt.
CLARIX_TOOL_SCHEMA = {
    "name": "clarix_projects",
    "description": (
        "Read and write projects and tasks in Clarix, the user's real project "
        "management workspace. Use this whenever the user asks about THEIR "
        "projects, modules or tasks, or asks you to create or update one. "
        "This writes to live data.\n\n"
        "PICKING THE ACTION — this is where it usually goes wrong:\n"
        "• Asked about ONE named project ('tasks in CRM-Clarix', 'who is on "
        "Apollo') → use get_project with project_name. It returns that "
        "project, its tasks AND its team in one call. Do NOT use list_projects "
        "and then summarise — that answers a question nobody asked.\n"
        "• Only use list_projects when the user wants the whole portfolio "
        "('what projects do I have').\n"
        "• You may pass project_name instead of project_id to any action that "
        "takes a project — it is resolved for you. Never guess a numeric id.\n"
        "• When CREATING a task, pass project_name unless you looked the id up "
        "in this same conversation. A guessed id writes into a real but wrong "
        "project.\n"
        "• You do NOT need a status, type or priority to create a task — "
        "sensible defaults are filled in. Do not go looking them up, and do "
        "not ask the user for them unless they raised the subject.\n"
        "• Asked to COMMENT on something ('add a comment on X', 'reply on that "
        "task', 'note that it is blocked') → add_comment. That is a Clarix "
        "task comment; it is never a web search and never a task update.\n"
        "• You may pass task_name instead of task_id, exactly like "
        "project_name — but a task name is only resolvable INSIDE a project, "
        "so pass the project too.\n\n"
        "Two rules that will trip you up:\n"
        "• Task status is a NUMERIC id, never a name. Call list_task_statuses "
        "for that project first and use the id — the list differs per project.\n"
        "• An assignee must already be on the project team, or create_task "
        "fails. Call list_project_team to see who is eligible.\n\n"
        "OMIT every parameter you are not using — do not pad them with 0 or an "
        "empty string, and never invent an id you have not looked up."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ACTIONS,
                "description": "What to do.",
            },
            "project_id": {
                "type": "integer",
                "description": "Numeric project id. Use project_name instead if you only know the name.",
            },
            "project_name": {
                "type": "string",
                "description": (
                    "Project name or code, e.g. 'CRM-Clarix' or 'CRX'. Resolved to an id "
                    "for you — prefer this over guessing project_id."
                ),
            },
            "task_id": {
                "type": "integer",
                "description": "Required for get_task and update_task.",
            },
            "name": {
                "type": "string",
                "description": "Name for create_project / create_task, or a new name for update_task.",
            },
            "code": {
                "type": "string",
                "description": "Short project code for create_project, e.g. 'APL'. Max 3-4 chars.",
            },
            "description": {"type": "string", "description": "Optional description."},
            "task_status_id": {
                "type": "integer",
                "description": "Numeric status id from list_task_statuses. Never a status name.",
            },
            "assignee_id": {
                "type": "integer",
                "description": "Numeric user id from list_users. Must already be on the project team.",
            },
            "task_name": {
                "type": "string",
                "description": (
                    "Task name, e.g. 'Fix the login redirect'. Resolved to a task_id for "
                    "you, but only within one project — send project_name as well."
                ),
            },
            "comment": {
                "type": "string",
                "description": (
                    "The comment text for add_comment. Write it as the user would post "
                    "it themselves; do not sign it or add 'as requested'."
                ),
            },
            "mention_user_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": (
                    "Optional user ids to @mention in the comment, from list_project_team. "
                    "The mention is written into the text for you."
                ),
            },
            "search": {"type": "string", "description": "Optional text filter for list_tasks."},
        },
        "required": ["action"],
        "additionalProperties": False,
    },
}


def _trim(rows: Any, fields: tuple[str, ...]) -> Any:
    """Keep only the fields the model needs.

    A raw Clarix task carries watchers, attachments, timestamps and nested
    relations — dozens of fields the model will never use but pays for in the
    next request's input tokens. Trimming is the difference between a readable
    tool result and one that crowds out the conversation.
    """
    rows = rows_of(rows)
    out = []
    for r in rows[:MAX_ROWS]:
        if not isinstance(r, dict):
            out.append(r)
            continue
        out.append({k: r.get(k) for k in fields if r.get(k) is not None})
    return out


PROJECT_FIELDS = ("id", "name", "code", "status_name", "project_status_name", "description")
TASK_FIELDS = ("id", "name", "task_no", "status_name", "assignee_name", "priority_name", "due_date")
STATUS_FIELDS = ("id", "name", "code")
USER_FIELDS = ("id", "name", "email")
TEAM_FIELDS = (
    "user_id", "user_name", "user_email", "template_name", "designation_title", "department_name",
)
COMMENT_FIELDS = ("id", "user_name", "comment", "created_at")


def _clean(args: dict) -> dict:
    """Drop the placeholder values small models pad every optional field with.

    This is not defensive coding for its own sake — it is what gpt-4o-mini
    actually sends. Asked to list projects it produced:

        {"action": "list_projects", "project_id": 1, "task_id": 0,
         "name": "", "assignee_id": 0, "search": "", ...}

    every optional field filled with a zero or an empty string rather than
    omitted. Harmless for a read, but `update_task` builds its body from any
    non-None field, so an unfiltered `name: ""` would BLANK a real task's name,
    and `assignee_id: 0` would fail every create with TASK_INVALID_ASSIGNEE.

    `0` is safe to treat as absent: Clarix ids are autoincrementing BigInts, so
    there is no row with id 0. An empty string is never a valid name either.
    """
    return {
        k: v
        for k, v in (args or {}).items()
        if v is not None and v != "" and not (k.endswith("_id") and v == 0)
    }


def run_clarix(args: dict) -> str:
    """Execute one action and return text for the model. Never raises."""
    args = _clean(args)
    action = args.get("action", "")
    if action not in ACTIONS:
        return f"Unknown action {action!r}. Valid actions: {', '.join(ACTIONS)}."

    client = get_clarix_client()
    if not client.configured:
        return (
            "Clarix is not configured on this server (CLARIX_API_KEY is unset). "
            "Tell the user you cannot reach their workspace."
        )

    def need(field: str) -> str | None:
        if args.get(field) is None:
            return f"{action} needs {field}. Ask the user, or look it up first."
        return None

    try:
        # Resolve project_name → project_id ONCE, up front, so every action
        # below can be written as if it had always been given an id. Doing it
        # here rather than per-action is what keeps "tasks in CRM-Clarix" a
        # single tool call instead of a list-then-guess round trip.
        # project_name WINS over project_id whenever both are present.
        #
        # This used to resolve the name only when no id was given, which is the
        # obvious reading and was wrong. gpt-4o-mini pads `project_id: 1` into
        # every call (see _clean), so asking for "a task in payroll-clarix"
        # arrives as {project_id: 1, project_name: 'payroll-clarix'} — the id
        # took precedence and the task was created in project 1, which is a
        # REAL project ("Projects-ClariX"), so nothing rejected it.
        #
        # The name is the higher-signal field: it echoes what the user actually
        # said, while a bare id from a small model is usually padding. When a
        # caller legitimately sends both they agree, so preferring the name
        # costs nothing and resolves to the same project.
        if args.get("project_name"):
            found = client.find_project(args["project_name"])
            if not found:
                return (
                    f"No project matches {args['project_name']!r}. "
                    "Call list_projects to see the exact names."
                )
            if isinstance(found, list):
                # Several projects match. Ask the user WHICH — do not pick one
                # and answer confidently about the wrong project.
                options = [
                    f"{p.get('name')} ({p.get('code') or 'no code'})" for p in found[:10]
                ]
                return (
                    f"{args['project_name']!r} matches {len(found)} projects: "
                    + "; ".join(options)
                    + ". Ask the user which one they mean, then call again with that exact name."
                )
            args["project_id"] = found.get("id")
            args["_project"] = found

        # Then task_name → task_id, the same way and for the same reason: the
        # user says "comment on the API access key task", never "comment on
        # 7822". It runs second because a task can only be looked up inside a
        # project, so the project has to be resolved first.
        if args.get("task_name") and not args.get("task_id"):
            if args.get("project_id") is None:
                return (
                    f"To find the task {args['task_name']!r} I need its project too — "
                    "pass project_name as well, or ask the user which project it is in."
                )
            found = client.find_task(args["project_id"], args["task_name"])
            if not found:
                return (
                    f"No task in that project matches {args['task_name']!r}. "
                    "Call list_tasks to see the exact names."
                )
            if isinstance(found, list):
                options = [
                    f"{t.get('name')} (id {t.get('id')})" for t in found[:10]
                ]
                return (
                    f"{args['task_name']!r} matches {len(found)} tasks: "
                    + "; ".join(options)
                    + ". Ask the user which one, then call again with that task_id."
                )
            args["task_id"] = found.get("id")
            args["_task"] = found

        if action == "list_projects":
            res = client.list_projects(page_size=MAX_ROWS)
            total = (res.pagination or {}).get("total")
            body = _trim(res.data, PROJECT_FIELDS)
            head = f"{total} project(s)" if total is not None else f"{len(body)} project(s)"
            return f"{head} (showing up to {MAX_ROWS}):\n{json.dumps(body, indent=2, default=str)}"

        if action == "create_project":
            if err := need("name"):
                return err
            body = {"name": args["name"]}
            for k in ("code", "description"):
                if args.get(k):
                    body[k] = args[k]
            res = client.create_project(**body)
            return f"Created project:\n{json.dumps(res.data, indent=2, default=str)}"

        if action == "get_project":
            # Deliberately THREE calls behind one action. The question "tell me
            # about project X" is always really "what is in it and who is on
            # it", and making the model chain three tool turns to answer that
            # is how it ends up answering a different question instead.
            if err := need("project_id"):
                return "get_project needs project_name (or project_id)."
            pid = args["project_id"]
            project = args.get("_project")
            if project is None:
                found = client.list_projects(page_size=100).data or []
                project = next(
                    (p for p in found if str(p.get("id")) == str(pid)), {"id": pid}
                )

            out = {"project": {k: project.get(k) for k in PROJECT_FIELDS if project.get(k) is not None}}

            # One failing part must not lose the others — a project with no
            # team is still worth reporting its tasks for.
            try:
                res = client.list_tasks(pid, page_size=MAX_ROWS)
                out["task_total"] = (res.pagination or {}).get("total", len(res.data or []))
                out["tasks"] = _trim(res.data, TASK_FIELDS)
            except ClarixError as exc:
                out["tasks"] = f"unavailable: {exc}"

            try:
                out["team"] = _trim(client.list_project_team(pid).data, TEAM_FIELDS)
            except ClarixError as exc:
                out["team"] = f"unavailable: {exc}"

            return (
                f"Project {project.get('name') or pid} (id={pid}) — tasks and team "
                f"(up to {MAX_ROWS} tasks shown):\n"
                f"{json.dumps(out, indent=2, default=str)}"
            )

        if action == "list_project_team":
            if err := need("project_id"):
                return "list_project_team needs project_name (or project_id)."
            res = client.list_project_team(args["project_id"])
            return (
                f"Team on project {args['project_id']} — only these people can be "
                f"assigned tasks:\n{json.dumps(_trim(res.data, TEAM_FIELDS), indent=2, default=str)}"
            )

        if action == "list_tasks":
            if err := need("project_id"):
                return err
            res = client.list_tasks(
                args["project_id"], page_size=MAX_ROWS, search=args.get("search")
            )
            total = (res.pagination or {}).get("total")
            body = _trim(res.data, TASK_FIELDS)
            head = f"{total} task(s)" if total is not None else f"{len(body)} task(s)"
            return f"{head} in project {args['project_id']}:\n{json.dumps(body, indent=2, default=str)}"

        if action == "list_task_statuses":
            if err := need("project_id"):
                return err
            res = client.list_task_statuses(args["project_id"])
            return (
                f"Task statuses for project {args['project_id']} — use the numeric id:\n"
                f"{json.dumps(_trim(res.data, STATUS_FIELDS), indent=2, default=str)}"
            )

        if action == "list_users":
            res = client.list_users()
            return (
                "Workspace members — use the numeric id as assignee_id:\n"
                f"{json.dumps(_trim(res.data, USER_FIELDS), indent=2, default=str)}"
            )

        if action == "create_task":
            if err := need("project_id") or need("name"):
                return err
            pid = args["project_id"]

            # A write into an unverified id is the one mistake with no undo.
            # Small models pad `project_id` with a plausible-looking default
            # (a real log shows `POST /projects/1/tasks` for a project the
            # model never looked up), and id 1 usually EXISTS — so the create
            # would quietly succeed in someone else's project. Confirm the id
            # is real and name it back; a resolved project_name skips this
            # because find_project already proved it.
            if args.get("_project") is None:
                known = client.list_projects(page_size=100).data or []
                match = next((p for p in known if str(p.get("id")) == str(pid)), None)
                if match is None:
                    return (
                        f"There is no project with id {pid}. Do not guess ids — pass "
                        "project_name instead and it will be resolved."
                    )
                args["_project"] = match

            body = {"name": args["name"]}
            for field in ("description", "task_status_id", "assignee_id"):
                if args.get(field) is not None:
                    body[field] = args[field]

            # Type, status and priority are NOT sent when the caller did not
            # name one: the API fills in that project's defaults itself now.
            # This client used to resolve them here, which cost three extra
            # HTTP calls per create and only ever fixed it for THIS client —
            # every other integration hit the same 400. Doing it server-side
            # fixed it for all of them, so the workaround is gone.
            res = client.create_task(pid, **body)
            where = (args.get("_project") or {}).get("name") or pid
            return (
                f"Created task in project {where!r}:\n"
                f"{json.dumps(res.data, indent=2, default=str)}"
            )

        if action == "get_task":
            if err := need("task_id"):
                return err
            res = client.get_task(args["task_id"])
            return json.dumps(res.data, indent=2, default=str)[:4000]

        if action == "update_task":
            if err := need("task_id"):
                return err
            body = {
                k: args[k]
                for k in ("name", "description", "task_status_id", "assignee_id")
                if args.get(k) is not None
            }
            if not body:
                return "update_task needs at least one field to change."
            res = client.update_task(args["task_id"], **body)
            return f"Updated task:\n{json.dumps(res.data, indent=2, default=str)}"

        if action == "list_comments":
            if err := need("task_id"):
                return "list_comments needs task_id (or task_name plus its project)."
            res = client.list_task_comments(args["task_id"], page_size=MAX_ROWS)
            rows = [_readable_mentions(c) for c in (res.data or []) if isinstance(c, dict)]
            total = (res.pagination or {}).get("total", len(rows))
            return (
                f"{total} comment(s) on task {args['task_id']}, newest first:\n"
                f"{json.dumps(_trim(rows, COMMENT_FIELDS), indent=2, default=str)}"
            )

        if action == "add_comment":
            if err := need("task_id"):
                return "add_comment needs task_id (or task_name plus its project)."
            text = (args.get("comment") or "").strip()
            if not text:
                # The one field only the user can supply. Say what is missing
                # rather than posting an empty comment nobody can delete.
                return (
                    "add_comment needs the comment text. Call ask_user_form with "
                    "form='add_comment' so the user can write it, instead of asking here."
                )
            res = client.add_task_comment(
                args["task_id"], text, _as_ids(args.get("mention_user_ids"))
            )
            posted = _readable_mentions(res.data if isinstance(res.data, dict) else {})
            where = (args.get("_task") or {}).get("name") or args["task_id"]
            return (
                f"Posted the comment on task {where!r}:\n"
                f"{json.dumps(posted, indent=2, default=str)[:1500]}"
            )

    except ClarixError as exc:
        log.warning("clarix tool %s failed: [%s] %s", action, exc.code, exc)
        return f"Clarix refused that ({exc.code or exc.status}): {exc}. {_hint(exc)}"
    except Exception as exc:  # noqa: BLE001 — a tool must not abort the turn
        log.exception("clarix tool %s crashed", action)
        return f"The Clarix call failed unexpectedly ({type(exc).__name__}). Tell the user it did not work."

    return f"Nothing ran for action {action!r}."


def _as_ids(raw: Any) -> list[int]:
    """Whatever the model sent for mention_user_ids → a list of ints.

    A form answer arrives as one id on a line, so a bare `12` is at least as
    likely as `[12]`, and a string id is likelier still. Anything that is not
    a number is dropped rather than guessed at — a bad mention id fails the
    whole comment, and a comment is worth more than a mention.
    """
    if raw is None:
        return []
    values = raw if isinstance(raw, (list, tuple)) else [raw]
    out = []
    for v in values:
        try:
            n = int(str(v).strip())
        except (TypeError, ValueError):
            continue
        if n > 0:
            out.append(n)
    return out


def _readable_mentions(comment: dict) -> dict:
    """`@[user:12]` → `@Dev Patel`, using the names the API sent alongside.

    The token is storage, not prose. Left as-is it reaches the model, which
    then repeats it back to the user as the literal string — and worse, copies
    the shape into the NEXT comment it writes, inventing ids.
    """
    text = comment.get("comment")
    if not isinstance(text, str) or "@[user:" not in text:
        return comment
    names = {
        str(u.get("id")): u.get("name")
        for u in (comment.get("mentioned_users") or [])
        if isinstance(u, dict) and u.get("id") is not None
    }
    return {
        **comment,
        "comment": re.sub(
            r"@\[user:(\d+)\]",
            lambda m: f"@{names.get(m.group(1), 'someone')}",
            text,
        ),
    }


def _hint(exc: ClarixError) -> str:
    """The next step, phrased for the model rather than for a developer."""
    if exc.code == "TASK_COMMENT_REQUIRED":
        return "The comment text was empty — ask the user what they want to say."
    if exc.code == "TASK_INVALID_ASSIGNEE":
        return "That person is not on the project team — they must be added before they can be assigned."
    if exc.code in ("NO_ENCRYPTION_KEY", "DECRYPT_FAILED", "UNREACHABLE", "NOT_CONFIGURED"):
        return "This is a server configuration problem, not something the user can fix — say so."
    if exc.status == 401:
        return "The API key is invalid, expired or revoked. Tell the user to issue a new one."
    if exc.status == 403:
        return "The account this key acts as lacks permission for that. Do not retry."
    if exc.status == 404:
        return "That id does not exist in this workspace. List first to get a valid id."
    if exc.status == 400:
        return "Check the arguments — a status must be a numeric id from list_task_statuses."
    return "Do not retry the same call unchanged."
