from __future__ import annotations

from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .advanced_inventory_http_server import build_advanced_inventory_handler
from .configurable_inventory_repository import ConfigurableInventoryRepository
from .taxonomy import fetch_lcsc_categories


def build_configurable_inventory_handler(
    repository: ConfigurableInventoryRepository, static_dir: Path
):
    base_handler = build_advanced_inventory_handler(repository, static_dir)

    class ConfigurableInventoryHandler(base_handler):
        def _post(self) -> None:
            path = urlparse(self.path).path
            if path == "/api/backup/save":
                self._payload()
                self._json(repository.save_normal_backup())
                return
            if path == "/api/categories/order/restore-lcsc":
                self._payload()
                self._json(repository.restore_lcsc_category_order(
                    fetch_lcsc_categories()
                ))
                return
            super()._post()

    return ConfigurableInventoryHandler


def create_configurable_inventory_server(
    host: str,
    port: int,
    repository: ConfigurableInventoryRepository,
    static_dir: Path,
) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(
        (host, port), build_configurable_inventory_handler(repository, static_dir)
    )
