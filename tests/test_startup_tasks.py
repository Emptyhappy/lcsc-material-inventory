from __future__ import annotations

import gc
import shutil
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import patch

from material_system.application_repository import ApplicationRepository
from material_system.repository import InventoryRepository
from material_system.startup_tasks import cache_existing_images


class FakeImageResponse:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.headers = Message()
        self.headers["Content-Type"] = "image/jpeg"
        self.headers["Content-Length"] = str(len(data))

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit: int = -1) -> bytes:
        return self.data if limit < 0 else self.data[:limit]


class StartupTaskTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="material-startup-test-"))
        self.repository = ApplicationRepository(self.temp_dir / "test.db")

    def tearDown(self) -> None:
        self.repository = None
        gc.collect()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_legacy_multiple_breviary_images_use_first_source_image(self) -> None:
        first = "https://alimg.szlcsc.com/upload/public/product/breviary/one.jpg"
        second = "https://alimg.szlcsc.com/upload/public/product/breviary/two.jpg"
        created = InventoryRepository.import_lcsc(
            self.repository,
            {
                "request_id": "legacy-image-1",
                "supplier_sku": "C2687968",
                "name": "TPS54360B-Q1",
                "image_url": f"{first}<$>{second}",
                "quantity": 2,
            },
        )
        requested_urls: list[str] = []

        def fake_urlopen(request, timeout=0):
            requested_urls.append(request.full_url)
            return FakeImageResponse(b"legacy-image")

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            result = cache_existing_images(self.repository)

        detail = self.repository.material_detail(created["id"])
        self.assertEqual(result["cached"], 1)
        self.assertEqual(
            requested_urls,
            ["https://alimg.szlcsc.com/upload/public/product/source/one.jpg"],
        )
        self.assertEqual(detail["stock"], 2)
        self.assertEqual(detail["image_url"], "/media/images/C2687968.jpg")
        self.assertEqual(
            (self.temp_dir / "images" / "C2687968.jpg").read_bytes(),
            b"legacy-image",
        )


if __name__ == "__main__":
    unittest.main()
