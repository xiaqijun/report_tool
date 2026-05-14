import re
from contextlib import contextmanager
from datetime import datetime

import pymysql
from pymysql.cursors import DictCursor

from app.config import DATABASE_CHARSET, DATABASE_HOST, DATABASE_NAME, DATABASE_PASSWORD, DATABASE_PORT, DATABASE_USER
from app.security import hash_password


DATASET_DEFINITIONS = {
    "owner-mappings": {
        "table": "owner_mappings",
        "title": "项目-责任人映射表",
        "template_filename": "项目负责人导入模板.xlsx",
        "columns": [("enterprise_project", "企业项目"), ("owner_name", "负责人"), ("note", "备注"), ("updated_at", "更新时间")],
        "search_fields": ["enterprise_project", "owner_name", "note"],
    },
    "unquota-hosts": {
        "table": "unquota_hosts",
        "title": "未配额主机列表",
        "template_filename": "未配额主机导入模板.xlsx",
        "columns": [("server_id", "服务器ID"), ("ip_address", "IP地址"), ("server_name", "服务器名称"), ("note", "备注"), ("updated_at", "更新时间")],
        "search_fields": ["server_id", "ip_address", "server_name", "note"],
    },
    "deferred-install-hosts": {
        "table": "deferred_install_hosts",
        "title": "暂不安装主机列表",
        "template_filename": "暂不安装主机导入模板.xlsx",
        "columns": [("server_id", "服务器ID"), ("ip_address", "IP地址"), ("server_name", "服务器名称"), ("note", "备注"), ("updated_at", "更新时间")],
        "search_fields": ["server_id", "ip_address", "server_name", "note"],
    },
}


class MySQLConnection:
    def __init__(self, connection: pymysql.connections.Connection):
        self._connection = connection

    def execute(self, query: str, params: tuple[object, ...] | list[object] = ()):
        with self._connection.cursor() as cursor:
            cursor.execute(_normalize_query(query), tuple(params))
            return MySQLResult(cursor)

    def executescript(self, script: str) -> None:
        statements = [statement.strip() for statement in script.split(";") if statement.strip()]
        with self._connection.cursor() as cursor:
            for statement in statements:
                cursor.execute(statement)

    def commit(self) -> None:
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()


class MySQLResult:
    def __init__(self, cursor):
        self._rows = cursor.fetchall() if cursor.description else []

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


def _normalize_query(query: str) -> str:
    return query.replace("?", "%s")


def _open_mysql_connection(*, database: str | None) -> MySQLConnection:
    connection = pymysql.connect(
        host=DATABASE_HOST,
        port=DATABASE_PORT,
        user=DATABASE_USER,
        password=DATABASE_PASSWORD,
        database=database,
        charset=DATABASE_CHARSET,
        autocommit=False,
        cursorclass=DictCursor,
    )
    return MySQLConnection(connection)


def _ensure_database_exists() -> None:
    connection = _open_mysql_connection(database=None)
    try:
        connection.execute(
            f"CREATE DATABASE IF NOT EXISTS `{DATABASE_NAME}` CHARACTER SET {DATABASE_CHARSET} COLLATE {DATABASE_CHARSET}_unicode_ci"
        )
        connection.commit()
    finally:
        connection.close()


