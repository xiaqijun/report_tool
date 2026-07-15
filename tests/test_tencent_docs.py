from datetime import datetime, timedelta
from unittest import TestCase
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from app.services import tencent_docs


class TencentDocsServiceTests(TestCase):
    def test_extract_file_id_from_sheet_url(self) -> None:
        self.assertEqual(
            tencent_docs.extract_file_id("https://docs.qq.com/sheet/ABCDE12345?tab=BB08J2"),
            "ABCDE12345",
        )
        self.assertEqual(tencent_docs.extract_file_id("300000000$AAAAAAAAAAAA"), "300000000$AAAAAAAAAAAA")

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

    def test_grid_data_to_records_uses_first_row_as_headers(self) -> None:
        grid_data = {
            "rows": [
                {
                    "values": [
                        {"cellValue": {"text": "服务器名称"}},
                        {"cellValue": {"text": "防护状态"}},
                        {"cellValue": {"text": "存在容器进程"}},
                    ]
                },
                {
                    "values": [
                        {"cellValue": {"text": "node-1"}},
                        {"cellValue": {"text": "未防护"}},
                        {"cellValue": {"text": "是"}},
                    ]
                },
            ]
        }

        self.assertEqual(
            tencent_docs.grid_data_to_records(grid_data),
            [{"服务器名称": "node-1", "防护状态": "未防护", "存在容器进程": "是"}],
        )

    def test_sync_discovers_first_sheet_and_replaces_snapshot(self) -> None:
        settings = {
            "client_id": "client-id",
            "client_secret": "client-secret",
            "redirect_uri": "https://report.example.com/api/tencent-docs/callback",
            "file_id": "file-id",
            "sheet_range": "A1:T500",
            "access_token": "access-token",
            "open_id": "open-id",
            "token_expires_at": (datetime.now() + timedelta(days=1)).isoformat(timespec="seconds"),
        }
        workbook_response = {"data": {"properties": [{"sheetId": "sheet-1", "title": "节点列表"}]}}
        range_response = {
            "data": {
                "gridData": {
                    "rows": [
                        {
                            "values": [
                                {"cellValue": {"text": "服务器名称"}},
                                {"cellValue": {"text": "防护状态"}},
                                {"cellValue": {"text": "存在容器进程"}},
                            ]
                        },
                        {
                            "values": [
                                {"cellValue": {"text": "node-1"}},
                                {"cellValue": {"text": "未防护"}},
                                {"cellValue": {"text": "是"}},
                            ]
                        },
                    ]
                }
            }
        }

        with (
            patch.object(tencent_docs, "get_settings", return_value=settings),
            patch.object(tencent_docs, "_request_json", side_effect=[workbook_response, range_response]),
            patch.object(tencent_docs, "_save_settings"),
            patch.object(tencent_docs.db, "import_dataset_records", return_value=1) as import_records,
        ):
            result = tencent_docs.sync_container_nodes()

        imported_rows = import_records.call_args.args[1]
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["sheet_id"], "sheet-1")
        self.assertEqual(imported_rows[0]["服务器名称"], "node-1")
