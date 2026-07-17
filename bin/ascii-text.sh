#!/bin/bash
# Launch the rotating ASCII text ball using the project virtualenv when available.
# Works regardless of the directory you invoke it from. Extra args pass through,
# e.g. ./ascii-text.sh --gap-ratio 2 --glyph-source notes.txt
set -euo pipefail

# Resolve actual script directory even if called via symlink
SOURCE="${BASH_SOURCE[0]}"
while [ -h "$SOURCE" ]; do
  DIR="$( cd -P "$( dirname "$SOURCE" )" >/dev/null 2>&1 && pwd )"
  SOURCE="$(readlink "$SOURCE")"
  [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE"
done
SCRIPT_DIR="$( cd -P "$( dirname "$SOURCE" )" >/dev/null 2>&1 && pwd )"
# The launcher lives in bin/; the repo root (with .venv and src/) is one up.
REPO_ROOT="$( cd -P "$SCRIPT_DIR/.." >/dev/null 2>&1 && pwd )"
VENV_PYTHON="$REPO_ROOT/.venv/bin/python"

if [ -x "$VENV_PYTHON" ]; then
    PY="$VENV_PYTHON"
else
    PY="$(command -v python3 || command -v python)"
fi

exec "$PY" "$REPO_ROOT/src/rotating_text.py" "$@"
