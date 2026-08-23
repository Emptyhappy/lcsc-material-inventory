from __future__ import annotations

from typing import Any

from .database import now
from .enhanced_repository import EnhancedInventoryRepository
from .repository import InventoryRepository


class ApplicationRepository(EnhancedInventoryRepository):
    """Final repository used by the application server."""

    def import_lcsc(self, payload: dict[str, Any]) -> dict[str, Any]:
        base_result = InventoryRepository.import_lcsc(self, payload)
        transient = {
            "created": base_result["created"],
            "transaction_id": base_result["transaction_id"],
            "duplicate_request": base_result["duplicate_request"],
            "added_quantity": base_result["added_quantity"],
        }
        material_id = int(base_result["id"])
        supplier_sku = str(payload.get("supplier_sku") or "").upper()
        external_image = str(payload.get("image_url") or "")
        local_image = ""
        image_error = ""
        try:
            if external_image:
                local_image = self._download_lcsc_image(supplier_sku, external_image)
        except Exception as exc:
            image_error = str(exc)

        updates: list[str] = []
        parameters: list[Any] = []
        if local_image:
            updates.append("image_url=?")
            parameters.append(local_image)
        if "min_stock" in payload and payload["min_stock"] not in (None, ""):
            updates.append("min_stock=?")
            parameters.append(float(payload["min_stock"]))
        if payload.get("unit"):
            updates.append("unit=?")
            parameters.append(str(payload["unit"]))
        if payload.get("notes"):
            updates.append("notes=?")
            parameters.append(str(payload["notes"]))
        if updates:
            with self.transaction() as connection:
                updates.append("updated_at=?")
                parameters.extend([now(), material_id])
                connection.execute(
                    f"UPDATE materials SET {','.join(updates)} WHERE id=?", parameters
                )

        result = self.material_detail(material_id)
        result.update(transient)
        result["image_cached"] = bool(local_image)
        result["image_error"] = image_error
        return result
