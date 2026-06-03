from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from app.config import EXPORT_DIR, UPLOAD_DIR
from app.db import build_match_key, build_match_keys, create_result_history, get_exclusion_match_keys, get_owner_mapping_dict, save_import_history
from app.services.spreadsheets import read_table_file, write_csv, write_xlsx


REPORT_PREFIX = "比亚迪"

OUTPUT_COLUMNS = [
    "服务器名称",
    "服务器ID",
    "IP地址",
    "配额ID",
    "服务器状态",
    "Agent状态",
    "风险状态",
    "防护状态",
    "操作系统",
    "版本类型",
    "企业项目",
    "来源",
    "负责人",
]

ASSET_FIELD_ALIASES = {
    "服务器名称": ["服务器名称", "主机名称", "实例名称"],
    "服务器ID": ["服务器ID", "主机ID", "实例ID", "服务器id"],
    "IP地址": ["IP地址", "IP", "私网IP", "内网IP", "ip地址"],
    "配额ID": ["配额ID", "配额id"],
    "服务器状态": ["服务器状态", "主机状态", "实例状态"],
    "Agent状态": ["Agent状态", "AGENT状态", "agent状态"],
    "风险状态": ["风险状态"],
    "防护状态": ["防护状态"],
    "操作系统": ["操作系统", "OS", "os"],
    "版本类型": ["版本类型"],
    "企业项目": ["企业项目", "项目", "项目名称"],
    "来源": ["来源"],
}


def generate_from_asset_file(file_path: Path, operator_name: str) -> dict[str, object]:
    rows = read_table_file(file_path)
    if not rows:
        raise ValueError("上传文件为空，无法生成清单。")

    standardized_rows, missing_columns = standardize_asset_rows(rows)
    if missing_columns:
        raise ValueError(f"总表缺少必要列：{', '.join(missing_columns)}")

    owner_mapping = get_owner_mapping_dict()
    unquota_keys = get_exclusion_match_keys("unquota-hosts")
    deferred_install_keys = get_exclusion_match_keys("deferred-install-hosts")
    missing_owner_projects: set[str] = set()

    online_unprotected: list[dict[str, str]] = []
    agent_missing: list[dict[str, str]] = []
    protection_interrupted: list[dict[str, str]] = []

    for row in standardized_rows:
        owner = owner_mapping.get(row["企业项目"].strip(), "")
        if row["企业项目"].strip() and not owner:
            missing_owner_projects.add(row["企业项目"].strip())

        output_row = {column: row.get(column, "") for column in OUTPUT_COLUMNS if column != "负责人"}
        output_row["负责人"] = owner
        match_keys = build_match_keys(row.get("服务器ID", ""), row.get("IP地址", ""), row.get("服务器名称", ""))

        if row["服务器状态"] == "运行中" and row["Agent状态"] == "在线" and row["防护状态"] == "未防护":
            if match_keys.isdisjoint(unquota_keys):
                online_unprotected.append(output_row)

        if row["服务器状态"] == "运行中" and row["Agent状态"] == "未安装":
            if match_keys.isdisjoint(deferred_install_keys):
                agent_missing.append(output_row)

        if row["服务器状态"] == "运行中" and row["防护状态"] == "防护中断":
            protection_interrupted.append(output_row)

    batch_code = datetime.now().strftime("%Y%m%d%H%M%S") + uuid4().hex[:6]
    date_text = datetime.now().strftime("%Y-%m-%d")
    batch_dir = EXPORT_DIR / batch_code
    batch_dir.mkdir(parents=True, exist_ok=True)

    online_path = _write_result_files(
        batch_dir,
        f"{REPORT_PREFIX}Agent在线未添加防护配置主机列表-{date_text}",
        online_unprotected,
        f"{REPORT_PREFIX}Agent在线未添加防护配置主机列表",
    )
    missing_path = _write_result_files(
        batch_dir,
        f"{REPORT_PREFIX}Agent未安装主机列表-{date_text}",
        agent_missing,
        f"{REPORT_PREFIX}Agent未安装主机列表",
    )
    interrupted_path = _write_result_files(
        batch_dir,
        f"{REPORT_PREFIX}Agent防护中断主机列表-{date_text}",
        protection_interrupted,
        f"{REPORT_PREFIX}Agent防护中断主机列表",
    )

    create_result_history(
        batch_code=batch_code,
        source_file_name=file_path.name,
        operator_name=operator_name,
        online_unprotected_count=len(online_unprotected),
        agent_missing_count=len(agent_missing),
        protection_interrupted_count=len(protection_interrupted),
        missing_owner_count=len(missing_owner_projects),
        online_unprotected_path=str(online_path["xlsx"]),
        agent_missing_path=str(missing_path["xlsx"]),
        protection_interrupted_path=str(interrupted_path["xlsx"]),
        missing_owner_projects="、".join(sorted(missing_owner_projects)),
    )
    save_import_history(file_path.name, operator_name, "processed")

    return {
        "batch_code": batch_code,
        "counts": {
            "online_unprotected": len(online_unprotected),
            "agent_missing": len(agent_missing),
            "protection_interrupted": len(protection_interrupted),
            "missing_owner": len(missing_owner_projects),
        },
        "previews": {
            "online_unprotected": online_unprotected[:20],
            "agent_missing": agent_missing[:20],
            "protection_interrupted": protection_interrupted[:20],
        },
        "missing_owner_projects": sorted(missing_owner_projects),
    }


