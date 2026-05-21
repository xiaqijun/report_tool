# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

An internal web tool (报告管理工具 / "Asset Ops") for generating server asset risk reports. Users upload a server asset spreadsheet; the system cross-references it against three admin-maintained datasets (owner mappings, unquota hosts, deferred-install hosts) and produces three categorized result lists as XLSX + CSV.

**Stack:** FastAPI (server-side Jinja2 templates, no SPA), MySQL via PyMySQL, Tabler CSS, openpyxl.

## Commands

```bash
# Run the app (reads .env for host/port/reload)
python main.py

# Run all tests
uv run pytest
# or just: pytest

# Install dependencies
uv sync
```

No linter/formatter is configured.

## Architecture

```
browser request
  → FastAPI + SessionMiddleware (cookie-based, Starlette)
    → auth router:      /login, /logout, /change-password
    → web router:       /dashboard, /generate, /history, /download/...
    → admin router:     /admin/{owner-mappings,unquota-hosts,deferred-install-hosts}
      → db.py (PyMySQL, `?` placeholders normalized to `%s` for MySQL)
      → services/inventory.py (core generation logic)
      → services/spreadsheets.py (XLSX/CSV read/write via openpyxl)
      → services/system_update.py (git pull + uv sync self-update)
```

**Auth flow:** `app/auth.py` reads user_id/username/display_name from `request.session`. `require_login()` returns the user dict or a `RedirectResponse` to `/login`. No OAuth, no roles — a single admin user created on startup is the only user.

**App factory:** `app/main.py` → `create_app()` creates the FastAPI instance, mounts SessionMiddleware, registers routers, and runs `init_db()` + `ensure_default_admin()` during lifespan startup.

## Database

MySQL accessed through `app/db.py`:

- **`get_connection()`** — context manager returning a `MySQLConnection`. Auto-commits on clean exit.
- **Placeholder style:** queries are written with `?` and `_normalize_query()` replaces them with `%s` before execution. Always use `?` in new code.
- **Tables:** `users`, `owner_mappings`, `unquota_hosts`, `deferred_install_hosts`, `import_histories`, `result_histories`
- **Schema management:** `init_db()` uses `CREATE TABLE IF NOT EXISTS` plus `_ensure_column()` for additive migrations. There is no migration framework.

## Core business logic (services/inventory.py)

`generate_from_asset_file(file_path, operator_name)`:

1. Reads the uploaded asset spreadsheet (XLSX/CSV) via `read_table_file()`.
2. Standardizes column headers using an alias map (`ASSET_FIELD_ALIASES` — Chinese ↔ English field name mappings).
3. Loads owner mappings and exclusion match keys from the database.
4. For each server row, evaluates three categories:
   - **Online unprotected** — status=运行中, agent=在线, protection=未防护, excluding hosts in unquota list
   - **Agent missing** — status=运行中, agent=未安装, excluding hosts in deferred-install list
   - **Protection interrupted** — status=运行中, protection=防护中断 (no exclusion)
5. Writes results as XLSX + CSV to a timestamped batch directory under `data/exports/`.
6. Records history in `result_histories` table.

**Match keys** for exclusion lists are built by `build_match_keys()` with priority: `id:<server_id>` → `ip:<extracted_ip>` → `name:<server_name>`. IP addresses are extracted from free-text fields with regex `\b(?:\d{1,3}\.){3}\d{1,3}\b`.

## Three datasets pattern

`admin.py` router uses a generic `dataset_key` parameter (one of `owner-mappings`, `unquota-hosts`, `deferred-install-hosts`). `DATASET_DEFINITIONS` in `db.py` maps each key to its table name, column list, search fields, and import template. All CRUD operations in `db.py` accept `dataset_key` to dispatch to the correct table.

## Configuration

`.env` file at repo root (gitignored, see `.env.example` for template). All settings read by `app/config.py` via `python-dotenv`. Key variables:

- `DATABASE_HOST/PORT/USER/PASSWORD/NAME/CHARSET`
- `APP_HOST/PORT/RELOAD`
- `SECRET_KEY` (for session signing)
- `DEFAULT_ADMIN_USERNAME/PASSWORD` (auto-created on first startup)

## Templates and static files

- Jinja2 templates in `app/templates/` — base.html → app_shell.html → individual pages. `asset_version` global busts CSS cache via file mtime.
- Custom CSS in `app/static/app.css`, vendor CSS/icons in `app/static/vendor/tabler/` and `tabler-icons/`.
- Excel import templates for each dataset live in `app/static/import-templates/`.