@contextmanager
def get_connection() -> MySQLConnection:
    connection = _open_mysql_connection(database=DATABASE_NAME)
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def init_db() -> None:
    _ensure_database_exists()
    with get_connection() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                username VARCHAR(255) NOT NULL UNIQUE,
                password_hash VARCHAR(255) NOT NULL,
                display_name VARCHAR(255) NOT NULL,
                is_active TINYINT(1) NOT NULL DEFAULT 1,
                created_at VARCHAR(32) NOT NULL
            );

            CREATE TABLE IF NOT EXISTS owner_mappings (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                enterprise_project VARCHAR(255) NOT NULL UNIQUE,
                owner_name VARCHAR(255) NOT NULL,
                note TEXT,
                updated_at VARCHAR(32) NOT NULL
            );

            CREATE TABLE IF NOT EXISTS unquota_hosts (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                server_id VARCHAR(255) NOT NULL DEFAULT '',
                ip_address VARCHAR(255) NOT NULL DEFAULT '',
                server_name VARCHAR(255) NOT NULL DEFAULT '',
                match_key VARCHAR(255) NOT NULL,
                note TEXT,
                updated_at VARCHAR(32) NOT NULL
            );

            CREATE TABLE IF NOT EXISTS deferred_install_hosts (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                server_id VARCHAR(255) NOT NULL DEFAULT '',
                ip_address VARCHAR(255) NOT NULL DEFAULT '',
                server_name VARCHAR(255) NOT NULL DEFAULT '',
                match_key VARCHAR(255) NOT NULL,
                note TEXT,
                updated_at VARCHAR(32) NOT NULL
            );

            CREATE TABLE IF NOT EXISTS import_histories (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                file_name VARCHAR(255) NOT NULL,
                operator_name VARCHAR(255) NOT NULL,
                status VARCHAR(64) NOT NULL,
                created_at VARCHAR(32) NOT NULL
            );

            CREATE TABLE IF NOT EXISTS result_histories (
                id BIGINT PRIMARY KEY AUTO_INCREMENT,
                batch_code VARCHAR(255) NOT NULL UNIQUE,
                source_file_name VARCHAR(255) NOT NULL,
                operator_name VARCHAR(255) NOT NULL,
                online_unprotected_count INT NOT NULL DEFAULT 0,
                agent_missing_count INT NOT NULL DEFAULT 0,
                protection_interrupted_count INT NOT NULL DEFAULT 0,
                missing_owner_count INT NOT NULL DEFAULT 0,
                online_unprotected_path TEXT,
                agent_missing_path TEXT,
                protection_interrupted_path TEXT,
                missing_owner_projects TEXT,
                created_at VARCHAR(32) NOT NULL
            );
            """
        )
        _ensure_column(connection, "result_histories", "online_unprotected_path", "TEXT NULL")
        _ensure_column(connection, "result_histories", "agent_missing_path", "TEXT NULL")
        _ensure_column(connection, "result_histories", "protection_interrupted_path", "TEXT NULL")
        _ensure_column(connection, "result_histories", "missing_owner_projects", "TEXT NULL")


def ensure_default_admin(username: str, password: str) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with get_connection() as connection:
        existing = connection.execute(
            "SELECT id FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        if existing:
            return

        connection.execute(
            """
            INSERT INTO users (username, password_hash, display_name, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (username, hash_password(password), "系统管理员", now),
        )


def get_user_by_username(username: str) -> dict[str, object] | None:
    with get_connection() as connection:
        return connection.execute(
            "SELECT * FROM users WHERE username = ? AND is_active = 1",
            (username,),
        ).fetchone()


def list_dataset_records(dataset_key: str, search: str = "", page: int = 1, page_size: int = 20) -> tuple[list[dict[str, object]], int]:
    definition = DATASET_DEFINITIONS[dataset_key]
    where_clause = ""
    parameters: list[object] = []
    if search.strip():
        like_value = f"%{search.strip()}%"
        where_parts = [f"{field} LIKE ?" for field in definition["search_fields"]]
        where_clause = " WHERE " + " OR ".join(where_parts)
        parameters.extend([like_value] * len(definition["search_fields"]))

    offset = (page - 1) * page_size
    with get_connection() as connection:
        total = connection.execute(f"SELECT COUNT(*) AS total FROM {definition['table']}{where_clause}", tuple(parameters)).fetchone()["total"]
        rows = connection.execute(
            f"SELECT * FROM {definition['table']}{where_clause} ORDER BY id DESC LIMIT ? OFFSET ?",
            tuple(parameters + [page_size, offset]),
        ).fetchall()
    return rows, int(total)


def get_dataset_record(dataset_key: str, record_id: int) -> dict[str, object] | None:
    definition = DATASET_DEFINITIONS[dataset_key]
    with get_connection() as connection:
        return connection.execute(f"SELECT * FROM {definition['table']} WHERE id = ?", (record_id,)).fetchone()


def save_dataset_record(dataset_key: str, payload: dict[str, str], record_id: int | None = None) -> None:
    if dataset_key == "owner-mappings":
        _save_owner_mapping(payload, record_id)
        return
    _save_host_record(DATASET_DEFINITIONS[dataset_key]["table"], payload, record_id)


def delete_dataset_record(dataset_key: str, record_id: int) -> None:
    definition = DATASET_DEFINITIONS[dataset_key]
    with get_connection() as connection:
        connection.execute(f"DELETE FROM {definition['table']} WHERE id = ?", (record_id,))


