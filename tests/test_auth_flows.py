import importlib
import sys
from pathlib import Path

from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
AUTH_DIR = PROJECT_ROOT / "auth_service"


def load_auth_app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'auth.db'}")
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/15")

    for name in ["main", "models", "schemas", "database", "auth"]:
        sys.modules.pop(name, None)
    sys.path.insert(0, str(AUTH_DIR))
    try:
        main = importlib.import_module("main")
    finally:
        sys.path.remove(str(AUTH_DIR))

    main.database.Base.metadata.create_all(bind=main.database.engine)
    invalidated = []
    monkeypatch.setattr(main, "invalidate_agent_token_cache", lambda *tokens: invalidated.extend(tokens))
    return main, TestClient(main.app), invalidated


def register_and_login(client):
    response = client.post("/register", json={"username": "alice", "password": "secret"})
    assert response.status_code == 200

    response = client.post(
        "/token",
        data={"username": "alice", "password": "secret"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 200
    return response.json()


def test_registration_login_refresh_and_protected_access(tmp_path, monkeypatch):
    _, client, _ = load_auth_app(tmp_path, monkeypatch)
    tokens = register_and_login(client)

    response = client.get("/users/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert response.status_code == 200
    assert response.json()["username"] == "alice"

    refresh_response = client.post("/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refresh_response.status_code == 200
    rotated = refresh_response.json()
    assert rotated["refresh_token"] != tokens["refresh_token"]

    reused_response = client.post("/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert reused_response.status_code == 401


def test_cleanup_tokens_requires_authenticated_user(tmp_path, monkeypatch):
    _, client, _ = load_auth_app(tmp_path, monkeypatch)

    assert client.delete("/admin/cleanup-tokens").status_code == 401

    tokens = register_and_login(client)
    response = client.delete(
        "/admin/cleanup-tokens",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert response.status_code == 200


def test_agent_token_regeneration_and_delete_invalidate_old_tokens(tmp_path, monkeypatch):
    _, client, invalidated = load_auth_app(tmp_path, monkeypatch)
    tokens = register_and_login(client)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    created = client.post("/agents", json={"name": "laptop"}, headers=headers).json()
    old_token = created["token"]

    valid_response = client.post("/agents/validate-token", params={"token": old_token})
    assert valid_response.status_code == 200
    assert valid_response.json()["valid"] is True

    regenerated = client.post(f"/agents/{created['id']}/regenerate-token", headers=headers).json()
    new_token = regenerated["token"]
    assert old_token != new_token
    assert old_token in invalidated
    assert new_token in invalidated

    old_response = client.post("/agents/validate-token", params={"token": old_token})
    assert old_response.json()["valid"] is False

    assert client.delete(f"/agents/{created['id']}", headers=headers).status_code == 200
    assert new_token in invalidated
    new_response = client.post("/agents/validate-token", params={"token": new_token})
    assert new_response.json()["valid"] is False
