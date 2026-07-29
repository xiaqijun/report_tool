from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
import zipfile

from openpyxl import Workbook, load_workbook

from app.services.table_tools import TableInput, merge_table_files


def _write_workbook(path: Path, headers: list[str], rows: list[list[object]]) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "数据"
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    workbook.save(path)


class TableToolsTests(TestCase):
    def test_merges_direct_and_zipped_workbooks_with_deduplication_and_provenance(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            direct = root / "直接上传.xlsx"
            archived_workbook = root / "压缩包明细.xlsx"
            archive = root / "批量数据.zip"
            output = root / "result.xlsx"
            headers = ["漏洞编号", "资产名称"]
            _write_workbook(direct, headers, [["V-1", "主机A"], ["V-2", "主机B"]])
            _write_workbook(archived_workbook, headers, [["V-2", "主机B"], ["V-3", "主机C"]])
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as handle:
                handle.write(archived_workbook, "目录/压缩包明细.xlsx")

            stats = merge_table_files(
                [TableInput(direct, direct.name), TableInput(archive, archive.name)],
                output,
                deduplicate=True,
            )

            self.assertEqual(stats["input_files"], 2)
            self.assertEqual(stats["workbooks"], 2)
            self.assertEqual(stats["rows_read"], 4)
            self.assertEqual(stats["rows_written"], 3)
            self.assertEqual(stats["duplicate_rows"], 1)

            workbook = load_workbook(output, read_only=True, data_only=True)
            try:
                rows = list(workbook["合并明细"].iter_rows(values_only=True))
            finally:
                workbook.close()
            self.assertEqual(
                rows[0],
                ("漏洞编号", "资产名称", "来源压缩包", "来源文件", "来源行号"),
            )
            self.assertEqual(rows[1], ("V-1", "主机A", None, "直接上传.xlsx", 2))
            self.assertEqual(rows[2], ("V-2", "主机B", None, "直接上传.xlsx", 3))
            self.assertEqual(rows[3], ("V-3", "主机C", "批量数据.zip", "目录/压缩包明细.xlsx", 3))

    def test_can_merge_without_removing_duplicate_rows(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "first.xlsx"
            second = root / "second.xlsx"
            output = root / "result.xlsx"
            _write_workbook(first, ["编号"], [[1]])
            _write_workbook(second, ["编号"], [[1]])

            stats = merge_table_files(
                [TableInput(first, first.name), TableInput(second, second.name)],
                output,
                deduplicate=False,
            )

            self.assertEqual(stats["rows_read"], 2)
            self.assertEqual(stats["rows_written"], 2)
            self.assertEqual(stats["duplicate_rows"], 0)

    def test_rejects_workbooks_with_different_headers(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "first.xlsx"
            second = root / "second.xlsx"
            _write_workbook(first, ["编号", "名称"], [[1, "A"]])
            _write_workbook(second, ["编号", "说明"], [[2, "B"]])

            with self.assertRaisesRegex(ValueError, "表头不一致"):
                merge_table_files(
                    [TableInput(first, first.name), TableInput(second, second.name)],
                    root / "result.xlsx",
                )
