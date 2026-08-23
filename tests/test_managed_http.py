from __future__ import annotations

import gc
import json
import shutil
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from material_system.managed_http_server import create_managed_server
from material_system.managed_repository import ManagedInventoryRepository


class ManagedHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="material-managed-http-test-"))
        self.repository = ManagedInventoryRepository(self.temp_dir / "test.db")
        self.material = self.repository.add_manual_material({"name": "测试物料", "quantity": 2})
        static_dir = Path(__file__).resolve().parents[1] / "web"
        self.server = create_managed_server("127.0.0.1", 0, self.repository, static_dir)
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

    def test_manage_and_clear_endpoints_preserve_stock(self) -> None:
        changes = self.request("/api/changes")
        self.assertEqual(changes["latest_transaction_id"], 1)

        visible = self.request("/api/transactions?limit=20")
        transaction_id = visible[0]["id"]
        updated = self.request(
            f"/api/transactions/{transaction_id}", "PUT", {"note": "已核对"}
        )
        self.assertEqual(updated["note"], "已核对")

        cleared = self.request(
            f"/api/materials/{self.material['id']}/transactions/clear", "POST", {}
        )
        self.assertEqual(cleared["archived_count"], 1)
        self.assertEqual(self.request("/api/transactions?limit=20"), [])
        archived = self.request("/api/transactions?limit=20&include_archived=1")
        self.assertTrue(archived[0]["archived"])
        detail = self.request(f"/api/materials/{self.material['id']}")
        self.assertEqual(detail["stock"], 2)


if __name__ == "__main__":
    unittest.main()
