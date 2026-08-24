from __future__ import annotations

import gc
import json
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from material_system.advanced_inventory_http_server import create_advanced_inventory_server
from material_system.advanced_inventory_repository import AdvancedInventoryRepository


class AdvancedHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="material-advanced-http-test-"))
        self.repository = AdvancedInventoryRepository(self.temp_dir / "materials.db")
        self.material = self.repository.add_manual_material({"name": "HTTP物料", "quantity": 2})
        static_dir = Path(__file__).resolve().parents[1] / "web"
        self.server = create_advanced_inventory_server(
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

    def test_manual_image_is_uploaded_served_and_material_can_be_deleted(self) -> None:
        png = b"\x89PNG\r\n\x1a\nhttp-image"
        request = urllib.request.Request(
            self.base_url + f"/api/materials/{self.material['id']}/image",
            method="POST",
            data=png,
            headers={"Content-Type": "image/png"},
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            uploaded = json.load(response)
        with urllib.request.urlopen(self.base_url + uploaded["image_url"], timeout=10) as response:
            self.assertEqual(response.read(), png)

        delete_request = urllib.request.Request(
            self.base_url + "/api/materials/delete-batch",
            method="POST",
            data=json.dumps({"material_ids": [self.material["id"]]}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(delete_request, timeout=10) as response:
            result = json.load(response)
        self.assertEqual(result["deleted_count"], 1)
        with self.assertRaises(urllib.error.HTTPError) as context:
            urllib.request.urlopen(
                self.base_url + f"/api/materials/{self.material['id']}", timeout=10
            )
        self.assertEqual(context.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
