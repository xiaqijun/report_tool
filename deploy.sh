#!/usr/bin/env bash

set -euo pipefail

SKIP_GIT_PULL=false
MIGRATE_SQLITE=false
NO_START=false

for arg in "$@"; do
    case "$arg" in
        -SkipGitPull|--skip-git-pull)
            SKIP_GIT_PULL=true
            ;;
        -MigrateSQLite|--migrate-sqlite)
            MIGRATE_SQLITE=true
            ;;
        -NoStart|--no-start)
            NO_START=true
            ;;
        *)
            echo "Unknown argument: $arg" >&2
            echo "Supported arguments: --skip-git-pull, --migrate-sqlite, --no-start" >&2
            exit 1
            ;;
    esac
done

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

run_step() {
    local title="$1"
    shift
    printf '\n==> %s\n' "$title"
    "$@"
}

assert_command() {
    local name="$1"
    if ! command -v "$name" >/dev/null 2>&1; then
        echo "Missing command: $name" >&2
        exit 1
    fi
}

assert_command git
assert_command uv

if [[ ! -f .env ]]; then
    echo "Missing .env. Create it from .env.example before deployment." >&2
    exit 1
fi

if [[ "$SKIP_GIT_PULL" != true ]]; then
    run_step "Pull latest code" git pull --ff-only
fi

run_step "Sync Python dependencies" uv sync

run_step "Initialize MySQL database" \
    uv run python -c "from app.config import DEFAULT_ADMIN_PASSWORD, DEFAULT_ADMIN_USERNAME; from app.db import ensure_default_admin, init_db; init_db(); ensure_default_admin(DEFAULT_ADMIN_USERNAME, DEFAULT_ADMIN_PASSWORD); print('Database initialization completed')"

if [[ "$MIGRATE_SQLITE" == true ]]; then
    if [[ -f ./data/app.db ]]; then
        run_step "Migrate SQLite data to MySQL" uv run python migrate_to_mysql.py
    else
        printf '\n==> Skip SQLite migration: data/app.db not found\n'
    fi
fi

if [[ "$NO_START" != true ]]; then
    run_step "Start application service" bash -lc "cd '$REPO_ROOT' && nohup uv run python main.py > deploy.log 2>&1 &"
    printf '\nDeployment complete. Service started in background. Default URL: http://127.0.0.1:8000\n'
    printf 'Runtime log: %s/deploy.log\n' "$REPO_ROOT"
else
    printf '\nDeployment complete. Service start skipped.\n'
fi