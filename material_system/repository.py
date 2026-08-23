from __future__ import annotations

import csv
import io
import json
from typing import Any

from .database import InventoryDatabase, as_number, now


class InventoryRepository(InventoryDatabase):
    """Application operations built on the SQLite schema."""

    def add_manual_material(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not str(payload.get("name") or payload.get("manufacturer_part") or "").strip():
            raise ValueError("物料名称或型号至少填写一项")
        with self.transaction() as connection:
            material_id = self._create_material(connection, payload)
            if payload.get("category_id"):
                self._assign_category(connection, material_id, int(payload["category_id"]))
            quantity = as_number(payload.get("quantity"), self._default_quantity(connection))
            location_id = int(payload.get("location_id") or self._default_location_id(connection))
            transaction_id = None
            if quantity:
                cursor = connection.execute(
                    """
                    INSERT INTO stock_transactions(
                        material_id,location_id,kind,quantity_delta,note,source,created_at
                    ) VALUES(?,?,'initial',?,'手动添加物料','manual',?)
                    """,
                    (material_id, location_id, quantity, now()),
                )
                transaction_id = int(cursor.lastrowid)
        result = self.material_detail(material_id)
        result.update({"transaction_id": transaction_id, "created": True})
        return result

    def _upsert_import_category(
        self, connection: Any, payload: dict[str, Any]
    ) -> int | None:
        category = payload.get("category") or {}
        external_id = str(category.get("external_id") or "").strip()
        if not external_id:
            return None
        category_id = self._upsert_category(
            connection,
            source="lcsc",
            external_id=external_id,
            name=str(category.get("name") or "未命名分类"),
            code=str(category.get("code") or ""),
            url=str(category.get("url") or ""),
            sort_order=int(category.get("sort_order") or 0),
        )
        parent_external = str(category.get("parent_external_id") or "").strip()
        if parent_external:
            parent = connection.execute(
                "SELECT id FROM categories WHERE source='lcsc' AND external_id=?",
                (parent_external,),
            ).fetchone()
            if parent:
                connection.execute(
                    "INSERT OR IGNORE INTO category_relations(parent_id,child_id) VALUES(?,?)",
                    (int(parent["id"]), category_id),
                )
        return category_id

    def import_lcsc(self, payload: dict[str, Any]) -> dict[str, Any]:
        sku = str(payload.get("supplier_sku") or "").strip().upper()
        if not sku.startswith("C") or not sku[1:].isdigit():
            raise ValueError("没有识别到有效的立创C编号")
        request_id = str(payload.get("request_id") or "").strip() or None
        duplicate_request = False
        created = False
        added_quantity = 0.0

        with self.transaction() as connection:
            previous = None
            if request_id:
                previous = connection.execute(
                    "SELECT material_id,id FROM stock_transactions WHERE request_id=?", (request_id,)
                ).fetchone()
            if previous:
                material_id = int(previous["material_id"])
                transaction_id = int(previous["id"])
                duplicate_request = True
            else:
                existing = connection.execute(
                    "SELECT material_id FROM supplier_parts WHERE supplier='lcsc' AND supplier_sku=?",
                    (sku,),
                ).fetchone()
                if existing:
                    material_id = int(existing["material_id"])
                else:
                    part = str(payload.get("manufacturer_part") or "").strip()
                    brand = str(payload.get("brand") or "").strip()
                    matched = None
                    if part:
                        matched = connection.execute(
                            """
                            SELECT id FROM materials
                            WHERE lower(manufacturer_part)=lower(?) AND lower(brand)=lower(?) LIMIT 1
                            """,
                            (part, brand),
                        ).fetchone()
                    if matched:
                        material_id = int(matched["id"])
                    else:
                        material_id = self._create_material(connection, payload)
                        created = True
                    stamp = now()
                    connection.execute(
                        """
                        INSERT INTO supplier_parts(
                            material_id,supplier,supplier_sku,product_url,last_price,currency,
                            raw_json,created_at,updated_at
                        ) VALUES(?,'lcsc',?,?,?,?,?,?,?)
                        """,
                        (
                            material_id, sku, str(payload.get("product_url") or ""),
                            payload.get("price"), str(payload.get("currency") or "CNY"),
                            json.dumps(payload, ensure_ascii=False), stamp, stamp,
                        ),
                    )

                stamp = now()
                values = {
                    "name": str(payload.get("name") or ""),
                    "manufacturer_part": str(payload.get("manufacturer_part") or ""),
                    "brand": str(payload.get("brand") or ""),
                    "package": str(payload.get("package") or ""),
                    "description": str(payload.get("description") or ""),
                    "specs_json": json.dumps(payload.get("specs") or {}, ensure_ascii=False),
                    "image_url": str(payload.get("image_url") or ""),
                    "datasheet_url": str(payload.get("datasheet_url") or ""),
                }
                for field, value in values.items():
                    if value and value != "{}":
                        connection.execute(
                            f"UPDATE materials SET {field}=?,updated_at=? WHERE id=?",
                            (value, stamp, material_id),
                        )
                connection.execute(
                    """
                    UPDATE supplier_parts SET product_url=?,last_price=?,currency=?,raw_json=?,updated_at=?
                    WHERE supplier='lcsc' AND supplier_sku=?
                    """,
                    (
                        str(payload.get("product_url") or ""), payload.get("price"),
                        str(payload.get("currency") or "CNY"),
                        json.dumps(payload, ensure_ascii=False), stamp, sku,
                    ),
                )
                category_id = self._upsert_import_category(connection, payload)
                if category_id:
                    self._assign_category(connection, material_id, category_id)
                quantity = as_number(payload.get("quantity"), self._default_quantity(connection))
                location_id = int(payload.get("location_id") or self._default_location_id(connection))
                cursor = connection.execute(
                    """
                    INSERT INTO stock_transactions(
                        material_id,location_id,kind,quantity_delta,unit_cost,note,
                        source,request_id,created_at
                    ) VALUES(?,?,'inbound',?,?,?,'lcsc-extension',?,?)
                    """,
                    (
                        material_id, location_id, quantity, payload.get("price"),
                        f"从立创商城一键添加 {sku}", request_id, now(),
                    ),
                )
                transaction_id = int(cursor.lastrowid)
                added_quantity = quantity

        result = self.material_detail(material_id)
        result.update(
            {
                "created": created,
                "transaction_id": transaction_id,
                "duplicate_request": duplicate_request,
                "added_quantity": added_quantity,
            }
        )
        return result

    @staticmethod
    def _descendant_ids(connection: Any, category_id: int) -> list[int]:
        return [int(row[0]) for row in connection.execute(
            """
            WITH RECURSIVE descendants(id) AS (
                SELECT ? UNION SELECT r.child_id FROM category_relations r
                JOIN descendants d ON r.parent_id=d.id
            ) SELECT id FROM descendants
            """,
            (category_id,),
        )]

    def list_materials(
        self, q: str = "", category_id: int | None = None, low_stock: bool = False
    ) -> list[dict[str, Any]]:
        clauses = ["1=1"]
        parameters: list[Any] = []
        with self.connect() as connection:
            if q.strip():
                pattern = f"%{q.strip()}%"
                clauses.append(
                    "(m.name LIKE ? OR m.manufacturer_part LIKE ? OR m.internal_code LIKE ? "
                    "OR EXISTS(SELECT 1 FROM supplier_parts sp2 "
                    "WHERE sp2.material_id=m.id AND sp2.supplier_sku LIKE ?))"
                )
                parameters.extend([pattern, pattern, pattern, pattern])
            if category_id:
                ids = self._descendant_ids(connection, int(category_id))
                placeholders = ",".join("?" for _ in ids)
                clauses.append(
                    f"EXISTS(SELECT 1 FROM material_categories mc2 WHERE mc2.material_id=m.id "
                    f"AND mc2.category_id IN ({placeholders}))"
                )
                parameters.extend(ids)
            if low_stock:
                clauses.append("COALESCE(s.stock,0)<=m.min_stock")
            sql = f"""
                SELECT m.*,COALESCE(s.stock,0) stock,
                       sp.supplier_sku,sp.product_url,sp.last_price,
                       c.id category_id,c.name category_name,l.name primary_location
                FROM materials m
                LEFT JOIN (SELECT material_id,SUM(quantity_delta) stock
                           FROM stock_transactions GROUP BY material_id) s ON s.material_id=m.id
                LEFT JOIN supplier_parts sp ON sp.id=(
                    SELECT MIN(id) FROM supplier_parts WHERE material_id=m.id
                )
                LEFT JOIN material_categories mc ON mc.material_id=m.id AND mc.is_primary=1
                LEFT JOIN categories c ON c.id=mc.category_id
                LEFT JOIN locations l ON l.id=(
                    SELECT st.location_id FROM stock_transactions st WHERE st.material_id=m.id
                    GROUP BY st.location_id ORDER BY SUM(st.quantity_delta) DESC LIMIT 1
                )
                WHERE {' AND '.join(clauses)}
                ORDER BY m.updated_at DESC,m.id DESC LIMIT 500
            """
            rows = [dict(row) for row in connection.execute(sql, parameters)]
        for row in rows:
            row["specs"] = json.loads(row.pop("specs_json") or "{}")
        return rows

    def material_detail(self, material_id: int) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT m.*,COALESCE(s.stock,0) stock FROM materials m
                LEFT JOIN (SELECT material_id,SUM(quantity_delta) stock
                           FROM stock_transactions GROUP BY material_id) s ON s.material_id=m.id
                WHERE m.id=?
                """,
                (material_id,),
            ).fetchone()
            if not row:
                raise KeyError("物料不存在")
            result = dict(row)
            result["suppliers"] = [dict(r) for r in connection.execute(
                "SELECT * FROM supplier_parts WHERE material_id=? ORDER BY supplier", (material_id,)
            )]
            result["categories"] = [dict(r) for r in connection.execute(
                """
                SELECT c.*,mc.is_primary FROM categories c
                JOIN material_categories mc ON mc.category_id=c.id
                WHERE mc.material_id=? ORDER BY mc.is_primary DESC,c.name
                """,
                (material_id,),
            )]
            result["locations"] = [dict(r) for r in connection.execute(
                """
                SELECT l.id,l.name,SUM(st.quantity_delta) quantity FROM stock_transactions st
                JOIN locations l ON l.id=st.location_id WHERE st.material_id=?
                GROUP BY l.id,l.name HAVING quantity<>0 ORDER BY l.name
                """,
                (material_id,),
            )]
            result["transactions"] = [dict(r) for r in connection.execute(
                """
                SELECT st.*,l.name location_name FROM stock_transactions st
                JOIN locations l ON l.id=st.location_id WHERE st.material_id=?
                ORDER BY st.id DESC LIMIT 100
                """,
                (material_id,),
            )]
        result["specs"] = json.loads(result.pop("specs_json") or "{}")
        return result

    def update_material(self, material_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "name", "manufacturer_part", "brand", "package", "description", "image_url",
            "datasheet_url", "unit", "min_stock", "notes",
        }
        assignments: list[str] = []
        parameters: list[Any] = []
        for key in allowed.intersection(payload):
            assignments.append(f"{key}=?")
            parameters.append(payload[key])
        if "specs" in payload:
            assignments.append("specs_json=?")
            parameters.append(json.dumps(payload["specs"] or {}, ensure_ascii=False))
        with self.transaction() as connection:
            if assignments:
                assignments.append("updated_at=?")
                parameters.extend([now(), material_id])
                connection.execute(
                    f"UPDATE materials SET {','.join(assignments)} WHERE id=?", parameters
                )
            if payload.get("category_id"):
                self._assign_category(connection, material_id, int(payload["category_id"]))
        return self.material_detail(material_id)

    def stock_operation(self, material_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        kind = str(payload.get("kind") or "inbound")
        raw_quantity = as_number(payload.get("quantity"), 0)
        if kind not in {"inbound", "outbound", "adjust"}:
            raise ValueError("不支持的库存操作")
        if kind == "adjust":
            delta = raw_quantity
            if not delta:
                raise ValueError("调整数量不能为0")
        else:
            quantity = abs(raw_quantity)
            if quantity <= 0:
                raise ValueError("数量必须大于0")
            delta = -quantity if kind == "outbound" else quantity
        with self.transaction() as connection:
            exists = connection.execute("SELECT 1 FROM materials WHERE id=?", (material_id,)).fetchone()
            if not exists:
                raise KeyError("物料不存在")
            current = as_number(connection.execute(
                "SELECT COALESCE(SUM(quantity_delta),0) total FROM stock_transactions WHERE material_id=?",
                (material_id,),
            ).fetchone()["total"])
            if current + delta < 0:
                raise ValueError(f"库存不足，当前库存为 {current:g}")
            location_id = int(payload.get("location_id") or self._default_location_id(connection))
            cursor = connection.execute(
                """
                INSERT INTO stock_transactions(
                    material_id,location_id,kind,quantity_delta,unit_cost,note,source,created_at
                ) VALUES(?,?,?,?,?,?,'manual',?)
                """,
                (
                    material_id, location_id, kind, delta, payload.get("unit_cost"),
                    str(payload.get("note") or ""), now(),
                ),
            )
            transaction_id = int(cursor.lastrowid)
        return {"transaction_id": transaction_id, "material": self.material_detail(material_id)}

    def undo_transaction(self, transaction_id: int) -> dict[str, Any]:
        with self.transaction() as connection:
            original = connection.execute(
                "SELECT * FROM stock_transactions WHERE id=?", (transaction_id,)
            ).fetchone()
            if not original:
                raise KeyError("库存流水不存在")
            if connection.execute(
                "SELECT id FROM stock_transactions WHERE reversal_of=?", (transaction_id,)
            ).fetchone():
                raise ValueError("这条流水已经撤销")
            cursor = connection.execute(
                """
                INSERT INTO stock_transactions(
                    material_id,location_id,kind,quantity_delta,note,source,reversal_of,created_at
                ) VALUES(?,?,'reversal',?,?,'undo',?,?)
                """,
                (
                    original["material_id"], original["location_id"],
                    -as_number(original["quantity_delta"]), f"撤销流水 #{transaction_id}",
                    transaction_id, now(),
                ),
            )
            undo_id = int(cursor.lastrowid)
            material_id = int(original["material_id"])
        return {"transaction_id": undo_id, "material": self.material_detail(material_id)}

    def recent_transactions(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(
                """
                SELECT st.*,m.internal_code,m.name,m.manufacturer_part,l.name location_name
                FROM stock_transactions st JOIN materials m ON m.id=st.material_id
                JOIN locations l ON l.id=st.location_id ORDER BY st.id DESC LIMIT ?
                """,
                (min(max(limit, 1), 200),),
            )]

    def dashboard(self) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) material_count,COALESCE(SUM(stock),0) stock_total,
                       COALESCE(SUM(CASE WHEN stock<=min_stock THEN 1 ELSE 0 END),0) low_stock_count,
                       COALESCE(SUM(CASE WHEN stock=0 THEN 1 ELSE 0 END),0) zero_stock_count
                FROM (
                    SELECT m.id,m.min_stock,COALESCE(SUM(st.quantity_delta),0) stock
                    FROM materials m LEFT JOIN stock_transactions st ON st.material_id=m.id
                    GROUP BY m.id
                )
                """
            ).fetchone()
        result = dict(row)
        result["recent_transactions"] = self.recent_transactions(8)
        return result

    def export_csv(self) -> bytes:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "内部编号", "名称", "制造商型号", "品牌", "封装", "立创编号",
            "分类", "库存", "单位", "仓位", "最低库存", "备注",
        ])
        for item in self.list_materials():
            writer.writerow([
                item["internal_code"], item["name"], item["manufacturer_part"], item["brand"],
                item["package"], item.get("supplier_sku") or "", item.get("category_name") or "",
                item["stock"], item["unit"], item.get("primary_location") or "",
                item["min_stock"], item["notes"],
            ])
        return ("\ufeff" + output.getvalue()).encode("utf-8")
