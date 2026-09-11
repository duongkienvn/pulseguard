import importlib
import sys
from pathlib import Path

from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INGESTION_DIR = PROJECT_ROOT / "ingestion_service"


def load_ingestion_app(monkeypatch):
    for name in ["main"]:
        sys.modules.pop(name, None)
    sys.path.insert(0, str(INGESTION_DIR))
    try:
        main = importlib.import_module("main")
    finally:
        sys.path.remove(str(INGESTION_DIR))
    return main, TestClient(main.app)


class FakeProducer:
    def __init__(self):
        self.messages = []

    async def send_and_wait(self, topic, key, value):
        self.messages.append({"topic": topic, "key": key, "value": value})


def test_ingest_rejects_invalid_agent_token(monkeypatch):
    main, client = load_ingestion_app(monkeypatch)

    async def invalid_token(_token):
        return {"valid": False}

    monkeypatch.setattr(main, "validate_agent_token", invalid_token)

    response = client.post(
        "/ingest",
        json={"timestamp": 123},
        headers={"X-Agent-Token": "bad-token"},
    )

    assert response.status_code == 401


def test_ingest_accepts_valid_payload_and_publishes_to_kafka(monkeypatch):
    main, client = load_ingestion_app(monkeypatch)
    producer = FakeProducer()
    main.kafka_producer = producer

    async def valid_token(_token):
        return {"valid": True, "agent_id": 42, "agent_name": "agent-a", "user_id": 7}

    monkeypatch.setattr(main, "validate_agent_token", valid_token)

    response = client.post(
        "/ingest",
        json={"timestamp": 123, "cpu": {"usage_percent": 50}},
        headers={"X-Agent-Token": "good-token"},
    )

    assert response.status_code == 200
    assert producer.messages == [
        {
            "topic": "metrics",
            "key": "42",
            "value": {
                "timestamp": 123,
                "cpu": {"usage_percent": 50},
                "agent_id": 42,
                "agent_name": "agent-a",
                "user_id": 7,
            },
        }
    ]
