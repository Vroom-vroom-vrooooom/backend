import hashlib
import hmac
import json
import os
import secrets
import time
from functools import lru_cache

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import ValidationError

from .claude import Claude
from .models import (Credentials, Device, DriveEvent, ExtractionRequest, PairClaim,
                     Place, RadioRequest, RadioResponse, RecommendationRequest, SpeakCommand, TripPlan, TripWrite)
from .store import Store

app = FastAPI(
    title="차곡 Backend & AI", version="1.0.1",
    description="""차곡 앱의 계정·여행·메시지·Claude AI용 자체 REST API입니다.
TripPlan / SpeakCommand / DriveEvent는 차곡 CONTRACT.md v1 규격입니다.

2026-11-13 [공모전 공식 개발 가이드](https://appdevchallenge.auto-hmg.io/guide/development)와
[Pleos SDK 문서](https://document.pleos.ai/docs/pleos-only/connect-sdk-pleos/)를 대조했습니다.
NaviHelper 호출, TTS 재생, CarUxRestrictions 적용, Audio Focus 처리는 차량 앱에서 수행합니다.
메시지 등록 성공은 내비게이션 실행·음성 재생 성공을 의미하지 않습니다.

**현재 상태:** BE 배포 및 API 테스트 완료. Android HTTP 연결, 주행 제한·오디오 포커스·Gleo 연동과
Pleos 에뮬레이터 종단 간 검증은 미완료입니다.
[공식 가이드 대조표와 FE 연동 주의사항](https://github.com/Vroom-vroom-vrooooom/backend/blob/main/docs/pleos-integration.md)

보호된 API는 Authorize에 로그인 access_token을 입력합니다. 계정 토큰은 여행·기기·AI를 관리하고,
기기 토큰은 여행 조회·자신의 메시지 조회·이벤트 전송에 사용합니다.
""",
    openapi_tags=[
        {"name": "Trips", "description": "차곡 여행 계획 저장. 실제 경로 설정은 차량의 NaviHelper SDK에서 처리합니다."},
        {"name": "Vehicle relay", "description": "차곡 v1 메시지 전달 및 사용자 행동 이벤트. Pleos SDK 실행 결과와 구분하세요."},
        {"name": "AI", "description": "서버의 Claude 호출. Gleo 음성 명령 연동은 차량 앱의 별도 구현입니다."},
    ],
    openapi_external_docs={"description": "현대자동차그룹 공모전 공식 개발 가이드",
                           "url": "https://appdevchallenge.auto-hmg.io/guide/development"},
)
bearer = HTTPBearer(auto_error=False)
hasher = PasswordHasher()
dummy_hash = hasher.hash(secrets.token_urlsafe(32))


@lru_cache
def store():
    return Store(os.environ["GOOGLE_CLOUD_PROJECT"])


@lru_cache
def claude():
    return Claude()


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def secret(name):
    value = os.environ.get(name, "")
    if len(value) < 32:
        raise HTTPException(503, "Server credentials are not configured")
    return value


def throttle(key, maximum, seconds=60):
    if not store().limit(key, maximum, seconds):
        raise HTTPException(429, "Rate limit exceeded", headers={"Retry-After": str(seconds)})


def token(uid, device_id=None):
    # A car must not have to pair again every day. Device tokens are checked against the devices
    # collection on every request (identity()), so DELETE /v1/devices/{id} still revokes them at once.
    now, ttl = int(time.time()), 86400 * (30 if device_id else 1)
    return {"access_token": jwt.encode({"sub": uid, "device": device_id, "iat": now,
            "exp": now + ttl, "iss": "chagok", "aud": "chagok-api"}, secret("JWT_SECRET"), algorithm="HS256"),
            "token_type": "bearer", "expires_in": ttl}


