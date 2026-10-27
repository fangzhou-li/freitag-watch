from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

from .analyzer import analyze_product
from .config import STATE_PATH, TARGETS
from .policy import verify_access_policy
from .scraper import FreitagScraper
from .storage import get_event, load_state, merge_page_result, save_state


LOG = logging.getLogger(__name__)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def collect() -> Dict[str, Any]:
    state = load_state(STATE_PATH)
    started = utc_now()
    state["last_attempt_at"] = started
    timeout = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "30"))
    try:
        state["policy_check"] = {"checked_at": started, "result": verify_access_policy(timeout=min(timeout, 20.0)), "ok": True}
    except Exception as exc:
        state["policy_check"] = {"checked_at": started, "result": str(exc), "ok": False}
        state["last_error"] = f"访问规则检查失败，已停止采集：{exc}"
        save_state(STATE_PATH, state)
        raise
    delay = float(os.getenv("REQUEST_DELAY_SECONDS", "1.5"))
    scraper = FreitagScraper(timeout=timeout)
    successes = 0
    required_successes = 0
    failures: List[str] = []
    warnings: List[str] = []
    new_event_ids: List[str] = []

    for index, target in enumerate(TARGETS):
        model_state = state.get("models", {}).get(target.key, {})
        cache = {key: model_state.get(key) for key in ("etag", "last_modified") if model_state.get(key)}
        checked_at = utc_now()
        result = scraper.fetch(target, checked_at, cache=cache)
        if result.success:
            successes += 1
            if not target.legacy:
                required_successes += 1
            LOG.info("%s: %s items%s", target.key, len(result.products), " (304)" if result.not_modified else "")
        else:
            message = f"{target.key}: {result.error}"
            if target.legacy and result.status_code == 404:
                warnings.append(message)
                LOG.warning("%s", message)
            else:
                failures.append(message)
                LOG.error("%s", message)
        created = merge_page_result(state, result)
        new_event_ids.extend(created)
        save_state(STATE_PATH, state)
        if index < len(TARGETS) - 1:
            time.sleep(max(0.0, delay))

    # Analyze only genuinely new or relisted events, never the first-run baseline.
    historical_hashes = [
        p.get("pattern", {}).get("perceptual_hash")
        for p in state.get("products", {}).values()
        if isinstance(p.get("pattern"), dict) and p.get("pattern", {}).get("perceptual_hash")
    ]
    for event_id in new_event_ids:
        event = get_event(state, event_id)
        if not event:
            continue
        product = state["products"].get(event["product_id"])
        if not product:
            continue
        product["pattern"] = analyze_product(product, historical_hashes)
        current_hash = product.get("pattern", {}).get("perceptual_hash")
        if current_hash:
            historical_hashes.append(current_hash)
        save_state(STATE_PATH, state)

    finished = utc_now()
    if successes:
        state["last_success_at"] = finished
    required_total = sum(1 for target in TARGETS if not target.legacy)
    if required_successes == required_total:
        state["last_full_success_at"] = finished
    state["last_error"] = "；".join(failures) if failures else None
    run = {
        "started_at": started, "finished_at": finished,
        "status": "success" if not failures else ("partial" if successes else "failed"),
        "successful_sources": successes, "failed_sources": len(failures),
        "new_events": len(new_event_ids), "errors": failures, "warnings": warnings,
    }
    state.setdefault("runs", []).append(run)
    state["runs"] = state["runs"][-100:]
    save_state(STATE_PATH, state)
    return run
