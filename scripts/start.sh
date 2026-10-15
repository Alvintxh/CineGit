#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
for dependency in uv npm ffmpeg ffprobe; do
  if ! command -v "$dependency" >/dev/null 2>&1; then
    echo "Missing dependency: $dependency"
    exit 1
  fi
done
uv sync --frozen
npm --prefix frontend ci
npm --prefix frontend run build
exec uv run uvicorn cinegit.api:app --host "${CINEGIT_HOST:-127.0.0.1}" --port "${CINEGIT_PORT:-8000}"
