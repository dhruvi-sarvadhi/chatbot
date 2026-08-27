"""Web search for the model, with two interchangeable backends.

Tavily is a search API built for LLMs: it returns text already extracted from
the pages plus a synthesized answer, so one call is enough. DuckDuckGo is the
no-key fallback, and it needs a second step — its results are only page
*descriptions*, so the pages have to be opened and read before there is an
actual number to hand the model.

That second step is the whole difference. A model given only descriptions
correctly answers "I cannot access real-time data", because nothing it was
given contains the answer.
"""

import logging
import time
from dataclasses import dataclass, field

from ..config import get_settings

log = logging.getLogger("chatbot")

# ── Tavily ──────────────────────────────────────────────────────────────
# "basic" costs half of "advanced" and, in testing, answered stock and
# weather queries just as well while being about a second faster.
TAVILY_DEPTH = "basic"
TAVILY_RESULTS = 5

# ── DuckDuckGo fallback ─────────────────────────────────────────────────
DDG_RESULTS = 5
# How many pages we want to come back with. Plenty of sites time out or block
# crawlers, so we keep trying further down the list rather than giving up on
# the first two.
PAGES_WANTED = 2
PAGES_TO_TRY = 4
MAX_SNIPPET = 300
MAX_PAGE_CHARS = 3000
# ddgs rotates across search backends and any one of them can time out. A
# second attempt usually lands on a different backend and succeeds.
SEARCH_ATTEMPTS = 3

FRESHNESS_NOTE = (
    "Cite the source URL, and say when the figure is from if the answer is "
    "time-sensitive."
)

# Which backend a request may ask for. "compare" runs both and times them,
# which costs twice as much and is purely a learning tool — the model is still
# only shown one of the two results.
BACKENDS = ["auto", "tavily", "duckduckgo", "compare"]


@dataclass
class SearchRun:
    """What one backend did, for the trace panel."""

    backend: str
    ms: int
    chars: int
    sources: int
    pages_read: int | None = None  # None where the backend does not fetch pages
    ok: bool = True


@dataclass
class SearchOutcome:
    """The text handed to the model, plus what it cost to get it."""

    text: str
    used: str
    runs: list[SearchRun] = field(default_factory=list)


def _count_sources(text: str) -> int:
    """Numbered result lines, which both backends emit in the same shape."""
    return sum(1 for line in text.splitlines() if line[:1].isdigit() and ". " in line[:5])


# What the model sees. Not documentation — it is the only thing the model
# reads when deciding whether to call this, so it names the cases that matter.
SEARCH_TOOL_SCHEMA = {
    "name": "web_search",
    "description": (
        "Search the web and read the top results. Use this for anything that "
        "changes over time or happened recently: stock and crypto prices, "
        "weather, news, sports results, product releases, or any fact you are "
        "not confident is still true. Returns page content, so the actual "
        "numbers are usually in the result. Do not use it for general "
        "knowledge, definitions, maths, or code."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query, phrased as you would type it into a search engine.",
            }
        },
        "required": ["query"],
        "additionalProperties": False,
    },
}


def _tavily(query: str, api_key: str) -> str | None:
    """Tavily's answer plus its sources, or None if the call did not work.

    None means "try the other backend" — a failed paid search should degrade
    to the free one, not to no search at all.
    """
    try:
        from tavily import TavilyClient

        data = TavilyClient(api_key).search(
            query=query,
            search_depth=TAVILY_DEPTH,
            max_results=TAVILY_RESULTS,
            include_answer="advanced",
        )
    except Exception as exc:  # noqa: BLE001 — fall through to DuckDuckGo
        log.warning("tavily search failed for %r: %s", query, exc)
        return None

    results = data.get("results") or []
    if not results and not data.get("answer"):
        return None

    out = [f"Search results for {query!r} (via Tavily):", ""]
    if data.get("answer"):
        # Tavily's own summary of what it found. Useful, but still a summary —
        # the sources below are what the model should quote from.
        out += ["Summary:", data["answer"], ""]

    for i, r in enumerate(results, 1):
        out.append(f"{i}. {r.get('title', '(untitled)')} — {r.get('url', '')}")
        out.append(f"   {(r.get('content') or '')[:MAX_PAGE_CHARS]}")
        out.append("")

    out.append(FRESHNESS_NOTE)
    return "\n".join(out)


