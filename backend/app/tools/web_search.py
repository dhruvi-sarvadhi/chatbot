"""Free web search, no API key, via DuckDuckGo.

Two steps, because one is not enough. Search alone returns snippets — page
descriptions a crawler wrote, which say "find the latest AAPL quote here"
rather than giving a number. A model handed only those correctly concludes it
does not know the price, and says so.

So this reads the top results too. Fetching the page is what turns "here is
where the answer lives" into the answer, and it is the step the paid hosted
search tools are really charging for.
"""

import logging

from ddgs import DDGS

log = logging.getLogger("chatbot")

MAX_RESULTS = 5
# How many pages we want to come back with. Plenty of sites time out or block
# crawlers, so we keep trying further down the list rather than giving up on
# the first two — landing on snippets only is what makes the model answer
# "I cannot access real-time data", which is the failure this tool exists to
# prevent.
PAGES_WANTED = 2
PAGES_TO_TRY = 4
MAX_SNIPPET = 300
# Enough to carry a quote, a headline and its surrounding paragraph; small
# enough that two pages do not crowd out the conversation.
MAX_PAGE_CHARS = 3000
# ddgs rotates across search backends and any one of them can time out. A
# second attempt usually lands on a different backend and succeeds.
SEARCH_ATTEMPTS = 3

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


def _read(url: str) -> str:
    """Page text, or "" if it cannot be fetched.

    Plenty of pages time out, block crawlers, or render entirely in JS. That
    is normal, not exceptional — a failed read just means we fall back to the
    snippet for that result.
    """
    try:
        return str(DDGS().extract(url).get("content", ""))
    except Exception as exc:  # noqa: BLE001 — one dead page is not a failure
        log.info("could not read %s: %s", url, type(exc).__name__)
        return ""


def web_search(query: str) -> str:
    """Run the search and format everything found as plain text for the model.

    Returns a string in every case, including failure. A tool that raises
    would abort the whole turn; a tool that reports "search failed" lets the
    model tell the user it could not look it up, which is a better answer.
    """
    results, last_error = [], None
    for attempt in range(SEARCH_ATTEMPTS):
        try:
            results = DDGS().text(query, max_results=MAX_RESULTS)
            break
        except Exception as exc:  # noqa: BLE001 — the model handles this, not us
            last_error = exc
            log.info("search attempt %d failed for %r: %s", attempt + 1, query, exc)

    if last_error is not None and not results:
        log.warning("web_search gave up on %r: %s", query, last_error)
        return f"Search failed: {last_error}. Tell the user you could not look this up."

    if not results:
        return f"No results for {query!r}."

    out = [f"Search results for {query!r}:", ""]
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

    out.append(
        "Page content is live but noisy — navigation and adverts come with it. "
        "Pull the figure the user asked for, cite the source URL, and say when "
        "it is from if the answer is time-sensitive."
    )
    return "\n".join(out)
