from __future__ import annotations

import re
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .enhanced_http_server import build_enhanced_handler
from .http_server import ApiError
from .managed_repository import ManagedInventoryRepository


def build_managed_handler(repository: ManagedInventoryRepository, static_dir: Path):
    base_handler = build_enhanced_handler(repository, static_dir)

    class ManagedHandler(base_handler):
        def _get(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)
            if path == "/api/changes":
                self._json(repository.change_state())
                return
            if path == "/api/transactions":
                material_id = (
                    int(query["material_id"][0]) if query.get("material_id") else None
                )
                self._json(repository.list_transactions(
                    limit=int(query.get("limit", ["200"])[0]),
                    material_id=material_id,
                    include_archived=query.get("include_archived", ["0"])[0] == "1",
                ))
                return
            super()._get()

        def _post(self) -> None:
            path = urlparse(self.path).path
            if match := re.fullmatch(r"/api/materials/(\d+)/transactions/clear", path):
                self._payload()
                self._json(repository.archive_transactions(int(match.group(1))))
                return
            if path == "/api/transactions/clear":
                self._payload()
                self._json(repository.archive_transactions())
                return
            super()._post()

        def _put(self) -> None:
            path = urlparse(self.path).path
            if match := re.fullmatch(r"/api/transactions/(\d+)", path):
                self._json(repository.update_transaction(
                    int(match.group(1)), self._payload()
                ))
                return
            super()._put()

    return ManagedHandler


def create_managed_server(
    host: str,
    port: int,
    repository: ManagedInventoryRepository,
    static_dir: Path,
) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(
        (host, port), build_managed_handler(repository, static_dir)
    )
