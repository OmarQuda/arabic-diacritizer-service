import json
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient

from app import auth
from app.main import create_app
from tests.test_providers import payload


@pytest.mark.parametrize("key,status", [("test-key", 200), ("old-key", 200), ("wrong", 401), ("", 401)])
def test_auth(client, key, status):
    response = client.post("/v1/diacritize", headers={"X-Service-Key": key}, json={"text": "قلم"})
    assert response.status_code == status
    if status == 401:
        assert response.json() == {"error": "unauthorized"}


def test_both_comparisons(monkeypatch):
    original = auth.hmac.compare_digest
    calls = []
    def spy(a, b):
        calls.append(b)
        return original(a, b)
    monkeypatch.setattr(auth.hmac, "compare_digest", spy)
    assert auth.authorized("key", "key", "old")
    assert calls == [b"key", b"old"]
    assert not auth.authorized("", "", "")


def test_missing_auth(client):
    assert client.get("/v1/corrections").json() == {"error": "unauthorized"}
    assert client.post("/v1/corrections", json={}).status_code == 401


def test_health_and_success(client, headers):
    assert client.get("/health/live").json() == {"status": "ok"}
    assert client.get("/health/ready").json() == {"status": "ready", "fake_provider": True, "provider": "fake", "model": "dictionary-v1"}
    response = client.post("/v1/diacritize", headers=headers, json={"text": "ذهب الولد إلى المدرسة", "request_id": "demo"})
    data = response.json()
    assert response.status_code == 200
    assert set(data) == {"request_id", "input", "output", "valid", "attempts", "provider", "model", "usage", "latency_ms"}
    assert data["output"] == "ذَهَبَ الْوَلَدُ إِلَى الْمَدْرَسَةِ"
    assert data["attempts"] == 1 and data["valid"] is True
    assert data["usage"] == {"prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0}
    assert response.headers["X-Request-ID"] == "demo"


@pytest.mark.parametrize("mode,reason", [("added_word", "added_words"), ("removed_word", "removed_words"), ("translation", "added_words"), ("markdown", "markdown")])
def test_simulations(client, headers, mode, reason):
    response = client.post("/v1/diacritize", headers=headers, json={"text": "ذهب الولد", "simulate": mode})
    assert response.status_code == 422
    assert response.json() == {"error": "validation_failed", "reason": reason, "attempts": 2,
                               "detail": {"added_words": "The provider added words.", "removed_words": "The provider removed words.", "markdown": "The provider added Markdown formatting."}[reason]}


def test_length(client, headers):
    response = client.post("/v1/diacritize", headers=headers, json={"text": "ب" * 5001})
    assert response.status_code == 413
    assert response.json() == {"error": "text_too_long", "max_chars": 5000}


@pytest.mark.parametrize("body", [{}, {"text": ""}, {"text": 42}, {"text": "قلم", "simulate": "invalid"}])
def test_bad_body(client, headers, body):
    response = client.post("/v1/diacritize", headers=headers, json=body)
    assert response.status_code == 422
    assert response.json() == {"error": "validation_failed", "reason": "empty", "attempts": 0, "detail": "Invalid request body or parameters."}


@pytest.mark.parametrize("failure,status,body", [(503, 502, {"error": "provider_error", "detail": "Upstream server failed."}), ("timeout", 504, {"error": "provider_timeout"}), ("malformed", 502, {"error": "provider_error", "detail": "Malformed upstream response."})])
def test_http_error_mapping(real_settings, headers, failure, status, body):
    def handle(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("timeout", request=request)
        return httpx.Response(200, json={}) if failure == "malformed" else httpx.Response(failure)
    with TestClient(create_app(real_settings, httpx.MockTransport(handle))) as client:
        response = client.post("/v1/diacritize", headers=headers, json={"text": "قلم"})
    assert response.status_code == status and response.json() == body


def test_repair_and_accumulated_usage(real_settings, headers):
    messages = []
    def handle(request):
        data = json.loads(request.content)
        messages.append(data["messages"])
        return httpx.Response(200, json=payload("wrong" if len(messages) == 1 else "قَلَمٌ"))
    with TestClient(create_app(real_settings, httpx.MockTransport(handle))) as client:
        response = client.post("/v1/diacritize", headers=headers, json={"text": "قلم", "simulate": "markdown"})
    data = response.json()
    assert data["attempts"] == 2
    assert data["usage"]["prompt_tokens"] == 20
    assert data["usage"]["cost_usd"] == pytest.approx(0.000036)
    assert len(messages[1]) == 3  # simulate is ignored with a real provider


def test_logs_no_text_by_default(client, headers, monkeypatch):
    events = []
    monkeypatch.setattr("app.main.logger.info", lambda event, **kw: events.append(kw["extra"]["fields"]))
    client.post("/v1/diacritize", headers=headers, json={"text": "قلم"})
    assert events and all("input" not in event and "output" not in event for event in events)
    assert all("request_id" in event for event in events)


def test_log_text_opt_in(settings, headers, monkeypatch):
    events = []
    monkeypatch.setattr("app.main.logger.info", lambda event, **kw: events.append(kw["extra"]["fields"]))
    with TestClient(create_app(replace(settings, log_text=True))) as client:
        client.post("/v1/diacritize", headers=headers, json={"text": "قلم"})
    assert events[0]["input"] == "قلم"
