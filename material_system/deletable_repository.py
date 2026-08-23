from __future__ import annotations

from typing import Any

from .managed_repository import ManagedInventoryRepository


class DeletableInventoryRepository(ManagedInventoryRepository):
    """Adds stock-safe deletion of user-visible transaction history."""

    def initialize(self) -> None:
        super().initialize()
        with self.connect() as connection:
            columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(stock_transactions)")
            }
            if "deleted" not in columns:
                connection.execute(
                    "ALTER TABLE stock_transactions "
                    "ADD COLUMN deleted INTEGER NOT NULL DEFAULT 0"
                )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_stock_deleted "
                "ON stock_transactions(deleted,id)"
            )

    def list_transactions(
        self,
        limit: int = 200,
        material_id: int | None = None,
        include_archived: bool = False,
    ) -> list[dict[str, Any]]:
        clauses = ["st.deleted=0"]
        parameters: list[Any] = []
        if not include_archived:
            clauses.append("st.archived=0")
        if material_id is not None:
            clauses.append("st.material_id=?")
            parameters.append(int(material_id))
        parameters.append(min(max(int(limit), 1), 1000))
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(
                f"""
                SELECT st.*,m.internal_code,m.name,m.manufacturer_part,l.name location_name
                FROM stock_transactions st
                JOIN materials m ON m.id=st.material_id
                JOIN locations l ON l.id=st.location_id
                WHERE {' AND '.join(clauses)}
                ORDER BY st.id DESC LIMIT ?
                """,
                parameters,
            )]

    def archive_transactions(self, material_id: int | None = None) -> dict[str, Any]:
        with self.transaction() as connection:
            if material_id is None:
                cursor = connection.execute(
                    "UPDATE stock_transactions SET archived=1 "
                    "WHERE archived=0 AND deleted=0"
                )
            else:
                exists = connection.execute(
                    "SELECT 1 FROM materials WHERE id=?", (int(material_id),)
                ).fetchone()
                if not exists:
                    raise KeyError("物料不存在")
                cursor = connection.execute(
                    "UPDATE stock_transactions SET archived=1 "
                    "WHERE material_id=? AND archived=0 AND deleted=0",
                    (int(material_id),),
                )
        return {
            "archived_count": max(int(cursor.rowcount), 0),
            "material_id": material_id,
        }

    def delete_transaction(self, transaction_id: int) -> dict[str, Any]:
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT material_id,deleted FROM stock_transactions WHERE id=?",
                (int(transaction_id),),
            ).fetchone()
            if not row or row["deleted"]:
                raise KeyError("库存流水不存在")
            connection.execute(
                "UPDATE stock_transactions SET deleted=1,archived=1 WHERE id=?",
                (int(transaction_id),),
            )
            material_id = int(row["material_id"])
        return {
            "deleted_count": 1,
            "transaction_id": int(transaction_id),
            "material_id": material_id,
        }

    def delete_transactions(self, material_id: int | None = None) -> dict[str, Any]:
        with self.transaction() as connection:
            if material_id is None:
                cursor = connection.execute(
                    "UPDATE stock_transactions SET deleted=1,archived=1 WHERE deleted=0"
                )
            else:
                exists = connection.execute(
                    "SELECT 1 FROM materials WHERE id=?", (int(material_id),)
                ).fetchone()
                if not exists:
                    raise KeyError("物料不存在")
                cursor = connection.execute(
                    "UPDATE stock_transactions SET deleted=1,archived=1 "
                    "WHERE material_id=? AND deleted=0",
                    (int(material_id),),
                )
        return {
            "deleted_count": max(int(cursor.rowcount), 0),
            "material_id": material_id,
        }

    def change_state(self) -> dict[str, Any]:
        result = super().change_state()
        with self.connect() as connection:
            deleted_count = int(connection.execute(
                "SELECT COALESCE(SUM(deleted),0) FROM stock_transactions"
            ).fetchone()[0])
        result["deleted_count"] = deleted_count
        result["token"] = f"{result['token']}:{deleted_count}"
        return result
