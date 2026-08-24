from __future__ import annotations

from http import HTTPStatus
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .backup_repository import BackupInventoryRepository, MAX_BACKUP_BYTES
from .deletable_http_server import build_deletable_handler
from .http_server import ApiError


def build_backup_handler(repository: BackupInventoryRepository, static_dir: Path):
    base_handler = build_deletable_handler(repository, static_dir)

    class BackupHandler(base_handler):
        def _get(self) -> None:
            if urlparse(self.path).path == "/api/backup/export":
                data, filename, _ = repository.export_full_backup()
                self._bytes(data, "application/zip", filename)
                return
            super()._get()

        def _post(self) -> None:
            if urlparse(self.path).path == "/api/backup/restore":
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError as exc:
                    raise ApiError(HTTPStatus.BAD_REQUEST, "请求长度无效") from exc
                if length <= 0:
                    raise ApiError(HTTPStatus.BAD_REQUEST, "请选择完整备份 ZIP 文件")
                if length > MAX_BACKUP_BYTES:
                    raise ApiError(
                        HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                        "备份文件超过 256MB 限制",
                    )
                self._json(repository.restore_full_backup(self.rfile.read(length)))
                return
            super()._post()

    return BackupHandler


def create_backup_server(
    host: str,
    port: int,
    repository: BackupInventoryRepository,
    static_dir: Path,
) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), build_backup_handler(repository, static_dir))
