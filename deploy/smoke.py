"""Run against the deployed API; secrets are read only from process environment."""
import hashlib
import json
import os
import secrets
from datetime import datetime, timezone

import httpx


def run():
    results = {"testedAt": datetime.now(timezone.utc).isoformat(),
               "serviceUrl": os.environ["SERVICE_URL"],
               "revision": os.environ.get("SERVICE_REVISION", "unknown")}
    email = "smoke-" + secrets.token_hex(8) + "@example.invalid"
    uid = hashlib.sha256(email.encode()).hexdigest()
    trip_id = device_id = None
    created_user = False
    with httpx.Client(base_url=os.environ["SERVICE_URL"], timeout=100) as client:
        def call(method, path, **kwargs):
            response = client.request(method, path, **kwargs)
            if response.status_code >= 400:
                raise RuntimeError(f"{method} {path}: HTTP {response.status_code}: {response.text[:500]}")
            return response.json() if response.content else None

        try:
            results["health"] = call("GET", "/health")
            assert client.get("/docs").status_code == 200
            schema = call("GET", "/openapi.json")
            results["apiVersion"] = schema["info"]["version"]
            assert all(name in schema["components"]["schemas"] for name in ("TripPlan", "SpeakCommand", "DriveEvent"))
            assert client.get("/v1/trips").status_code == 401
            credentials = {"email": email, "password": secrets.token_urlsafe(24)}
            call("POST", "/v1/auth/register", headers={"X-Invite-Key": os.environ["INVITE_KEY"]}, json=credentials)
            created_user = True
            login = call("POST", "/v1/auth/login", json=credentials)
            client.headers["Authorization"] = "Bearer " + login["access_token"]
            pair = call("POST", "/v1/pairings")
            device = call("POST", "/v1/pairings/claim", json={"code": pair["code"], "name": "smoke Pleos", "kind": "pleos"})
            device_id = device["deviceId"]
            assert client.post("/v1/pairings/claim", json={"code": pair["code"], "name": "replay", "kind": "pleos"}).status_code == 400
            place = {"id": "yeongnangho", "name": "영랑호", "source": "검증용 제공 사실", "group": "공유"}
            trip = call("POST", "/v1/trips", json={"destination": "속초", "departure": "2026-11-22", "companions": ["부모님"], "interests": ["지역 이야기"], "mood": "잔잔한", "density": "보통", "places": [place]})
            trip_id = trip["tripId"]
            call("POST", f"/v1/trips/{trip_id}/stage", params={"device_id": device_id})
            device_headers = {"Authorization": "Bearer " + device["access_token"]}
            messages = call("GET", f"/v1/devices/{device_id}/messages", headers=device_headers)
            assert messages["messages"][0]["payload"] == trip
            assert call("GET", f"/v1/devices/{device_id}/messages", headers=device_headers,
                        params={"after": messages["nextCursor"]})["messages"] == []
            assert client.post("/v1/pairings", headers=device_headers).status_code == 403
            assert client.post("/v1/ai/recommendations", headers=device_headers,
                               json={"tripId": trip_id, "candidates": [place]}).status_code == 403
            event = {"v": 1, "tripId": trip_id, "type": "PLACE_SAVED", "placeId": place["id"], "at": datetime.now(timezone.utc).isoformat()}
            first = call("POST", f"/v1/trips/{trip_id}/events", headers=device_headers, json=event)
            assert call("POST", f"/v1/trips/{trip_id}/events", headers=device_headers, json=event) == first
            assert len(call("GET", f"/v1/trips/{trip_id}/events")) == 1
            assert client.post(f"/v1/trips/{trip_id}/events", headers=device_headers,
                               json={**event, "v": 9}).status_code == 422
            assert client.post(f"/v1/trips/{trip_id}/events", headers=device_headers,
                               json={**event, "placeId": "unknown-place"}).status_code == 422
            results["backend"] = "registration, login, one-use pairing, persistence, stage, device polling, cursor replay prevention, capability restrictions, invalid event rejection and idempotent events passed"
            results["recommendations"] = call("POST", "/v1/ai/recommendations", json={"tripId": trip_id, "candidates": [place]})
            assert results["recommendations"]["places"][0]["id"] == place["id"]
            radio = call("POST", f"/v1/trips/{trip_id}/radio", params={"device_id": device_id}, json={"place": place, "facts": ["영랑호는 속초에 있는 호수다.", "호수 주위에 산책로가 있다."]})
            results["radio"] = radio["command"]
            next_messages = call("GET", f"/v1/devices/{device_id}/messages", headers=device_headers, params={"after": messages["nextCursor"]})
            assert next_messages["messages"][0]["payload"] == radio["command"]
            results["extraction"] = call("POST", "/v1/ai/extract-places", json={"text": "오늘은 속초의 영랑호를 산책했습니다.", "source": "smoke transcript"})
            results["summary"] = call("POST", f"/v1/trips/{trip_id}/summary")
            assert results["summary"]["savedPlaceCount"] == 1
            call("DELETE", f"/v1/devices/{device_id}")
            device_id = None
            assert client.get("/v1/trips", headers=device_headers).status_code == 401
            results["deviceRevocation"] = "revoked token rejected immediately"
            results["status"] = "passed"
        finally:
            if trip_id:
                call("DELETE", f"/v1/trips/{trip_id}")
            if device_id:
                call("DELETE", f"/v1/devices/{device_id}")
            if created_user:
                # Delete only this generated test account using the deployer's short-lived token.
                response = httpx.delete(f"https://firestore.googleapis.com/v1/projects/vroom-514610/databases/(default)/documents/users/{uid}", headers={"Authorization": "Bearer " + os.environ["GCP_ACCESS_TOKEN"]})
                response.raise_for_status()
    with open("deploy/smoke-results.json", "w", encoding="utf-8", newline="\n") as output:
        json.dump(results, output, ensure_ascii=False, indent=2)
        output.write("\n")
    print(json.dumps(results, ensure_ascii=True))


if __name__ == "__main__":
    run()
