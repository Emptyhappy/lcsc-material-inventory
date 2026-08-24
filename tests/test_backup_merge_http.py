from __future__ import annotations

import gc
import json
import shutil
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from material_system.advanced_inventory_http_server import create_advanced_inventory_server
from material_system.advanced_inventory_repository import AdvancedInventoryRepository


class BackupMergeHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="material-merge-http-test-"))
        self.target = AdvancedInventoryRepository(self.temp_dir / "target" / "materials.db")
        self.target.add_manual_material({"name": "原有物料", "quantity": 5})
        self.source = AdvancedInventoryRepository(self.temp_dir / "source" / "materials.db")
        self.source.add_manual_material({
            "name": "备份新增物料",
            "manufacturer_part": "MERGE-HTTP-01",
            "quantity": 7,
        })
        self.backup, _, _ = self.source.export_full_backup()
        static_dir = Path(__file__).resolve().parents[1] / "web"
        self.server = create_advanced_inventory_server(
            "127.0.0.1", 0, self.target, static_dir
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.target = None
        self.source = None
        gc.collect()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_merge_endpoint_keeps_current_and_adds_backup_material(self) -> None:
        request = urllib.request.Request(
            self.base_url + "/api/backup/merge",
            method="POST",
            data=self.backup,
            headers={"Content-Type": "application/zip"},
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            result = json.load(response)
        self.assertTrue(result["merged"])
        self.assertEqual(result["added_materials"], 1)
        self.assertEqual(len(self.target.list_materials(q="原有物料")), 1)
        imported = self.target.list_materials(q="MERGE-HTTP-01")[0]
        self.assertEqual(imported["stock"], 7)


if __name__ == "__main__":
    unittest.main()
