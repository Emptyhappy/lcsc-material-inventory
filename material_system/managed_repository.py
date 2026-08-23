from __future__ import annotations

from typing import Any

from .application_repository import ApplicationRepository


class ManagedInventoryRepository(ApplicationRepository):
    """Adds reversible transaction-history management to the application repository."""

    def initialize(self) -> None:
        super().initialize()
        with self.connect() as connection:
            columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(stock_transactions)")
            }
            if "archived" not in columns:
                connection.execute(
                    "ALTER TABLE stock_transactions "
                    "ADD COLUMN archived INTEGER NOT NULL DEFAULT 0"
                )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_stock_archived "
                "ON stock_transactions(archived,id)"
            )

    def list_transactions(
        self,
        limit: int = 200,
        material_id: int | None = None,
        include_archived: bool = False,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        parameters: list[Any] = []
        if not include_archived:
            clauses.append("st.archived=0")
        if material_id is not None:
            clauses.append("st.material_id=?")
            parameters.append(int(material_id))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        parameters.append(min(max(int(limit), 1), 1000))
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(
                f"""
                SELECT st.*,m.internal_code,m.name,m.manufacturer_part,l.name location_name
                FROM stock_transactions st
                JOIN materials m ON m.id=st.material_id
                JOIN locations l ON l.id=st.location_id
                {where}
                ORDER BY st.id DESC LIMIT ?
                """,
                parameters,
            )]

    def recent_transactions(
        self, limit: int = 50, include_archived: bool = False
    ) -> list[dict[str, Any]]:
        return self.list_transactions(limit=limit, include_archived=include_archived)

    def material_detail(self, material_id: int) -> dict[str, Any]:
        result = super().material_detail(material_id)
        result["transactions"] = self.list_transactions(
            limit=100, material_id=material_id, include_archived=False
        )
        return result

    def update_transaction(self, transaction_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        assignments: list[str] = []
        parameters: list[Any] = []
        if "note" in payload:
            note = str(payload.get("note") or "").strip()
            if len(note) > 1000:
                raise ValueError("流水备注不能超过1000个字符")
            assignments.append("note=?")
            parameters.append(note)
        if "archived" in payload:
            assignments.append("archived=?")
            parameters.append(1 if bool(payload["archived"]) else 0)
        if not assignments:
            raise ValueError("没有需要更新的流水内容")

        with self.transaction() as connection:
            exists = connection.execute(
                "SELECT id FROM stock_transactions WHERE id=?", (int(transaction_id),)
            ).fetchone()
            if not exists:
                raise KeyError("库存流水不存在")
            parameters.append(int(transaction_id))
            connection.execute(
                f"UPDATE stock_transactions SET {','.join(assignments)} WHERE id=?",
                parameters,
            )
        return self.transaction_detail(transaction_id)

    def transaction_detail(self, transaction_id: int) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT st.*,m.internal_code,m.name,m.manufacturer_part,l.name location_name
                FROM stock_transactions st
                JOIN materials m ON m.id=st.material_id
                JOIN locations l ON l.id=st.location_id
                WHERE st.id=?
                """,
                (int(transaction_id),),
            ).fetchone()
        if not row:
            raise KeyError("库存流水不存在")
        return dict(row)

    def archive_transactions(self, material_id: int | None = None) -> dict[str, Any]:
        with self.transaction() as connection:
            if material_id is None:
                cursor = connection.execute(
                    "UPDATE stock_transactions SET archived=1 WHERE archived=0"
                )
            else:
                exists = connection.execute(
                    "SELECT 1 FROM materials WHERE id=?", (int(material_id),)
                ).fetchone()
                if not exists:
                    raise KeyError("物料不存在")
                cursor = connection.execute(
                    "UPDATE stock_transactions SET archived=1 "
                    "WHERE material_id=? AND archived=0",
                    (int(material_id),),
                )
        return {
            "archived_count": max(int(cursor.rowcount), 0),
            "material_id": material_id,
        }

    def change_state(self) -> dict[str, Any]:
        with self.connect() as connection:
            transactions = connection.execute(
                """
                SELECT COALESCE(MAX(id),0) latest_transaction_id,
                       COUNT(*) transaction_count,
                       COALESCE(SUM(archived),0) archived_count
                FROM stock_transactions
                """
            ).fetchone()
            materials = connection.execute(
                "SELECT COUNT(*) material_count,COALESCE(MAX(updated_at),'') latest_material_update "
                "FROM materials"
            ).fetchone()
        result = {**dict(transactions), **dict(materials)}
        result["token"] = ":".join(str(result[key]) for key in (
            "latest_transaction_id",
            "transaction_count",
            "archived_count",
            "material_count",
            "latest_material_update",
        ))
        return result
