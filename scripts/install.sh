#!/usr/bin/env sh
set -eu

browser=0
if [ "${1:-}" = "--browser" ]; then
  browser=1
elif [ "$#" -gt 0 ]; then
  echo "Usage: ./scripts/install.sh [--browser]" >&2
  exit 2
fi

command -v git >/dev/null 2>&1 || {
  echo "Git is required. Install Git, then run this script again." >&2
  exit 1
}
command -v uv >/dev/null 2>&1 || {
  echo "uv is required. Install uv, then run this script again." >&2
  exit 1
}

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repository_root=$(dirname -- "$script_dir")
cd "$repository_root"

uv sync
if [ "$browser" -eq 1 ]; then
  uv sync --extra browser
  uv run playwright install chromium
fi
uv run wechat-reader-mcp doctor

echo "Installation verified. Choose a client template under clients/."
