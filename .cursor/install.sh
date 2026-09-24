#!/usr/bin/env bash
# Idempotent repository bootstrap for the scrapy-extension Cloud Agent
# environment. Runs after the repository is checked out. Installs the two tools
# the base image lacks (uv and a loopback Redis for the live-backend tier) and
# then materializes the exact locked dependency set.
set -euo pipefail

export PATH="$HOME/.local/bin:$PATH"

# uv drives dependency management and downloads the pinned CPython 3.10
# interpreter (see .python-version). Installed into ~/.local/bin, which is on
# the agent's PATH. Pinned for reproducibility.
if ! command -v uv >/dev/null 2>&1; then
  echo "Installing uv..."
  python3 -m pip install --user --break-system-packages "uv==0.12.18"
fi
uv --version

# redis-server backs the live integration tier (tests/integration) and the
# runnable examples. It is optional for the mock-based unit suite. Install it
# when apt/sudo are available; never fail the whole bootstrap if it is not.
if ! command -v redis-server >/dev/null 2>&1; then
  if command -v sudo >/dev/null 2>&1 && command -v apt-get >/dev/null 2>&1; then
    echo "Installing redis-server..."
    sudo apt-get update -qq && sudo apt-get install -y -qq redis-server || \
      echo "WARNING: redis-server install failed; unit suite still works, live backend tier will skip." >&2
  else
    echo "WARNING: apt/sudo unavailable; skipping redis-server (unit suite still works)." >&2
  fi
fi

# Materialize the locked runtime + dev + test dependency groups plus every
# optional backend extra, exactly as pinned in uv.lock. Idempotent: a second
# run is a no-op when the venv already matches the lock.
uv sync --locked --all-extras

echo "Install complete."
