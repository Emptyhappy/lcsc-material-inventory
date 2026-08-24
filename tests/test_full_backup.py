from __future__ import annotations

import gc
import io
import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from material_system.backup_repository import (
    BACKUP_FORMAT,
    BackupInventoryRepository,
)


class FullBackupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="material-backup-test-"))
        self.database = BackupInventoryRepository(self.temp_dir / "materials.db")

    def tearDown(self) -> None:
        self.database = None
        gc.collect()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_full_backup_restores_all_database_data_order_and_images(self) -> None:
        original = self.database.add_manual_material({
            "name": "备份测试电阻",
            "manufacturer_part": "R-BACKUP-10K",
            "quantity": 23,
            "notes": "必须完整保留",
        })
        categories = self.database.categories()
        root = next(
            item for item in categories["categories"]
            if item["source"] == "lcsc" and item["external_id"] == "1"
        )
        original_order = [
            relation["child_id"]
            for relation in categories["relations"]
            if relation["parent_id"] == root["id"]
        ]
        expected_order = list(reversed(original_order))
        self.database.reorder_categories(root["id"], expected_order)
        image_path = self.database.image_dir / "C12345.jpg"
        image_path.write_bytes(b"complete-image-data")
        original_token = self.database.get_settings()["extension_token"]

        backup_data, filename, manifest = self.database.export_full_backup()
        self.assertTrue(filename.endswith(".zip"))
        self.assertEqual(manifest["format"], BACKUP_FORMAT)
        self.assertEqual(manifest["counts"]["materials"], 1)
        self.assertEqual(len(manifest["images"]), 1)

        self.database.add_manual_material({"name": "备份后新增物料", "quantity": 5})
        image_path.write_bytes(b"changed")
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE settings SET value='changed-token' WHERE key='extension_token'"
            )

        result = self.database.restore_full_backup(backup_data)
        self.assertTrue(result["restored"])
        self.assertEqual(result["counts"]["materials"], 1)
        self.assertEqual(result["image_count"], 1)
        self.assertTrue((self.database.backup_dir / result["safety_backup"]).is_file())
        self.assertEqual(image_path.read_bytes(), b"complete-image-data")
        self.assertEqual(self.database.get_settings()["extension_token"], original_token)

        with self.database.connect() as connection:
            names = [row[0] for row in connection.execute("SELECT name FROM materials")]
        self.assertEqual(names, ["备份测试电阻"])
        self.assertEqual(self.database.material_detail(original["id"])["stock"], 23)

        restored_categories = self.database.categories()
        by_id = {item["id"]: item for item in restored_categories["categories"]}
        restored_order = [
            relation["child_id"]
            for relation in sorted(
                (
                    item for item in restored_categories["relations"]
                    if item["parent_id"] == root["id"]
                ),
                key=lambda item: by_id[item["child_id"]]["sort_order"],
            )
        ]
        self.assertEqual(restored_order, expected_order)

    def test_restore_rejects_path_traversal_before_changing_data(self) -> None:
        self.database.add_manual_material({"name": "不能丢失", "quantity": 1})
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("../outside.txt", "bad")
            archive.writestr("manifest.json", json.dumps({"format": BACKUP_FORMAT}))
            archive.writestr("materials.db", b"bad")
        with self.assertRaisesRegex(ValueError, "不安全"):
            self.database.restore_full_backup(output.getvalue())
        self.assertEqual(len(self.database.list_materials(q="不能丢失")), 1)


if __name__ == "__main__":
    unittest.main()
