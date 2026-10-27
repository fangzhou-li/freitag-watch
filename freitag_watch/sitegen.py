from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path
from typing import Any, Dict, Mapping

from .config import PUBLIC_DIR, SITE_SOURCE_DIR


def _public_product(product: Mapping[str, Any]) -> Dict[str, Any]:
    allowed = (
        "id", "sku", "official_item_number", "model", "family", "name", "full_name",
        "source_key", "source_url", "url", "images", "price", "currency", "primary_color",
        "secondary_colors", "official_attributes", "first_seen_at", "last_seen_at", "status",
        "previous_status", "missing_checks", "listing_count", "is_relisted", "pattern", "status_history",
    )
    return {key: product.get(key) for key in allowed}


def build_public_site(state: Mapping[str, Any], output_dir: Path = PUBLIC_DIR) -> None:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    shutil.copytree(SITE_SOURCE_DIR, output_dir)
    data_dir = output_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    products = [_public_product(value) for value in state.get("products", {}).values()]
    products.sort(key=lambda item: item.get("first_seen_at") or "", reverse=True)
    events = [{
        "id": event.get("id"), "product_id": event.get("product_id"), "type": event.get("type"),
        "detected_at": event.get("detected_at"), "source_key": event.get("source_key"),
    } for event in state.get("events", [])]
    models = state.get("models", {})
    status = {
        "last_attempt_at": state.get("last_attempt_at"),
        "last_success_at": state.get("last_success_at"),
        "last_full_success_at": state.get("last_full_success_at"),
        "last_error": state.get("last_error"),
        "initialized_at": state.get("initialized_at"),
        "models": models,
        "counts": {
            "total": len(products),
            "available": sum(1 for p in products if p.get("status") == "available"),
            "possibly_sold": sum(1 for p in products if p.get("status") == "possibly_sold"),
            "sold": sum(1 for p in products if p.get("status") == "sold"),
        },
        "disclosure": "公开：商品编号、官方图片链接、价格、颜色、库存历史与图案判断。不会公开 Bark 密钥、邮箱、SMTP 密码或其他 Secrets。",
    }
    for filename, payload in (("inventory.json", products), ("events.json", events), ("status.json", status)):
        with (data_dir / filename).open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")

    columns = [
        "id", "official_item_number", "model", "full_name", "url", "price", "currency",
        "primary_color", "first_seen_at", "last_seen_at", "status", "listing_count",
        "pattern_level", "pattern_score", "pattern_categories", "pattern_reason",
    ]
    with (data_dir / "inventory.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for product in products:
            pattern = product.get("pattern") or {}
            writer.writerow({
                **{key: product.get(key) for key in columns if not key.startswith("pattern_")},
                "pattern_level": pattern.get("level"), "pattern_score": pattern.get("score"),
                "pattern_categories": " | ".join(pattern.get("categories") or []),
                "pattern_reason": pattern.get("reason"),
            })

