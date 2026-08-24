from __future__ import annotations

import gc
import json
import shutil
import tempfile
import threading
import unittest
import urllib.request
import zipfile
from io import BytesIO
from pathlib import Path

from material_system.backup_http_server import create_backup_server
from material_system.backup_repository import BackupInventoryRepository


class BackupHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="material-backup-http-test-"))
        self.repository = BackupInventoryRepository(self.temp_dir / "materials.db")
        self.repository.add_manual_material({"name": "接口备份物料", "quantity": 8})
        (self.repository.image_dir / "C88888.png").write_bytes(b"image-via-http")
        static_dir = Path(__file__).resolve().parents[1] / "web"
        self.server = create_backup_server("127.0.0.1", 0, self.repository, static_dir)
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

    def test_export_and_restore_endpoints_round_trip_complete_backup(self) -> None:
        with urllib.request.urlopen(self.base_url + "/api/backup/export", timeout=10) as response:
            backup = response.read()
            self.assertEqual(response.headers.get_content_type(), "application/zip")
            self.assertIn("full-backup", response.headers["Content-Disposition"])
        with zipfile.ZipFile(BytesIO(backup)) as archive:
            self.assertIn("manifest.json", archive.namelist())
            self.assertIn("materials.db", archive.namelist())
            self.assertIn("images/C88888.png", archive.namelist())

        self.repository.add_manual_material({"name": "恢复后应消失", "quantity": 1})
        request = urllib.request.Request(
            self.base_url + "/api/backup/restore",
            method="POST",
            data=backup,
            headers={"Content-Type": "application/zip"},
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            result = json.load(response)
        self.assertTrue(result["restored"])
        self.assertEqual(result["counts"]["materials"], 1)
        self.assertEqual(result["image_count"], 1)
        self.assertEqual(len(self.repository.list_materials(q="接口备份物料")), 1)
        self.assertEqual(self.repository.list_materials(q="恢复后应消失"), [])


if __name__ == "__main__":
    unittest.main()