def import_dataset_records(dataset_key: str, rows: list[dict[str, str]]) -> int:
    count = 0
    for row in rows:
        payload = map_import_row(dataset_key, row)
        if payload is None:
            continue
        save_dataset_record(dataset_key, payload)
        count += 1
    return count


def map_import_row(dataset_key: str, row: dict[str, str]) -> dict[str, str] | None:
    if dataset_key == "owner-mappings":
        enterprise_project = row.get("企业项目", row.get("项目", row.get("enterprise_project", ""))).strip()
        owner_name = row.get("负责人", row.get("owner_name", "")).strip()
        note = row.get("备注", row.get("note", "")).strip()
        if not enterprise_project or not owner_name:
            return None
        return {"enterprise_project": enterprise_project, "owner_name": owner_name, "note": note}

    server_id = row.get("服务器ID", row.get("server_id", "")).strip()
    ip_address = row.get("IP地址", row.get("ip_address", "")).strip()
    server_name = row.get("服务器名称", row.get("server_name", "")).strip()
    note = row.get("备注", row.get("note", "")).strip()
    if not server_id and not ip_address and not server_name:
        return None
    return {"server_id": server_id, "ip_address": ip_address, "server_name": server_name, "note": note}


def get_owner_mapping_dict() -> dict[str, str]:
    with get_connection() as connection:
        rows = connection.execute("SELECT enterprise_project, owner_name FROM owner_mappings").fetchall()
    return {str(row["enterprise_project"]): str(row["owner_name"]) for row in rows}


def get_exclusion_match_keys(dataset_key: str) -> set[str]:
    definition = DATASET_DEFINITIONS[dataset_key]
    with get_connection() as connection:
        rows = connection.execute(
            f"SELECT server_id, ip_address, server_name, match_key FROM {definition['table']}"
        ).fetchall()

    match_keys: set[str] = set()
    for row in rows:
        match_keys.update(
            build_match_keys(
                str(row.get("server_id", "")),
                str(row.get("ip_address", "")),
                str(row.get("server_name", "")),
            )
        )
        stored_key = str(row.get("match_key", "")).strip().lower()
        if stored_key:
            match_keys.add(stored_key)
    return match_keys


def save_import_history(file_name: str, operator_name: str, status: str) -> None:
    with get_connection() as connection:
        connection.execute(
            "INSERT INTO import_histories (file_name, operator_name, status, created_at) VALUES (?, ?, ?, ?)",
            (file_name, operator_name, status, datetime.now().isoformat(timespec="seconds")),
        )


def create_result_history(batch_code: str, source_file_name: str, operator_name: str, online_unprotected_count: int, agent_missing_count: int, protection_interrupted_count: int, missing_owner_count: int, online_unprotected_path: str, agent_missing_path: str, protection_interrupted_path: str, missing_owner_projects: str) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO result_histories (
                batch_code, source_file_name, operator_name,
                online_unprotected_count, agent_missing_count, protection_interrupted_count, missing_owner_count,
                online_unprotected_path, agent_missing_path, protection_interrupted_path, missing_owner_projects, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                batch_code,
                source_file_name,
                operator_name,
                online_unprotected_count,
                agent_missing_count,
                protection_interrupted_count,
                missing_owner_count,
                online_unprotected_path,
                agent_missing_path,
                protection_interrupted_path,
                missing_owner_projects,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )


def list_result_histories(search: str = "", page: int = 1, page_size: int = 20) -> tuple[list[dict[str, object]], int]:
    parameters: list[object] = []
    where_clause = ""
    if search.strip():
        like_value = f"%{search.strip()}%"
        where_clause = " WHERE source_file_name LIKE ? OR operator_name LIKE ? OR batch_code LIKE ? OR created_at LIKE ?"
        parameters.extend([like_value, like_value, like_value, like_value])

    offset = (page - 1) * page_size
    with get_connection() as connection:
        total = connection.execute(f"SELECT COUNT(*) AS total FROM result_histories{where_clause}", tuple(parameters)).fetchone()["total"]
        rows = connection.execute(
            f"SELECT * FROM result_histories{where_clause} ORDER BY id DESC LIMIT ? OFFSET ?",
            tuple(parameters + [page_size, offset]),
        ).fetchall()
    return rows, int(total)


def get_result_history(batch_code: str) -> dict[str, object] | None:
    with get_connection() as connection:
        return connection.execute("SELECT * FROM result_histories WHERE batch_code = ?", (batch_code,)).fetchone()


