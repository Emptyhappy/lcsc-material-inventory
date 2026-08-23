from __future__ import annotations

import json
import mimetypes
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .database import now
from .repository import InventoryRepository


IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
MAX_IMAGE_BYTES = 6 * 1024 * 1024


class EnhancedInventoryRepository(InventoryRepository):
    """Adds local image caching and persistent category order overrides."""

    @property
    def image_dir(self) -> Path:
        path = self.path.parent / "images"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _existing_image(self, supplier_sku: str) -> Path | None:
        for path in self.image_dir.glob(f"{supplier_sku}.*"):
            if path.is_file() and path.stat().st_size > 0 and not path.name.endswith(".part"):
                return path
        return None

    def _download_lcsc_image(self, supplier_sku: str, image_url: str) -> str:
        existing = self._existing_image(supplier_sku)
        if existing:
            return f"/media/images/{existing.name}"

        parsed = urlparse(image_url)
        hostname = (parsed.hostname or "").lower()
        allowed_host = (
            hostname == "szlcsc.com"
            or hostname.endswith(".szlcsc.com")
            or hostname == "lcsc.com"
            or hostname.endswith(".lcsc.com")
        )
        if parsed.scheme != "https" or not allowed_host:
            raise ValueError("商品图片不是受支持的立创图片地址")

        request = urllib.request.Request(
            image_url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/124 Safari/537.36"
                ),
                "Referer": "https://item.szlcsc.com/",
            },
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            declared_size = int(response.headers.get("Content-Length") or 0)
            if declared_size > MAX_IMAGE_BYTES:
                raise ValueError("商品图片超过6MB限制")
            content_type = (response.headers.get_content_type() or "").lower()
            data = response.read(MAX_IMAGE_BYTES + 1)
        if len(data) > MAX_IMAGE_BYTES:
            raise ValueError("商品图片超过6MB限制")
        if not data:
            raise ValueError("商品图片内容为空")

        extension = IMAGE_TYPES.get(content_type)
        if not extension:
            extension = Path(parsed.path).suffix.lower()
            if extension not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
                guessed = mimetypes.guess_extension(content_type)
                extension = guessed if guessed in {".jpg", ".jpeg", ".png", ".webp", ".gif"} else ".jpg"
        if extension == ".jpeg":
            extension = ".jpg"
        target = self.image_dir / f"{supplier_sku}{extension}"
        temporary = target.with_suffix(target.suffix + ".part")
        temporary.write_bytes(data)
        temporary.replace(target)
        return f"/media/images/{target.name}"

    def _category_order_overrides(self) -> dict[str, list[int]]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT value FROM settings WHERE key='category_order_overrides'"
            ).fetchone()
        if not row:
            return {}
        try:
            value = json.loads(row["value"])
            return {str(key): [int(item) for item in items] for key, items in value.items()}
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}

    def categories(self) -> dict[str, Any]:
        result = super().categories()
        overrides = self._category_order_overrides()
        categories = {int(item["id"]): item for item in result["categories"]}
        for parent_id, ordered_ids in overrides.items():
            order = {child_id: index for index, child_id in enumerate(ordered_ids)}
            for relation in result["relations"]:
                if str(relation["parent_id"]) == parent_id and relation["child_id"] in order:
                    position = order[relation["child_id"]]
                    relation["sort_order"] = position
                    if relation["child_id"] in categories:
                        categories[relation["child_id"]]["sort_order"] = position
        result["relations"].sort(
            key=lambda item: (int(item["parent_id"]), int(item["sort_order"]), int(item["child_id"]))
        )
        return result

    def reorder_categories(self, parent_id: int, ordered_child_ids: list[int]) -> dict[str, Any]:
        ordered_child_ids = [int(item) for item in ordered_child_ids]
        with self.transaction() as connection:
            existing = [int(row["child_id"]) for row in connection.execute(
                """
                SELECT r.child_id FROM category_relations r
                JOIN categories c ON c.id=r.child_id AND c.enabled=1
                WHERE r.parent_id=?
                """,
                (parent_id,),
            )]
            if len(existing) < 2:
                raise ValueError("该分类下没有可调整顺序的子分类")
            if len(ordered_child_ids) != len(existing) or set(ordered_child_ids) != set(existing):
                raise ValueError("分类排序数据与当前子分类不一致，请刷新后重试")
            row = connection.execute(
                "SELECT value FROM settings WHERE key='category_order_overrides'"
            ).fetchone()
            try:
                overrides = json.loads(row["value"]) if row else {}
            except json.JSONDecodeError:
                overrides = {}
            overrides[str(parent_id)] = ordered_child_ids
            connection.execute(
                "INSERT INTO settings(key,value) VALUES('category_order_overrides',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (json.dumps(overrides, ensure_ascii=False),),
            )
        return self.categories()
