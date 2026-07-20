import base64
import json
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from openpyxl import Workbook

from app.services import tencent_docs


class TencentDocsServiceTests(TestCase):
    def test_build_authorize_url_uses_official_oauth_parameters(self) -> None:
        settings = {
            "client_id": "client-id",
            "redirect_uri": "https://report.example.com/api/tencent-docs/callback",
        }
        with patch.object(tencent_docs, "_require_configuration", return_value=settings):
            authorize_url = tencent_docs.build_authorize_url("state-value")

        parsed = urlparse(authorize_url)
        query = parse_qs(parsed.query)
        self.assertEqual(parsed.path, "/oauth/v2/authorize")
        self.assertEqual(query["client_id"], ["client-id"])
        self.assertEqual(query["response_type"], ["code"])
        self.assertEqual(query["scope"], ["all"])
        self.assertEqual(query["state"], ["state-value"])

    def test_public_settings_exposes_folder_without_secrets(self) -> None:
        with patch.object(
            tencent_docs,
            "get_settings",
            return_value={
                "client_id": "client-id",
                "client_secret": "secret",
                "target_document_url": "https://docs.qq.com/sheet/document-id",
                "access_token": "token",
                "open_id": "open-id",
            },
        ):
            settings = tencent_docs.get_public_settings()

        self.assertEqual(settings["target_document_url"], "https://docs.qq.com/sheet/document-id")
        self.assertTrue(settings["has_client_secret"])
        self.assertTrue(settings["authorized"])
        self.assertNotIn("client_secret", settings)
        self.assertNotIn("access_token", settings)

    def test_manual_access_token_does_not_require_oauth_secret(self) -> None:
        settings = {
            "client_id": "client-id",
            "access_token": "access-token",
            "open_id": "open-id",
        }
        with patch.object(tencent_docs, "get_settings", return_value=settings):
            self.assertEqual(tencent_docs._ensure_access_token(), settings)

    def test_save_configuration_updates_manual_token_without_exposing_it(self) -> None:
        expires_at_timestamp = int((datetime.now() + timedelta(days=30)).timestamp())
        encoded_payload = base64.urlsafe_b64encode(
            json.dumps({"exp": expires_at_timestamp}).encode("utf-8")
        ).decode("ascii").rstrip("=")
        access_token = f"header.{encoded_payload}.signature"
        settings = {
            "client_id": "old-client-id",
            "access_token": "old-token",
            "open_id": "old-open-id",
            "refresh_token": "old-refresh-token",
        }
        with (
            patch.object(tencent_docs, "get_settings", return_value=settings),
            patch.object(tencent_docs, "_save_settings") as save_settings,
        ):
            public_settings = tencent_docs.save_configuration(
                {
                    "client_id": "client-id",
                    "access_token": access_token,
                    "open_id": "new-open-id",
                    "target_document_url": "https://docs.qq.com/sheet/DRGRZS3pnY3RScFhM?tab=BB08J2",
                }
            )

        saved_settings = save_settings.call_args.args[0]
        self.assertEqual(saved_settings["access_token"], access_token)
        self.assertEqual(saved_settings["open_id"], "new-open-id")
        self.assertEqual(
            saved_settings["token_expires_at"],
            datetime.fromtimestamp(expires_at_timestamp).isoformat(timespec="seconds"),
        )
        self.assertNotIn("refresh_token", saved_settings)
        self.assertTrue(public_settings["authorized"])
        self.assertNotIn("access_token", public_settings)

    def test_save_configuration_rejects_token_without_expiration(self) -> None:
        with (
            patch.object(tencent_docs, "get_settings", return_value={}),
            patch.object(tencent_docs, "_save_settings") as save_settings,
            self.assertRaisesRegex(ValueError, "无法从 Access Token 获取有效期"),
        ):
            tencent_docs.save_configuration({"access_token": "invalid-token"})

        save_settings.assert_not_called()

    def test_import_document_uploads_to_cos_and_waits_for_online_document(self) -> None:
        encoded_id, normalized_url = tencent_docs._parse_target_document_url(
            "https://docs.qq.com/sheet/DRGRZS3pnY3RScFhM?tab=BB08J2"
        )

        self.assertEqual(encoded_id, "DRGRZS3pnY3RScFhM")
        self.assertEqual(normalized_url, "https://docs.qq.com/sheet/DRGRZS3pnY3RScFhM")

    def test_read_detail_sheet_values_skips_summary_sheet(self) -> None:
        with TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "report.xlsx"
            workbook = Workbook()
            summary = workbook.active
            summary.title = "汇总"
            summary.append(["负责人", "服务器ID计数"])
            detail = workbook.create_sheet("服务器明细")
            detail.append(["服务器ID", "是否为容器节点"])
            detail.append(["server-1", "是"])
            workbook.save(file_path)

            values = tencent_docs._read_detail_sheet_values(file_path)

        self.assertEqual(values, [["服务器ID", "是否为容器节点"], ["server-1", "是"]])

    def test_replace_sheet_values_writes_new_data_then_clears_stale_cells(self) -> None:
        with patch.object(tencent_docs, "_request_json", return_value={"ret": 0}) as request_json:
            tencent_docs._replace_sheet_values(
                "book-id",
                {"sheetID": "sheet-id", "rowCount": 10, "columnCount": 3},
                [["a", "b"], ["1", "2"]],
                {"Access-Token": "token"},
            )

        self.assertEqual(request_json.call_args_list[0].args, ("PUT", "/openapi/sheetbook/v2/book-id/values/sheet-id!A1:B2"))
        self.assertEqual(request_json.call_args_list[0].kwargs["json_body"]["values"], [["a", "b"], ["1", "2"]])
        self.assertEqual(request_json.call_args_list[1].args[0], "POST")
        self.assertIn("sheet-id!A3:C10:clear", request_json.call_args_list[1].args[1])
        self.assertIn("sheet-id!C1:C2:clear", request_json.call_args_list[2].args[1])

    def test_replace_sheet_values_rebuilds_sheet_when_target_range_is_too_small(self) -> None:
        replacement = {"sheetID": "replacement-id", "title": "目标", "rowCount": 2, "columnCount": 2}
        with (
            patch.object(tencent_docs, "_sheet_range_exists", return_value=False),
            patch.object(tencent_docs, "_rebuild_sheet", return_value=replacement) as rebuild_sheet,
        ):
            result = tencent_docs._replace_sheet_values(
                "book-id",
                {"sheetID": "old-id", "title": "目标", "rowCount": 1, "columnCount": 2},
                [["a", "b"], ["1", "2"]],
                {"Access-Token": "token"},
            )

        self.assertEqual(result, replacement)
        rebuild_sheet.assert_called_once()

    def test_rebuild_sheet_keeps_temporary_copy_until_replacement_is_written(self) -> None:
        with (
            patch.object(
                tencent_docs,
                "_add_sheet",
                side_effect=[
                    {"sheetID": "temporary-id", "title": "临时", "rowCount": 2, "columnCount": 2},
                    {"sheetID": "replacement-id", "title": "目标", "rowCount": 2, "columnCount": 2},
                ],
            ) as add_sheet,
            patch.object(tencent_docs, "_write_sheet_values") as write_values,
            patch.object(tencent_docs, "_delete_sheet") as delete_sheet,
        ):
            result = tencent_docs._rebuild_sheet(
                "book-id",
                {"sheetID": "old-id", "title": "目标", "rowCount": 1, "columnCount": 2},
                [["a", "b"], ["1", "2"]],
                {"Access-Token": "token"},
            )

        self.assertEqual(result["sheetID"], "replacement-id")
        self.assertEqual(add_sheet.call_count, 2)
        self.assertEqual(write_values.call_args_list[0].args[1], "temporary-id")
        self.assertEqual(write_values.call_args_list[1].args[1], "replacement-id")
        self.assertEqual([call.args[1] for call in delete_sheet.call_args_list], ["old-id", "temporary-id"])

    def test_sync_history_documents_uploads_all_three_reports_and_saves_links(self) -> None:
        with TemporaryDirectory() as temp_dir:
            paths = [Path(temp_dir) / f"report-{index}.xlsx" for index in range(3)]
            for path in paths:
                path.write_bytes(b"placeholder")
            history = {
                "batch_code": "batch-1",
                "online_unprotected_path": str(paths[0]),
                "agent_missing_path": str(paths[1]),
                "protection_interrupted_path": str(paths[2]),
            }
            settings = {
                "access_token": "token",
                "client_id": "client",
                "open_id": "open",
                "target_document_url": "https://docs.qq.com/sheet/document-id?tab=sheet-missing",
            }
            sheets = {
                "未添加防护配额信息": {"sheetID": "sheet-online", "rowCount": 1, "columnCount": 14},
                "未安装Agent信息": {"sheetID": "sheet-missing", "rowCount": 1, "columnCount": 14},
                "Agent防护中断信息": {"sheetID": "sheet-interrupted", "rowCount": 1, "columnCount": 14},
            }
            with (
                patch.object(tencent_docs.db, "get_result_history", return_value=history),
                patch.object(tencent_docs, "_ensure_access_token", return_value=settings),
                patch.object(tencent_docs, "_convert_document_id", return_value="book-id"),
                patch.object(tencent_docs, "_get_sheets_by_title", return_value=sheets),
                patch.object(tencent_docs, "_read_detail_sheet_values", return_value=[["header"], ["value"]]),
                patch.object(
                    tencent_docs,
                    "_replace_sheet_values",
                    side_effect=[
                        sheets["未添加防护配额信息"],
                        sheets["未安装Agent信息"],
                        sheets["Agent防护中断信息"],
                    ],
                ) as replace_sheet,
                patch.object(tencent_docs.db, "update_result_history_tencent_docs") as save_links,
            ):
                result = tencent_docs.sync_history_documents("batch-1")

        self.assertEqual(replace_sheet.call_count, 3)
        self.assertEqual(result["count"], 3)
        save_links.assert_called_once_with(
            "batch-1",
            "https://docs.qq.com/sheet/document-id?tab=sheet-online",
            "https://docs.qq.com/sheet/document-id?tab=sheet-missing",
            "https://docs.qq.com/sheet/document-id?tab=sheet-interrupted",
        )

    def test_rejects_non_tencent_cos_upload_url(self) -> None:
        with self.assertRaisesRegex(ValueError, "在线表格"):
            tencent_docs._parse_target_document_url("https://docs.qq.com/doc/document-id")
