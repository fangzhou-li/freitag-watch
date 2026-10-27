from __future__ import annotations

import json
import os
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from .scraper import PageResult


SCHEMA_VERSION = 1


def empty_state() -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "initialized_at": None,
        "last_attempt_at": None,
        "last_success_at": None,
        "last_full_success_at": None,
        "last_error": None,
        "products": {},
        "events": [],
        "models": {},
        "runs": [],
    }


def load_state(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return empty_state()
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    base = empty_state()
    base.update(data)
    if base.get("schema_version") != SCHEMA_VERSION:
        raise RuntimeError(f"不支持的数据版本: {base.get('schema_version')}")
    return base


def save_state(path: Path, state: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="state-", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _event_id(product_id: str, event_type: str, listing_number: int) -> str:
    return f"{product_id}:{event_type}:{listing_number}"


def _new_event(product: Mapping[str, Any], event_type: str, now: str, listing_number: int) -> Dict[str, Any]:
    return {
        "id": _event_id(str(product["id"]), event_type, listing_number),
        "product_id": product["id"],
        "type": event_type,
        "detected_at": now,
        "source_key": product["source_key"],
        "bark": {"status": "pending", "attempts": 0},
        "email": {"status": "pending", "attempts": 0},
    }


def _is_count_anomaly(model_state: Dict[str, Any], current_count: int) -> bool:
    previous = int(model_state.get("last_valid_count") or 0)
    if previous < 5 or current_count >= max(1, int(previous * 0.25)):
        model_state.pop("anomaly_signature", None)
        model_state["anomaly_streak"] = 0
        return False
    signature = f"{previous}->{current_count}"
    if model_state.get("anomaly_signature") == signature:
        model_state["anomaly_streak"] = int(model_state.get("anomaly_streak") or 0) + 1
    else:
        model_state["anomaly_signature"] = signature
        model_state["anomaly_streak"] = 1
    # The same drastic count on two valid HTTP responses is accepted as a real
    # inventory change. The first occurrence is quarantined.
    return model_state["anomaly_streak"] < 2


def merge_page_result(state: Dict[str, Any], result: PageResult) -> List[str]:
    """Merge one independent source. Returns newly created event IDs."""
    model_state = state["models"].setdefault(result.target_key, {
        "initialized": False,
        "last_valid_count": 0,
        "consecutive_failures": 0,
    })
    model_state["last_checked_at"] = result.checked_at
    model_state["source_url"] = result.url
    if result.etag:
        model_state["etag"] = result.etag
    if result.last_modified:
        model_state["last_modified"] = result.last_modified

    if not result.success:
        model_state["consecutive_failures"] = int(model_state.get("consecutive_failures") or 0) + 1
        model_state["last_error"] = result.error
        model_state["last_status_code"] = result.status_code
        return []

    if result.not_modified:
        model_state["last_success_at"] = result.checked_at
        model_state["consecutive_failures"] = 0
        model_state["last_error"] = None
        for product in state["products"].values():
            if product.get("source_key") == result.target_key and product.get("status") == "available":
                product["last_seen_at"] = result.checked_at
        return []

    current_count = len(result.products)
    if model_state.get("initialized") and _is_count_anomaly(model_state, current_count):
        model_state["consecutive_failures"] = int(model_state.get("consecutive_failures") or 0) + 1
        model_state["last_error"] = (
            f"数量异常：上次 {model_state.get('last_valid_count')} 件，本次 {current_count} 件；"
            "等待下一次有效检查确认"
        )
        return []

    was_initialized = bool(model_state.get("initialized"))
    current_ids = {str(p["id"]) for p in result.products}
    created_events: List[str] = []

    for incoming in result.products:
        product_id = str(incoming["id"])
        existing = state["products"].get(product_id)
        if existing is None:
            record = deepcopy(incoming)
            record.update({
                "first_seen_at": result.checked_at,
                "last_seen_at": result.checked_at,
                "status": "available",
                "previous_status": None,
                "missing_checks": 0,
                "listing_count": 1,
                "is_relisted": False,
                "pattern": None,
                "status_history": [{"status": "available", "at": result.checked_at, "reason": "baseline" if not was_initialized else "new"}],
            })
            state["products"][product_id] = record
            if was_initialized:
                event = _new_event(record, "new", result.checked_at, 1)
                state["events"].append(event)
                created_events.append(event["id"])
            continue

        previous_status = existing.get("status")
        preserved = {"first_seen_at", "pattern", "status_history", "listing_count"}
        for key, value in incoming.items():
            if key not in preserved:
                existing[key] = deepcopy(value)
        existing["last_seen_at"] = result.checked_at
        existing["previous_status"] = previous_status
        existing["missing_checks"] = 0
        existing["is_relisted"] = previous_status == "sold"
        existing["status"] = "available"
        if previous_status == "sold":
            existing["listing_count"] = int(existing.get("listing_count") or 1) + 1
            existing.setdefault("status_history", []).append({"status": "available", "at": result.checked_at, "reason": "relisted"})
            event = _new_event(existing, "relisted", result.checked_at, existing["listing_count"])
            state["events"].append(event)
            created_events.append(event["id"])
        elif previous_status == "possibly_sold":
            existing.setdefault("status_history", []).append({"status": "available", "at": result.checked_at, "reason": "returned_before_confirmation"})

    # Missing inventory is only evaluated after a successful, non-anomalous
    # source check. Two consecutive checks are required for confirmed sell-out.
    for product in state["products"].values():
        if product.get("source_key") != result.target_key or product.get("id") in current_ids:
            continue
        if product.get("status") == "sold":
            continue
        product["previous_status"] = product.get("status")
        product["missing_checks"] = int(product.get("missing_checks") or 0) + 1
        next_status = "sold" if product["missing_checks"] >= 2 else "possibly_sold"
        if product.get("status") != next_status:
            product["status"] = next_status
            product.setdefault("status_history", []).append({
                "status": next_status,
                "at": result.checked_at,
                "reason": "two_valid_checks" if next_status == "sold" else "first_missing_check",
            })

    model_state.update({
        "initialized": True,
        "last_success_at": result.checked_at,
        "last_valid_count": current_count,
        "last_page_f_number": result.page_f_number,
        "last_status_code": result.status_code,
        "consecutive_failures": 0,
        "last_error": None,
        "anomaly_streak": 0,
    })
    if not state.get("initialized_at"):
        state["initialized_at"] = result.checked_at
    return created_events


def get_event(state: Mapping[str, Any], event_id: str) -> Optional[Dict[str, Any]]:
    for event in state.get("events", []):
        if event.get("id") == event_id:
            return event  # type: ignore[return-value]
    return None

