from freitag_watch.notifiers import deliver_bark, prepare_notifications
from freitag_watch.storage import empty_state


def sample_state():
    state = empty_state()
    state["products"]["F141_X"] = {
        "id": "F141_X", "model": "F141", "full_name": "F141 BERYL",
        "official_item_number": "X", "primary_color": "蓝色", "url": "https://example.invalid/x",
        "images": ["https://example.invalid/x.png"], "pattern": {"level": "普通", "worth_email": False},
    }
    state["events"].append({
        "id": "F141_X:new:1", "product_id": "F141_X", "source_key": "F141", "type": "new",
        "detected_at": "2026-10-27T00:00:00+00:00",
        "bark": {"status": "pending", "attempts": 0}, "email": {"status": "pending", "attempts": 0},
    })
    return state


def test_bark_transaction_is_prepared_then_sent(monkeypatch):
    state = sample_state()
    monkeypatch.setenv("BARK_KEY", "TEST_ONLY")
    assert prepare_notifications(state, "2026-10-27T01:00:00+00:00") == 1
    assert state["events"][0]["bark"]["status"] == "sending"
    delivered = []
    monkeypatch.setattr("freitag_watch.notifiers._send_bark", lambda payload: delivered.append(payload))
    assert deliver_bark(state, "2026-10-27T01:01:00+00:00") == 1
    assert state["events"][0]["bark"]["status"] == "sent"
    assert delivered[0]["url"] == "https://example.invalid/x"


def test_bark_failure_is_retryable_but_bounded(monkeypatch):
    state = sample_state()
    monkeypatch.setenv("BARK_KEY", "TEST_ONLY")
    monkeypatch.setattr("freitag_watch.notifiers._send_bark", lambda payload: (_ for _ in ()).throw(RuntimeError("test failure")))
    for attempt in range(3):
        prepare_notifications(state, f"2026-10-27T0{attempt}:00:00+00:00")
        deliver_bark(state, f"2026-10-27T0{attempt}:01:00+00:00")
    event = state["events"][0]
    assert event["bark"]["status"] == "failed"
    assert event["bark"]["attempts"] == 3
    assert prepare_notifications(state, "2026-10-28T00:00:00+00:00") == 0


def test_email_is_prepared_only_for_reference_match(monkeypatch):
    state = sample_state()
    monkeypatch.setenv("EMAIL_ENABLED", "true")
    monkeypatch.setenv("SMTP_USERNAME", "sender@example.invalid")
    monkeypatch.setenv("SMTP_PASSWORD", "APP_PASSWORD")
    monkeypatch.setenv("EMAIL_TO", "recipient@example.invalid")

    assert prepare_notifications(state, "2026-10-27T01:00:00+00:00") == 0
    assert state["events"][0]["email"]["status"] == "pending"

    state["products"]["F141_X"]["pattern"] = {
        "level": "疑似稀有",
        "worth_email": True,
        "reference_match": {"matched": True},
    }
    assert prepare_notifications(state, "2026-10-27T01:01:00+00:00") == 1
    assert state["events"][0]["email"]["status"] == "sending"


def test_incomplete_email_configuration_does_not_consume_attempt(monkeypatch):
    state = sample_state()
    state["products"]["F141_X"]["pattern"] = {"worth_email": True}
    monkeypatch.setenv("EMAIL_ENABLED", "true")
    monkeypatch.setenv("SMTP_PASSWORD", "APP_PASSWORD")

    assert prepare_notifications(state, "2026-10-27T01:00:00+00:00") == 0
    assert state["events"][0]["email"]["status"] == "pending"
    assert state["events"][0]["email"]["attempts"] == 0
