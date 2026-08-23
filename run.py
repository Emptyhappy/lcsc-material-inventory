from __future__ import annotations

import argparse
import threading
import time
import webbrowser
from pathlib import Path

from material_system.enhanced_http_server import create_enhanced_server
from material_system.application_repository import ApplicationRepository
from material_system.taxonomy import fetch_lcsc_categories
from material_system.startup_tasks import cache_existing_images


ROOT = Path(__file__).resolve().parent


def sync_categories_once(repository: ApplicationRepository) -> None:
    try:
        settings = repository.get_settings()
        if not settings.get("last_category_sync"):
            print("正在同步立创商城分类……")
            result = repository.sync_categories(fetch_lcsc_categories())
            print(f"分类同步完成：{result['categories']} 个分类")
    except Exception as exc:
        print(f"分类自动同步暂未完成：{exc}。可进入系统后手动重试。")


def main() -> None:
    parser = argparse.ArgumentParser(description="本地物料管理系统")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--data-dir", default=str(ROOT / "data"))
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    repository = ApplicationRepository(data_dir / "materials.db")
    server = create_enhanced_server(args.host, args.port, repository, ROOT / "web")
    url = f"http://{args.host}:{args.port}"
    print(f"物料管理系统已启动：{url}")
    print(f"数据库：{repository.path}")
    print("按 Ctrl+C 停止服务。")

    threading.Thread(target=sync_categories_once, args=(repository,), daemon=True).start()
    threading.Thread(target=cache_existing_images, args=(repository,), daemon=True).start()
    if not args.no_browser:
        threading.Thread(target=lambda: (time.sleep(0.6), webbrowser.open(url)), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在停止……")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
