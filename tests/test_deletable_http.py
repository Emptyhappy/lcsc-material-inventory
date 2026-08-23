from __future__ import annotations

import gc
import json
import shutil
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from material_system.deletable_http_server import create_deletable_server
from material_system.deletable_repository import DeletableInventoryRepository


class DeletableHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="material-deletable-http-test-"))
        self.repository = DeletableInventoryRepository(self.temp_dir / "test.db")
        self.material = self.repository.add_manual_material({"name": "测试物料", "quantity": 2})
        self.inbound = self.repository.stock_operation(
            self.material["id"], {"kind": "inbound", "quantity": 3, "note": "采购"}
        )
        static_dir = Path(__file__).resolve().parents[1] / "web"
        self.server = create_deletable_server(
            "127.0.0.1", 0, self.repository, static_dir
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.repository = None
        gc.collect()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def request(self, path: str, method: str = "GET", body=None):
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path,
            method=method,
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.load(response)

    def test_delete_endpoints_remove_history_without_changing_stock(self) -> None:
        result = self.request(
            f"/api/transactions/{self.inbound['transaction_id']}/delete", "POST", {}
        )
        self.assertEqual(result["deleted_count"], 1)
        detail = self.request(f"/api/materials/{self.material['id']}")
        self.assertEqual(detail["stock"], 5)
        self.assertEqual(len(detail["transactions"]), 1)

        result = self.request(
            f"/api/materials/{self.material['id']}/transactions/delete-all",
            "POST",
            {},
        )
        self.assertEqual(result["deleted_count"], 1)
        self.assertEqual(self.request("/api/transactions?include_archived=1"), [])
        detail = self.request(f"/api/materials/{self.material['id']}")
        self.assertEqual(detail["stock"], 5)
        self.assertEqual(self.request("/api/changes")["deleted_count"], 2)


if __name__ == "__main__":
    unittest.main()