def identity(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if not credentials:
        raise HTTPException(401, "Authentication required")
    try:
        claims = jwt.decode(credentials.credentials, secret("JWT_SECRET"), algorithms=["HS256"],
                            audience="chagok-api", issuer="chagok", options={"require": ["exp", "iat", "sub"]})
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid or expired token") from None
    if not store().get("users", claims["sub"]):
        raise HTTPException(401, "Account unavailable")
    if claims.get("device"):
        device = store().get("devices", claims["device"])
        if not device or device["owner"] != claims["sub"]:
            raise HTTPException(401, "Device revoked")
    return claims


def owner(claims=Depends(identity)):
    return claims["sub"]


def account(claims=Depends(identity)):
    if claims.get("device"):
        raise HTTPException(403, "Account login required")
    return claims["sub"]


def owned(collection, key, uid):
    value = store().get(collection, key)
    if not value or value["owner"] != uid:
        raise HTTPException(404, "Not found")
    return value


def trip_plan(trip):
    return {**trip["plan"], "v": 1, "tripId": trip["id"]}


def queue(uid, trip_id, kind, payload, device_id=None):
    key = secrets.token_hex(16)
    created = time.time_ns()
    store().create("messages", key, {"id": key, "owner": uid, "tripId": trip_id,
                   "kind": kind, "payload": payload, "deviceId": device_id,
                   "created": created, "cursor": f"{created:020d}-{key}"})
    return key


@app.get("/health")
@app.get("/healthz", include_in_schema=False)
def health():
    return {"status": "ok", "contractVersion": 1}


@app.post("/v1/auth/register", status_code=201)
def register(body: Credentials, x_invite_key: str = Header(default="")):
    if not hmac.compare_digest(x_invite_key, secret("INVITE_KEY")):
        raise HTTPException(403, "A team invitation is required")
    uid = digest(body.email.lower())
    throttle("signup-" + uid, 3)
    if not store().create("users", uid, {"email": body.email.lower(), "password": hasher.hash(body.password)}):
        raise HTTPException(409, "Account already exists")
    return token(uid)


@app.post("/v1/auth/login")
def login(body: Credentials):
    uid = digest(body.email.lower())
    throttle("login-" + uid, 5)
    user = store().get("users", uid)
    try:
        hasher.verify(user["password"] if user else dummy_hash, body.password)
    except VerificationError:
        raise HTTPException(401, "Invalid credentials") from None
    if not user:
        raise HTTPException(401, "Invalid credentials")
    return token(uid)


@app.post("/v1/devices", status_code=201)
def register_device(body: Device, uid=Depends(account)):
    key = secrets.token_hex(16)
    store().put("devices", key, {"id": key, "owner": uid, **body.model_dump()})
    return {"deviceId": key, **token(uid, key)}


@app.get("/v1/devices")
def devices(uid=Depends(account)):
    return store().list("devices", "owner", uid)


@app.delete("/v1/devices/{device_id}", status_code=204)
def revoke_device(device_id: str, uid=Depends(account)):
    owned("devices", device_id, uid)
    store().delete("devices", device_id)


@app.post("/v1/pairings", status_code=201)
def pairing(uid=Depends(account)):
    """8자리 숫자 코드(5분, 1회용). 폰에 띄우고 차량 앱에서 숫자 키패드로 입력합니다."""
    throttle("pair-" + uid, 5)
    while True:  # a clash with another live code is ~1e-8; just draw again
        code = f"{secrets.randbelow(10**8):08d}"
        if store().create("pairings", digest(code), {"owner": uid, "expires": time.time() + 300}):
            return {"code": code, "expires_in": 300}


@app.post("/v1/pairings/claim")
def claim_pair(body: PairClaim):
    # 8 digits are typeable in a car but guessable without a cap: 30 tries/min across all callers
    # gives ~150 guesses per 5-minute code (~1.5e-6 per code).
    # ponytail: global cap, so a flood can block pairing for a minute; per-client limits if that happens.
    throttle("claim", 30)
    pairing = store().consume_pair(digest(body.code))
    if not pairing:
        raise HTTPException(400, "Pairing expired or already used")
    return register_device(Device(name=body.name, kind=body.kind), pairing["owner"])


@app.post("/v1/trips", status_code=201, response_model=TripPlan, tags=["Trips"])
def create_trip(body: TripWrite, uid=Depends(account)):
    key = secrets.token_hex(16)
    data = body.model_dump(mode="json")
    visibility = data.pop("visibility")
    trip = {"id": key, "owner": uid, "plan": data, "visibility": visibility}
    store().put("trips", key, trip)
    return trip_plan(trip)


@app.get("/v1/trips", response_model=list[TripPlan], tags=["Trips"])
def trips(uid=Depends(owner)):
    return [trip_plan(t) for t in store().list("trips", "owner", uid)]


@app.get("/v1/trips/{trip_id}", response_model=TripPlan, tags=["Trips"])
def get_trip(trip_id: str, uid=Depends(owner)):
    return trip_plan(owned("trips", trip_id, uid))


@app.put("/v1/trips/{trip_id}", response_model=TripPlan, tags=["Trips"])
def update_trip(trip_id: str, body: TripWrite, uid=Depends(account)):
    trip = owned("trips", trip_id, uid)
    data = body.model_dump(mode="json")
    trip.update(visibility=data.pop("visibility"), plan=data)
    store().put("trips", trip_id, trip)
    return trip_plan(trip)


@app.delete("/v1/trips/{trip_id}", status_code=204, tags=["Trips"])
def delete_trip(trip_id: str, uid=Depends(account)):
    owned("trips", trip_id, uid)
    # Delete associated data before the parent. Repeating deletion is safe.
    for collection in ("events", "messages", "trip_places"):
        while rows := store().list(collection, "tripId", trip_id, 100):
            for row in rows:
                store().delete(collection, row["id"])
    store().delete("trips", trip_id)


@app.post("/v1/trips/{trip_id}/stage", tags=["Vehicle relay"])
def stage_trip(trip_id: str, device_id: str, uid=Depends(account)):
    """TripPlan을 소유한 Pleos 기기 큐에 등록합니다.

    응답 messageId는 큐 등록 확인입니다. 차량 앱은 사용자 선택과 실제 좌표를 기준으로
    NaviHelper에 목적지·최대 두 경유지를 전달하고, 결과를 SDK 콜백으로 확인해야 합니다.
    여행의 전체 places 목록은 내비게이션의 활성 경유지 목록과 다릅니다.
    """
    trip = owned("trips", trip_id, uid)
    device = owned("devices", device_id, uid)
    if device["kind"] != "pleos":
        raise HTTPException(422, "Target must be a Pleos device")
    return {"messageId": queue(uid, trip_id, "TripPlan", trip_plan(trip), device_id)}


@app.get("/v1/devices/{device_id}/messages", tags=["Vehicle relay"])
def messages(device_id: str, after: str = "", claims=Depends(identity)):
    """최대 100개 메시지와 nextCursor를 반환합니다.

    envelope의 kind는 TripPlan 또는 SpeakCommand, payload는 차곡 v1 JSON입니다.
    id로 중복 처리하고 처리 후 nextCursor를 저장하세요. cursor는 불투명 문자열이며,
    created(Unix nanoseconds)를 JavaScript Number로 변환해 커서를 만들면 안 됩니다.
    현재 서버에 메시지 만료 기능은 없습니다. 재접속 시 오래된 음성 메시지를 무조건 재생하지 말고
    활성 tripId·현재 맥락·오디오 포커스를 차량에서 다시 확인해야 합니다.
    """
    uid = claims["sub"]
    owned("devices", device_id, uid)
    if claims.get("device") and claims["device"] != device_id:
        raise HTTPException(403, "Wrong device")
    # Firestore cursor pagination uses one composite index, provided in deployment.
    rows = store().messages(uid, device_id, after)
    return {"messages": rows, "nextCursor": rows[-1]["cursor"] if rows else after}


@app.post("/v1/trips/{trip_id}/events", status_code=201, tags=["Vehicle relay"])
def event(trip_id: str, body: DriveEvent, uid=Depends(owner)):
    """사용자 행동을 중복 없이 저장합니다.

    WAYPOINT_APPROVED는 사용자의 승인 기록이며 경로 설정 성공·실제 방문 증명이 아닙니다.
    NaviHelper 성공/실패는 차량 앱이 SDK 콜백으로 처리합니다. v1에는 SDK 결과 이벤트가 없습니다.
    """
    trip = owned("trips", trip_id, uid)
    if body.tripId != trip_id:
        raise HTTPException(422, "tripId mismatch")
    if body.placeId and body.placeId not in {p["id"] for p in trip["plan"]["places"]}:
        # AI-recommended/saved places are registered separately in the trip catalogue.
        known = store().get("trip_places", trip_id + "-" + body.placeId)
        if not known or known["owner"] != uid:
            raise HTTPException(422, "Unknown place")
    payload = body.model_dump(mode="json")
    key = digest(json.dumps(payload, sort_keys=True))
    store().create("events", key, {"id": key, "owner": uid, "tripId": trip_id, "payload": payload})
    return {"eventId": key}


@app.post("/v1/trips/{trip_id}/places", status_code=201, tags=["Vehicle relay"])
def add_place(trip_id: str, body: Place, uid=Depends(owner)):
    """여행 계획 밖의 장소(차량 '발견' 탭 등)를 여행 카탈로그에 등록합니다.

    등록한 placeId로 PLACE_SAVED·WAYPOINT_APPROVED 이벤트를 보낼 수 있습니다. 기기 토큰 허용, 같은 id는 덮어씁니다.
    """
    owned("trips", trip_id, uid)
    key = trip_id + "-" + body.id
    store().put("trip_places", key, {"id": key, "tripId": trip_id, "owner": uid, "place": body.model_dump(mode="json")})
    return {"placeId": body.id}


@app.get("/v1/trips/{trip_id}/events", response_model=list[DriveEvent], tags=["Vehicle relay"])
def events(trip_id: str, uid=Depends(owner)):
    owned("trips", trip_id, uid)
    rows = store().trip_events(trip_id)
    return [r["payload"] for r in rows]


@app.post("/v1/ai/recommendations", tags=["AI"])
async def recommendations(body: RecommendationRequest, uid=Depends(account)):
    trip = owned("trips", body.tripId, uid)
    throttle("ai-" + uid, 20, 3600)
    result = await claude().structured("Rank up to 5 supplied candidate places for this trip. Use only supplied IDs. Explain suitability briefly.",
        {"trip": trip["plan"], "candidates": [p.model_dump(mode="json") for p in body.candidates]},
        {"type": "object", "properties": {"places": {"type": "array", "maxItems": 5, "items": {"type": "object", "properties": {"id": {"type": "string"}, "reason": {"type": "string"}}, "required": ["id", "reason"]}}}, "required": ["places"]})
    candidates = {p.id: p for p in body.candidates}
    try:
        selected = result["places"]
        if not isinstance(selected, list) or not 1 <= len(selected) <= 5 or len({p["id"] for p in selected}) != len(selected):
            raise ValueError()
        output = [Place.model_validate({**candidates[p["id"]].model_dump(), "reason": p["reason"]}) for p in selected]
    except (KeyError, TypeError, ValueError):
        raise HTTPException(502, "AI returned invalid recommendations") from None
    for place in output:
        store().put("trip_places", body.tripId + "-" + place.id, {"id": body.tripId + "-" + place.id,
                    "tripId": body.tripId, "owner": uid, "place": place.model_dump(mode="json")})
    return {"places": output, "model": claude().model}


@app.post("/v1/trips/{trip_id}/radio", response_model=RadioResponse, tags=["AI"])
async def radio(trip_id: str, body: RadioRequest, device_id: str, uid=Depends(account)):
    """제공된 사실로 짧은 대사를 생성하고 SpeakCommand를 큐에 등록합니다.

    서버는 차량 상태를 판정하거나 TTS를 직접 재생하지 않습니다. 차량 앱은 Pleos TTS와
    Audio Focus 정책을 적용하고, Gleo·통화 등에 의한 포커스 상실 시 재생을 중단해야 합니다.
    같은 명령이 응답과 메시지 큐 양쪽에 있으므로 messageId로 중복 재생을 방지하세요.
    """
    trip = owned("trips", trip_id, uid)
    device = owned("devices", device_id, uid)
    if device["kind"] != "pleos":
        raise HTTPException(422, "Target must be a Pleos device")
    throttle("ai-" + uid, 20, 3600)
    result = await claude().structured("Write one or two short sentences for a driving companion, using only supplied facts. Never give driving instructions or claim visibility/location without evidence.",
        {"destination": trip["plan"]["destination"], **body.model_dump(mode="json")},
        {"type": "object", "properties": {"text": {"type": "string", "maxLength": 500}}, "required": ["text"]})
    try:
        command = SpeakCommand(tripId=trip_id, text=result["text"], place=body.place)
    except (KeyError, TypeError, ValidationError):
        raise HTTPException(502, "AI returned invalid radio text") from None
    place_key = trip_id + "-" + body.place.id
    store().put("trip_places", place_key, {"id": place_key, "tripId": trip_id, "owner": uid,
                "place": body.place.model_dump(mode="json")})
    return {"command": command, "messageId": queue(uid, trip_id, "SpeakCommand", command.model_dump(mode="json"), device_id)}


@app.post("/v1/ai/extract-places", tags=["AI"])
async def extract_places(body: ExtractionRequest, uid=Depends(account)):
    throttle("ai-" + uid, 20, 3600)
    result = await claude().structured("Extract explicitly named travel places from supplied transcript/description. Quote the exact supporting phrase in evidence. Return no places when absent. Do not infer coordinates.",
        body.model_dump(), {"type": "object", "properties": {"places": {"type": "array", "maxItems": 20, "items": {"type": "object", "properties": {"name": {"type": "string"}, "evidence": {"type": "string"}}, "required": ["name", "evidence"]}}}, "required": ["places"]})
    try:
        values = result["places"]
        if not isinstance(values, list) or len(values) > 20:
            raise ValueError()
        output = []
        for item in values:
            if not item["evidence"] or item["evidence"] not in body.text or item["name"] not in item["evidence"]:
                raise ValueError()
            output.append(Place(id=digest(body.source + item["name"])[:24], name=item["name"],
                         source=body.source, group=body.group, reason=item["evidence"]))
    except (KeyError, TypeError, ValueError):
        raise HTTPException(502, "AI returned unsupported place evidence") from None
    return {"places": output}


@app.post("/v1/trips/{trip_id}/summary", tags=["AI"])
async def summary(trip_id: str, uid=Depends(account)):
    trip = owned("trips", trip_id, uid)
    recorded = events(trip_id, uid)
    throttle("ai-" + uid, 20, 3600)
    result = await claude().structured("Summarize this travel plan and recorded events. Distinguish planned places, saved places, approved waypoints and completed travel. Do not invent visits, mileage or elapsed time.",
        {"trip": trip_plan(trip), "events": recorded},
        {"type": "object", "properties": {"text": {"type": "string", "maxLength": 3000}}, "required": ["text"]})
    if not isinstance(result.get("text"), str) or not 1 <= len(result["text"].strip()) <= 3000:
        raise HTTPException(502, "AI returned invalid summary")
    return {"text": result["text"], "eventCount": len(recorded),
            "savedPlaceCount": len({e["placeId"] for e in recorded if e["type"] == "PLACE_SAVED"})}
