import asyncio
from dataclasses import replace

import httpx
import pytest

from app.errors import ServiceError
from app.providers import Provider


def payload(text="قَلَمٌ"):
    return {"choices": [{"message": {"content": text}}], "usage": {"prompt_tokens": 10, "completion_tokens": 4}}


def run(settings, handler, **kwargs):
    async def invoke():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await Provider(settings, client).complete("قلم", **kwargs)
    return asyncio.run(invoke())


def test_success_and_cost(real_settings):
    def handle(request):
        assert request.headers["authorization"] == "Bearer secret"
        assert b"messages" in request.content
        return httpx.Response(200, json=payload())
    result = run(real_settings, handle)
    assert result.text == "قَلَمٌ"
    assert result.prompt_tokens == 10 and result.completion_tokens == 4
    assert result.cost_usd == pytest.approx(0.000018)


@pytest.mark.parametrize("failure", ["timeout", 500, 503])
def test_fallback(real_settings, failure):
    calls = []
    def handle(request):
        calls.append(request.url.host)
        if request.url.host == "primary.test":
            if failure == "timeout":
                raise httpx.ReadTimeout("timed out", request=request)
            return httpx.Response(failure)
        return httpx.Response(200, json=payload())
    result = run(real_settings, handle)
    assert calls == ["primary.test", "fallback.test"]
    assert result.provider == "fallback"
    assert result.cost_usd == pytest.approx(0.000036)


@pytest.mark.parametrize("failure,status,error", [("timeout", 504, "provider_timeout"), (503, 502, "provider_error"), (401, 502, "provider_error"), (429, 502, "provider_error"), ("connection", 502, "provider_error")])
def test_failure_mapping(real_settings, failure, status, error):
    def handle(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("secret should never leak", request=request)
        if failure == "connection":
            raise httpx.ConnectError("secret", request=request)
        return httpx.Response(failure, text="upstream secret")
    with pytest.raises(ServiceError) as exc:
        run(real_settings, handle)
    assert exc.value.status == status and exc.value.body["error"] == error
    assert "secret" not in str(exc.value.body)


@pytest.mark.parametrize("data", [{}, {"choices": []}, payload(None), {**payload(), "usage": {"prompt_tokens": -1, "completion_tokens": 1}}, {**payload(), "usage": {"prompt_tokens": True, "completion_tokens": 1}}])
def test_malformed_no_fallback(real_settings, data):
    calls = []
    def handle(request):
        calls.append(request.url.host)
        return httpx.Response(200, json=data)
    with pytest.raises(ServiceError) as exc:
        run(real_settings, handle)
    assert exc.value.body == {"error": "provider_error", "detail": "Malformed upstream response."}
    assert calls == ["primary.test"]


def test_retry_bound(real_settings):
    calls = []
    def handle(request):
        calls.append(request.url.host)
        return httpx.Response(503)
    with pytest.raises(ServiceError):
        run(replace(real_settings, max_retries=1), handle)
    assert calls == ["primary.test", "primary.test", "fallback.test", "fallback.test"]


def test_non_json(real_settings):
    with pytest.raises(ServiceError):
        run(real_settings, lambda request: httpx.Response(200, text="not JSON"))
