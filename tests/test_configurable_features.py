from __future__ import annotations

import gc
import json
import shutil
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from material_system.configurable_inventory_http_server import (
    create_configurable_inventory_server,
)
from material_system.configurable_inventory_repository import (
    ConfigurableInventoryRepository,
)


class ConfigurableFeatureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="material-configurable-test-"))
        self.repository = ConfigurableInventoryRepository(
            self.temp_dir / "live" / "materials.db"
        )
        self.safety_dir = self.temp_dir / "chosen-safety"
        self.normal_dir = self.temp_dir / "chosen-normal"
        self.repository.update_settings({
            "safety_backup_dir": str(self.safety_dir),
            "normal_backup_dir": str(self.normal_dir),
        })

    def tearDown(self) -> None:
        self.repository = None
        gc.collect()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _manual(self, name: str, quantity: int = 1) -> dict:
        return self.repository.add_manual_material({
            "name": name,
            "quantity": quantity,
        })

    def test_high_medium_and_low_safety_backup_levels(self) -> None:
        high_item = self._manual("高安全单删")
        high_result = self.repository.delete_materials([high_item["id"]])
        self.assertTrue(high_result["safety_backup"])
        self.assertTrue((self.safety_dir / high_result["safety_backup"]).is_file())

        self.repository.update_settings({"auto_backup_level": "medium"})
        medium_single = self._manual("中安全单删")
        single_result = self.repository.delete_materials([medium_single["id"]])
        self.assertIsNone(single_result["safety_backup"])

        medium_a = self._manual("中安全批量A")
        medium_b = self._manual("中安全批量B")
        batch_result = self.repository.delete_materials(
            [medium_a["id"], medium_b["id"]]
        )
        self.assertTrue(batch_result["safety_backup"])
        self.assertTrue((self.safety_dir / batch_result["safety_backup"]).is_file())

        transaction_item = self._manual("中安全清空流水", quantity=3)
        clear_result = self.repository.archive_transactions(transaction_item["id"])
        self.assertTrue(clear_result["safety_backup"])

        self.repository.update_settings({"auto_backup_level": "low"})
        low_item = self._manual("低安全单删")
        low_result = self.repository.delete_materials([low_item["id"]])
        self.assertIsNone(low_result["safety_backup"])

    def test_normal_backup_uses_configured_directory(self) -> None:
        self._manual("正常备份物料", quantity=8)
        result = self.repository.save_normal_backup()
        second = self.repository.save_normal_backup()
        target = Path(result["path"])
        self.assertEqual(target.parent, self.normal_dir.resolve())
        self.assertTrue(target.is_file())
        self.assertEqual(result["counts"]["materials"], 1)
        self.assertTrue(Path(second["path"]).is_file())
        self.assertNotEqual(result["path"], second["path"])

    def test_low_level_restore_is_atomic_without_disk_safety_zip(self) -> None:
        self.repository.update_settings({"auto_backup_level": "low"})
        self._manual("恢复前保留物料")
        backup, _, _ = self.repository.export_full_backup()
        self._manual("恢复后应消失物料")
        before = set(self.safety_dir.glob("*.zip"))

        result = self.repository.restore_full_backup(backup)

        self.assertIsNone(result["safety_backup"])
        self.assertEqual(set(self.safety_dir.glob("*.zip")), before)
        self.assertEqual(
            [item["name"] for item in self.repository.list_materials()],
            ["恢复前保留物料"],
        )

    def test_restore_all_lcsc_category_levels_to_synced_order(self) -> None:
        items = [
            {"external_id": "1", "parent_external_id": None, "name": "电子元器件", "sort_order": 0},
            {"external_id": "312", "parent_external_id": "1", "name": "电容", "sort_order": 0},
            {"external_id": "308", "parent_external_id": "1", "name": "电阻", "sort_order": 1},
            {"external_id": "31201", "parent_external_id": "312", "name": "贴片电容", "sort_order": 0},
            {"external_id": "31202", "parent_external_id": "312", "name": "直插电容", "sort_order": 1},
        ]
        self.repository.sync_categories(items)
        categories = self.repository.categories()
        by_external = {
            item["external_id"]: item["id"] for item in categories["categories"]
        }
        self.repository.reorder_categories(
            by_external["1"], [by_external["308"], by_external["312"]]
        )
        self.repository.reorder_categories(
            by_external["312"], [by_external["31202"], by_external["31201"]]
        )

        restored = self.repository.restore_lcsc_category_order(items)

        self.assertEqual(restored["first_category"], "电容")
        by_id = {item["id"]: item for item in restored["categories"]}
        root_children = [
            by_id[relation["child_id"]]["name"]
            for relation in restored["relations"]
            if relation["parent_id"] == by_external["1"]
        ]
        capacitor_children = [
            by_id[relation["child_id"]]["name"]
            for relation in restored["relations"]
            if relation["parent_id"] == by_external["312"]
        ]
        self.assertEqual(root_children, ["电容", "电阻"])
        self.assertEqual(capacitor_children, ["贴片电容", "直插电容"])
        with self.repository.connect() as connection:
            overrides = json.loads(connection.execute(
                "SELECT value FROM settings WHERE key='category_order_overrides'"
            ).fetchone()[0])
        self.assertEqual(overrides, {})

    def test_existing_lcsc_material_receives_later_custom_note(self) -> None:
        first = self.repository.import_lcsc({
            "request_id": "note-later-1",
            "supplier_sku": "C556677",
            "name": "后补备注测试物料",
            "manufacturer_part": "NOTE-LATER",
            "quantity": 1,
        })
        self.assertEqual(first["notes"], "")

        second = self.repository.import_lcsc({
            "request_id": "note-later-2",
            "supplier_sku": "C556677",
            "name": "后补备注测试物料",
            "manufacturer_part": "NOTE-LATER",
            "quantity": 2,
            "material_notes": "后来通过自定义加入补上的元器件备注",
            "transaction_note": "第二次入库备注",
        })
        self.assertFalse(second["created"])
        self.assertEqual(second["notes"], "后来通过自定义加入补上的元器件备注")
        self.assertEqual(second["transactions"][0]["note"], "第二次入库备注")


class ConfigurableHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="material-configurable-http-test-"))
        self.repository = ConfigurableInventoryRepository(
            self.temp_dir / "materials.db"
        )
        self.normal_dir = self.temp_dir / "normal-target"
        self.repository.update_settings({"normal_backup_dir": str(self.normal_dir)})
        self.repository.add_manual_material({"name": "HTTP正常备份", "quantity": 2})
        static_dir = Path(__file__).resolve().parents[1] / "web"
        self.server = create_configurable_inventory_server(
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

    def test_save_normal_backup_endpoint(self) -> None:
        request = urllib.request.Request(
            self.base_url + "/api/backup/save",
            method="POST",
            data=b"{}",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            result = json.load(response)
        self.assertTrue(result["saved"])
        self.assertEqual(Path(result["path"]).parent, self.normal_dir.resolve())


if __name__ == "__main__":
    unittest.main()
