"""Read-only release checks; no production credentials or paid AI calls."""
import json
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.main import app


def fetch(base, path):
    try:
        with urlopen(base.rstrip("/") + path, timeout=30) as response:
            return response.status, response.read()
    except HTTPError as error:
        return error.code, error.read()


def verify(base):
    status, body = fetch(base, "/health")
    if status != 200 or json.loads(body) != {"status": "ok", "contractVersion": 1}:
        raise RuntimeError("Health check failed")
    status, body = fetch(base, "/openapi.json")
    if status != 200 or json.loads(body) != app.openapi():
        raise RuntimeError("Deployed OpenAPI does not match the tested commit")
    status, body = fetch(base, "/docs")
    if status != 200 or b"SwaggerUIBundle" not in body:
        raise RuntimeError("Swagger is unavailable")
    status, _ = fetch(base, "/v1/trips")
    if status != 401:
        raise RuntimeError("Protected trips endpoint did not require authentication")
    print("PASS: health, exact OpenAPI, Swagger and authentication boundary")


if __name__ == "__main__":
    verify(sys.argv[1])
