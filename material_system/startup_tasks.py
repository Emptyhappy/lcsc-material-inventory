from __future__ import annotations

import json
from typing import Any

from .application_repository import ApplicationRepository
from .database import now


def cache_existing_images(repository: ApplicationRepository, limit: int = 200) -> dict[str, Any]:
    """Download images for LCSC materials created before local caching was enabled."""
    with repository.connect() as connection:
        rows = [dict(row) for row in connection.execute(
            """
            SELECT m.id,m.image_url,sp.supplier_sku,sp.raw_json
            FROM materials m JOIN supplier_parts sp ON sp.material_id=m.id AND sp.supplier='lcsc'
            WHERE m.image_url NOT LIKE '/media/images/%'
            ORDER BY m.id LIMIT ?
            """,
            (max(1, min(int(limit), 1000)),),
        )]
    cached = 0
    failed: list[dict[str, str]] = []
    for row in rows:
        try:
            raw = json.loads(row.get("raw_json") or "{}")
            image_url = str(raw.get("image_url") or row.get("image_url") or "")
            image_url = image_url.split("<$>", 1)[0]
            image_url = image_url.replace("/product/breviary/", "/product/source/")
            if not image_url:
                continue
            local_url = repository._download_lcsc_image(row["supplier_sku"], image_url)
            with repository.transaction() as connection:
                connection.execute(
                    "UPDATE materials SET image_url=?,updated_at=? WHERE id=?",
                    (local_url, now(), int(row["id"])),
                )
            cached += 1
        except Exception as exc:
            failed.append({"supplier_sku": row["supplier_sku"], "error": str(exc)})
    return {"checked": len(rows), "cached": cached, "failed": failed}
