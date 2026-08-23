from __future__ import annotations

import gc
import json
import shutil
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from material_system.application_repository import ApplicationRepository
from material_system.enhanced_http_server import create_enhanced_server


class EnhancedHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="material-http-test-"))
        self.repository = ApplicationRepository(self.temp_dir / "test.db")
        static_dir = Path(__file__).resolve().parents[1] / "web"
        self.server = create_enhanced_server("127.0.0.1", 0, self.repository, static_dir)
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

    def test_extension_status_always_includes_locations(self) -> None:
        settings = self.repository.get_settings()
        request = urllib.request.Request(
            self.base_url + "/api/extension/status",
            headers={"X-Inventory-Token": settings["extension_token"]},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.load(response)

        self.assertTrue(payload["ok"])
        self.assertIsInstance(payload["locations"], list)
        self.assertGreaterEqual(len(payload["locations"]), 1)
        self.assertEqual(payload["default_location_id"], payload["locations"][0]["id"])

    def test_image_viewer_assets_are_served(self) -> None:
        for path, marker in (
            ("/image-viewer.js", "materialImageViewer"),
            ("/image-viewer.css", ".image-viewer"),
        ):
            with urllib.request.urlopen(self.base_url + path, timeout=5) as response:
                content = response.read().decode("utf-8")
            self.assertIn(marker, content)


if __name__ == "__main__":
    unittest.main()
