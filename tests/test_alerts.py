import importlib
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ALERT_DIR = PROJECT_ROOT / "alert_service"


def load_alert_module():
    for name in ["main", "models", "schemas", "database", "telegram_bot"]:
        sys.modules.pop(name, None)
    sys.path.insert(0, str(ALERT_DIR))
    try:
        return importlib.import_module("main")
    finally:
        sys.path.remove(str(ALERT_DIR))


class FakeDb:
    def __init__(self, records):
        self.records = records

    def add(self, record):
        self.records.append(record)

    def commit(self):
        return None

    def close(self):
        return None


def test_alert_threshold_match_logs_history_and_sends_once_during_cooldown(monkeypatch):
    main = load_alert_module()
    main.RULES_CACHE = {
        "42": [
            {"id": 1, "metric_type": "cpu", "condition": "gt", "threshold": 90, "user_id": 7}
        ]
    }
    main.RECIPIENTS_CACHE = {7: "12345"}
    main.COOLDOWN_TRACKER = {}
    records = []
    sent = []

    monkeypatch.setattr(main.database, "SessionLocal", lambda: FakeDb(records))
    monkeypatch.setattr(main, "send_telegram_message", lambda chat_id, msg: sent.append((chat_id, msg)) or True)
    monkeypatch.setattr(main.time, "time", lambda: 1000)

    metric = {
        "agent_id": 42,
        "user_id": 7,
        "agent_name": "agent-a",
        "cpu": {"usage_percent": 95},
    }
    main.check_metrics(metric)
    main.check_metrics(metric)

    assert len(records) == 1
    assert records[0].metric_type == "cpu"
    assert records[0].value == 95
    assert len(sent) == 1


def test_alert_threshold_skips_rules_from_other_users(monkeypatch):
    main = load_alert_module()
    main.RULES_CACHE = {
        "42": [
            {"id": 1, "metric_type": "cpu", "condition": "gt", "threshold": 90, "user_id": 99}
        ]
    }
    main.RECIPIENTS_CACHE = {99: "12345"}
    main.COOLDOWN_TRACKER = {}
    records = []
    sent = []

    monkeypatch.setattr(main.database, "SessionLocal", lambda: FakeDb(records))
    monkeypatch.setattr(main, "send_telegram_message", lambda chat_id, msg: sent.append((chat_id, msg)) or True)

    main.check_metrics({
        "agent_id": 42,
        "user_id": 7,
        "agent_name": "agent-a",
        "cpu": {"usage_percent": 95},
    })

    assert records == []
    assert sent == []
