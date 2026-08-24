from __future__ import annotations

import gc
import shutil
import tempfile
import unittest
from pathlib import Path

from material_system.advanced_inventory_repository import AdvancedInventoryRepository


PNG_DATA = b"\x89PNG\r\n\x1a\nmaterial-image-test"


class AdvancedMaterialTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="material-advanced-test-"))
        self.database = AdvancedInventoryRepository(self.temp_dir / "live" / "materials.db")

    def tearDown(self) -> None:
        self.database = None
        gc.collect()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_manual_material_separates_notes_edits_image_and_deletes_safely(self) -> None:
        item = self.database.add_manual_material({
            "name": "手动测试物料",
            "quantity": 6,
            "notes": "元器件长期备注",
            "transaction_note": "第一次采购入库",
        })
        self.assertEqual(item["notes"], "元器件长期备注")
        self.assertEqual(item["transactions"][0]["note"], "第一次采购入库")
        self.assertTrue(item["editable"])

        updated = self.database.update_material(item["id"], {
            "name": "修改后的物料",
            "brand": "手动品牌",
            "notes": "修改后的元器件备注",
            "category_id": None,
        })
        self.assertEqual(updated["name"], "修改后的物料")
        self.assertEqual(updated["notes"], "修改后的元器件备注")

        with_image = self.database.save_material_image(item["id"], PNG_DATA)
        image_path = self.temp_dir / "live" / "images" / f"M{item['id']}.png"
        self.assertEqual(with_image["image_url"], f"/media/images/M{item['id']}.png")
        self.assertEqual(image_path.read_bytes(), PNG_DATA)

        result = self.database.delete_materials([item["id"]])
        self.assertEqual(result["deleted_count"], 1)
        self.assertTrue((self.database.backup_dir / result["safety_backup"]).is_file())
        self.assertFalse(image_path.exists())
        with self.assertRaises(KeyError):
            self.database.material_detail(item["id"])

    def test_merge_backup_adds_only_missing_materials_with_stock_history_and_image(self) -> None:
        source = AdvancedInventoryRepository(self.temp_dir / "source" / "materials.db")
        source_item = source.add_manual_material({
            "name": "备份独有连接线",
            "manufacturer_part": "WIRE-BACKUP-01",
            "quantity": 9,
            "notes": "整件备注",
            "transaction_note": "备份中的入库备注",
        })
        source.save_material_image(source_item["id"], PNG_DATA)
        backup, _, _ = source.export_full_backup()

        existing = self.database.add_manual_material({
            "name": "当前已有电阻",
            "manufacturer_part": "R-LIVE-01",
            "quantity": 4,
        })
        first = self.database.merge_full_backup(backup)
        self.assertEqual(first["added_materials"], 1)
        self.assertEqual(first["skipped_duplicates"], 0)
        self.assertEqual(first["added_transactions"], 1)
        self.assertEqual(first["added_images"], 1)
        self.assertTrue((self.database.backup_dir / first["safety_backup"]).is_file())

        imported = self.database.list_materials(q="WIRE-BACKUP-01")[0]
        detail = self.database.material_detail(imported["id"])
        self.assertEqual(detail["stock"], 9)
        self.assertEqual(detail["notes"], "整件备注")
        self.assertEqual(detail["transactions"][0]["note"], "备份中的入库备注")
        self.assertEqual(
            (self.temp_dir / "live" / "images" / f"M{imported['id']}.png").read_bytes(),
            PNG_DATA,
        )
        self.assertEqual(self.database.material_detail(existing["id"])["stock"], 4)

        second = self.database.merge_full_backup(backup)
        self.assertEqual(second["added_materials"], 0)
        self.assertEqual(second["skipped_duplicates"], 1)
        self.assertEqual(len(self.database.list_materials()), 2)

    def test_reset_category_order_returns_to_synced_sibling_order(self) -> None:
        items = [
            {"external_id": "1", "parent_external_id": None, "name": "电子元器件", "sort_order": 0},
            {"external_id": "312", "parent_external_id": "1", "name": "电容", "sort_order": 0},
            {"external_id": "308", "parent_external_id": "1", "name": "电阻", "sort_order": 1},
        ]
        self.database.sync_categories(items)
        categories = self.database.categories()
        root = next(item for item in categories["categories"] if item["external_id"] == "1")
        by_external = {
            item["external_id"]: item["id"] for item in categories["categories"]
        }
        self.database.reorder_categories(
            root["id"], [by_external["308"], by_external["312"]]
        )
        reset = self.database.reset_category_order(root["id"])
        by_id = {item["id"]: item for item in reset["categories"]}
        ordered = [
            by_id[relation["child_id"]]["name"]
            for relation in sorted(
                (item for item in reset["relations"] if item["parent_id"] == root["id"]),
                key=lambda item: (item["sort_order"], item["child_id"]),
            )
        ]
        self.assertEqual(ordered, ["电容", "电阻"])


if __name__ == "__main__":
    unittest.main()
