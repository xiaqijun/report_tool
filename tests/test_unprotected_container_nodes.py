from unittest import TestCase
from unittest.mock import MagicMock, patch

from app import db


class UnprotectedContainerNodeTests(TestCase):
    def test_map_import_row_keeps_unprotected_container_node(self) -> None:
        row = {
            "服务器名称": "container-node-1",
            "服务器ID": "server-1",
            "IP地址": "10.0.0.1（私有）",
            "集群名称": "cluster-a",
            "集群ID": "cluster-id-1",
            "Agent状态": "在线",
            "防护状态": "未防护",
            "服务器状态": "正常",
            "企业项目": "项目A",
            "服务商": "CCE",
            "Agent ID": "agent-1",
            "防护版本": "--",
            "存在容器进程": "是",
        }

        payload = db.map_import_row("unprotected-container-nodes", row)

        self.assertIsNotNone(payload)
        self.assertEqual(payload["server_id"], "server-1")
        self.assertEqual(payload["cluster_name"], "cluster-a")
        self.assertEqual(payload["has_container_process"], "是")

    def test_map_import_row_excludes_protected_or_non_container_node(self) -> None:
        protected = {"防护状态": "防护中", "存在容器进程": "是"}
        no_container = {"防护状态": "未防护", "存在容器进程": "否"}

        self.assertIsNone(db.map_import_row("unprotected-container-nodes", protected))
        self.assertIsNone(db.map_import_row("unprotected-container-nodes", no_container))

    def test_import_replaces_previous_snapshot(self) -> None:
        rows = [
            {
                "服务器名称": "container-node-1",
                "服务器ID": "server-1",
                "防护状态": "未防护",
                "存在容器进程": "是",
            },
            {
                "服务器名称": "standard-node",
                "服务器ID": "server-2",
                "防护状态": "未防护",
                "存在容器进程": "否",
            },
        ]
        connection = MagicMock()
        connection_context = MagicMock()
        connection_context.__enter__.return_value = connection
        connection_context.__exit__.return_value = False

        with patch.object(db, "get_connection", return_value=connection_context):
            count = db.import_dataset_records("unprotected-container-nodes", rows)

        self.assertEqual(count, 1)
        self.assertEqual(connection.execute.call_args_list[0].args, ("DELETE FROM unprotected_container_nodes",))
        self.assertEqual(connection.execute.call_count, 2)
