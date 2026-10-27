from copy import deepcopy

from freitag_watch.scraper import PageResult
from freitag_watch.storage import empty_state, merge_page_result


NOW = "2026-10-27T10:00:00+00:00"


def product(identifier="F141_1"):
    return {"id": identifier, "sku": identifier, "official_item_number": identifier.split("_")[-1],
            "model": "F141", "family": "F141", "name": "BERYL", "full_name": "F141 BERYL",
            "source_key": "F141", "source_url": "https://example.invalid", "url": "https://example.invalid/p",
            "images": [], "price": 1.0, "currency": "CHF", "primary_color": "蓝色", "secondary_colors": []}


def result(items, at=NOW, success=True):
    return PageResult("F141", "https://example.invalid", success, at, products=items,
                      status_code=200 if success else 500, error=None if success else "network")


def test_first_run_is_baseline_and_second_run_deduplicates():
    state = empty_state()
    assert merge_page_result(state, result([product()])) == []
    assert state["events"] == []
    assert merge_page_result(state, result([product()], "2026-10-27T11:00:00+00:00")) == []


def test_new_item_missing_confirmation_and_relist_event():
    state = empty_state()
    merge_page_result(state, result([product("F141_A")]))
    created = merge_page_result(state, result([product("F141_A"), product("F141_B")], "2026-10-27T11:00:00+00:00"))
    assert len(created) == 1 and state["events"][0]["type"] == "new"
    merge_page_result(state, result([product("F141_A")], "2026-10-27T12:00:00+00:00"))
    assert state["products"]["F141_B"]["status"] == "possibly_sold"
    merge_page_result(state, result([product("F141_A")], "2026-10-27T13:00:00+00:00"))
    assert state["products"]["F141_B"]["status"] == "sold"
    relist = merge_page_result(state, result([product("F141_A"), product("F141_B")], "2026-10-27T14:00:00+00:00"))
    assert len(relist) == 1 and state["events"][-1]["type"] == "relisted"


def test_failure_does_not_change_inventory_status():
    state = empty_state()
    merge_page_result(state, result([product()]))
    before = deepcopy(state["products"])
    merge_page_result(state, result([], success=False))
    assert state["products"] == before


def test_large_count_drop_is_quarantined_once():
    state = empty_state()
    items = [product(f"F141_{i}") for i in range(8)]
    merge_page_result(state, result(items))
    merge_page_result(state, result([items[0]], "2026-10-27T11:00:00+00:00"))
    assert all(p["status"] == "available" for p in state["products"].values())
    merge_page_result(state, result([items[0]], "2026-10-27T12:00:00+00:00"))
    assert state["products"]["F141_1"]["status"] == "possibly_sold"