def _read(url: str) -> str:
    """Page text, or "" if it cannot be fetched.

    Plenty of pages time out, block crawlers, or render entirely in JS. That
    is normal, not exceptional — a failed read just means we fall back to the
    snippet for that result.
    """
    try:
        from ddgs import DDGS

        return str(DDGS().extract(url).get("content", ""))
    except Exception as exc:  # noqa: BLE001 — one dead page is not a failure
        log.info("could not read %s: %s", url, type(exc).__name__)
        return ""


def _duckduckgo(query: str) -> str:
    """Free, no key: search, then open the top results and read them."""
    from ddgs import DDGS

    results, last_error = [], None
    for attempt in range(SEARCH_ATTEMPTS):
        try:
            results = DDGS().text(query, max_results=DDG_RESULTS)
            break
        except Exception as exc:  # noqa: BLE001 — the model handles this
            last_error = exc
            log.info("search attempt %d failed for %r: %s", attempt + 1, query, exc)

    if last_error is not None and not results:
        log.warning("web_search gave up on %r: %s", query, last_error)
        return f"Search failed: {last_error}. Tell the user you could not look this up."

    if not results:
        return f"No results for {query!r}."

    out = [f"Search results for {query!r} (via DuckDuckGo):", ""]
    for i, r in enumerate(results, 1):
        out.append(f"{i}. {r.get('title', '(untitled)')} — {r.get('href', '')}")
        out.append(f"   {r.get('body', '')[:MAX_SNIPPET]}")
    out.append("")

    read = 0
    for r in results[:PAGES_TO_TRY]:
        if read >= PAGES_WANTED:
            break
        content = _read(r.get("href", ""))
        if not content:
            continue
        read += 1
        out.append(f"--- Page content: {r.get('href', '')} ---")
        out.append(content[:MAX_PAGE_CHARS])
        out.append("")

    if not read:
        out.append("(None of the pages could be opened — only the snippets above are available.)")

    out.append("Page content is live but noisy — navigation and adverts come with it. " + FRESHNESS_NOTE)
    return "\n".join(out)


def _timed(backend: str, fn, query: str) -> tuple[str | None, SearchRun]:
    """Run one backend and measure it, so the two can be compared honestly."""
    start = time.perf_counter()
    text = fn(query)
    ms = round((time.perf_counter() - start) * 1000)
    ok = bool(text) and not str(text).startswith("Search failed")
    return text, SearchRun(
        backend=backend,
        ms=ms,
        chars=len(text or ""),
        sources=_count_sources(text or ""),
        pages_read=(text or "").count("--- Page content") if backend == "duckduckgo" else None,
        ok=ok,
    )


def run_search(query: str, backend: str = "auto") -> SearchOutcome:
    """Search with the requested backend, reporting what it cost.

    Never raises: a tool that raises aborts the whole turn, while a tool that
    says "search failed" lets the model tell the user it could not look it up.
    """
    key = get_settings().tavily_api_key
    if backend not in BACKENDS:
        backend = "auto"
    # Asking for Tavily without a key is a configuration mistake, not a reason
    # to answer nothing — fall back rather than fail.
    if backend in ("auto", "tavily") and not key:
        backend = "duckduckgo"
    if backend == "compare" and not key:
        backend = "duckduckgo"

    runs: list[SearchRun] = []

    if backend == "duckduckgo":
        text, run = _timed("duckduckgo", _duckduckgo, query)
        return SearchOutcome(text=text, used="duckduckgo", runs=[run])

    if backend == "compare":
        # Both, sequentially, so the timings are not fighting for bandwidth.
        tav, tav_run = _timed("tavily", lambda q: _tavily(q, key), query)
        ddg, ddg_run = _timed("duckduckgo", _duckduckgo, query)
        runs = [tav_run, ddg_run]
        if tav is not None:
            return SearchOutcome(text=tav, used="tavily", runs=runs)
        return SearchOutcome(text=ddg, used="duckduckgo", runs=runs)

    # auto / tavily
    text, run = _timed("tavily", lambda q: _tavily(q, key), query)
    runs.append(run)
    if text is not None:
        return SearchOutcome(text=text, used="tavily", runs=runs)

    log.info("tavily unavailable, falling back to DuckDuckGo for %r", query)
    text, run = _timed("duckduckgo", _duckduckgo, query)
    runs.append(run)
    return SearchOutcome(text=text, used="duckduckgo", runs=runs)


def web_search(query: str, backend: str = "auto") -> str:
    """Plain-text search, for callers that do not want the timings."""
    return run_search(query, backend).text
