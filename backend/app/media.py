"""Where generated images live on disk.

An `image_generation_call` comes back as roughly 2.6 MB of PNG — about 3.5 MB
once base64 has inflated it. That is the wrong thing to put in a database
column: every transcript query would drag megabytes across the wire for a
picture the browser can fetch once and then cache. So the bytes go to a file
here and only a short URL goes in the message row.

The filename is a hash of the content, which buys two things for free: the
same image generated twice is stored once, and a name can never collide.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import logging
from pathlib import Path

from .config import get_settings

log = logging.getLogger("chatbot.media")

# Served from this path by main.py. Kept in one place so the route and the
# URLs written into the database can never drift apart.
MEDIA_URL_PREFIX = "/media"

# `output_format` on the tool call maps to a file extension. Anything the
# gateway invents that is not on this list is stored as .bin rather than
# guessed at — a wrong extension is worse than an unhelpful one.
EXTENSIONS = {"png": "png", "jpeg": "jpg", "jpg": "jpg", "webp": "webp"}


def media_dir() -> Path:
    """The directory images are written to, created on first use."""
    settings = get_settings()
    path = Path(settings.media_dir)
    if not path.is_absolute():
        # Relative to the backend/ folder — the same place .env is read from —
        # so it does not move when the server is started from elsewhere.
        path = Path(__file__).resolve().parent.parent / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_image(b64: str, *, output_format: str = "png") -> dict | None:
    """Write one generated image to disk. Returns what the UI needs, or None.

    Never raises: an image that cannot be stored must not take down the answer
    it came with. The turn is still worth showing without the picture.
    """
    try:
        raw = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        log.warning("generated image was not valid base64 — dropping it")
        return None

    if not raw:
        return None

    ext = EXTENSIONS.get((output_format or "png").lower(), "bin")
    name = f"{hashlib.sha256(raw).hexdigest()[:32]}.{ext}"
    path = media_dir() / name

    try:
        # Skipped when the file is already there: identical content means an
        # identical hash, so rewriting it would only cost time.
        if not path.exists():
            path.write_bytes(raw)
    except OSError:
        log.exception("could not write generated image to %s", path)
        return None

    return {"url": f"{MEDIA_URL_PREFIX}/{name}", "bytes": len(raw)}
