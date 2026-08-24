from __future__ import annotations

import json
import re
import shutil
import sqlite3
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from .backup_repository import BackupInventoryRepository
from .database import as_number, now


MATERIAL_IMAGE_TYPES = {
    "jpeg": ".jpg",
    "png": ".png",
    "gif": ".gif",
    "webp": ".webp",
}
MAX_MATERIAL_IMAGE_BYTES = 8 * 1024 * 1024


def _image_kind(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


class AdvancedInventoryRepository(BackupInventoryRepository):
    """Final inventory features: merge, material management and manual images."""

    def list_materials(
        self, q: str = "", category_id: int | None = None, low_stock: bool = False
    ) -> list[dict[str, Any]]:
        rows = super().list_materials(q=q, category_id=category_id, low_stock=low_stock)
        for row in rows:
            row["editable"] = not bool(row.get("supplier_sku"))
        return rows

    def material_detail(self, material_id: int) -> dict[str, Any]:
        result = super().material_detail(material_id)
        result["editable"] = not any(
            str(item.get("supplier") or "").lower() == "lcsc"
            for item in result["suppliers"]
        )
        return result

    @staticmethod
    def _validate_material_notes(payload: dict[str, Any]) -> None:
        if len(str(payload.get("notes") or "")) > 4000:
            raise ValueError("元器件备注不能超过4000个字符")
        if len(str(payload.get("transaction_note") or "")) > 1000:
            raise ValueError("入库备注不能超过1000个字符")

    def add_manual_material(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not str(payload.get("name") or payload.get("manufacturer_part") or "").strip():
            raise ValueError("物料名称或型号至少填写一项")
        self._validate_material_notes(payload)
        with self.transaction() as connection:
            material_id = self._create_material(connection, payload)
            if payload.get("category_id"):
                self._assign_category(connection, material_id, int(payload["category_id"]))
            quantity = as_number(payload.get("quantity"), self._default_quantity(connection))
            if quantity < 0:
                raise ValueError("初始数量不能小于0")
            location_id = int(
                payload.get("location_id") or self._default_location_id(connection)
            )
            transaction_id = None
            if quantity:
                transaction_note = str(payload.get("transaction_note") or "").strip()
                cursor = connection.execute(
                    """
                    INSERT INTO stock_transactions(
                        material_id,location_id,kind,quantity_delta,note,source,created_at
                    ) VALUES(?,?,'initial',?,?,'manual',?)
                    """,
                    (
                        material_id,
                        location_id,
                        quantity,
                        transaction_note or "手动添加物料",
                        now(),
                    ),
                )
                transaction_id = int(cursor.lastrowid)
        result = self.material_detail(material_id)
        result.update({"transaction_id": transaction_id, "created": True})
        return result

    def import_lcsc(self, payload: dict[str, Any]) -> dict[str, Any]:
        adapted = dict(payload)
        if "material_notes" in adapted:
            adapted["notes"] = str(adapted.get("material_notes") or "")
        transaction_note = str(
            adapted.get("transaction_note") or adapted.get("inbound_note") or ""
        ).strip()
        result = super().import_lcsc(adapted)
        if transaction_note and result.get("transaction_id") and not result.get("duplicate_request"):
            with self.transaction() as connection:
                connection.execute(
                    "UPDATE stock_transactions SET note=? WHERE id=?",
                    (transaction_note, int(result["transaction_id"])),
                )
            result = self.material_detail(int(result["id"])) | {
                key: result[key]
                for key in (
                    "created",
                    "transaction_id",
                    "duplicate_request",
                    "added_quantity",
                    "image_cached",
                    "image_error",
                )
            }
        return result

    def update_material(self, material_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "name",
            "manufacturer_part",
            "brand",
            "package",
            "description",
            "datasheet_url",
            "unit",
            "min_stock",
            "notes",
        }
        if "name" in payload and not str(payload.get("name") or "").strip():
            raise ValueError("物料名称不能为空")
        self._validate_material_notes(payload)
        if "min_stock" in payload and as_number(payload.get("min_stock"), 0) < 0:
            raise ValueError("最低库存不能小于0")
        assignments: list[str] = []
        parameters: list[Any] = []
        for key in allowed.intersection(payload):
            assignments.append(f"{key}=?")
            value = payload[key]
            if key in {"name", "manufacturer_part", "brand", "package", "unit"}:
                value = str(value or "").strip()
            parameters.append(value)
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT id FROM materials WHERE id=?", (int(material_id),)
            ).fetchone()
            if not row:
                raise KeyError("物料不存在")
            if assignments:
                assignments.append("updated_at=?")
                parameters.extend([now(), int(material_id)])
                connection.execute(
                    f"UPDATE materials SET {','.join(assignments)} WHERE id=?",
                    parameters,
                )
            if "category_id" in payload:
                connection.execute(
                    "DELETE FROM material_categories WHERE material_id=?",
                    (int(material_id),),
                )
                if payload.get("category_id"):
                    self._assign_category(
                        connection, int(material_id), int(payload["category_id"])
                    )
        return self.material_detail(int(material_id))

    def save_material_image(self, material_id: int, data: bytes) -> dict[str, Any]:
        if not data:
            raise ValueError("请选择图片文件")
        if len(data) > MAX_MATERIAL_IMAGE_BYTES:
            raise ValueError("物料图片不能超过8MB")
        kind = _image_kind(data)
        if not kind:
            raise ValueError("仅支持 JPG、PNG、WEBP 或 GIF 图片")
        with self.connect() as connection:
            row = connection.execute(
                "SELECT image_url FROM materials WHERE id=?", (int(material_id),)
            ).fetchone()
            if not row:
                raise KeyError("物料不存在")
            is_lcsc = connection.execute(
                "SELECT 1 FROM supplier_parts WHERE material_id=? AND supplier='lcsc'",
                (int(material_id),),
            ).fetchone()
        if is_lcsc:
            raise ValueError("立创物料图片由商城自动更新")

        extension = MATERIAL_IMAGE_TYPES[kind]
        target = self.image_dir / f"M{int(material_id)}{extension}"
        previous_target_data = target.read_bytes() if target.exists() else None
        temporary = target.with_suffix(target.suffix + ".part")
        temporary.write_bytes(data)
        temporary.replace(target)
        old_url = str(row["image_url"] or "")
        new_url = f"/media/images/{target.name}"
        try:
            with self.transaction() as connection:
                connection.execute(
                    "UPDATE materials SET image_url=?,updated_at=? WHERE id=?",
                    (new_url, now(), int(material_id)),
                )
        except Exception:
            if previous_target_data is None:
                target.unlink(missing_ok=True)
            else:
                target.write_bytes(previous_target_data)
            raise
        self._remove_unused_local_image(old_url, except_path=target)
        return self.material_detail(int(material_id))

    def _remove_unused_local_image(
        self, image_url: str, except_path: Path | None = None
    ) -> None:
        prefix = "/media/images/"
        if not image_url.startswith(prefix):
            return
        filename = PurePosixPath(image_url.removeprefix(prefix)).name
        if not filename:
            return
        target = self.image_dir / filename
        if except_path is not None and target.resolve() == except_path.resolve():
            return
        with self.connect() as connection:
            used = connection.execute(
                "SELECT 1 FROM materials WHERE image_url=? LIMIT 1", (image_url,)
            ).fetchone()
        if not used:
            target.unlink(missing_ok=True)

    def _write_safety_backup(self, purpose: str) -> str:
        data, filename, _ = self._export_full_backup_unlocked()
        safety_name = filename.replace("full-backup", f"{purpose}-safety")
        safety_path = self.backup_dir / safety_name
        counter = 1
        while safety_path.exists():
            safety_path = self.backup_dir / safety_name.replace(".zip", f"-{counter}.zip")
            counter += 1
        safety_path.write_bytes(data)
        return safety_path.name

    def delete_materials(self, material_ids: list[int]) -> dict[str, Any]:
        ids = list(dict.fromkeys(int(item) for item in material_ids))
        if not ids:
            raise ValueError("没有选择要删除的物料")
        if len(ids) > 500:
            raise ValueError("一次最多删除500种物料")
        placeholders = ",".join("?" for _ in ids)
        with self._backup_lock:
            with self.connect() as connection:
                rows = [dict(row) for row in connection.execute(
                    f"SELECT id,name,image_url FROM materials WHERE id IN ({placeholders})",
                    ids,
                )]
            if len(rows) != len(ids):
                raise KeyError("部分物料不存在，请刷新后重试")
            safety_backup = self._write_safety_backup("material-delete")
            image_urls = [str(row["image_url"] or "") for row in rows]
            with self.transaction() as connection:
                transaction_ids = [
                    int(row[0])
                    for row in connection.execute(
                        f"SELECT id FROM stock_transactions WHERE material_id IN ({placeholders})",
                        ids,
                    )
                ]
                if transaction_ids:
                    tx_placeholders = ",".join("?" for _ in transaction_ids)
                    connection.execute(
                        f"UPDATE stock_transactions SET reversal_of=NULL "
                        f"WHERE reversal_of IN ({tx_placeholders})",
                        transaction_ids,
                    )
                connection.execute(
                    f"DELETE FROM stock_transactions WHERE material_id IN ({placeholders})",
                    ids,
                )
                connection.execute(
                    f"DELETE FROM materials WHERE id IN ({placeholders})", ids
                )
            for image_url in image_urls:
                self._remove_unused_local_image(image_url)
        return {
            "deleted_count": len(ids),
            "material_ids": ids,
            "safety_backup": safety_backup,
        }

    def reset_category_order(self, parent_id: int) -> dict[str, Any]:
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT value FROM settings WHERE key='category_order_overrides'"
            ).fetchone()
            try:
                overrides = json.loads(row["value"]) if row else {}
            except (TypeError, json.JSONDecodeError):
                overrides = {}
            overrides.pop(str(int(parent_id)), None)
            connection.execute(
                "INSERT INTO settings(key,value) VALUES('category_order_overrides',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (json.dumps(overrides, ensure_ascii=False),),
            )
        return self.categories()

    @staticmethod
    def _source_columns(connection: sqlite3.Connection, table: str) -> set[str]:
        return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}

    @staticmethod
    def _find_existing_material(
        connection: sqlite3.Connection,
        material: sqlite3.Row,
        suppliers: list[sqlite3.Row],
    ) -> int | None:
        for supplier in suppliers:
            sku = str(supplier["supplier_sku"] or "").strip()
            if not sku:
                continue
            row = connection.execute(
                "SELECT sp.material_id FROM supplier_parts sp JOIN merge_preexisting_material_ids pre ON pre.id=sp.material_id WHERE sp.supplier=? AND sp.supplier_sku=?",
                (str(supplier["supplier"]), sku),
            ).fetchone()
            if row:
                return int(row[0])
        fields = (
            str(material["name"] or "").strip(),
            str(material["manufacturer_part"] or "").strip(),
            str(material["brand"] or "").strip(),
            str(material["package"] or "").strip(),
            str(material["description"] or "").strip(),
            str(material["notes"] or "").strip(),
        )
        if not fields[0] and not fields[1]:
            return None
        row = connection.execute(
            """
            SELECT m.id FROM materials m JOIN merge_preexisting_material_ids pre ON pre.id=m.id
            WHERE lower(trim(name))=lower(?)
              AND lower(trim(manufacturer_part))=lower(?)
              AND lower(trim(brand))=lower(?)
              AND lower(trim(package))=lower(?)
              AND trim(description)=? AND trim(notes)=?
            LIMIT 1
            """,
            fields,
        ).fetchone()
        return int(row[0]) if row else None

    def merge_full_backup(self, data: bytes) -> dict[str, Any]:
        with self._backup_lock:
            temporary_root = Path(
                tempfile.mkdtemp(prefix=".backup-merge-", dir=self.path.parent)
            )
            created_files: list[Path] = []
            try:
                source_path, staged_images, manifest = self._stage_backup(
                    data, temporary_root
                )
                safety_backup = self._write_safety_backup("backup-merge")
                source = sqlite3.connect(source_path)
                source.row_factory = sqlite3.Row
                try:
                    source_transaction_columns = self._source_columns(
                        source, "stock_transactions"
                    )
                    counts = {
                        "added_materials": 0,
                        "skipped_duplicates": 0,
                        "added_transactions": 0,
                        "added_images": 0,
                        "added_locations": 0,
                    }
                    with self.transaction() as target:
                        target.execute("CREATE TEMP TABLE merge_preexisting_material_ids(id INTEGER PRIMARY KEY)")
                        target.execute("INSERT INTO merge_preexisting_material_ids SELECT id FROM materials")
                        location_map: dict[int, int] = {}
                        for location in source.execute("SELECT * FROM locations ORDER BY id"):
                            existing = target.execute(
                                "SELECT id FROM locations WHERE name=?",
                                (str(location["name"]),),
                            ).fetchone()
                            if existing:
                                location_map[int(location["id"])] = int(existing[0])
                            else:
                                cursor = target.execute(
                                    "INSERT INTO locations(name,enabled,created_at) VALUES(?,?,?)",
                                    (
                                        str(location["name"]),
                                        int(location["enabled"]),
                                        str(location["created_at"]),
                                    ),
                                )
                                location_map[int(location["id"])] = int(cursor.lastrowid)
                                counts["added_locations"] += 1

                        category_map: dict[int, int] = {}
                        for category in source.execute("SELECT * FROM categories ORDER BY id"):
                            external_id = category["external_id"]
                            if external_id is not None:
                                existing = target.execute(
                                    "SELECT id FROM categories WHERE source=? AND external_id=?",
                                    (str(category["source"]), str(external_id)),
                                ).fetchone()
                            else:
                                existing = target.execute(
                                    "SELECT id FROM categories WHERE source=? AND external_id IS NULL "
                                    "AND name=? AND code=? LIMIT 1",
                                    (
                                        str(category["source"]),
                                        str(category["name"]),
                                        str(category["code"]),
                                    ),
                                ).fetchone()
                            if existing:
                                category_map[int(category["id"])] = int(existing[0])
                            else:
                                cursor = target.execute(
                                    """
                                    INSERT INTO categories(
                                        source,external_id,name,code,url,source_count,sort_order,
                                        enabled,created_at,updated_at
                                    ) VALUES(?,?,?,?,?,?,?,?,?,?)
                                    """,
                                    (
                                        str(category["source"]),
                                        external_id,
                                        str(category["name"]),
                                        str(category["code"]),
                                        str(category["url"]),
                                        int(category["source_count"]),
                                        int(category["sort_order"]),
                                        int(category["enabled"]),
                                        str(category["created_at"]),
                                        str(category["updated_at"]),
                                    ),
                                )
                                category_map[int(category["id"])] = int(cursor.lastrowid)
                        for relation in source.execute("SELECT * FROM category_relations"):
                            parent_id = category_map.get(int(relation["parent_id"]))
                            child_id = category_map.get(int(relation["child_id"]))
                            if parent_id and child_id and parent_id != child_id:
                                target.execute(
                                    "INSERT OR IGNORE INTO category_relations"
                                    "(parent_id,child_id,sort_order) VALUES(?,?,?)",
                                    (parent_id, child_id, int(relation["sort_order"])),
                                )

                        for material in source.execute("SELECT * FROM materials ORDER BY id"):
                            source_id = int(material["id"])
                            suppliers = list(source.execute(
                                "SELECT * FROM supplier_parts WHERE material_id=? ORDER BY id",
                                (source_id,),
                            ))
                            if self._find_existing_material(target, material, suppliers):
                                counts["skipped_duplicates"] += 1
                                continue
                            try:
                                specs = json.loads(str(material["specs_json"] or "{}"))
                            except json.JSONDecodeError:
                                specs = {}
                            new_id = self._create_material(target, {
                                "name": material["name"],
                                "manufacturer_part": material["manufacturer_part"],
                                "brand": material["brand"],
                                "package": material["package"],
                                "description": material["description"],
                                "specs": specs,
                                "image_url": material["image_url"],
                                "datasheet_url": material["datasheet_url"],
                                "unit": material["unit"],
                                "min_stock": material["min_stock"],
                                "notes": material["notes"],
                            })
                            counts["added_materials"] += 1
                            for supplier in suppliers:
                                target.execute(
                                    """
                                    INSERT INTO supplier_parts(
                                        material_id,supplier,supplier_sku,product_url,last_price,
                                        currency,raw_json,created_at,updated_at
                                    ) VALUES(?,?,?,?,?,?,?,?,?)
                                    """,
                                    (
                                        new_id,
                                        supplier["supplier"],
                                        supplier["supplier_sku"],
                                        supplier["product_url"],
                                        supplier["last_price"],
                                        supplier["currency"],
                                        supplier["raw_json"],
                                        supplier["created_at"],
                                        supplier["updated_at"],
                                    ),
                                )
                            for assignment in source.execute(
                                "SELECT * FROM material_categories WHERE material_id=?",
                                (source_id,),
                            ):
                                category_id = category_map.get(int(assignment["category_id"]))
                                if category_id:
                                    target.execute(
                                        "INSERT OR IGNORE INTO material_categories"
                                        "(material_id,category_id,is_primary) VALUES(?,?,?)",
                                        (new_id, category_id, int(assignment["is_primary"])),
                                    )

                            transaction_map: dict[int, int] = {}
                            source_transactions = list(source.execute(
                                "SELECT * FROM stock_transactions WHERE material_id=? ORDER BY id",
                                (source_id,),
                            ))
                            for transaction in source_transactions:
                                request_id = transaction["request_id"]
                                if request_id and target.execute(
                                    "SELECT 1 FROM stock_transactions WHERE request_id=?",
                                    (request_id,),
                                ).fetchone():
                                    request_id = None
                                cursor = target.execute(
                                    """
                                    INSERT INTO stock_transactions(
                                        material_id,location_id,kind,quantity_delta,unit_cost,note,
                                        source,request_id,reversal_of,created_at,archived,deleted
                                    ) VALUES(?,?,?,?,?,?,?,?,NULL,?,?,?)
                                    """,
                                    (
                                        new_id,
                                        location_map[int(transaction["location_id"])],
                                        transaction["kind"],
                                        transaction["quantity_delta"],
                                        transaction["unit_cost"],
                                        transaction["note"],
                                        transaction["source"],
                                        request_id,
                                        transaction["created_at"],
                                        int(transaction["archived"])
                                        if "archived" in source_transaction_columns else 0,
                                        int(transaction["deleted"])
                                        if "deleted" in source_transaction_columns else 0,
                                    ),
                                )
                                transaction_map[int(transaction["id"])] = int(cursor.lastrowid)
                                counts["added_transactions"] += 1
                            for transaction in source_transactions:
                                reversal_of = transaction["reversal_of"]
                                if reversal_of and int(reversal_of) in transaction_map:
                                    target.execute(
                                        "UPDATE stock_transactions SET reversal_of=? WHERE id=?",
                                        (
                                            transaction_map[int(reversal_of)],
                                            transaction_map[int(transaction["id"])],
                                        ),
                                    )

                            image_url = str(material["image_url"] or "")
                            prefix = "/media/images/"
                            if image_url.startswith(prefix):
                                source_name = PurePosixPath(
                                    image_url.removeprefix(prefix)
                                ).name
                                source_image = staged_images / source_name
                                if source_image.is_file():
                                    suffix = source_image.suffix.lower()
                                    target_name = (
                                        source_name
                                        if bool(re.fullmatch(r"C\d+\.(jpg|jpeg|png|webp|gif)", source_name, re.IGNORECASE))
                                        else f"M{new_id}{suffix}"
                                    )
                                    target_image = self.image_dir / target_name
                                    if not target_image.exists():
                                        temporary_image = target_image.with_suffix(
                                            target_image.suffix + ".merge-part"
                                        )
                                        shutil.copyfile(source_image, temporary_image)
                                        temporary_image.replace(target_image)
                                        created_files.append(target_image)
                                        counts["added_images"] += 1
                                    target.execute(
                                        "UPDATE materials SET image_url=? WHERE id=?",
                                        (f"/media/images/{target_name}", new_id),
                                    )
                    return {
                        "merged": True,
                        "created_at": manifest.get("created_at"),
                        **counts,
                        "safety_backup": safety_backup,
                    }
                except Exception:
                    for path in created_files:
                        path.unlink(missing_ok=True)
                    raise
                finally:
                    source.close()
            finally:
                shutil.rmtree(temporary_root, ignore_errors=True)
