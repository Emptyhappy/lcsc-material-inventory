from __future__ import annotations

import mimetypes
import re
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from .application_repository import ApplicationRepository
from .http_server import ApiError, build_handler


def build_enhanced_handler(repository: ApplicationRepository, static_dir: Path):
    base_handler = build_handler(repository, static_dir)

    class EnhancedHandler(base_handler):
        def _get(self) -> None:
            path = urlparse(self.path).path
            if path == "/api/extension/status":
                self._require_extension_token()
                settings = repository.get_settings()
                self._json({
                    "ok": True,
                    "default_quantity": settings["default_quantity"],
                    "default_location_id": settings["default_location_id"],
                    "default_location_name": settings["default_location_name"],
                    "locations": repository.list_locations(),
                })
                return
            if path.startswith("/media/images/"):
                filename = unquote(path.removeprefix("/media/images/"))
                if not re.fullmatch(r"C\d+\.(jpg|jpeg|png|webp|gif)", filename, re.IGNORECASE):
                    raise ApiError(HTTPStatus.NOT_FOUND, "图片不存在")
                target = (repository.image_dir / filename).resolve()
                if repository.image_dir.resolve() not in target.parents or not target.is_file():
                    raise ApiError(HTTPStatus.NOT_FOUND, "图片不存在")
                content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
                self._bytes(target.read_bytes(), content_type)
                return
            super()._get()

        def _post(self) -> None:
            path = urlparse(self.path).path
            if path == "/api/categories/reorder":
                payload = self._payload()
                parent_id = int(payload.get("parent_id") or 0)
                child_ids = payload.get("child_ids")
                if not parent_id or not isinstance(child_ids, list):
                    raise ApiError(HTTPStatus.BAD_REQUEST, "分类排序参数不完整")
                self._json(repository.reorder_categories(parent_id, child_ids))
                return
            super()._post()

    return EnhancedHandler


def create_enhanced_server(
    host: str, port: int, repository: ApplicationRepository, static_dir: Path
) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), build_enhanced_handler(repository, static_dir))
