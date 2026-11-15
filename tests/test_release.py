import json

import pytest

from deploy import verify_release


def responses():
    return {
        "/health": (200, b'{"status":"ok","contractVersion":1}'),
        "/openapi.json": (200, json.dumps(verify_release.app.openapi()).encode()),
        "/docs": (200, b"SwaggerUIBundle"),
        "/v1/trips": (401, b"{}"),
    }


def test_release_accepts_matching_service(monkeypatch):
    values = responses()
    monkeypatch.setattr(verify_release, "fetch", lambda base, path: values[path])
    verify_release.verify("https://candidate.example")


@pytest.mark.parametrize("path,response", [
    ("/health", (503, b"{}")),
    ("/openapi.json", (200, b"{}")),
    ("/docs", (200, b"unavailable")),
    ("/v1/trips", (200, b"[]")),
])
def test_release_rejects_unhealthy_stale_or_unprotected_service(monkeypatch, path, response):
    values = responses()
    values[path] = response
    monkeypatch.setattr(verify_release, "fetch", lambda base, path: values[path])
    with pytest.raises(RuntimeError):
        verify_release.verify("https://candidate.example")
