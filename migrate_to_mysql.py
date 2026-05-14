import sqlite3
from pathlib import Path

from app.config import DATA_DIR
from app.db import get_connection, init_db


SQLITE_DATABASE_PATH = DATA_DIR / "app.db"
TABLES = [
    "users",
    "owner_mappings",
    "unquota_hosts",
    "deferred_install_hosts",
    "import_histories",
    "result_histories",
]


def migrate_table(table_name: str, sqlite_connection: sqlite3.Connection) -> int:
    rows = sqlite_connection.execute(f"SELECT * FROM {table_name}").fetchall()
    if not rows:
        return 0

    column_names = [column[0] for column in sqlite_connection.execute(f"SELECT * FROM {table_name}").description]
    placeholders = ", ".join(["?"] * len(column_names))
    columns = ", ".join(column_names)

    with get_connection() as mysql_connection:
        mysql_connection.execute(f"DELETE FROM {table_name}")
        for row in rows:
            mysql_connection.execute(
                f"INSERT INTO {table_name} ({columns}) VALUES ({placeholders})",
                row,
            )
    return len(rows)


def main() -> None:
    if not SQLITE_DATABASE_PATH.exists():
        raise FileNotFoundError(f"SQLite database not found: {SQLITE_DATABASE_PATH}")

    init_db()

    sqlite_connection = sqlite3.connect(SQLITE_DATABASE_PATH)
    try:
        migrated_counts = {table_name: migrate_table(table_name, sqlite_connection) for table_name in TABLES}
    finally:
        sqlite_connection.close()

    for table_name, count in migrated_counts.items():
        print(f"{table_name}: migrated {count} rows")


if __name__ == "__main__":
    main()