def _ensure_column(connection: MySQLConnection, table_name: str, column_name: str, column_definition: str) -> None:
    existing_columns = connection.execute(
        """
        SELECT COLUMN_NAME
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
        """,
        (DATABASE_NAME, table_name),
    ).fetchall()
    existing_names = {str(column["COLUMN_NAME"]) for column in existing_columns}
    if column_name not in existing_names:
        connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}")


def _save_owner_mapping(payload: dict[str, str], record_id: int | None) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with get_connection() as connection:
        if record_id is not None:
            connection.execute(
                "UPDATE owner_mappings SET enterprise_project = ?, owner_name = ?, note = ?, updated_at = ? WHERE id = ?",
                (payload["enterprise_project"], payload["owner_name"], payload.get("note", ""), now, record_id),
            )
            return

        existing = connection.execute("SELECT id FROM owner_mappings WHERE enterprise_project = ?", (payload["enterprise_project"],)).fetchone()
        if existing:
            connection.execute(
                "UPDATE owner_mappings SET owner_name = ?, note = ?, updated_at = ? WHERE id = ?",
                (payload["owner_name"], payload.get("note", ""), now, existing["id"]),
            )
            return

        connection.execute(
            "INSERT INTO owner_mappings (enterprise_project, owner_name, note, updated_at) VALUES (?, ?, ?, ?)",
            (payload["enterprise_project"], payload["owner_name"], payload.get("note", ""), now),
        )


def _save_host_record(table_name: str, payload: dict[str, str], record_id: int | None) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    match_key = build_match_key(payload.get("server_id", ""), payload.get("ip_address", ""), payload.get("server_name", ""))
    candidate_keys = build_match_keys(payload.get("server_id", ""), payload.get("ip_address", ""), payload.get("server_name", ""))
    with get_connection() as connection:
        if record_id is not None:
            connection.execute(
                f"UPDATE {table_name} SET server_id = ?, ip_address = ?, server_name = ?, match_key = ?, note = ?, updated_at = ? WHERE id = ?",
                (payload.get("server_id", ""), payload.get("ip_address", ""), payload.get("server_name", ""), match_key, payload.get("note", ""), now, record_id),
            )
            return

        existing = None
        rows = connection.execute(f"SELECT id, server_id, ip_address, server_name, match_key FROM {table_name}").fetchall()
        for row in rows:
            row_keys = build_match_keys(
                str(row.get("server_id", "")),
                str(row.get("ip_address", "")),
                str(row.get("server_name", "")),
            )
            stored_key = str(row.get("match_key", "")).strip().lower()
            if stored_key:
                row_keys.add(stored_key)
            if row_keys.intersection(candidate_keys):
                existing = row
                break
        if existing:
            connection.execute(
                f"UPDATE {table_name} SET server_id = ?, ip_address = ?, server_name = ?, note = ?, updated_at = ? WHERE id = ?",
                (payload.get("server_id", ""), payload.get("ip_address", ""), payload.get("server_name", ""), payload.get("note", ""), now, existing["id"]),
            )
            return

        connection.execute(
            f"INSERT INTO {table_name} (server_id, ip_address, server_name, match_key, note, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (payload.get("server_id", ""), payload.get("ip_address", ""), payload.get("server_name", ""), match_key, payload.get("note", ""), now),
        )


def extract_ip_candidates(ip_address: str) -> list[str]:
    return [match.lower() for match in re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", ip_address)]


def build_match_keys(server_id: str, ip_address: str, server_name: str) -> set[str]:
    keys: set[str] = set()

    normalized_server_id = server_id.strip().lower()
    if normalized_server_id:
        keys.add(f"id:{normalized_server_id}")

    for ip_candidate in extract_ip_candidates(ip_address):
        keys.add(f"ip:{ip_candidate}")

    normalized_ip = ip_address.strip().lower()
    if normalized_ip and not keys:
        keys.add(f"ip:{normalized_ip}")

    normalized_server_name = server_name.strip().lower()
    if normalized_server_name and not keys:
        keys.add(f"name:{normalized_server_name}")

    return keys


def build_match_key(server_id: str, ip_address: str, server_name: str) -> str:
    if server_id.strip():
        return f"id:{server_id.strip().lower()}"
    ip_candidates = extract_ip_candidates(ip_address)
    if ip_candidates:
        return f"ip:{ip_candidates[0]}"
    if ip_address.strip():
        return f"ip:{ip_address.strip().lower()}"
    return f"name:{server_name.strip().lower()}"
