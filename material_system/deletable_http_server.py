from __future__ import annotations

import re
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .deletable_repository import DeletableInventoryRepository
from .managed_http_server import build_managed_handler


def build_deletable_handler(repository: DeletableInventoryRepository, static_dir: Path):
    base_handler = build_managed_handler(repository, static_dir)

    class DeletableHandler(base_handler):
        def _post(self) -> None:
            path = urlparse(self.path).path
            if match := re.fullmatch(r"/api/transactions/(\d+)/delete", path):
                self._payload()
                self._json(repository.delete_transaction(int(match.group(1))))
                return
            if match := re.fullmatch(
                r"/api/materials/(\d+)/transactions/delete-all", path
            ):
                self._payload()
                self._json(repository.delete_transactions(int(match.group(1))))
                return
            if path == "/api/transactions/delete-all":
                self._payload()
                self._json(repository.delete_transactions())
                return
            super()._post()

    return DeletableHandler


def create_deletable_server(
    host: str,
    port: int,
    repository: DeletableInventoryRepository,
    static_dir: Path,
) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(
        (host, port), build_deletable_handler(repository, static_dir)
    )
