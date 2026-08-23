from __future__ import annotations

import gc
import shutil
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import patch

from material_system.application_repository import ApplicationRepository


class FakeImageResponse:
    def __init__(self, data: bytes, content_type: str = "image/jpeg") -> None:
        self.data = data
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        self.headers["Content-Length"] = str(len(data))

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit: int = -1) -> bytes:
        return self.data if limit < 0 else self.data[:limit]


class EnhancementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="material-enhancement-test-"))
        self.database = ApplicationRepository(self.temp_dir / "test.db")

    def tearDown(self) -> None:
        self.database = None
        gc.collect()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_lcsc_image_is_cached_and_custom_fields_are_saved(self) -> None:
        payload = {
            "request_id": "image-request-1",
            "supplier_sku": "C99198",
            "name": "厚膜电阻 10kΩ",
            "manufacturer_part": "RC0603JR-0710KL",
            "brand": "YAGEO(国巨)",
            "image_url": "https://alimg.szlcsc.com/example/test.jpg",
            "quantity": 12,
            "min_stock": 5,
            "unit": "片",
            "notes": "项目A备料",
        }
        with patch("urllib.request.urlopen", return_value=FakeImageResponse(b"fake-jpeg-data")):
            result = self.database.import_lcsc(payload)
        self.assertTrue(result["created"])
        self.assertTrue(result["image_cached"])
        self.assertEqual(result["image_url"], "/media/images/C99198.jpg")
        self.assertEqual(result["stock"], 12)
        self.assertEqual(result["min_stock"], 5)
        self.assertEqual(result["unit"], "片")
        self.assertEqual(result["notes"], "项目A备料")
        self.assertEqual((self.temp_dir / "images" / "C99198.jpg").read_bytes(), b"fake-jpeg-data")

    def test_category_order_survives_lcsc_resync(self) -> None:
        items = [
            {"external_id": "1", "parent_external_id": None, "name": "电子元器件"},
            {"external_id": "101", "parent_external_id": "1", "name": "第一类", "sort_order": 1},
            {"external_id": "102", "parent_external_id": "1", "name": "第二类", "sort_order": 2},
            {"external_id": "103", "parent_external_id": "1", "name": "第三类", "sort_order": 3},
        ]
        self.database.sync_categories(items)
        first = self.database.categories()
        root = next(item for item in first["categories"] if item["external_id"] == "1")
        child_ids = [
            relation["child_id"] for relation in first["relations"] if relation["parent_id"] == root["id"]
        ]
        expected = list(reversed(child_ids))
        self.database.reorder_categories(root["id"], expected)
        self.database.sync_categories(items)
        after = self.database.categories()
        by_id = {item["id"]: item for item in after["categories"]}
        actual = [
            relation["child_id"]
            for relation in sorted(
                (item for item in after["relations"] if item["parent_id"] == root["id"]),
                key=lambda item: by_id[item["child_id"]]["sort_order"],
            )
        ]
        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
