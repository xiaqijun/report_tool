from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from app.services import inventory


class InventoryGenerationTests(TestCase):
    def test_build_match_key_extracts_ip_from_annotated_or_multi_ip_text(self) -> None:
        self.assertEqual(
            inventory.build_match_keys("", "10.167.89.35（私有）", "host-a"),
            {"ip:10.167.89.35"},
        )
        self.assertEqual(
            inventory.build_match_keys("", "10.167.89.35（私有）/172.16.8.20（公网）", "host-b"),
            {"ip:10.167.89.35", "ip:172.16.8.20"},
        )
        self.assertEqual(
            inventory.build_match_key("", "10.167.89.35（私有）", "host-a"),
            "ip:10.167.89.35",
        )

    def test_online_unprotected_excludes_host_when_any_ip_matches_exclusion_list(self) -> None:
        rows = [
            {
                "服务器名称": "host-multi-ip",
                "服务器ID": "",
                "IP地址": "10.167.89.35（私有）/172.16.8.20（公网）",
                "配额ID": "quota-1",
                "服务器状态": "运行中",
                "Agent状态": "在线",
                "风险状态": "高危",
                "防护状态": "未防护",
                "操作系统": "Linux",
                "版本类型": "正式",
                "企业项目": "项目A",
                "来源": "CMDB",
            }
        ]

        with TemporaryDirectory() as temp_dir:
            export_dir = Path(temp_dir)
            with (
                patch.object(inventory, "read_table_file", return_value=rows),
                patch.object(inventory, "get_owner_mapping_dict", return_value={"项目A": "张三"}),
                patch.object(inventory, "get_exclusion_match_keys", side_effect=[{"ip:172.16.8.20"}, set()]),
                patch.object(inventory, "EXPORT_DIR", export_dir),
                patch.object(inventory, "create_result_history"),
                patch.object(inventory, "save_import_history"),
            ):
                result = inventory.generate_from_asset_file(export_dir / "asset.xlsx", "系统管理员")

        self.assertEqual(result["counts"]["online_unprotected"], 0)

    def test_protection_interrupted_requires_running_server(self) -> None:
        rows = [
            {
                "服务器名称": "host-interrupted",
                "服务器ID": "srv-1",
                "IP地址": "10.0.0.1",
                "配额ID": "quota-1",
                "服务器状态": "运行中",
                "Agent状态": "在线",
                "风险状态": "高危",
                "防护状态": "防护中断",
                "操作系统": "Linux",
                "版本类型": "正式",
                "企业项目": "项目A",
                "来源": "CMDB",
            },
            {
                "服务器名称": "host-no-agent",
                "服务器ID": "srv-2",
                "IP地址": "10.0.0.2",
                "配额ID": "quota-2",
                "服务器状态": "运行中",
                "Agent状态": "未安装",
                "风险状态": "高危",
                "防护状态": "防护中断",
                "操作系统": "Linux",
                "版本类型": "正式",
                "企业项目": "项目A",
                "来源": "CMDB",
            },
            {
                "服务器名称": "host-not-running",
                "服务器ID": "srv-3",
                "IP地址": "10.0.0.3",
                "配额ID": "quota-3",
                "服务器状态": "已停止",
                "Agent状态": "在线",
                "风险状态": "高危",
                "防护状态": "防护中断",
                "操作系统": "Linux",
                "版本类型": "正式",
                "企业项目": "项目A",
                "来源": "CMDB",
            },
            {
                "服务器名称": "host-unprotected",
                "服务器ID": "srv-4",
                "IP地址": "10.0.0.4",
                "配额ID": "quota-4",
                "服务器状态": "运行中",
                "Agent状态": "在线",
                "风险状态": "高危",
                "防护状态": "未防护",
                "操作系统": "Linux",
                "版本类型": "正式",
                "企业项目": "项目A",
                "来源": "CMDB",
            },
        ]

        with TemporaryDirectory() as temp_dir:
            export_dir = Path(temp_dir)
            with (
                patch.object(inventory, "read_table_file", return_value=rows),
                patch.object(inventory, "get_owner_mapping_dict", return_value={"项目A": "张三"}),
                patch.object(inventory, "get_exclusion_match_keys", return_value=set()),
                patch.object(inventory, "EXPORT_DIR", export_dir),
                patch.object(inventory, "create_result_history"),
                patch.object(inventory, "save_import_history"),
            ):
                result = inventory.generate_from_asset_file(export_dir / "asset.xlsx", "系统管理员")

        self.assertEqual(result["counts"]["protection_interrupted"], 2)
        self.assertEqual(
            [row["服务器ID"] for row in result["previews"]["protection_interrupted"]],
            ["srv-1", "srv-2"],
        )