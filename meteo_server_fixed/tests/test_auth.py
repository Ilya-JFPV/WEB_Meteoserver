import importlib
import os
import sys

from fastapi.testclient import TestClient


def create_client(monkeypatch, api_key="secret"):
    monkeypatch.setenv("API_KEY", api_key)
    monkeypatch.setenv("API_KEY_HEADER", "X-API-Key")
    monkeypatch.setenv("ENABLE_TCP", "0")
    monkeypatch.setenv("PERSIST_STATIONS", "0")
    monkeypatch.setenv("INGEST_LOG_TO_FILE", "0")
    sys.modules.pop("app", None)
    import app  # type: ignore
    importlib.reload(app)
    return TestClient(app.app)


def test_logs_tail_requires_api_key(monkeypatch):
    client = create_client(monkeypatch)

    resp = client.get("/logs/tail")
    assert resp.status_code == 401

    resp = client.get("/logs/tail", headers={"X-API-Key": "secret"})
    assert resp.status_code == 200
    assert "lines" in resp.json()


def test_mutating_endpoint_requires_key(monkeypatch):
    client = create_client(monkeypatch)

    resp = client.post("/stations", json={"lat": 1.0, "lon": 2.0})
    assert resp.status_code == 401

    resp = client.post("/stations", json={"lat": 1.0, "lon": 2.0}, headers={"X-API-Key": "secret"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"].startswith("st-")
    assert body["lat"] == 1.0
    assert body["lon"] == 2.0
