"""Client for the Clarix Projects API.

Talks to the Clarix gateway with a long-lived API key (`clx_live_…`) instead of
a user session, so this process can read and write projects, modules, features
and tasks without holding anyone's password.

Three things about that API are not guessable, and each one is a wasted
afternoon if you find it the hard way:

1. **There is no `/projects-api` URL prefix.** The Projects app answers on bare
   top-level paths — `/projects`, `/tasks`, `/master`. The `/projects-api`
   prefix serves the API reference only, and the paths published there carry a
   `{slug}` segment the gateway does not route, so a client generated from that
   spec 404s on every call.

2. **Responses are encrypted.** With `ENABLE_PAYLOAD_ENCRYPTION=true` (which is
   the case in Clarix's local and production envs) every response body —
   including errors — comes back as `{"encrypted": true, iv, data, tag}`,
   AES-256-GCM, hex-encoded, keyed on the first 32 characters of Clarix's
   `ENCRYPTION_KEY`. There is no header, query flag or route allowlist to opt
   out. Requests may stay plaintext, which is why `_request` sends plain JSON.

3. **Statuses are ids, not names.** There is no set-status-by-name call; you
   resolve a name against `/projects/:id/task-statuses`, and that list is
   PER PROJECT, not global.

Both secrets come from `backend/.env` and are never hardcoded — the same rule
this project already applies to the LLM keys.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import get_settings

log = logging.getLogger("chatbot")

TIMEOUT_SECONDS = 20.0

# Clarix's envelope is asymmetric: `page`/`page_size` go OUT, `pageIndex`/
# `pageSize` come BACK. Pagination is also OPT-IN — send neither and you get
# the ENTIRE collection with no pagination block at all, so always send both.
DEFAULT_PAGE_SIZE = 25


class ClarixError(RuntimeError):
    """A call Clarix refused. Carries the envelope's stable `code`."""

    def __init__(self, message: str, status: int = 0, code: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.code = code


@dataclass
class ClarixResponse:
    data: Any
    pagination: dict | None = None


# Where a wrapped collection actually keeps its rows. `/projects/:id/team` is
# the one that matters — it answers `{members: [...], analytics: {...}}` rather
# than a bare list, so anything treating `data` as iterable rows silently sees
# nothing. (That is not hypothetical: it is why the assignee dropdown on the
# task form was empty for every project.)
ROW_KEYS = ("members", "items", "rows", "results", "data", "list")


def rows_of(data: Any) -> list:
    """The rows in a Clarix payload, whichever shape it arrived in."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ROW_KEYS:
            if isinstance(data.get(key), list):
                return data[key]
    return []


def _decrypt(envelope: dict, key: str) -> Any:
    """`{encrypted, iv, data, tag}` → the real body.

    The wire format is fixed by Clarix's shared middleware: AES-256-GCM, a
    12-byte IV, a 16-byte tag, everything hex, and the key is the first 32
    characters of ENCRYPTION_KEY read as utf-8 — not a hash of it and not
    base64. A mismatch here surfaces as `InvalidTag`, which reads like a
    corrupt payload but is almost always the wrong key.
    """
    aes = AESGCM(key[:32].encode("utf-8"))
    plaintext = aes.decrypt(
        bytes.fromhex(envelope["iv"]),
        # Python's AESGCM expects the tag appended to the ciphertext; Node's
        # crypto keeps them as separate fields. Same bytes, different shape.
        bytes.fromhex(envelope["data"]) + bytes.fromhex(envelope["tag"]),
        None,
    )
    return json.loads(plaintext.decode("utf-8"))


class ClarixClient:
    """Thin, synchronous wrapper. One instance per process is plenty."""

    def __init__(
        self,
        base_url: str = "",
        api_key: str = "",
        encryption_key: str = "",
    ) -> None:
        s = get_settings()
        self.base_url = (base_url or s.clarix_api_url).rstrip("/")
        self.api_key = api_key or s.clarix_api_key
        self.encryption_key = encryption_key or s.clarix_encryption_key

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    # ── transport ───────────────────────────────────────────────────────
    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        body: dict | None = None,
    ) -> ClarixResponse:
        if not self.configured:
            raise ClarixError(
                "CLARIX_API_KEY is not set in backend/.env", code="NOT_CONFIGURED"
            )

        url = f"{self.base_url}{path}"
        try:
            resp = httpx.request(
                method,
                url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                params=params,
                json=body,
                timeout=TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            raise ClarixError(
                f"Could not reach Clarix at {url}: {exc}", code="UNREACHABLE"
            ) from exc

        try:
            payload = resp.json()
        except ValueError:
            raise ClarixError(
                f"Clarix returned a non-JSON body ({resp.status_code}): {resp.text[:200]}",
                status=resp.status_code,
            ) from None

        # Errors are encrypted too, so decrypt BEFORE reading the status —
        # bailing out on the status code first would throw away the `code` and
        # `message` that say what actually went wrong.
        if isinstance(payload, dict) and payload.get("encrypted"):
            if not self.encryption_key:
                raise ClarixError(
                    "Clarix encrypted the response but CLARIX_ENCRYPTION_KEY is not set. "
                    "Copy ENCRYPTION_KEY from the Clarix backend's .env.local.",
                    status=resp.status_code,
                    code="NO_ENCRYPTION_KEY",
                )
            try:
                payload = _decrypt(payload, self.encryption_key)
            except Exception as exc:  # noqa: BLE001 — surface it, never swallow
                raise ClarixError(
                    f"Could not decrypt the Clarix response ({type(exc).__name__}). "
                    "CLARIX_ENCRYPTION_KEY probably does not match the server's.",
                    status=resp.status_code,
                    code="DECRYPT_FAILED",
                ) from exc

        if not isinstance(payload, dict):
            raise ClarixError(f"Unexpected Clarix body: {payload!r}", status=resp.status_code)

        if resp.status_code >= 400 or payload.get("success") is False:
            err = payload.get("error") or {}
            raise ClarixError(
                payload.get("message") or f"Clarix returned {resp.status_code}",
                status=resp.status_code,
                code=err.get("code", ""),
            )

        return ClarixResponse(data=payload.get("data"), pagination=payload.get("pagination"))

    # ── reads ───────────────────────────────────────────────────────────
    def list_projects(self, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE) -> ClarixResponse:
        return self._request("GET", "/projects", params={"page": page, "page_size": page_size})

    def list_tasks(
        self,
        project_id: int | str,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        **filters,
    ) -> ClarixResponse:
        params = {
            "page": page,
            "page_size": page_size,
            **{k: v for k, v in filters.items() if v is not None},
        }
        return self._request("GET", f"/projects/{project_id}/tasks", params=params)

    def get_task(self, task_id: int | str) -> ClarixResponse:
        return self._request("GET", f"/tasks/{task_id}")

    def list_task_statuses(self, project_id: int | str) -> ClarixResponse:
        """Per-project, not global — cache the name→id map per project."""
        return self._request("GET", f"/projects/{project_id}/task-statuses")

    def list_task_types(self, project_id: int | str) -> ClarixResponse:
        return self._request("GET", f"/projects/{project_id}/task-types")

    def list_modules(self, project_id: int | str) -> ClarixResponse:
        return self._request("GET", f"/projects/{project_id}/modules")

    def list_priorities(self) -> ClarixResponse:
        """The PRIORITY master. Workspace-wide, unlike statuses and types,
        which are per project."""
        return self._request("GET", "/master/by-parent-code/PRIORITY")

    def list_project_team(self, project_id: int | str) -> ClarixResponse:
        """Who is ON this project. Also the gate on assignment: a person who is
        not here cannot be set as a task's assignee."""
        return self._request("GET", f"/projects/{project_id}/team")

    def list_users(self) -> ClarixResponse:
        """The member directory — how you resolve a person to an assignee id."""
        return self._request("GET", "/users")

    def list_task_comments(
        self, task_id: int | str, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE
    ) -> ClarixResponse:
        return self._request(
            "GET",
            f"/tasks/{task_id}/comments",
            params={"page": page, "page_size": page_size},
        )

    # ── name → id ───────────────────────────────────────────────────────
    def find_project(self, name: str) -> dict | list[dict] | None:
        """Resolve a project NAME to its row, because the API only takes ids.

        Every project endpoint is keyed by a numeric id, so without this a
        caller has to list projects, eyeball the match and pass the id back —
        and a model asked for "tasks in the Clarix project" reliably stops at
        the listing step and dumps all of them instead. Doing the match here
        turns two turns into one and removes the step it was getting wrong.

        Returns:
            dict        exactly one project matched
            list[dict]  the term is AMBIGUOUS — these all matched
            None        nothing matched

        The list case is the important one and the reason this does not just
        return a best guess. `Support-Clarix`, `Payroll-Clarix` and
        `CRM-Clarix` all contain "clarix", so "the clarix project" names three
        things. Silently picking the first would answer confidently about the
        wrong project, which is worse than asking — so the caller is handed the
        candidates and can ask which one was meant.

        Precision still wins outright where it exists: an exact name, an exact
        code, or a unique prefix resolves to one project without the question,
        so only genuinely ambiguous input costs a round trip.
        """
        needle = (name or "").strip().lower()
        if not needle:
            return None

        rows = [r for r in (self.list_projects(page_size=100).data or []) if isinstance(r, dict)]

        def name_of(r: dict) -> str:
            return str(r.get("name") or "").lower()

        def code_of(r: dict) -> str:
            return str(r.get("code") or "").lower()

        def words(text: str) -> set[str]:
            """Word set, ignoring separators and order."""
            return {w for w in re.split(r"[^a-z0-9]+", text.lower()) if w}

        needle_words = words(needle)

        # Each rung is tried against EVERY project before falling to the next,
        # so a weaker match on one row never beats a stronger match on another.
        #
        # The last rung is order-independent, and it is not a nicety: people
        # name a project by its words, not its punctuation. "clarix-payroll",
        # "payroll clarix" and "Payroll Clarix" all mean `Payroll-Clarix`, and
        # every substring-based rung above misses all three because the words
        # are in the other order. It runs LAST so an exact name or code still
        # wins outright, and it still reports ambiguity like the others — a
        # single word such as "clarix" matches three projects here too.
        for matches in (
            lambda r: name_of(r) == needle,
            lambda r: code_of(r) == needle,
            lambda r: name_of(r).startswith(needle),
            lambda r: needle in name_of(r),
            lambda r: bool(needle_words) and needle_words <= words(name_of(r)),
        ):
            hits = [row for row in rows if matches(row)]
            if len(hits) == 1:
                return hits[0]
            if hits:
                # Ambiguous at this precision. Report rather than guess — and
                # do NOT fall through to a looser rung, which could only widen
                # the ambiguity, never resolve it.
                return hits
        return None

    def find_task(self, project_id: int | str, name: str) -> dict | list[dict] | None:
        """Resolve a task NAME to its row, within one project.

        Unlike projects there is no workspace-wide task list to search — every
        task listing hangs off a project — so this needs the project first and
        the caller has to resolve that (find_project) before calling here.

        The API's own `search` does the narrowing; this only decides between
        what comes back. An exact, case-insensitive name match wins outright,
        because "Login" must not be ambiguous just because "Login redirect"
        also exists. Otherwise every candidate is returned and the caller asks.
        """
        wanted = (name or "").strip().lower()
        if not wanted:
            return None

        rows = self.list_tasks(project_id, page_size=50, search=name).data or []
        rows = [r for r in rows if isinstance(r, dict)]
        if not rows:
            return None

        exact = [r for r in rows if str(r.get("name", "")).strip().lower() == wanted]
        if len(exact) == 1:
            return exact[0]
        if len(rows) == 1:
            return rows[0]
        return exact or rows

    # ── writes ──────────────────────────────────────────────────────────
    def create_project(self, **body) -> ClarixResponse:
        return self._request("POST", "/projects", body=body)

    def create_task(self, project_id: int | str, **body) -> ClarixResponse:
        """An assignee must ALREADY be on the project's team, or this fails
        with TASK_INVALID_ASSIGNEE. Add them via POST /projects/:id/team first.
        """
        return self._request("POST", f"/projects/{project_id}/tasks", body=body)

    def update_task(self, task_id: int | str, **body) -> ClarixResponse:
        """Set status by passing `task_status_id` — a NUMBER from
        list_task_statuses(), never a status name."""
        return self._request("PUT", f"/tasks/{task_id}", body=body)

    def add_task_comment(
        self, task_id: int | str, comment: str, mention_user_ids: list | None = None
    ) -> ClarixResponse:
        """Post a comment on a task. Mentions are TOKENS IN THE TEXT.

        Two things about this endpoint are not guessable:

        1. **It is documented as multipart/form-data** — that is for the
           optional file upload. Multer only touches a multipart body, so a
           plain JSON `{"comment": ...}` falls through to the normal parser and
           works. This client sends JSON; attachments would need multipart.

        2. **Do not send `mentioned_user_ids`.** The server reconciles that
           field against the `@[user:id]` tokens it finds in the text, and
           rejects the whole request if the two disagree — so a list of ids
           without matching tokens is a 400, not a mention. Omitted, it derives
           the mentions from the text alone, which is why this method writes
           the tokens in and never sends the field.
        """
        text = comment or ""
        for uid in mention_user_ids or []:
            token = f"@[user:{uid}]"
            if token not in text:
                text = f"{token} {text}"
        return self._request("POST", f"/tasks/{task_id}/comments", body={"comment": text})


_client: ClarixClient | None = None


def get_clarix_client() -> ClarixClient:
    global _client
    if _client is None:
        _client = ClarixClient()
    return _client
