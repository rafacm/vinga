#!/bin/sh
# The browser lane, run inside Playwright's own image (#613, Q5, Q5a, Q5b).
#
# Run from vinga-server/ in a container of
# mcr.microsoft.com/playwright/python:v1.63.0-noble, the image whose
# Chromium and system libraries match the Playwright the `browser`
# dependency group locks; docs/contributing.md has the one command that
# starts it locally, and the server workflow's `browser` job is the same
# thing in CI.
#
# What it serves the page from is the point of it. Unless
# VINGA_BROWSER_URL names a server that is already up (CI's run against
# the image it built), this builds the wheel, installs it into an
# environment of its own, constrained to the lockfile, and the lane
# starts the server from that install: a module the wheel does not carry
# is a page that does not load, here and not in a deployment.
#
# Nothing it builds lands in the checkout. The runner's environment, the
# wheel and the server's environment all go under VINGA_BROWSER_WORK,
# and the checkout's own .venv is never touched (UV_PROJECT_ENVIRONMENT).
#
# The database is the instance VINGA_DB_HOST and its siblings name
# (the server's defaults: the development instance on 127.0.0.1:5432),
# in a database of this run's own, dropped on the way out.
#
# Arguments are pytest's.
set -eu

# Nothing here is to leave bytecode in the mounted checkout.
export PYTHONDONTWRITEBYTECODE=1

work="${VINGA_BROWSER_WORK:-/tmp/vinga-browser}"
mkdir -p "$work"

# Throwaway values for this run alone, and only when the caller set
# none: the lane talks to the server it starts with the same ones.
export VINGA_AUTH_SECRET="${VINGA_AUTH_SECRET:-browser-lane-secret-not-a-real-deployment}"
export VINGA_API_SECRET="${VINGA_API_SECRET:-browser-lane-api-token-not-a-real-deployment}"

if ! command -v uv >/dev/null 2>&1; then
    # The image carries Python and pip and no uv. A throwaway container,
    # so its system interpreter is fair game.
    python3 -m pip install --quiet --root-user-action=ignore --break-system-packages uv
fi

# The runner: Playwright and pytest from the lockfile, nothing else.
export UV_PROJECT_ENVIRONMENT="$work/runner"
uv sync --quiet --frozen --only-group browser --python 3.12

if [ -z "${VINGA_BROWSER_URL:-}" ]; then
    rm -rf "$work/dist" "$work/server"
    uv build --quiet --wheel --out-dir "$work/dist"
    # Every version the lockfile pins, as constraints: the install takes
    # only what the wheel's `serve` extra needs, at the versions a
    # checkout runs. `psycopg[binary]` beside it, as the image and CI's
    # wheel migration install it, since `serve` carries the plain driver.
    uv export --quiet --frozen --all-extras --all-groups --no-emit-project --no-hashes \
        --output-file "$work/constraints.txt"
    uv venv --quiet --python 3.12 "$work/server"
    uv pip install --quiet --python "$work/server/bin/python" \
        --constraints "$work/constraints.txt" \
        "$(echo "$work"/dist/*.whl)[serve]" "psycopg[binary]"
    export VINGA_BROWSER_SERVER="$work/server/bin/vinga-server"

    database="vinga_browser_$$"
    export VINGA_DB_NAME="$database"
    # Created and dropped with the driver the server's own install
    # carries, so the image needs no Postgres client.
    db() {
        "$work/server/bin/python" - "$1" "$database" <<'PY'
import os
import sys

import psycopg

action, name = sys.argv[1], sys.argv[2]
with psycopg.connect(
    host=os.environ.get("VINGA_DB_HOST", "127.0.0.1"),
    port=int(os.environ.get("VINGA_DB_PORT", "5432")),
    user=os.environ.get("VINGA_DB_USER", "vinga"),
    password=os.environ.get("VINGA_DB_PASSWORD", "vinga"),
    dbname="postgres",
    autocommit=True,
) as connection:
    if action == "create":
        connection.execute(f'create database "{name}"')
    else:
        connection.execute(f'drop database if exists "{name}" with (force)')
PY
    }
    db create
    trap 'db drop' EXIT
fi

export VINGA_BROWSER_LANE=1
"$work/runner/bin/pytest" -c tests/browser/pytest.ini --confcutdir="$PWD/tests/browser" \
    tests/browser "$@"
