import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

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
                "parent_folder_id": "folder-id",
                "access_token": "token",
                "open_id": "open-id",
            },
        ):
            settings = tencent_docs.get_public_settings()

        self.assertEqual(settings["parent_folder_id"], "folder-id")
        self.assertTrue(settings["has_client_secret"])
        self.assertTrue(settings["authorized"])
        self.assertNotIn("client_secret", settings)
        self.assertNotIn("access_token", settings)

    def test_import_document_uploads_to_cos_and_waits_for_online_document(self) -> None:
        content = b"xlsx-content"
        expected_md5 = hashlib.md5(content).hexdigest()
        put_response = MagicMock()
        headers = {
            "Access-Token": "access-token",
            "Client-Id": "client-id",
            "Open-Id": "open-id",
        }
        with TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "report.xlsx"
            file_path.write_bytes(content)
            with (
                patch.object(
                    tencent_docs,
                    "_request_json",
                    side_effect=[
                        {
                            "data": {
                                "COSPutURL": "https://docs-import-export.cos.ap-guangzhou.myqcloud.com/report.xlsx?signature=1",
                                "COSFileKey": "temp/report.xlsx",
                                "CustomHeader": {
                                    "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                    "x-cos-acl": "default",
                                },
                            }
                        },
                        {"data": {"progressQueryID": "progress-id"}},
                        {
                            "data": {
                                "ID": "file-id",
                                "title": "report",
                                "url": "https://docs.qq.com/sheet/report-id",
                                "progress": 100,
                            }
                        },
                    ],
                ) as request_json,
                patch.object(tencent_docs.requests, "put", return_value=put_response) as put_file,
            ):
                result = tencent_docs._import_document(
                    file_path,
                    {"parent_folder_id": "folder-id"},
                    headers,
                )

        self.assertEqual(result["url"], "https://docs.qq.com/sheet/report-id")
        self.assertEqual(request_json.call_args_list[0].args, ("POST", "/openapi/drive/v2/files/upload"))
        self.assertEqual(request_json.call_args_list[0].kwargs["data"]["fileMD5"], expected_md5)
        self.assertEqual(request_json.call_args_list[1].kwargs["data"]["parentfolderID"], "folder-id")
        self.assertEqual(
            request_json.call_args_list[2].kwargs["params"],
            {"progressQueryID": "progress-id"},
        )
        put_file.assert_called_once()
        put_response.raise_for_status.assert_called_once()

    def test_sync_history_documents_uploads_all_three_reports_and_saves_links(self) -> None:
        with TemporaryDirectory() as temp_dir:
            paths = [Path(temp_dir) / f"report-{index}.xlsx" for index in range(3)]
            for path in paths:
                path.write_bytes(b"content")
            history = {
                "batch_code": "batch-1",
                "online_unprotected_path": str(paths[0]),
                "agent_missing_path": str(paths[1]),
                "protection_interrupted_path": str(paths[2]),
                "tencent_online_unprotected_url": "",
                "tencent_agent_missing_url": "",
                "tencent_protection_interrupted_url": "",
            }
            with (
                patch.object(tencent_docs.db, "get_result_history", return_value=history),
                patch.object(
                    tencent_docs,
                    "_ensure_access_token",
                    return_value={"access_token": "token", "client_id": "client", "open_id": "open"},
                ),
                patch.object(
                    tencent_docs,
                    "_import_document",
                    side_effect=[
                        {"url": "https://docs.qq.com/sheet/online"},
                        {"url": "https://docs.qq.com/sheet/missing"},
                        {"url": "https://docs.qq.com/sheet/interrupted"},
                    ],
                ) as import_document,
                patch.object(tencent_docs.db, "update_result_history_tencent_docs") as save_links,
            ):
                result = tencent_docs.sync_history_documents("batch-1")

        self.assertEqual(import_document.call_count, 3)
        self.assertEqual(result["count"], 3)
        save_links.assert_called_once_with(
            "batch-1",
            "https://docs.qq.com/sheet/online",
            "https://docs.qq.com/sheet/missing",
            "https://docs.qq.com/sheet/interrupted",
        )

    def test_sync_history_documents_reuses_existing_links(self) -> None:
        history = {
            "batch_code": "batch-1",
            "tencent_online_unprotected_url": "https://docs.qq.com/sheet/online",
            "tencent_agent_missing_url": "https://docs.qq.com/sheet/missing",
            "tencent_protection_interrupted_url": "https://docs.qq.com/sheet/interrupted",
        }
        with (
            patch.object(tencent_docs.db, "get_result_history", return_value=history),
            patch.object(
                tencent_docs,
                "_ensure_access_token",
                return_value={"access_token": "token", "client_id": "client", "open_id": "open"},
            ),
            patch.object(tencent_docs, "_import_document") as import_document,
            patch.object(tencent_docs.db, "update_result_history_tencent_docs"),
        ):
            result = tencent_docs.sync_history_documents("batch-1")

        import_document.assert_not_called()
        self.assertEqual(result["count"], 3)

    def test_rejects_non_tencent_cos_upload_url(self) -> None:
        with self.assertRaisesRegex(ValueError, "不可信"):
            tencent_docs._validate_cos_put_url("https://example.com/upload")
