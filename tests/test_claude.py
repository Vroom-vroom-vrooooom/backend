import asyncio
import json

import httpx
import pytest
from fastapi import HTTPException

from app.claude import Claude


def invoke(monkeypatch, status, response):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-only-secret")
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(status, json=response)

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    result = asyncio.run(Claude().structured("test", {}, {"type": "object", "properties": {"text": {"type": "string", "maxLength": 50}}, "required": ["text"]}))
    return result, requests


def test_structured_output_matches_sonnet_api(monkeypatch):
    result, requests = invoke(monkeypatch, 200, {"stop_reason": "end_turn", "content": [{"type": "text", "text": '{"text":"ok"}'}]})
    assert result == {"text": "ok"}
    assert "tool_choice" not in requests[0]
    schema = requests[0]["output_config"]["format"]["schema"]
    assert schema["additionalProperties"] is False
    assert "maxLength" not in schema["properties"]["text"]


@pytest.mark.parametrize("status,body,expected", [
    (401, {"error": "test-only-secret"}, 502),
    (429, {}, 503),
    (200, {"stop_reason": "max_tokens", "content": []}, 502),
    (200, {"stop_reason": "refusal", "content": []}, 502),
    (200, {"stop_reason": "end_turn", "content": [{"type": "text", "text": "not JSON"}]}, 502),
])
def test_provider_failures_are_sanitized(monkeypatch, status, body, expected):
    with pytest.raises(HTTPException) as caught:
        invoke(monkeypatch, status, body)
    assert caught.value.status_code == expected
    assert "test-only-secret" not in caught.value.detail
