from __future__ import annotations

import csv
import io
import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS locations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL DEFAULT 'custom',
    external_id TEXT,
    name TEXT NOT NULL,
    code TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    source_count INTEGER NOT NULL DEFAULT 0,
    sort_order INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(source, external_id)
);

CREATE TABLE IF NOT EXISTS category_relations (
    parent_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    child_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    sort_order INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(parent_id, child_id),
    CHECK(parent_id <> child_id)
);

CREATE TABLE IF NOT EXISTS materials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    internal_code TEXT UNIQUE,
    name TEXT NOT NULL,
    manufacturer_part TEXT NOT NULL DEFAULT '',
    brand TEXT NOT NULL DEFAULT '',
    package TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    specs_json TEXT NOT NULL DEFAULT '{}',
    image_url TEXT NOT NULL DEFAULT '',
    datasheet_url TEXT NOT NULL DEFAULT '',
    unit TEXT NOT NULL DEFAULT '个',
    min_stock REAL NOT NULL DEFAULT 0,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS supplier_parts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id INTEGER NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
    supplier TEXT NOT NULL,
    supplier_sku TEXT NOT NULL,
    product_url TEXT NOT NULL DEFAULT '',
    last_price REAL,
    currency TEXT NOT NULL DEFAULT 'CNY',
    raw_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(supplier, supplier_sku)
);

CREATE TABLE IF NOT EXISTS material_categories (
    material_id INTEGER NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    is_primary INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(material_id, category_id)
);

