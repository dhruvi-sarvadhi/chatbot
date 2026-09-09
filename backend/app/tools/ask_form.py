"""Ask the user for missing details with a FORM, not with a question.

The problem this exists to fix, from a real transcript:

    user > create task in solance
    bot  > Sure — what should be the task name/title for the new task?
    user > ...

Every field the model needs costs a full round trip, the user has to type a
status name the API does not even accept (statuses are numeric ids, per
project), and nothing validates until the write fails. Three questions in
prose is three chances to get it wrong.

So instead the model calls `ask_user_form`, and this builds a spec the UI
renders as a boxed card with real inputs: a title box, a description box, and
dropdowns already populated with THIS project's statuses and THIS project's
team. The user fills it in once and submits; the answers come back as one
message and the model writes them straight through to `clarix_projects`.

Two design notes worth keeping:

1. **The options are fetched here, not guessed by the model.** The dropdown
   carries the numeric id as its value and the name as its label, so the user
   picks "In Progress" and the model receives `task_status_id: 5`. That is the
   single mistake this tool removes — the model can no longer invent a status.

2. **It never raises, and it degrades in one direction only.** If the statuses
   or the team cannot be fetched, the form still renders with the fields that
   do not need a lookup. A form with two fields beats an aborted turn.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from ..clarix_client import ClarixError, get_clarix_client, rows_of

log = logging.getLogger("chatbot")

FORMS = ["create_task", "create_project", "update_task", "add_comment"]

# A dropdown is a picker, not a directory listing. Past this many rows it stops
# being faster than typing, and it is a lot of JSON to push down the stream.
MAX_OPTIONS = 50


# What the model sees. The important half is not the parameters — it is the
# sentence telling it to stop writing questions, because that is the habit
# being replaced.
FORM_TOOL_SCHEMA = {
    "name": "ask_user_form",
    "description": (
        "Show the user a FORM to fill in, instead of asking them for details "
        "one question at a time in the chat.\n\n"
        "USE THIS whenever you are about to write a sentence like 'what should "
        "the task name be?', 'which project?', or 'what status do you want?'. "
        "Asking in prose is the wrong move — call this instead. It renders a "
        "boxed card in the chat with a title box, a description box, and "
        "dropdowns already filled with that project's real statuses and real "
        "team members, so the user cannot pick something the API will reject.\n\n"
        "Also use it for COMMENTS. 'Add a comment on the login task' with no "
        "text to post is the same mistake as asking for a task title in prose: "
        "call ask_user_form with form='add_comment' and the task, and the user "
        "gets a comment box with the people they can @mention already listed. "
        "If they already told you what to say, skip the form and post it.\n\n"
        "Typical trigger: the user says 'create a task in Solnce' or just "
        "'add a task' and has not given you a title. Call ask_user_form with "
        "form='create_task' — pass project_name if they named a project, and "
        "omit it if they did not (the form will then include a project "
        "picker).\n\n"
        "AFTER CALLING IT: write ONE short line ('Fill in the details below "
        "and I'll create it.') and stop. Do NOT ask for any of the fields in "
        "text as well, and do NOT call clarix_projects yet — the user's "
        "answers arrive as their next message, and you create the task then.\n\n"
        "Do NOT use this when the user already gave you everything you need — "
        "if they said 'create task Fix login in Solnce', just create it."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "form": {
                "type": "string",
                "enum": FORMS,
                "description": (
                    "Which form to show. create_task is the common one; "
                    "update_task also needs task_id."
                ),
            },
            "project_name": {
                "type": "string",
                "description": (
                    "The project the user named, e.g. 'Solnce'. Pass it if they "
                    "named one — it is what populates the status and assignee "
                    "dropdowns. Omit it if they did not, and the form asks."
                ),
            },
            "project_id": {
                "type": "integer",
                "description": "Numeric project id, if you looked one up. Prefer project_name.",
            },
            "task_id": {
                "type": "integer",
                "description": (
                    "Required for form='update_task' — the task being edited. For "
                    "form='add_comment', the task being commented on."
                ),
            },
            "task_name": {
                "type": "string",
                "description": (
                    "The task the user named, for form='add_comment' when you have no "
                    "id. Needs project_name too — task names are only unique inside a "
                    "project. If you have neither, the form shows a task picker."
                ),
            },
            "comment": {
                "type": "string",
                "description": "Prefill for the comment box, if the user already said what to post.",
            },
            "title": {
                "type": "string",
                "description": "Optional heading for the card, e.g. 'New task in Solnce'.",
            },
            "name": {
                "type": "string",
                "description": (
                    "Prefill for the title box — pass whatever the user already "
                    "said the task should be called, so they do not retype it."
                ),
            },
            "description": {
                "type": "string",
                "description": "Prefill for the description box, if the user already described it.",
            },
        },
        "required": ["form"],
        "additionalProperties": False,
    },
}


def _options(rows: Any, value_keys: tuple[str, ...], label_keys: tuple[str, ...]) -> list[dict]:
    """Clarix rows → `{value, label}` pairs for a dropdown.

    The key names differ between endpoints — a team row identifies the person
    as `user_id` while the user directory calls the same thing `id` — so the
    caller passes the candidates in priority order rather than this guessing.

    `rows_of` is what makes the team endpoint work here: it answers with
    `{members, analytics}`, and iterating that dict directly yields key names,
    not people.
    """
    out = []
    for row in rows_of(rows):
        if not isinstance(row, dict):
            continue
        value = next((row[k] for k in value_keys if row.get(k) is not None), None)
        label = next((row[k] for k in label_keys if row.get(k)), None)
        if value is None or not label:
            continue
        out.append({"value": value, "label": str(label)})
        if len(out) >= MAX_OPTIONS:
            break
    return out


def _text(name: str, label: str, **extra) -> dict:
    return {"name": name, "label": label, "type": "text", **extra}


# Two presentation hints the UI reads instead of sniffing at field names.
# Deciding this here is not a layout leak — it is the only place that knows a
# status is a small fixed set worth showing as buttons while an assignee is a
# person worth showing with a face. `span` is "half" or "full" of the card's
# two-column grid.
STATUS_STYLE = {"style": "status", "span": "half"}
PEOPLE_STYLE = {"style": "people", "span": "half"}


def _project_field(client) -> dict | None:
    """A project picker, for when the user never named one.

    Returns None if the list cannot be fetched — the form is still worth
    showing without it, and the model can resolve the project afterwards.
    """
    try:
        rows = client.list_projects(page_size=MAX_OPTIONS).data
    except ClarixError as exc:
        log.warning("form: could not list projects: %s", exc)
        return None
    options = _options(rows, ("id",), ("name", "code"))
    if not options:
        return None
    return {
        "name": "project_id",
        "label": "Project",
        "type": "select",
        "span": "full",
        "required": True,
        "options": options,
        "placeholder": "Choose a project",
    }


def _status_field(client, project_id) -> dict | None:
    try:
        rows = client.list_task_statuses(project_id).data
    except ClarixError as exc:
        log.warning("form: could not list statuses for project %s: %s", project_id, exc)
        return None
    options = _options(rows, ("id",), ("name", "code"))
    if not options:
        return None
    return {
        "name": "task_status_id",
        "label": "Status",
        "type": "select",
        **STATUS_STYLE,
        "options": options,
        # Clarix fills in the project's default status when none is sent, so
        # an empty pick is a real choice here, not a missing answer — and the
        # UI shows it as a pill beside the real ones. No hint: the control
        # already says "Default", and a line of prose repeating that is a line
        # of prose making the card taller.
        "placeholder": "Default",
    }


def _assignee_field(client, project_id) -> dict | None:
    """Only people ON the project — anyone else is rejected as an assignee."""
    try:
        rows = client.list_project_team(project_id).data
    except ClarixError as exc:
        log.warning("form: could not list team for project %s: %s", project_id, exc)
        return None
    options = _options(rows, ("user_id", "id"), ("user_name", "name", "user_email", "email"))
    if not options:
        return None
    return {
        "name": "assignee_id",
        "label": "Assignee",
        "type": "select",
        **PEOPLE_STYLE,
        "options": options,
        "placeholder": "Unassigned",
        "hint": "Only project members can be assigned.",
    }


def _task_field(client, project_id) -> dict | None:
    """A picker of the tasks in one project, for commenting on."""
    try:
        rows = client.list_tasks(project_id, page_size=MAX_OPTIONS).data
    except ClarixError as exc:
        log.warning("form: could not list tasks for project %s: %s", project_id, exc)
        return None
    options = _options(rows, ("id",), ("name",))
    if not options:
        return None
    return {
        "name": "task_id",
        "label": "Task",
        "type": "select",
        "span": "full",
        "required": True,
        "options": options,
        "placeholder": "Which task?",
    }


def _mention_field(client, project_id) -> dict | None:
    """Who to @mention. Optional, and the same team list an assignee comes from.

    A picker rather than a free-text @name because a mention is a numeric id
    written into the comment as a token — typed by hand it is just text that
    looks like a mention and notifies nobody.
    """
    try:
        rows = client.list_project_team(project_id).data
    except ClarixError as exc:
        log.warning("form: could not list team for project %s: %s", project_id, exc)
        return None
    options = _options(rows, ("user_id", "id"), ("user_name", "name", "user_email", "email"))
    if not options:
        return None
    return {
        "name": "mention_user_ids",
        "label": "Notify",
        "type": "select",
        **PEOPLE_STYLE,
        "options": options,
        "placeholder": "No one",
        "hint": "They get an @mention on the comment.",
    }


def build_form(args: dict, *, supported: bool = True) -> tuple[dict | None, str]:
    """Build one form spec. Returns `(spec_for_the_ui, text_for_the_model)`.

    `supported=False` is the non-streaming path, which has no channel to push
    a form down. Say so plainly rather than telling the model a form is on
    screen when none is — it would then wait forever for an answer nobody was
    asked to give.

    Never raises: a tool that raises aborts the turn.
    """
    args = args or {}
    kind = args.get("form") or ""
    if kind not in FORMS:
        return None, f"Unknown form {kind!r}. Valid: {', '.join(FORMS)}."

    if not supported:
        return None, (
            "Forms cannot be shown in this mode. Ask the user for the details "
            "in plain text instead, in one message."
        )

    client = get_clarix_client()
    if not client.configured:
        return None, (
            "Clarix is not configured on this server, so there is nothing to "
            "fill a form in for. Tell the user you cannot reach their workspace."
        )

    project = None
    project_id = args.get("project_id") or None

    # Same rule as the clarix tool: the NAME wins over an id, because a name
    # echoes what the user actually said while a bare id from a small model is
    # usually padding. See `_clean` in clarix_projects.py for the log that
    # taught us that.
    if args.get("project_name"):
        try:
            found = client.find_project(args["project_name"])
        except ClarixError as exc:
            log.warning("form: project lookup failed: %s", exc)
            found = None
        if isinstance(found, list):
            names = "; ".join(f"{p.get('name')}" for p in found[:10])
            return None, (
                f"{args['project_name']!r} matches {len(found)} projects: {names}. "
                "Ask the user which one, then call ask_user_form again with that "
                "exact name."
            )
        if isinstance(found, dict):
            project = found
            project_id = found.get("id")

    # A comment is the one form anchored to a TASK rather than a project, so
    # it resolves in the other direction too: given a task id and no project,
    # the task itself says which project it belongs to — and that is what the
    # mention list is built from.
    task = None
    task_id = args.get("task_id") or None
    if kind == "add_comment":
        if task_id is None and args.get("task_name") and project_id is not None:
            try:
                found = client.find_task(project_id, args["task_name"])
            except ClarixError as exc:
                log.warning("form: task lookup failed: %s", exc)
                found = None
            if isinstance(found, list):
                names = "; ".join(f"{t.get('name')}" for t in found[:10])
                return None, (
                    f"{args['task_name']!r} matches {len(found)} tasks: {names}. Ask "
                    "the user which one, then call ask_user_form again with its task_id."
                )
            if isinstance(found, dict):
                task = found
                task_id = found.get("id")

        if task_id is not None and project_id is None:
            try:
                row = client.get_task(task_id).data
            except ClarixError as exc:
                log.warning("form: could not load task %s: %s", task_id, exc)
                row = None
            if isinstance(row, dict):
                task = task or row
                project_id = row.get("project_id") or project_id

        if task_id is None and project_id is None:
            # Nothing to hang a comment on. A form asking "which project?" and
            # "what do you want to say?" would collect the text and still not
            # know the task, so the model resolves it first instead.
            return None, (
                "A comment needs a task, and I have neither a task nor a project. "
                "Find the task first (get_project, or list_tasks with a search), then "
                "call ask_user_form again with its task_id."
            )

    fields: list[dict] = []

    if kind == "create_project":
        fields = [
            _text("name", "Project name", span="half", required=True, placeholder="e.g. Solnce"),
            _text("code", "Code", span="half", placeholder="e.g. SOL", hint="Short, 3–4 characters."),
            {
                "name": "description",
                "label": "Description",
                "type": "textarea",
                "span": "full",
                "placeholder": "What is this project for?",
            },
        ]
        heading = args.get("title") or "New project"
        submit = "Create project"

    elif kind == "add_comment":
        if task_id is None:
            picker = _task_field(client, project_id)
            if picker is None:
                return None, (
                    "That project has no tasks to comment on, or the list could not be "
                    "fetched. Tell the user, and do not show a form."
                )
            fields.append(picker)

        fields.append({
            "name": "comment",
            "label": "Comment",
            "type": "textarea",
            "span": "full",
            "required": True,
            "placeholder": "What do you want to say on this task?",
            "value": args.get("comment") or "",
        })

        if project_id is not None:
            mention = _mention_field(client, project_id)
            if mention:
                fields.append(mention)

        on = (task or {}).get("name")
        heading = args.get("title") or (f"Comment on {on}" if on else "Add a comment")
        submit = "Post comment"

    else:
        # create_task / update_task. Without a project there is nothing to
        # fetch statuses or a team FROM, so the form asks for the project
        # first and those two dropdowns sit this one out.
        if project_id is None:
            picker = _project_field(client)
            if picker:
                fields.append(picker)

        fields.append(
            _text(
                "name",
                "Task title" if kind == "create_task" else "New title",
                span="full",
                required=kind == "create_task",
                placeholder="e.g. Fix the login redirect",
                value=args.get("name") or "",
            )
        )
        fields.append({
            "name": "description",
            "label": "Description",
            "type": "textarea",
            "span": "full",
            "placeholder": "What needs doing? Anything the assignee should know.",
            "value": args.get("description") or "",
        })

        if project_id is not None:
            for field in (_status_field(client, project_id), _assignee_field(client, project_id)):
                if field:
                    fields.append(field)

        where = (project or {}).get("name")
        heading = args.get("title") or (
            f"New task in {where}" if kind == "create_task" and where
            else "New task" if kind == "create_task"
            else "Update task"
        )
        submit = "Create task" if kind == "create_task" else "Save changes"

    spec = {
        # Distinguishes two forms in the same conversation, so the UI can key
        # its local state on something stabler than a message index.
        "id": f"form_{uuid.uuid4().hex[:8]}",
        "kind": kind,
        "title": heading,
        "submit_label": submit,
        "fields": fields,
        "context": {
            k: v
            for k, v in {
                "project_id": project_id,
                "project_name": (project or {}).get("name") or args.get("project_name"),
                "task_id": task_id if kind == "add_comment" else args.get("task_id"),
                "task_name": (task or {}).get("name") if kind == "add_comment" else None,
            }.items()
            # Not just `is not None`: gpt-4o-mini pads unused ids with 0 (see
            # `_clean` in clarix_projects.py), and a padded `task_id: 0` in the
            # context is copied verbatim into the message the user's answers
            # become — telling the model to create a task on task zero.
            if v is not None and str(v).strip() not in ("", "0")
        },
    }

    labels = ", ".join(f["label"] for f in fields)
    return spec, (
        f"A form is now on the user's screen asking for: {labels}. "
        "Reply with ONE short line telling them to fill it in — nothing else. "
        "Do NOT ask for any of these fields in text, do NOT list them, and do "
        "NOT call clarix_projects yet. Their answers will arrive as their next "
        "message, with the numeric ids already resolved, and you write them "
        "through then."
    )
