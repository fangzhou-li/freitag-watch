from pathlib import Path


def test_schedule_concurrency_and_manual_dispatch_present():
    text = Path(".github/workflows/monitor.yml").read_text(encoding="utf-8")
    assert 'cron: "17 * * * *"' in text
    assert "push:" in text and "- main" in text
    assert "workflow_dispatch:" in text
    assert "cancel-in-progress: false" in text
    assert "actions/deploy-pages" in text
    assert "data/state.remote.json" in text
    assert "mv data/state.remote.json data/state.json" in text
