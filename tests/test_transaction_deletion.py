from __future__ import annotations

import gc
import shutil
import tempfile
import unittest
from pathlib import Path

from material_system.deletable_repository import DeletableInventoryRepository


class TransactionDeletionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="material-deletion-test-"))
        self.repository = DeletableInventoryRepository(self.temp_dir / "test.db")

    def tearDown(self) -> None:
        self.repository = None
        gc.collect()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_delete_one_and_all_keep_stock_but_remove_history(self) -> None:
        material = self.repository.add_manual_material({"name": "测试电容", "quantity": 2})
        inbound = self.repository.stock_operation(
            material["id"], {"kind": "inbound", "quantity": 3, "note": "采购"}
        )
        self.assertEqual(self.repository.material_detail(material["id"])["stock"], 5)

        self.repository.delete_transaction(inbound["transaction_id"])
        visible = self.repository.list_transactions(include_archived=True)
        self.assertNotIn(inbound["transaction_id"], {item["id"] for item in visible})
        self.assertEqual(self.repository.material_detail(material["id"])["stock"], 5)

        deleted = self.repository.delete_transactions(material["id"])
        self.assertEqual(deleted["deleted_count"], 1)
        self.assertEqual(self.repository.list_transactions(include_archived=True), [])
        self.assertEqual(self.repository.material_detail(material["id"])["stock"], 5)
        with self.repository.connect() as connection:
            rows = [dict(row) for row in connection.execute(
                "SELECT quantity_delta,deleted FROM stock_transactions ORDER BY id"
            )]
        self.assertEqual(sum(row["quantity_delta"] for row in rows), 5)
        self.assertTrue(all(row["deleted"] for row in rows))


if __name__ == "__main__":
    unittest.main()
