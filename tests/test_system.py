from __future__ import annotations

import gc
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from material_system.repository import InventoryRepository
from material_system.taxonomy import parse_lcsc_categories


class TaxonomyTests(unittest.TestCase):
    def test_parse_next_data_category_tree(self) -> None:
        payload = {
            "props": {
                "pageProps": {
                    "catalogCount": 123,
                    "catalogListData": [
                        {
                            "catalogId": 312,
                            "catalogCode": "0102",
                            "catalogName": "电容",
                            "parentId": 1,
                            "sort": 4,
                            "groupProductCount": 100,
                            "sonCatalogList": [
                                {
                                    "catalogId": 313,
                                    "catalogCode": "010201",
                                    "catalogName": "贴片电容(MLCC)",
                                    "parentId": 312,
                                    "sort": 1,
                                    "groupProductCount": 80,
                                    "sonCatalogList": None,
                                }
                            ],
                        }
                    ],
                }
            }
        }
        html = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'
        result = parse_lcsc_categories(html)
        self.assertEqual([item["external_id"] for item in result], ["1", "312", "313"])
        self.assertEqual(result[2]["parent_external_id"], "312")


class RepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="material-inventory-test-"))
        self.database = InventoryRepository(self.temp_dir / "test.db")

    def tearDown(self) -> None:
        self.database = None
        gc.collect()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_manual_material_uses_defaults(self) -> None:
        item = self.database.add_manual_material({"name": "测试物料"})
        self.assertEqual(item["stock"], 1)
        self.assertEqual(item["locations"][0]["name"], "默认仓位")
        self.assertEqual(item["internal_code"], "MAT-000001")

    def test_lcsc_import_is_idempotent_and_repeated_click_adds_stock(self) -> None:
        payload = {
            "request_id": "request-1",
            "supplier_sku": "C99198",
            "name": "厚膜电阻 10kΩ",
            "manufacturer_part": "RC0603JR-0710KL",
            "brand": "YAGEO(国巨)",
            "package": "0603",
            "specs": {"阻值": "10kΩ"},
            "category": {
                "external_id": "439", "parent_external_id": "1", "name": "贴片电阻"
            },
        }
        first = self.database.import_lcsc(payload)
        duplicate = self.database.import_lcsc(payload)
        payload["request_id"] = "request-2"
        repeated = self.database.import_lcsc(payload)
        self.assertTrue(first["created"])
        self.assertTrue(duplicate["duplicate_request"])
        self.assertEqual(repeated["stock"], 2)
        self.assertEqual(len(self.database.list_materials(q="C99198")), 1)

    def test_outbound_validation_and_undo(self) -> None:
        item = self.database.add_manual_material({"name": "测试物料", "quantity": 2})
        result = self.database.stock_operation(item["id"], {"kind": "outbound", "quantity": 1})
        self.assertEqual(result["material"]["stock"], 1)
        undone = self.database.undo_transaction(result["transaction_id"])
        self.assertEqual(undone["material"]["stock"], 2)
        with self.assertRaisesRegex(ValueError, "库存不足"):
            self.database.stock_operation(item["id"], {"kind": "outbound", "quantity": 3})


if __name__ == "__main__":
    unittest.main()
