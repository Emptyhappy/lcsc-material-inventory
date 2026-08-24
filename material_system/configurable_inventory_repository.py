from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any

from .advanced_inventory_repository import AdvancedInventoryRepository


SAFETY_LEVELS = {"high", "medium", "low"}
MEDIUM_SAFETY_OPERATIONS = {
    "material_batch_delete",
    "transaction_clear",
    "transaction_bulk_delete",
    "backup_restore",
    "backup_merge",
}


class ConfigurableInventoryRepository(AdvancedInventoryRepository):
    """Adds configurable backup policy, paths and reliable taxonomy restoration."""

    def __init__(self, path: str | Path) -> None:
        self._safety_context = threading.local()
        super().__init__(path)

    def initialize(self) -> None:
        super().initialize()
        defaults = {
            "auto_backup_level": "high",
            "safety_backup_dir": str(
                (self.path.parent / "backups" / "safety").resolve()
            ),
            "normal_backup_dir": str(
                (self.path.parent / "backups" / "normal").resolve()
            ),
        }
        with self.connect() as connection:
            for key, value in defaults.items():
                connection.execute(
                    "INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",
                    (key, value),
                )

    def _setting_value(self, key: str, default: str) -> str:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT value FROM settings WHERE key=?", (key,)
            ).fetchone()
        return str(row["value"] if row else default)

    def _default_backup_path(self, kind: str) -> Path:
        return (self.path.parent / "backups" / kind).resolve()

    def _configured_directory(self, key: str, kind: str) -> Path:
        raw = self._setting_value(key, str(self._default_backup_path(kind))).strip()
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = self.path.parent / path
        path = path.resolve()
        if path.exists() and not path.is_dir():
            raise ValueError(f"备份地址不是文件夹：{path}")
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def backup_dir(self) -> Path:
        return self._configured_directory("safety_backup_dir", "safety")

    @property
    def normal_backup_dir(self) -> Path:
        return self._configured_directory("normal_backup_dir", "normal")

    def get_settings(self) -> dict[str, Any]:
        result = super().get_settings()
        level = str(result.get("auto_backup_level") or "high").lower()
        result["auto_backup_level"] = level if level in SAFETY_LEVELS else "high"
        result["safety_backup_dir"] = str(
            result.get("safety_backup_dir")
            or self._default_backup_path("safety")
        )
        result["normal_backup_dir"] = str(
            result.get("normal_backup_dir")
            or self._default_backup_path("normal")
        )
        return result

    def _validate_backup_directory(self, value: Any, label: str) -> str:
        raw = str(value or "").strip()
        if not raw or "\x00" in raw:
            raise ValueError(f"{label}不能为空")
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = self.path.parent / path
        path = path.resolve()
        if path.exists() and not path.is_dir():
            raise ValueError(f"{label}不是文件夹")
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ValueError(f"无法创建或访问{label}：{path}") from exc
        return str(path)

    def update_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        base_payload = {
            key: value
            for key, value in payload.items()
            if key in {"default_quantity", "default_location_id"}
        }
        if base_payload:
            super().update_settings(base_payload)
        updates: dict[str, str] = {}
        if "auto_backup_level" in payload:
            level = str(payload.get("auto_backup_level") or "").lower()
            if level not in SAFETY_LEVELS:
                raise ValueError("自动安全备份级别无效")
            updates["auto_backup_level"] = level
        if "safety_backup_dir" in payload:
            updates["safety_backup_dir"] = self._validate_backup_directory(
                payload["safety_backup_dir"], "安全备份地址"
            )
        if "normal_backup_dir" in payload:
            updates["normal_backup_dir"] = self._validate_backup_directory(
                payload["normal_backup_dir"], "正常备份地址"
            )
        if updates:
            with self.transaction() as connection:
                for key, value in updates.items():
                    connection.execute(
                        "INSERT INTO settings(key,value) VALUES(?,?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (key, value),
                    )
        return self.get_settings()

    def _safety_level(self) -> str:
        level = self._setting_value("auto_backup_level", "high").lower()
        return level if level in SAFETY_LEVELS else "high"

    @staticmethod
    def _unique_backup_target(directory: Path, filename: str) -> Path:
        target = directory / filename
        counter = 1
        while target.exists():
            target = directory / filename.replace(".zip", f"-{counter}.zip")
            counter += 1
        return target

    def _should_write_safety_backup(self, operation: str) -> bool:
        level = self._safety_level()
        if level == "low":
            return False
        if level == "high":
            return True
        return operation in MEDIUM_SAFETY_OPERATIONS

    def _current_safety_operation(self, purpose: str) -> str:
        explicit = getattr(self._safety_context, "operation", "")
        if explicit:
            return str(explicit)
        return {
            "backup-merge": "backup_merge",
            "restore": "backup_restore",
        }.get(purpose, purpose)

    def _write_safety_backup(self, purpose: str) -> str | None:
        operation = self._current_safety_operation(purpose)
        if not self._should_write_safety_backup(operation):
            return None
        return super()._write_safety_backup(purpose)

    def _run_with_safety_operation(self, operation: str, callback):
        previous = getattr(self._safety_context, "operation", "")
        self._safety_context.operation = operation
        try:
            return callback()
        finally:
            self._safety_context.operation = previous

    def delete_materials(self, material_ids: list[int]) -> dict[str, Any]:
        unique_count = len(set(int(item) for item in material_ids))
        operation = (
            "material_batch_delete" if unique_count > 1 else "material_single_delete"
        )
        return self._run_with_safety_operation(
            operation, lambda: super(ConfigurableInventoryRepository, self).delete_materials(material_ids)
        )

    def delete_transaction(self, transaction_id: int) -> dict[str, Any]:
        with self._backup_lock:
            safety = self._write_safety_for_operation(
                "transaction_single_delete", "transaction-delete"
            )
            result = super().delete_transaction(transaction_id)
        result["safety_backup"] = safety
        return result

    def delete_transactions(self, material_id: int | None = None) -> dict[str, Any]:
        with self._backup_lock:
            safety = self._write_safety_for_operation(
                "transaction_bulk_delete", "transactions-delete"
            )
            result = super().delete_transactions(material_id)
        result["safety_backup"] = safety
        return result

    def archive_transactions(self, material_id: int | None = None) -> dict[str, Any]:
        with self._backup_lock:
            safety = self._write_safety_for_operation(
                "transaction_clear", "transactions-clear"
            )
            result = super().archive_transactions(material_id)
        result["safety_backup"] = safety
        return result

    def _write_safety_for_operation(self, operation: str, purpose: str) -> str | None:
        if not self._should_write_safety_backup(operation):
            return None
        return super()._write_safety_backup(purpose)

    def merge_full_backup(self, data: bytes) -> dict[str, Any]:
        return self._run_with_safety_operation(
            "backup_merge",
            lambda: super(ConfigurableInventoryRepository, self).merge_full_backup(data),
        )

    def restore_full_backup(self, data: bytes) -> dict[str, Any]:
        with self._backup_lock:
            temporary_root = Path(
                tempfile.mkdtemp(prefix=".backup-restore-", dir=self.path.parent)
            )
            current_images = self.path.parent / "images"
            previous_images = temporary_root / "previous-images"
            image_swap_started = False
            safety_data: bytes | None = None
            safety_name: str | None = None
            try:
                database_path, staged_images, manifest = self._stage_backup(
                    data, temporary_root
                )
                safety_data, safety_filename, _ = self._export_full_backup_unlocked()
                if self._should_write_safety_backup("backup_restore"):
                    safety_name = safety_filename.replace(
                        "full-backup", "restore-safety"
                    )
                    safety_path = self._unique_backup_target(
                        self.backup_dir, safety_name
                    )
                    safety_name = safety_path.name
                    safety_path.write_bytes(safety_data)

                current_images.mkdir(parents=True, exist_ok=True)
                os.replace(current_images, previous_images)
                image_swap_started = True
                os.replace(staged_images, current_images)
                self._copy_database(database_path, self.path)
                self.initialize()
                self._validate_database(self.path)

                counts = self._record_counts(self.path)
                shutil.rmtree(previous_images, ignore_errors=True)
                return {
                    "restored": True,
                    "created_at": manifest.get("created_at"),
                    "counts": counts,
                    "image_count": len(manifest.get("images") or []),
                    "safety_backup": safety_name,
                }
            except Exception:
                if image_swap_started:
                    shutil.rmtree(current_images, ignore_errors=True)
                    if previous_images.exists():
                        os.replace(previous_images, current_images)
                if safety_data:
                    rollback_database = temporary_root / "rollback-materials.db"
                    self._database_from_archive(safety_data, rollback_database)
                    self._copy_database(rollback_database, self.path)
                    self.initialize()
                raise
            finally:
                shutil.rmtree(temporary_root, ignore_errors=True)

    def save_normal_backup(self) -> dict[str, Any]:
        with self._backup_lock:
            data, filename, manifest = self._export_full_backup_unlocked()
            target = self._unique_backup_target(self.normal_backup_dir, filename)
            target.write_bytes(data)
        return {
            "saved": True,
            "filename": target.name,
            "path": str(target),
            "size": len(data),
            "counts": manifest["counts"],
            "image_count": len(manifest["images"]),
        }

    def restore_lcsc_category_order(
        self, items: list[dict[str, Any]]
    ) -> dict[str, Any]:
        sync_result = self.sync_categories(items)
        with self.transaction() as connection:
            lcsc_ids = {
                str(row[0])
                for row in connection.execute(
                    "SELECT id FROM categories WHERE source='lcsc'"
                )
            }
            row = connection.execute(
                "SELECT value FROM settings WHERE key='category_order_overrides'"
            ).fetchone()
            try:
                overrides = json.loads(row["value"]) if row else {}
            except (TypeError, json.JSONDecodeError):
                overrides = {}
            overrides = {
                key: value for key, value in overrides.items() if str(key) not in lcsc_ids
            }
            connection.execute(
                "INSERT INTO settings(key,value) VALUES('category_order_overrides',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (json.dumps(overrides, ensure_ascii=False),),
            )
        categories = self.categories()
        root = next(
            (
                item
                for item in categories["categories"]
                if item["source"] == "lcsc" and item["external_id"] == "1"
            ),
            None,
        )
        first_category = None
        if root:
            by_id = {item["id"]: item for item in categories["categories"]}
            children = sorted(
                (
                    relation
                    for relation in categories["relations"]
                    if relation["parent_id"] == root["id"]
                ),
                key=lambda relation: (
                    relation["sort_order"],
                    relation["child_id"],
                ),
            )
            if children:
                first_category = by_id[children[0]["child_id"]]["name"]
        return {
            **categories,
            "synced": sync_result,
            "first_category": first_category,
        }
