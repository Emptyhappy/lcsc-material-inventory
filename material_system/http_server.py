from __future__ import annotations

import json
import mimetypes
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlparse

from .repository import InventoryRepository
from .taxonomy import fetch_lcsc_categories


class ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def build_handler(
    repository: InventoryRepository, static_dir: Path
) -> type[BaseHTTPRequestHandler]:
    class InventoryHandler(BaseHTTPRequestHandler):
        server_version = "MaterialInventory/0.5.0"

        def log_message(self, fmt: str, *args: Any) -> None:
            print(f"[{self.log_date_time_string()}] {fmt % args}")

        def _cors(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Inventory-Token")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
            self.send_header("Access-Control-Allow-Private-Network", "true")

        def _json(self, payload: Any, status: int = HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self._cors()
            self.end_headers()
            self.wfile.write(body)

        def _bytes(self, body: bytes, content_type: str, filename: str | None = None) -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            if filename:
                self.send_header("Content-Disposition", f"attachment; filename={filename}")
            self.end_headers()
            self.wfile.write(body)

        def _payload(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 2_000_000:
                raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "请求数据过大")
            if length == 0:
                return {}
            try:
                value = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ApiError(HTTPStatus.BAD_REQUEST, "JSON格式错误") from exc
            if not isinstance(value, dict):
                raise ApiError(HTTPStatus.BAD_REQUEST, "请求内容必须是JSON对象")
            return value

        def _require_extension_token(self) -> None:
            expected = repository.get_settings()["extension_token"]
            supplied = self.headers.get("X-Inventory-Token", "")
            if not supplied or supplied != expected:
                raise ApiError(HTTPStatus.UNAUTHORIZED, "扩展连接密钥错误，请在扩展设置中重新配置")

        def _handle(self, callback: Callable[[], None]) -> None:
            try:
                callback()
            except ApiError as exc:
                self._json({"error": exc.message}, exc.status)
            except KeyError as exc:
                self._json({"error": str(exc).strip("'\"")}, HTTPStatus.NOT_FOUND)
            except (ValueError, TypeError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            except Exception as exc:
                print(f"API error: {exc!r}")
                self._json({"error": "服务器处理失败，请查看启动窗口日志"}, HTTPStatus.INTERNAL_SERVER_ERROR)

        def do_OPTIONS(self) -> None:
            self.send_response(HTTPStatus.NO_CONTENT)
            self._cors()
            self.end_headers()

        def do_GET(self) -> None:
            self._handle(self._get)

        def do_POST(self) -> None:
            self._handle(self._post)

        def do_PUT(self) -> None:
            self._handle(self._put)

        def _get(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)
            if path == "/api/health":
                self._json({"ok": True, "service": "material-inventory"})
            elif path == "/api/dashboard":
                self._json(repository.dashboard())
            elif path == "/api/settings":
                self._json(repository.get_settings())
            elif path == "/api/locations":
                self._json(repository.list_locations())
            elif path == "/api/categories":
                self._json(repository.categories())
            elif path == "/api/materials":
                category_id = int(query["category_id"][0]) if query.get("category_id") else None
                self._json(repository.list_materials(
                    q=query.get("q", [""])[0],
                    category_id=category_id,
                    low_stock=query.get("low_stock", ["0"])[0] == "1",
                ))
            elif match := re.fullmatch(r"/api/materials/(\d+)", path):
                self._json(repository.material_detail(int(match.group(1))))
            elif path == "/api/transactions":
                self._json(repository.recent_transactions(int(query.get("limit", ["50"])[0])))
            elif path == "/api/export.csv":
                self._bytes(
                    repository.export_csv(), "text/csv; charset=utf-8", "materials.csv"
                )
            elif path == "/api/extension/status":
                self._require_extension_token()
                settings = repository.get_settings()
                self._json({
                    "ok": True,
                    "default_quantity": settings["default_quantity"],
                    "default_location_name": settings["default_location_name"],
                })
            elif path.startswith("/api/"):
                raise ApiError(HTTPStatus.NOT_FOUND, "接口不存在")
            else:
                self._static(path)

        def _post(self) -> None:
            path = urlparse(self.path).path
            payload = self._payload()
            if path == "/api/materials/manual":
                self._json(repository.add_manual_material(payload), HTTPStatus.CREATED)
            elif path == "/api/import/lcsc":
                self._require_extension_token()
                self._json(repository.import_lcsc(payload), HTTPStatus.CREATED)
            elif path == "/api/locations":
                self._json(repository.add_location(str(payload.get("name") or "")), HTTPStatus.CREATED)
            elif path == "/api/categories/custom":
                self._json(repository.add_custom_category(
                    str(payload.get("name") or ""),
                    int(payload["parent_id"]) if payload.get("parent_id") else None,
                ), HTTPStatus.CREATED)
            elif path == "/api/categories/sync":
                items = fetch_lcsc_categories()
                self._json(repository.sync_categories(items))
            elif match := re.fullmatch(r"/api/materials/(\d+)/stock", path):
                self._json(repository.stock_operation(int(match.group(1)), payload), HTTPStatus.CREATED)
            elif match := re.fullmatch(r"/api/transactions/(\d+)/undo", path):
                self._json(repository.undo_transaction(int(match.group(1))), HTTPStatus.CREATED)
            else:
                raise ApiError(HTTPStatus.NOT_FOUND, "接口不存在")

        def _put(self) -> None:
            path = urlparse(self.path).path
            payload = self._payload()
            if path == "/api/settings":
                self._json(repository.update_settings(payload))
            elif match := re.fullmatch(r"/api/materials/(\d+)", path):
                self._json(repository.update_material(int(match.group(1)), payload))
            else:
                raise ApiError(HTTPStatus.NOT_FOUND, "接口不存在")

        def _static(self, request_path: str) -> None:
            relative = unquote(request_path).lstrip("/") or "index.html"
            candidate = (static_dir / relative).resolve()
            if static_dir.resolve() not in candidate.parents and candidate != static_dir.resolve():
                raise ApiError(HTTPStatus.FORBIDDEN, "无权访问该文件")
            if not candidate.is_file():
                candidate = static_dir / "index.html"
            body = candidate.read_bytes()
            content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
            if content_type.startswith("text/") or candidate.suffix in {".js", ".json"}:
                content_type += "; charset=utf-8"
            self._bytes(body, content_type)

    return InventoryHandler


def create_server(
    host: str, port: int, repository: InventoryRepository, static_dir: Path
) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), build_handler(repository, static_dir))
