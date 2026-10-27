from pathlib import Path

from freitag_watch.config import TARGETS
from freitag_watch.scraper import parse_products


def test_parse_realistic_next_data_fixture():
    page = Path("tests/fixtures/f141.html").read_text(encoding="utf-8")
    target = next(item for item in TARGETS if item.key == "F141")
    products, f_number = parse_products(page, target, "https://freitag.ch/en_US/products/f141-beryl")
    assert f_number == "F141"
    assert len(products) == 1
    item = products[0]
    assert item["id"] == "F141_000004312345"
    assert item["official_item_number"] == "000004312345"
    assert item["price"] == 240.0
    assert item["currency"] == "USD"
    assert item["primary_color"] == "蓝色"
    assert item["url"].endswith("?v=000004312345")

