from __future__ import annotations

import html as html_lib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple
from urllib.parse import urljoin

import requests

from .config import ProductTarget, USER_AGENT, product_url


LOG = logging.getLogger(__name__)
NEXT_DATA_RE = re.compile(
    r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', re.DOTALL
)


@dataclass
class PageResult:
    target_key: str
    url: str
    success: bool
    checked_at: str
    products: List[Dict[str, Any]] = field(default_factory=list)
    status_code: Optional[int] = None
    error: Optional[str] = None
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    not_modified: bool = False
    page_f_number: Optional[str] = None


class ScrapeError(RuntimeError):
    pass


def _walk(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def extract_next_data(page_html: str) -> Mapping[str, Any]:
    match = NEXT_DATA_RE.search(page_html)
    if not match:
        raise ScrapeError("页面缺少 __NEXT_DATA__ 公开数据")
    try:
        return json.loads(html_lib.unescape(match.group(1)))
    except (ValueError, TypeError) as exc:
        raise ScrapeError(f"__NEXT_DATA__ 解析失败: {exc}") from exc


def find_inventory_source(document: Mapping[str, Any], expected_model: str) -> Mapping[str, Any]:
    candidates: List[Mapping[str, Any]] = []
    for node in _walk(document):
        if isinstance(node.get("allVariants"), list):
            candidates.append(node)
    if not candidates:
        raise ScrapeError("页面没有 allVariants 商品库存列表")

    expected = expected_model.upper()
    exact = [c for c in candidates if str(c.get("fNumber", "")).upper() == expected]
    if exact:
        return max(exact, key=lambda x: len(x.get("allVariants", [])))
    # Product pages occasionally label RF640 as F640. Prefer a candidate whose
    # item attributes expose the expected model, then fall back to the largest.
    for candidate in candidates:
        for item in candidate.get("allVariants", []):
            variants = item.get("variants") or []
            attrs = variants[0].get("attributes", {}) if variants else {}
            if str(attrs.get("model", "")).upper() == expected:
                return candidate
    return max(candidates, key=lambda x: len(x.get("allVariants", [])))


COLOR_WORDS = {
    "schwarz": "黑色", "black": "黑色", "weiss": "白色", "weiß": "白色", "white": "白色",
    "rot": "红色", "red": "红色", "blau": "蓝色", "blue": "蓝色", "grün": "绿色",
    "green": "绿色", "gelb": "黄色", "yellow": "黄色", "orange": "橙色",
    "silber": "银色", "silver": "银色", "grau": "灰色", "grey": "灰色", "gray": "灰色",
    "braun": "棕色", "brown": "棕色", "violett": "紫色", "purple": "紫色",
    "pink": "粉色", "türkis": "青色", "turquoise": "青色", "beige": "米色",
}


def _clean_color(value: Any) -> str:
    if isinstance(value, Mapping):
        value = value.get("label") or value.get("key") or ""
    text = re.sub(r"^\d+\s+", "", str(value or "")).strip()
    lower = text.casefold()
    for needle, translated in COLOR_WORDS.items():
        if needle in lower:
            return translated
    return text or "未标注"


def _money(price: Mapping[str, Any]) -> Tuple[Optional[float], Optional[str]]:
    try:
        digits = int(price.get("fractionDigits", 2))
        amount = Decimal(int(price["centAmount"])) / (Decimal(10) ** digits)
        return float(amount), str(price.get("currencyCode") or "") or None
    except (KeyError, TypeError, ValueError, ArithmeticError):
        return None, None


def parse_products(page_html: str, target: ProductTarget, page_url: str) -> Tuple[List[Dict[str, Any]], str]:
    document = extract_next_data(page_html)
    source = find_inventory_source(document, target.model)
    found: Dict[str, Dict[str, Any]] = {}

    for item in source.get("allVariants", []):
        variants = item.get("variants") or []
        if not variants:
            continue
        variant = variants[0]
        attrs = variant.get("attributes") or {}
        if variant.get("isOnStock") is False or int(variant.get("availableQuantity", 1) or 0) <= 0:
            continue

        sku = str(variant.get("sku") or item.get("productId") or "").strip()
        barcode = str(attrs.get("barcode") or "").strip()
        if not sku or not barcode:
            LOG.warning("Skipping item without a stable SKU/barcode on %s", page_url)
            continue
        price, currency = _money(variant.get("price") or {})
        images = [str(x) for x in (variant.get("images") or []) if str(x).startswith("https://")]
        official_path = str(item.get("_url") or "")
        detail_url = urljoin(page_url, official_path) if official_path else f"{page_url}?v={barcode}"

        model = str(attrs.get("model") or target.model).upper()
        # Keep RF640 distinct even if the legacy internal model attribute is F640.
        if target.key == "RF640":
            model = "RF640"
        colors_raw = [attrs.get("ai-main-color-1"), attrs.get("ai-main-color-2"), attrs.get("char1")]
        colors: List[str] = []
        for raw in colors_raw:
            color = _clean_color(raw)
            if color != "未标注" and color not in colors:
                colors.append(color)
        if not colors:
            colors = [_clean_color(attrs.get("ranking"))]

        found[sku] = {
            "id": sku,
            "sku": sku,
            "official_item_number": barcode,
            "model": model,
            "family": target.family,
            "name": str(attrs.get("model-name") or item.get("name") or target.name),
            "full_name": str(attrs.get("model-full-name") or f"{model} {target.name}"),
            "source_key": target.key,
            "source_url": page_url,
            "url": detail_url,
            "images": images,
            "price": price,
            "currency": currency,
            "primary_color": colors[0],
            "secondary_colors": colors[1:],
            "official_attributes": {
                "design": _clean_color(attrs.get("char2")),
                "finish": _clean_color(attrs.get("char5")),
                "description": attrs.get("description"),
                "good_type": attrs.get("good-type"),
            },
        }

    return list(found.values()), str(source.get("fNumber") or target.model)


class FreitagScraper:
    def __init__(self, timeout: float = 30.0, retries: int = 3, backoff: float = 1.0):
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})

    def fetch(
        self,
        target: ProductTarget,
        checked_at: str,
        cache: Optional[Mapping[str, str]] = None,
    ) -> PageResult:
        url = product_url(target)
        headers: Dict[str, str] = {}
        if cache:
            if cache.get("etag"):
                headers["If-None-Match"] = str(cache["etag"])
            if cache.get("last_modified"):
                headers["If-Modified-Since"] = str(cache["last_modified"])

        last_error: Optional[str] = None
        for attempt in range(1, self.retries + 1):
            try:
                response = self.session.get(url, headers=headers, timeout=self.timeout, allow_redirects=True)
                etag = response.headers.get("ETag")
                modified = response.headers.get("Last-Modified")
                if response.status_code == 304:
                    return PageResult(target.key, url, True, checked_at, status_code=304,
                                      etag=etag, last_modified=modified, not_modified=True)
                if response.status_code == 404:
                    return PageResult(target.key, url, False, checked_at, status_code=404,
                                      error="官方商品页返回 404；仅记录源不可用，不视为售罄")
                if response.status_code in (429, 500, 502, 503, 504):
                    raise ScrapeError(f"HTTP {response.status_code}")
                response.raise_for_status()
                products, page_f_number = parse_products(response.text, target, response.url)
                return PageResult(target.key, response.url, True, checked_at, products=products,
                                  status_code=response.status_code, etag=etag,
                                  last_modified=modified, page_f_number=page_f_number)
            except (requests.RequestException, ScrapeError, ValueError) as exc:
                last_error = str(exc)
                if attempt < self.retries:
                    time.sleep(self.backoff * (2 ** (attempt - 1)))
        return PageResult(target.key, url, False, checked_at, error=last_error or "未知采集错误")

