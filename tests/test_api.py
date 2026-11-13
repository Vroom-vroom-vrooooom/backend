import copy
import time
from collections import defaultdict

import pytest
from fastapi.testclient import TestClient

from app import main


class MemoryStore:
    def __init__(self):
        self.data = defaultdict(dict)
        self.counts = defaultdict(int)

    def get(self, c, k):
        return copy.deepcopy(self.data[c].get(k))

    def put(self, c, k, v):
        self.data[c][k] = copy.deepcopy(v)

    def create(self, c, k, v):
        if k in self.data[c]:
            return False
        self.put(c, k, v)
        return True

    def delete(self, c, k):
        self.data[c].pop(k, None)

    def list(self, c, f, v, limit=100):
        return [copy.deepcopy(d) for d in self.data[c].values() if d.get(f) == v][:limit]

    def limit(self, key, maximum, seconds=60):
        self.counts[key] += 1
        return self.counts[key] <= maximum

    def consume_pair(self, key):
        value = self.data["pairings"].pop(key, None)
        return value if value and value["expires"] > time.time() else None

    def messages(self, uid, device_id, after):
        return sorted([d for d in self.data["messages"].values() if d["owner"] == uid and d["deviceId"] == device_id and d["cursor"] > after], key=lambda d: d["cursor"])[:100]

    def trip_events(self, trip_id):
        return sorted(self.list("events", "tripId", trip_id, 1000), key=lambda d: d["payload"]["at"])


class FakeClaude:
    model = "test-model"
    result = {"text": "영랑호에는 호수 둘레길이 있어요."}

    async def structured(self, *args):
        return copy.deepcopy(self.result)


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "j" * 48)
    monkeypatch.setenv("INVITE_KEY", "i" * 48)
    db, ai = MemoryStore(), FakeClaude()
    monkeypatch.setattr(main, "store", lambda: db)
    monkeypatch.setattr(main, "claude", lambda: ai)
    with TestClient(main.app) as client:
        yield client, db, ai


def user(client, email="one@example.com"):
    result = client.post("/v1/auth/register", headers={"X-Invite-Key": "i" * 48}, json={"email": email, "password": "sample-passphrase-123"})
    assert result.status_code == 201, result.text
    return {"Authorization": "Bearer " + result.json()["access_token"]}


def trip(client, headers):
    result = client.post("/v1/trips", headers=headers, json={"destination": "속초", "departure": "2026-11-22", "companions": ["부모님"], "interests": ["지역 이야기"], "mood": "잔잔한", "density": "보통", "places": [{"id": "lake", "name": "영랑호"}]})
    assert result.status_code == 201, result.text
    return result.json()


def test_auth_invitation_login_and_isolation(env):
    client, _, _ = env
    assert client.get("/v1/trips").status_code == 401
    assert client.post("/v1/auth/register", json={"email": "x@y.co", "password": "sample-passphrase-123"}).status_code == 403
    h1, h2 = user(client), user(client, "two@example.com")
    plan = trip(client, h1)
    assert plan["v"] == 1 and "visibility" not in plan
    assert client.get("/v1/trips/" + plan["tripId"], headers=h2).status_code == 404
    assert client.post("/v1/auth/login", json={"email": "one@example.com", "password": "wrong-password-123"}).status_code == 401
    assert client.post("/v1/auth/login", json={"email": "one@example.com", "password": "sample-passphrase-123"}).status_code == 200


