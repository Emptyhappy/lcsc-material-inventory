from __future__ import annotations

import gc
import shutil
import tempfile
import unittest
from pathlib import Path

from material_system.managed_repository import ManagedInventoryRepository


class TransactionManagementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="material-transactions-test-"))
        self.repository = ManagedInventoryRepository(self.temp_dir / "test.db")

    def tearDown(self) -> None:
        self.repository = None
        gc.collect()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_notes_can_be_edited_and_archived_without_changing_stock(self) -> None:
        material = self.repository.add_manual_material({"name": "测试芯片", "quantity": 2})
        inbound = self.repository.stock_operation(
            material["id"],
            {"kind": "inbound", "quantity": 3, "note": "项目A备料"},
        )
        transaction_id = inbound["transaction_id"]
        self.assertEqual(self.repository.material_detail(material["id"])["stock"], 5)
        self.assertEqual(self.repository.recent_transactions()[0]["note"], "项目A备料")

        updated = self.repository.update_transaction(transaction_id, {"note": "项目B备料"})
        self.assertEqual(updated["note"], "项目B备料")
        self.repository.update_transaction(transaction_id, {"archived": True})

        visible_ids = {item["id"] for item in self.repository.recent_transactions()}
        all_items = self.repository.list_transactions(include_archived=True)
        self.assertNotIn(transaction_id, visible_ids)
        self.assertTrue(next(item for item in all_items if item["id"] == transaction_id)["archived"])
        self.assertEqual(self.repository.material_detail(material["id"])["stock"], 5)

    def test_clear_archives_history_and_new_transactions_remain_visible(self) -> None:
        material = self.repository.add_manual_material({"name": "测试电阻", "quantity": 4})
        result = self.repository.archive_transactions(material["id"])
        self.assertEqual(result["archived_count"], 1)
        detail = self.repository.material_detail(material["id"])
        self.assertEqual(detail["stock"], 4)
        self.assertEqual(detail["transactions"], [])

        self.repository.stock_operation(
            material["id"], {"kind": "outbound", "quantity": 1, "note": "领用"}
        )
        detail = self.repository.material_detail(material["id"])
        self.assertEqual(detail["stock"], 3)
        self.assertEqual(len(detail["transactions"]), 1)
        self.assertEqual(detail["transactions"][0]["note"], "领用")


if __name__ == "__main__":
    unittest.main()
