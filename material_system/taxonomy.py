from __future__ import annotations

import json
import urllib.request
from html.parser import HTMLParser
from typing import Any


LCSC_CATALOG_URL = "https://www.szlcsc.com/catalog.html"


class _NextDataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._inside = False
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script" and dict(attrs).get("id") == "__NEXT_DATA__":
            self._inside = True

    def handle_data(self, data: str) -> None:
        if self._inside:
            self.parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._inside:
            self._inside = False


def parse_lcsc_categories(html: str) -> list[dict[str, Any]]:
    parser = _NextDataParser()
    parser.feed(html)
    if not parser.parts:
        raise ValueError("立创分类页中没有找到结构化分类数据")

    data = json.loads("".join(parser.parts))
    page_props = data["props"]["pageProps"]
    roots = page_props["catalogListData"]
    result: list[dict[str, Any]] = [
        {
            "external_id": "1",
            "parent_external_id": None,
            "name": "电子元器件",
            "code": "root",
            "sort_order": 0,
            "source_count": page_props.get("catalogCount", 0),
            "url": LCSC_CATALOG_URL,
        }
    ]

    def visit(node: dict[str, Any], default_parent: str) -> None:
        external_id = str(node["catalogId"])
        parent_id = str(node.get("parentId") or default_parent)
        result.append(
            {
                "external_id": external_id,
                "parent_external_id": parent_id,
                "name": node["catalogName"],
                "code": node.get("catalogCode") or "",
                "sort_order": int(node.get("sort") or 0),
                "source_count": int(node.get("groupProductCount") or 0),
                "url": f"https://list.szlcsc.com/catalog/{external_id}.html",
            }
        )
        for child in node.get("sonCatalogList") or []:
            visit(child, external_id)

    for root in roots:
        visit(root, "1")
    return result


def fetch_lcsc_categories(timeout: int = 20) -> list[dict[str, Any]]:
    request = urllib.request.Request(
        LCSC_CATALOG_URL,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/124 Safari/537.36"
            )
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        html = response.read().decode("utf-8", errors="replace")
    return parse_lcsc_categories(html)