def test_pairing_single_use_stage_poll_and_revoke(env):
    client, _, _ = env
    headers = user(client)
    code = client.post("/v1/pairings", headers=headers).json()["code"]
    payload = {"code": code, "name": "car", "kind": "pleos"}
    pair = client.post("/v1/pairings/claim", json=payload).json()
    assert client.post("/v1/pairings/claim", json=payload).status_code == 400
    device_headers = {"Authorization": "Bearer " + pair["access_token"]}
    plan = trip(client, headers)
    path = "/v1/devices/" + pair["deviceId"]
    assert client.post("/v1/trips/" + plan["tripId"] + "/stage", params={"device_id": pair["deviceId"]}, headers=headers).status_code == 200
    messages = client.get(path + "/messages", headers=device_headers).json()
    assert messages["messages"][0]["payload"] == plan
    assert client.get(path + "/messages", params={"after": messages["nextCursor"]}, headers=device_headers).json()["messages"] == []
    assert client.post("/v1/pairings", headers=device_headers).status_code == 403
    assert client.delete(path, headers=headers).status_code == 204
    assert client.get("/v1/trips", headers=device_headers).status_code == 401


def test_contract_validation_and_event_idempotency(env):
    client, db, _ = env
    headers = user(client)
    plan = trip(client, headers)
    url = "/v1/trips/" + plan["tripId"] + "/events"
    event = {"v": 1, "tripId": plan["tripId"], "type": "PLACE_SAVED", "placeId": "lake", "at": "2026-11-22T01:00:00Z"}
    first = client.post(url, headers=headers, json=event)
    assert first.status_code == 201
    assert client.post(url, headers=headers, json=event).json() == first.json()
    assert len(db.data["events"]) == 1
    for invalid in ({**event, "v": 2}, {**event, "placeId": None}, {**event, "at": "2026-11-22T01:00:00"}, {**event, "tripId": "wrong"}):
        assert client.post(url, headers=headers, json=invalid).status_code == 422


def test_ai_preserves_sources_and_rejects_invented_ids(env):
    client, _, ai = env
    headers = user(client)
    plan = trip(client, headers)
    body = {"tripId": plan["tripId"], "candidates": [{"id": "lake", "name": "영랑호", "lat": 38.2, "lng": 128.5, "group": "좋아요", "source": "original"}]}
    ai.result = {"places": [{"id": "fake", "reason": "reason"}]}
    assert client.post("/v1/ai/recommendations", headers=headers, json=body).status_code == 502
    ai.result = {"places": [{"id": "lake", "reason": "가족과 산책하기 좋아요"}]}
    result = client.post("/v1/ai/recommendations", headers=headers, json=body).json()["places"][0]
    assert result["source"] == "original" and result["lat"] == 38.2


def test_radio_and_ai_limit(env):
    client, db, _ = env
    headers = user(client)
    plan = trip(client, headers)
    device = client.post("/v1/devices", headers=headers, json={"name": "car", "kind": "pleos"}).json()
    url = "/v1/trips/" + plan["tripId"] + "/radio"
    body = {"place": {"id": "lake", "name": "영랑호"}, "facts": ["영랑호에는 호수 둘레길이 있다."]}
    result = client.post(url, headers=headers, params={"device_id": device["deviceId"]}, json=body)
    assert result.status_code == 200, result.text
    assert result.json()["command"]["v"] == 1
    uid = main.digest("one@example.com")
    db.counts["ai-" + uid] = 20
    assert client.post(url, headers=headers, params={"device_id": device["deviceId"]}, json=body).status_code == 429


def test_extraction_requires_verbatim_evidence(env):
    client, _, ai = env
    headers = user(client)
    body = {"text": "영랑호를 산책했어요.", "source": "shared description"}
    ai.result = {"places": [{"name": "설악산", "evidence": "설악산 여행"}]}
    assert client.post("/v1/ai/extract-places", headers=headers, json=body).status_code == 502
    ai.result = {"places": [{"name": "영랑호", "evidence": "영랑호를 산책했어요."}]}
    assert client.post("/v1/ai/extract-places", headers=headers, json=body).status_code == 200


def test_delete_removes_trip_data(env):
    client, db, _ = env
    headers = user(client)
    plan = trip(client, headers)
    key = plan["tripId"]
    for collection in ("messages", "events", "trip_places"):
        db.put(collection, "x", {"id": "x", "tripId": key})
    assert client.delete("/v1/trips/" + key, headers=headers).status_code == 204
    assert all(not db.data[c] for c in ("trips", "messages", "events", "trip_places"))
