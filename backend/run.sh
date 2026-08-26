#!/usr/bin/env bash
# Convenience launcher: creates the venv on first run, then starts the API.
set -e
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv .venv
  ./.venv/bin/pip install --quiet --upgrade pip
  ./.venv/bin/pip install -r requirements.txt
fi

exec ./.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