def persist_upload(file_name: str, file_bytes: bytes) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    safe_name = f"{timestamp}_{Path(file_name).name}"
    target = UPLOAD_DIR / safe_name
    target.write_bytes(file_bytes)
    return target


def standardize_asset_rows(rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[str]]:
    header_map = {normalize_header(key): key for key in rows[0].keys()}
    resolved_keys: dict[str, str] = {}
    missing_fields: list[str] = []
    for standard_field, aliases in ASSET_FIELD_ALIASES.items():
        matched = None
        for alias in aliases:
            matched = header_map.get(normalize_header(alias))
            if matched:
                break
        if matched is None:
            missing_fields.append(standard_field)
        else:
            resolved_keys[standard_field] = matched

    standardized: list[dict[str, str]] = []
    for row in rows:
        normalized_row = {field: row.get(source_key, "").strip() for field, source_key in resolved_keys.items()}
        if any(value for value in normalized_row.values()):
            standardized.append(normalized_row)
    return standardized, missing_fields


def normalize_header(value: str) -> str:
    return value.strip().replace(" ", "").replace("_", "").replace("-", "").lower()


def _write_result_files(batch_dir: Path, base_name: str, rows: list[dict[str, str]], detail_sheet_name: str) -> dict[str, Path]:
    xlsx_path = batch_dir / f"{base_name}.xlsx"
    csv_path = batch_dir / f"{base_name}.csv"
    write_xlsx(
        xlsx_path,
        OUTPUT_COLUMNS,
        rows,
        summary_rows=_build_summary_rows(rows),
        detail_sheet_name=detail_sheet_name,
    )
    write_csv(csv_path, OUTPUT_COLUMNS, rows)
    return {"xlsx": xlsx_path, "csv": csv_path}


def _build_summary_rows(rows: Iterable[dict[str, str]]) -> list[dict[str, object]]:
    owner_counts: dict[str, int] = {}
    for row in rows:
        owner = row.get("负责人", "").strip() or "未匹配负责人"
        owner_counts[owner] = owner_counts.get(owner, 0) + (1 if row.get("服务器ID", "").strip() else 0)

    summary_rows = [
        {"负责人": owner, "服务器ID计数": count}
        for owner, count in sorted(owner_counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    total_count = sum(item["服务器ID计数"] for item in summary_rows)
    summary_rows.append({"负责人": "合计", "服务器ID计数": total_count})
    return summary_rows
