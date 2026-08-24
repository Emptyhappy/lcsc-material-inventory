from __future__ import annotations

import gc
import shutil
import tempfile
import unittest
from pathlib import Path

from material_system.advanced_inventory_repository import AdvancedInventoryRepository


class BackupMergeDuplicateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="material-merge-duplicate-test-"))

    def tearDown(self) -> None:
        gc.collect()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_first_merge_keeps_duplicate_records_inside_backup_but_repeat_is_idempotent(self) -> None:
        source = AdvancedInventoryRepository(self.temp_dir / "source" / "materials.db")
        payload = {
            "name": "有意分别建档的同名物料",
            "manufacturer_part": "SAME-MANUAL-01",
            "brand": "同一品牌",
            "quantity": 2,
            "notes": "相同备注",
        }
        source.add_manual_material(payload)
        source.add_manual_material({**payload, "quantity": 3})
        backup, _, _ = source.export_full_backup()

        target = AdvancedInventoryRepository(self.temp_dir / "target" / "materials.db")
        first = target.merge_full_backup(backup)
        self.assertEqual(first["added_materials"], 2)
        self.assertEqual(first["skipped_duplicates"], 0)
        self.assertEqual(len(target.list_materials()), 2)
        self.assertEqual(target.dashboard()["stock_total"], 5)

        second = target.merge_full_backup(backup)
        self.assertEqual(second["added_materials"], 0)
        self.assertEqual(second["skipped_duplicates"], 2)
        self.assertEqual(len(target.list_materials()), 2)
        self.assertEqual(target.dashboard()["stock_total"], 5)


if __name__ == "__main__":
    unittest.main()
