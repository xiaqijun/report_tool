import csv
from pathlib import Path

from openpyxl import Workbook, load_workbook


def read_table_file(file_path: Path) -> list[dict[str, str]]:
    suffix = file_path.suffix.lower()
    if suffix == ".csv":
        with file_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            return [_stringify_row(row) for row in reader]
    if suffix in {".xlsx", ".xlsm"}:
        workbook = load_workbook(file_path, read_only=True, data_only=True)
        sheet = workbook.active
        rows = list(sheet.iter_rows(values_only=True))
        if not rows:
            return []
        headers = [str(cell).strip() if cell is not None else "" for cell in rows[0]]
        data: list[dict[str, str]] = []
        for raw_row in rows[1:]:
            row = {headers[index]: _cell_to_text(value) for index, value in enumerate(raw_row) if index < len(headers)}
            if any(value.strip() for value in row.values()):
                data.append(row)
        return data
    raise ValueError("仅支持 csv、xlsx、xlsm 文件。")


def write_xlsx(file_path: Path, headers: list[str], rows: list[dict[str, str]]) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(headers)
    for row in rows:
        sheet.append([row.get(header, "") for header in headers])
    workbook.save(file_path)


def write_csv(file_path: Path, headers: list[str], rows: list[dict[str, str]]) -> None:
    with file_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def _stringify_row(row: dict[str, object]) -> dict[str, str]:
    return {str(key).strip(): _cell_to_text(value) for key, value in row.items() if key is not None}


def _cell_to_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()
