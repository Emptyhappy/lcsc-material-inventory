from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sqlite3
import tempfile
import threading
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from .deletable_repository import DeletableInventoryRepository


BACKUP_FORMAT = "lcsc-material-inventory-backup"
BACKUP_VERSION = 1
MAX_BACKUP_BYTES = 256 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
MAX_BACKUP_ENTRIES = 5000
MAX_IMAGE_BYTES = 12 * 1024 * 1024
REQUIRED_TABLES = {
    "settings",
    "locations",
    "categories",
    "category_relations",
    "materials",
    "supplier_parts",
    "material_categories",
    "stock_transactions",
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _stamp() -> str:
    return datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")


class BackupInventoryRepository(DeletableInventoryRepository):
    """Adds validated full export and restore of the database and cached images."""

    def __init__(self, path: str | Path) -> None:
        self._backup_lock = threading.RLock()
        super().__init__(path)

    @property
    def backup_dir(self) -> Path:
        path = self.path.parent / "backups"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _snapshot_database(self, target: Path) -> None:
        source = self.connect()
        destination = sqlite3.connect(target)
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()
        self._validate_database(target)

    @staticmethod
    def _validate_database(path: Path) -> None:
        try:
            connection = sqlite3.connect(path)
            try:
                quick_check = connection.execute("PRAGMA quick_check").fetchone()
                if not quick_check or str(quick_check[0]).lower() != "ok":
                    raise ValueError("备份数据库完整性校验未通过")
                tables = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                missing = REQUIRED_TABLES - tables
                if missing:
                    raise ValueError("备份缺少必要的数据表")
                foreign_key_errors = connection.execute(
                    "PRAGMA foreign_key_check"
                ).fetchall()
                if foreign_key_errors:
                    raise ValueError("备份数据库的关联数据不完整")
            finally:
                connection.close()
        except sqlite3.DatabaseError as exc:
            raise ValueError("备份中的数据库文件无效") from exc

    def _record_counts(self, database_path: Path) -> dict[str, int]:
        connection = sqlite3.connect(database_path)
        try:
            return {
                table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for table in sorted(REQUIRED_TABLES)
            }
        finally:
            connection.close()

    def _export_full_backup_unlocked(self) -> tuple[bytes, str, dict[str, Any]]:
        temporary_root = Path(
            tempfile.mkdtemp(prefix=".backup-export-", dir=self.path.parent)
        )
        try:
            database_snapshot = temporary_root / "materials.db"
            self._snapshot_database(database_snapshot)
            database_bytes = database_snapshot.read_bytes()
            counts = self._record_counts(database_snapshot)

            images: list[dict[str, Any]] = []
            image_files: list[Path] = []
            image_dir = self.image_dir
            for path in sorted(image_dir.iterdir(), key=lambda item: item.name.lower()):
                if not path.is_file() or path.name.endswith(".part"):
                    continue
                data = path.read_bytes()
                images.append({
                    "path": f"images/{path.name}",
                    "size": len(data),
                    "sha256": _sha256(data),
                })
                image_files.append(path)

            created_at = datetime.now().astimezone().isoformat(timespec="seconds")
            manifest = {
                "format": BACKUP_FORMAT,
                "version": BACKUP_VERSION,
                "created_at": created_at,
                "database": {
                    "path": "materials.db",
                    "size": len(database_bytes),
                    "sha256": _sha256(database_bytes),
                },
                "counts": counts,
                "images": images,
            }
            output = io.BytesIO()
            with zipfile.ZipFile(
                output, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
            ) as archive:
                archive.writestr(
                    "manifest.json",
                    json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
                )
                archive.writestr("materials.db", database_bytes)
                for path in image_files:
                    archive.write(path, f"images/{path.name}")
            filename = f"material-inventory-full-backup-{_stamp()}.zip"
            return output.getvalue(), filename, manifest
        finally:
            shutil.rmtree(temporary_root, ignore_errors=True)

    def export_full_backup(self) -> tuple[bytes, str, dict[str, Any]]:
        with self._backup_lock:
            return self._export_full_backup_unlocked()

    @staticmethod
    def _safe_archive_name(name: str) -> str:
        normalized = name.replace("\\", "/")
        path = PurePosixPath(normalized)
        if (
            not normalized
            or normalized.startswith("/")
            or ".." in path.parts
            or ":" in normalized
        ):
            raise ValueError("备份包中包含不安全的文件路径")
        return normalized

    def _stage_backup(self, data: bytes, temporary_root: Path) -> tuple[Path, Path, dict[str, Any]]:
        if not data:
            raise ValueError("请选择完整备份 ZIP 文件")
        if len(data) > MAX_BACKUP_BYTES:
            raise ValueError("备份文件超过 256MB 限制")
        try:
            archive = zipfile.ZipFile(io.BytesIO(data), mode="r")
        except zipfile.BadZipFile as exc:
            raise ValueError("备份文件不是有效的 ZIP 包") from exc

        with archive:
            entries = archive.infolist()
            if len(entries) > MAX_BACKUP_ENTRIES:
                raise ValueError("备份包中的文件数量过多")
            names: set[str] = set()
            total_size = 0
            image_entries: list[tuple[zipfile.ZipInfo, str]] = []
            for entry in entries:
                name = self._safe_archive_name(entry.filename)
                if name in names:
                    raise ValueError("备份包中存在重复文件")
                names.add(name)
                if entry.flag_bits & 0x1:
                    raise ValueError("不支持加密的备份包")
                total_size += int(entry.file_size)
                if total_size > MAX_UNCOMPRESSED_BYTES:
                    raise ValueError("备份包解压后的数据过大")
                if entry.is_dir():
                    if name.rstrip("/") != "images":
                        raise ValueError("备份包中包含未知目录")
                    continue
                if name in {"manifest.json", "materials.db"}:
                    continue
                parts = PurePosixPath(name).parts
                if len(parts) != 2 or parts[0] != "images":
                    raise ValueError("备份包中包含未知文件")
                if entry.file_size > MAX_IMAGE_BYTES:
                    raise ValueError("备份包中有图片超过 12MB 限制")
                image_entries.append((entry, name))

            if "manifest.json" not in names or "materials.db" not in names:
                raise ValueError("备份包缺少清单或数据库文件")
            try:
                manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError, KeyError) as exc:
                raise ValueError("备份清单格式错误") from exc
            if not isinstance(manifest, dict):
                raise ValueError("备份清单格式错误")
            if manifest.get("format") != BACKUP_FORMAT:
                raise ValueError("这不是本物料系统生成的完整备份")
            if int(manifest.get("version") or 0) != BACKUP_VERSION:
                raise ValueError("备份版本暂不受支持")

            database_bytes = archive.read("materials.db")
            database_info = manifest.get("database") or {}
            if _sha256(database_bytes) != str(database_info.get("sha256") or ""):
                raise ValueError("备份数据库校验值不一致，文件可能已损坏")
            database_path = temporary_root / "materials.db"
            database_path.write_bytes(database_bytes)
            self._validate_database(database_path)

            declared_images = {
                str(item.get("path")): item
                for item in manifest.get("images", [])
                if isinstance(item, dict)
            }
            actual_image_names = {name for _, name in image_entries}
            if set(declared_images) != actual_image_names:
                raise ValueError("备份图片清单与文件内容不一致")
            staged_images = temporary_root / "restored-images"
            staged_images.mkdir()
            for entry, name in image_entries:
                image_data = archive.read(entry)
                expected_hash = str(declared_images[name].get("sha256") or "")
                if _sha256(image_data) != expected_hash:
                    raise ValueError(f"备份图片 {PurePosixPath(name).name} 已损坏")
                (staged_images / PurePosixPath(name).name).write_bytes(image_data)
        return database_path, staged_images, manifest

    @staticmethod
    def _copy_database(source_path: Path, target_path: Path) -> None:
        source = sqlite3.connect(source_path)
        target = sqlite3.connect(target_path, timeout=30)
        try:
            target.execute("PRAGMA foreign_keys = OFF")
            source.backup(target)
        finally:
            target.close()
            source.close()

    @staticmethod
    def _database_from_archive(data: bytes, target: Path) -> None:
        with zipfile.ZipFile(io.BytesIO(data), mode="r") as archive:
            target.write_bytes(archive.read("materials.db"))

    def restore_full_backup(self, data: bytes) -> dict[str, Any]:
        with self._backup_lock:
            temporary_root = Path(
                tempfile.mkdtemp(prefix=".backup-restore-", dir=self.path.parent)
            )
            current_images = self.path.parent / "images"
            previous_images = temporary_root / "previous-images"
            image_swap_started = False
            safety_data: bytes | None = None
            try:
                database_path, staged_images, manifest = self._stage_backup(
                    data, temporary_root
                )

                safety_data, safety_filename, _ = self._export_full_backup_unlocked()
                safety_path = self.backup_dir / safety_filename.replace(
                    "full-backup", "restore-safety"
                )
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
                    "safety_backup": safety_path.name,
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
