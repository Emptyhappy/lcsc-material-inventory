from __future__ import annotations

import mimetypes
import re
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from .advanced_inventory_repository import (
    MAX_MATERIAL_IMAGE_BYTES,
    AdvancedInventoryRepository,
)
from .backup_http_server import build_backup_handler
from .backup_repository import MAX_BACKUP_BYTES
from .http_server import ApiError


def build_advanced_inventory_handler(
    repository: AdvancedInventoryRepository, static_dir: Path
):
    base_handler = build_backup_handler(repository, static_dir)

    class AdvancedInventoryHandler(base_handler):
        def _read_body(self, maximum: int, empty_message: str) -> bytes:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as exc:
                raise ApiError(HTTPStatus.BAD_REQUEST, "请求长度无效") from exc
            if length <= 0:
                raise ApiError(HTTPStatus.BAD_REQUEST, empty_message)
            if length > maximum:
                raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "上传文件过大")
            return self.rfile.read(length)

        def _get(self) -> None:
            path = urlparse(self.path).path
            if path.startswith("/media/images/"):
                filename = unquote(path.removeprefix("/media/images/"))
                if re.fullmatch(
                    r"M\d+\.(jpg|jpeg|png|webp|gif)", filename, re.IGNORECASE
                ):
                    target = (repository.image_dir / filename).resolve()
                    if (
                        repository.image_dir.resolve() not in target.parents
                        or not target.is_file()
                    ):
                        raise ApiError(HTTPStatus.NOT_FOUND, "图片不存在")
                    content_type = (
                        mimetypes.guess_type(target.name)[0]
                        or "application/octet-stream"
                    )
                    self._bytes(target.read_bytes(), content_type)
                    return
            super()._get()

        def _post(self) -> None:
            path = urlparse(self.path).path
            if path == "/api/backup/merge":
                self._json(repository.merge_full_backup(self._read_body(
                    MAX_BACKUP_BYTES, "请选择完整备份 ZIP 文件"
                )))
                return
            if path == "/api/materials/delete-batch":
                payload = self._payload()
                material_ids = payload.get("material_ids")
                if not isinstance(material_ids, list):
                    raise ApiError(HTTPStatus.BAD_REQUEST, "请选择要删除的物料")
                self._json(repository.delete_materials(material_ids))
                return
            if match := re.fullmatch(r"/api/materials/(\d+)/delete", path):
                self._payload()
                self._json(repository.delete_materials([int(match.group(1))]))
                return
            if match := re.fullmatch(r"/api/materials/(\d+)/image", path):
                data = self._read_body(MAX_MATERIAL_IMAGE_BYTES, "请选择图片文件")
                self._json(repository.save_material_image(int(match.group(1)), data))
                return
            if path == "/api/categories/reorder/reset":
                payload = self._payload()
                parent_id = int(payload.get("parent_id") or 0)
                if not parent_id:
                    raise ApiError(HTTPStatus.BAD_REQUEST, "请选择父分类")
                self._json(repository.reset_category_order(parent_id))
                return
            super()._post()

    return AdvancedInventoryHandler


def create_advanced_inventory_server(
    host: str,
    port: int,
    repository: AdvancedInventoryRepository,
    static_dir: Path,
) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(
        (host, port), build_advanced_inventory_handler(repository, static_dir)
    )