CREATE TABLE IF NOT EXISTS stock_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id INTEGER NOT NULL REFERENCES materials(id) ON DELETE RESTRICT,
    location_id INTEGER NOT NULL REFERENCES locations(id) ON DELETE RESTRICT,
    kind TEXT NOT NULL,
    quantity_delta REAL NOT NULL,
    unit_cost REAL,
    note TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'manual',
    request_id TEXT UNIQUE,
    reversal_of INTEGER REFERENCES stock_transactions(id),
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_material_name ON materials(name);
CREATE INDEX IF NOT EXISTS idx_material_part ON materials(manufacturer_part);
CREATE INDEX IF NOT EXISTS idx_supplier_sku ON supplier_parts(supplier_sku);
CREATE INDEX IF NOT EXISTS idx_stock_material ON stock_transactions(material_id);
CREATE INDEX IF NOT EXISTS idx_material_category ON material_categories(category_id);
"""


FALLBACK_CATEGORIES = [
    "电容", "电阻", "连接器", "二极管", "电源管理", "光电器件",
    "电感/线圈/变压器", "开发板/开发工具", "存储器", "传感器", "继电器",
    "功能模块", "物联网/通信模块", "单片机/微控制器", "逻辑器件",
    "时钟和定时", "ADC/DAC/数据转换", "射频芯片/天线", "运算放大器/比较器",
    "通信接口芯片", "数码管驱动/LED驱动", "三极管/MOS管/晶体管",
    "振荡器/谐振器", "音频器件/振动马达", "TVS/保险丝/板级保护",
    "按键/开关", "仪器仪表", "电子工具/仪器/耗材", "方案验证板", "其它",
]


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def as_number(value: Any, default: float = 0) -> float:
    if value in (None, ""):
        return default
    return float(value)


class InventoryDatabase:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            stamp = now()
            connection.execute(
                "INSERT OR IGNORE INTO locations(name, created_at) VALUES(?, ?)",
                ("默认仓位", stamp),
            )
            default_location = connection.execute(
                "SELECT id FROM locations WHERE name = '默认仓位'"
            ).fetchone()["id"]
            defaults = {
                "default_quantity": "1",
                "default_location_id": str(default_location),
                "extension_token": secrets.token_urlsafe(24),
                "last_category_sync": "",
            }
            for key, value in defaults.items():
                connection.execute(
                    "INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)", (key, value)
                )
            root_id = self._upsert_category(
                connection,
                source="lcsc",
                external_id="1",
                name="电子元器件",
                code="root",
                url="https://www.szlcsc.com/catalog.html",
                sort_order=0,
                source_count=0,
            )
            for index, name in enumerate(FALLBACK_CATEGORIES, start=1):
                child_id = self._upsert_category(
                    connection,
                    source="lcsc",
                    external_id=f"fallback-{index}",
                    name=name,
                    sort_order=index,
                )
                connection.execute(
                    "INSERT OR IGNORE INTO category_relations(parent_id, child_id, sort_order) "
                    "VALUES(?, ?, ?)",
                    (root_id, child_id, index),
                )

            last_sync = connection.execute(
                "SELECT value FROM settings WHERE key=?", ("last_category_sync",)
            ).fetchone()["value"]
            if last_sync:
                connection.execute(
                    "UPDATE categories SET enabled=0 WHERE source=? AND external_id LIKE ?",
                    ("lcsc", "fallback-%"),
                )

    @staticmethod
    def _upsert_category(
        connection: sqlite3.Connection,
        *,
        source: str,
        external_id: str | None,
        name: str,
        code: str = "",
        url: str = "",
        sort_order: int = 0,
        source_count: int = 0,
    ) -> int:
        stamp = now()
        connection.execute(
            """
            INSERT INTO categories(
                source, external_id, name, code, url, source_count, sort_order,
                enabled, created_at, updated_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT(source, external_id) DO UPDATE SET
                name=excluded.name, code=excluded.code, url=excluded.url,
                source_count=excluded.source_count, sort_order=excluded.sort_order,
                enabled=1, updated_at=excluded.updated_at
            """,
            (source, external_id, name, code, url, source_count, sort_order, stamp, stamp),
        )
        row = connection.execute(
            "SELECT id FROM categories WHERE source=? AND external_id IS ?",
            (source, external_id),
        ).fetchone()
        return int(row["id"])

    def get_settings(self) -> dict[str, Any]:
        with self.connect() as connection:
            result = {row["key"]: row["value"] for row in connection.execute("SELECT * FROM settings")}
            location = connection.execute(
                "SELECT name FROM locations WHERE id=?",
                (int(result["default_location_id"]),),
            ).fetchone()
        result["default_quantity"] = as_number(result.get("default_quantity"), 1)
        result["default_location_id"] = int(result["default_location_id"])
        result["default_location_name"] = location["name"] if location else "默认仓位"
        return result

    def update_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        allowed = {"default_quantity", "default_location_id"}
        with self.transaction() as connection:
            if "default_quantity" in payload and as_number(payload["default_quantity"]) <= 0:
                raise ValueError("默认数量必须大于0")
            if "default_location_id" in payload:
                exists = connection.execute(
                    "SELECT 1 FROM locations WHERE id=? AND enabled=1",
                    (int(payload["default_location_id"]),),
                ).fetchone()
                if not exists:
                    raise ValueError("默认仓位不存在")
            for key in allowed.intersection(payload):
                connection.execute(
                    "INSERT INTO settings(key,value) VALUES(?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, str(payload[key])),
                )
        return self.get_settings()

    def list_locations(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT * FROM locations WHERE enabled=1 ORDER BY name"
            )]

    def add_location(self, name: str) -> dict[str, Any]:
        name = name.strip()
        if not name:
            raise ValueError("仓位名称不能为空")
        with self.transaction() as connection:
            cursor = connection.execute(
                "INSERT INTO locations(name,created_at) VALUES(?,?)", (name, now())
            )
            row = connection.execute("SELECT * FROM locations WHERE id=?", (cursor.lastrowid,)).fetchone()
        return dict(row)

    def sync_categories(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        if not items:
            raise ValueError("分类数据为空")
        with self.transaction() as connection:
            ids: dict[str, int] = {}
            for item in items:
                external_id = str(item["external_id"])
                ids[external_id] = self._upsert_category(
                    connection,
                    source="lcsc",
                    external_id=external_id,
                    name=str(item["name"]),
                    code=str(item.get("code") or ""),
                    url=str(item.get("url") or ""),
                    sort_order=int(item.get("sort_order") or 0),
                    source_count=int(item.get("source_count") or 0),
                )
            connection.execute(
                "DELETE FROM category_relations WHERE parent_id IN "
                "(SELECT id FROM categories WHERE source='lcsc')"
            )
            relation_count = 0
            for item in items:
                parent_external = item.get("parent_external_id")
                if parent_external is None:
                    continue
                parent_id = ids.get(str(parent_external))
                child_id = ids[str(item["external_id"])]
                if parent_id:
                    connection.execute(
                        "INSERT OR IGNORE INTO category_relations(parent_id,child_id,sort_order) "
                        "VALUES(?,?,?)",
                        (parent_id, child_id, int(item.get("sort_order") or 0)),
                    )
                    relation_count += 1
            connection.execute(
                "INSERT INTO settings(key,value) VALUES('last_category_sync',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (now(),),
            )
            connection.execute(
                "UPDATE categories SET enabled=0,updated_at=? "
                "WHERE source='lcsc' AND external_id LIKE 'fallback-%'",
                (now(),),
            )
        return {"categories": len(items), "relations": relation_count, "synced_at": now()}

    def categories(self) -> dict[str, Any]:
        with self.connect() as connection:
            rows = [dict(row) for row in connection.execute(
                """
                SELECT c.*,
                       COUNT(DISTINCT mc.material_id) material_count,
                       COALESCE(SUM(ms.stock),0) stock_quantity,
                       COALESCE(SUM(CASE WHEN ms.stock<=m.min_stock THEN 1 ELSE 0 END),0) low_stock_count
                FROM categories c
                LEFT JOIN material_categories mc ON mc.category_id=c.id
                LEFT JOIN materials m ON m.id=mc.material_id
                LEFT JOIN (
                    SELECT material_id,SUM(quantity_delta) stock
                    FROM stock_transactions GROUP BY material_id
                ) ms ON ms.material_id=m.id
                WHERE c.enabled=1 GROUP BY c.id
                ORDER BY c.source,c.sort_order,c.name
                """
            )]
            relations = [dict(row) for row in connection.execute(
                """
                SELECT r.parent_id,r.child_id,r.sort_order FROM category_relations r
                JOIN categories p ON p.id=r.parent_id AND p.enabled=1
                JOIN categories c ON c.id=r.child_id AND c.enabled=1
                ORDER BY r.sort_order
                """
            )]
        return {"categories": rows, "relations": relations}

    def add_custom_category(self, name: str, parent_id: int | None = None) -> dict[str, Any]:
        name = name.strip()
        if not name:
            raise ValueError("分类名称不能为空")
        with self.transaction() as connection:
            stamp = now()
            cursor = connection.execute(
                "INSERT INTO categories(source,name,created_at,updated_at) VALUES('custom',?,?,?)",
                (name, stamp, stamp),
            )
            category_id = int(cursor.lastrowid)
            if parent_id:
                connection.execute(
                    "INSERT INTO category_relations(parent_id,child_id) VALUES(?,?)",
                    (int(parent_id), category_id),
                )
            row = connection.execute("SELECT * FROM categories WHERE id=?", (category_id,)).fetchone()
        return dict(row)

    def _default_location_id(self, connection: sqlite3.Connection) -> int:
        return int(connection.execute(
            "SELECT value FROM settings WHERE key='default_location_id'"
        ).fetchone()["value"])

    def _default_quantity(self, connection: sqlite3.Connection) -> float:
        return as_number(connection.execute(
            "SELECT value FROM settings WHERE key='default_quantity'"
        ).fetchone()["value"], 1)

    @staticmethod
    def _assign_category(connection: sqlite3.Connection, material_id: int, category_id: int) -> None:
        connection.execute("UPDATE material_categories SET is_primary=0 WHERE material_id=?", (material_id,))
        connection.execute(
            "INSERT INTO material_categories(material_id,category_id,is_primary) VALUES(?,?,1) "
            "ON CONFLICT(material_id,category_id) DO UPDATE SET is_primary=1",
            (material_id, category_id),
        )

    @staticmethod
    def _create_material(connection: sqlite3.Connection, payload: dict[str, Any]) -> int:
        stamp = now()
        cursor = connection.execute(
            """
            INSERT INTO materials(
                name,manufacturer_part,brand,package,description,specs_json,image_url,
                datasheet_url,unit,min_stock,notes,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                str(payload.get("name") or payload.get("manufacturer_part") or "未命名物料").strip(),
                str(payload.get("manufacturer_part") or "").strip(),
                str(payload.get("brand") or "").strip(),
                str(payload.get("package") or "").strip(),
                str(payload.get("description") or "").strip(),
                json.dumps(payload.get("specs") or {}, ensure_ascii=False),
                str(payload.get("image_url") or ""), str(payload.get("datasheet_url") or ""),
                str(payload.get("unit") or "个"), as_number(payload.get("min_stock"), 0),
                str(payload.get("notes") or ""), stamp, stamp,
            ),
        )
        material_id = int(cursor.lastrowid)
        connection.execute(
            "UPDATE materials SET internal_code=? WHERE id=?",
            (f"MAT-{material_id:06d}", material_id),
        )
        return material_id
