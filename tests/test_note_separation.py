from __future__ import annotations

import gc
import shutil
import tempfile
import unittest
from pathlib import Path

from material_system.advanced_inventory_repository import AdvancedInventoryRepository


class NoteSeparationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="material-note-separation-test-"))
        self.database = AdvancedInventoryRepository(self.temp_dir / "materials.db")

    def tearDown(self) -> None:
        self.database = None
        gc.collect()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_lcsc_custom_import_separates_transaction_and_material_notes(self) -> None:
        result = self.database.import_lcsc({
            "request_id": "separate-notes-1",
            "supplier_sku": "C778899",
            "name": "立创备注测试物料",
            "manufacturer_part": "NOTE-SPLIT-01",
            "quantity": 11,
            "transaction_note": "这批从采购单A入库",
            "material_notes": "这个元器件长期用于控制板",
        })
        self.assertEqual(result["notes"], "这个元器件长期用于控制板")
        self.assertEqual(result["transactions"][0]["note"], "这批从采购单A入库")
        self.assertFalse(result["editable"])


if __name__ == "__main__":
    unittest.main()
