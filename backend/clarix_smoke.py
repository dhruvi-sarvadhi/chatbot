"""Prove the Clarix API key works, end to end, without involving an LLM.

Run this FIRST. If the chatbot cannot create a task, this script tells you
which of the four things is actually wrong — the key, the encryption key, the
gateway, or the permissions — instead of the model reporting "the tool failed".

    cd backend
    .venv/bin/python clarix_smoke.py            # read-only checks
    .venv/bin/python clarix_smoke.py --write    # also creates a project + task

Read-only by default on purpose: `--write` creates real rows in a real
workspace, and there is no undo.
"""

from __future__ import annotations

import sys
from datetime import datetime

from app.clarix_client import ClarixError, get_clarix_client

OK = "\033[32m✓\033[0m"
NO = "\033[31m✗\033[0m"


def show(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {OK if ok else NO} {label}" + (f" — {detail}" if detail else ""))


def main() -> int:
    write = "--write" in sys.argv
    client = get_clarix_client()

    print(f"\nClarix smoke test → {client.base_url}")
    if not client.configured:
        show("CLARIX_API_KEY", False, "not set in backend/.env")
        return 1

    # The workspace is encoded in the key itself, which is how a verifier knows
    # which tenant database to look in. Printing it makes "wrong workspace"
    # obvious rather than mysterious.
    parts = client.api_key.split("_")
    workspace = parts[2] if len(parts) > 3 else "?"
    show("CLARIX_API_KEY", True, f"…{client.api_key[-4:]} (workspace: {workspace})")
    show("CLARIX_ENCRYPTION_KEY", bool(client.encryption_key),
         "set" if client.encryption_key else "MISSING — responses cannot be read")

    print("\nReads")
    try:
        projects = client.list_projects(page=1, page_size=5)
    except ClarixError as exc:
        show("GET /projects", False, f"[{exc.code or exc.status}] {exc}")
        print("\n" + _diagnose(exc))
        return 1

    rows = projects.data if isinstance(projects.data, list) else []
    total = (projects.pagination or {}).get("total", len(rows))
    show("GET /projects", True, f"{total} project(s)")
    for p in rows[:5]:
        print(f"      · [{p.get('id')}] {p.get('name')}  ({p.get('code') or '—'})")

    if not rows:
        print("\n  No projects yet — run with --write to create one.")
        return 0

    project_id = rows[0].get("id")

    for label, call in (
        (f"GET /projects/{project_id}/task-statuses", lambda: client.list_task_statuses(project_id)),
        (f"GET /projects/{project_id}/tasks", lambda: client.list_tasks(project_id, page_size=5)),
        ("GET /users", client.list_users),
    ):
        try:
            res = call()
            n = len(res.data) if isinstance(res.data, list) else "—"
            show(label, True, f"{n} row(s)")
        except ClarixError as exc:
            show(label, False, f"[{exc.code or exc.status}] {exc}")

    if not write:
        print("\n  (read-only — pass --write to create a project and a task)\n")
        return 0

    print("\nWrites")
    stamp = datetime.now().strftime("%H:%M:%S")
    try:
        created = client.create_project(name=f"Smoke test {stamp}", code="SMK")
        new_id = created.data.get("id") if isinstance(created.data, dict) else None
        show("POST /projects", True, f"id={new_id}")
    except ClarixError as exc:
        show("POST /projects", False, f"[{exc.code or exc.status}] {exc}")
        return 1

    # Statuses are ids, not names, and the list is per-project — so resolve
    # against the project we just made rather than reusing anything.
    try:
        statuses = client.list_task_statuses(new_id).data or []
        status_id = statuses[0].get("id") if statuses else None
        show(f"GET /projects/{new_id}/task-statuses", True,
             f"using status id={status_id} ({statuses[0].get('name') if statuses else '—'})")
    except ClarixError as exc:
        show("task-statuses", False, f"[{exc.code or exc.status}] {exc}")
        status_id = None

    try:
        body = {"name": f"Smoke task {stamp}"}
        if status_id:
            body["project_task_status_id"] = status_id
        task = client.create_task(new_id, **body)
        tid = task.data.get("id") if isinstance(task.data, dict) else None
        show(f"POST /projects/{new_id}/tasks", True, f"id={tid}")
    except ClarixError as exc:
        show("POST tasks", False, f"[{exc.code or exc.status}] {exc}")
        return 1

    print("\n  Created a real project and task. Check them in the Projects app.\n")
    return 0


def _diagnose(exc: ClarixError) -> str:
    """Turn the first failure into the one thing worth checking next."""
    hints = {
        "UNREACHABLE": "The gateway is not running. Start it: pnpm --filter @clarix/gateway local",
        "NO_ENCRYPTION_KEY": "Set CLARIX_ENCRYPTION_KEY in backend/.env (copy ENCRYPTION_KEY from the Clarix backend's .env.local).",
        "DECRYPT_FAILED": "CLARIX_ENCRYPTION_KEY does not match the server's ENCRYPTION_KEY.",
        "INVALID_TOKEN": "The key is unknown, expired or revoked. Issue a new one in Settings → API access.",
        "MISSING_TOKEN": "The Authorization header did not reach the gateway.",
        "APP_NOT_ACTIVE": "The PROJECTS app is not ACTIVE for this workspace.",
        "USER_APP_ACCESS_NOT_ACTIVE": "The account this key acts as has no active Projects access.",
        "RATE_LIMITED": "Too many requests for this key this minute. Wait and retry.",
    }
    if exc.code in hints:
        return f"  → {hints[exc.code]}"
    if exc.status == 401:
        return "  → 401: the key was rejected. Confirm it was issued for THIS environment."
    if exc.status == 403:
        return ("  → 403: authenticated but not allowed. Either the workspace has that module off, "
                "or the account this key acts as lacks the permission.")
    if exc.status == 404:
        return ("  → 404: check the path has NO /projects-api prefix — the app answers on "
                "bare paths like /projects.")
    return "  → Check the gateway logs for the matching request id."


if __name__ == "__main__":
    raise SystemExit(main())
