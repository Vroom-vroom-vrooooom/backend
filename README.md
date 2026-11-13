# 차곡 Backend & AI

FastAPI + Firestore + Claude Messages API. Cloud Run service: `chagok-api`, project: `vroom-514610`, region: `asia-northeast3` (Seoul).

- Live API: https://chagok-api-om4h3skohq-du.a.run.app
- Interactive API docs: https://chagok-api-om4h3skohq-du.a.run.app/docs
- Health: https://chagok-api-om4h3skohq-du.a.run.app/health (`/healthz` is not usable through the public Google frontend in this deployment).
- Release 1.0.1 verified on 2026-11-13: 13 automated tests; live health, Swagger and OpenAPI checks. Live revision: `chagok-api-00003-nbf`.
- Latest live Firestore/Claude [smoke results](deploy/smoke-results.json) contain synthetic data only and were recorded against revision `chagok-api-00003-nbf`. See the [2026-11-13 verification report](docs/verification-2026-11-13.md): both APKs build, but vehicle integration is incomplete and a wrong-trip speech bug was reproduced. App/FE source was not changed.

The existing phone and Pleos applications still use demo repositories and adb broadcasts. This server implements their CONTRACT.md v1 payloads; mobile developers must connect HTTP transport. It does not modify or build the Android applications.

Official contest/Pleos documentation was cross-checked on 2026-11-13 after the initial implementation. These are Chagok's own REST APIs, with the vehicle app responsible for Pleos SDK calls. See the [official-guide comparison and FE integration notes (한국어)](docs/pleos-integration.md), including incomplete driving restrictions, audio focus, Gleo integration and emulator validation. Swagger includes this boundary and the TripPlan / DriveEvent / SpeakCommand response schemas.

## Implemented

- Invitation-only email/password registration and login (Argon2 hashes, 24-hour signed tokens).
- Account-owned phone/Pleos devices, one-use 5-minute pairing codes, device revocation.
- Persistent travel CRUD; server-generated trip IDs; account isolation on all resources.
- TripPlan and SpeakCommand polling with durable cursors, idempotent DriveEvent storage and phone event retrieval.
- Claude Sonnet 5.5: rank supplied places with source-preserving explanations, extract named places from supplied transcripts/descriptions with verbatim evidence, generate brief radio text from supplied facts, summarize recorded events.
- Per-account AI limit: 20 attempts/hour; limited login attempts; secrets injected from Secret Manager; no route history collected.

## API usage

Open `/docs` for interactive OpenAPI or `/openapi.json` for the contract.

1. `POST /v1/auth/register` with `X-Invite-Key` and `{ "email": "...", "password": "..." }`. Passwords must be at least 12 characters. The team invite is an administrator secret; never bundle it in an app. Accounts are provisioned by a trusted team administrator. Use `POST /v1/auth/login` thereafter.
2. All protected requests use `Authorization: Bearer <access_token>`. Account login tokens can manage trips, devices, pairing and AI. Device tokens can read the owner's trips, read only their own message queue and send/read events; they cannot manage accounts or trigger paid AI calls.
3. `POST /v1/devices` with `{ "name": "My Pleos", "kind": "pleos" }`, or create a pairing using `POST /v1/pairings`, transfer its code using a QR code or a trusted channel, then claim it at `POST /v1/pairings/claim` with `code`, `name`, `kind`. Device tokens expire after 24 hours; pair again when expired. Revocation takes effect immediately.
4. `POST /v1/trips` with the TripDraft fields and optional `visibility`. Response is the CONTRACT.md TripPlan, including its server `tripId`. Keep this ID for subsequent events.
5. `POST /v1/trips/{tripId}/stage?device_id={deviceId}` queues TripPlan. Pleos polls `GET /v1/devices/{deviceId}/messages?after={cursor}` every 5–10 seconds while active. Process up to 100 messages, persist `nextCursor` only after processing, and deduplicate by envelope `id`. The envelope `payload` is the original v1 JSON.
6. Pleos posts DriveEvent to `POST /v1/trips/{tripId}/events`; phone polls `GET /v1/trips/{tripId}/events`. Identical payloads are deduplicated. Unknown versions, mismatched trip IDs, non-UTC timestamps and unknown places are rejected. The client deduplicates events by their complete payload. This initial endpoint returns up to 1,000 events per trip.
7. `POST /v1/ai/recommendations` with `tripId` and `candidates` ranks up to 5 of those candidates. It never invents coordinates or opening hours. Approved candidate metadata is available to event validation. AI does not query a live places catalogue.
8. `POST /v1/trips/{tripId}/radio?device_id={deviceId}` with `place` and `facts` creates and queues a SpeakCommand. The caller decides when it is appropriate; Pleos still handles TTS, microphone interruption, and real navigation.
9. `POST /v1/ai/extract-places` accepts `text`, `source`, and `group` (좋아요/재생목록/구독/공유). Text must be supplied by the caller. This endpoint does not fetch URLs or access private video accounts.
10. `POST /v1/trips/{tripId}/summary` creates a textual summary and counts saved places/events. It does not mislabel approved waypoints as verified visits or infer mileage.

Trips/devices lists initially return up to 100 items. Phone and Pleos must handle HTTP 401 (login/pair again), 403 (wrong token capability), 404, 422, 429 (wait `Retry-After`), 502/503 (AI failure). Never substitute a generated success result after an upstream error.

## Pending external integrations

The following BACKEND.md items require additional implementation/configuration and are not claimed as working: YouTube OAuth/Data API and Takeout parsing; geocoding/live places and routing travel-time calculation; location-triggered radio scheduling; photo upload/storage and timeline matching; generated videos/booklets and share links; email verification/password recovery. `visibility` is stored but no public share endpoint exists. No location history is collected, even when `recordRoute` is true. Real navigation remains with Pleos SDK.

## Local checks

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m pytest -q
```

Tests use an in-memory store and mocked AI; the deployment smoke test separately exercises real Firestore and Claude. Production always uses Firestore, never local ephemeral SQLite.

## Deployment

Prerequisites: gcloud authenticated to the project; billing enabled; APIs `run`, `cloudbuild`, `artifactregistry`, `firestore`, `secretmanager`, `iam` enabled. Runtime identity `chagok-runtime` has `roles/datastore.user` and secret-level accessor grants. Build identity `chagok-builder` has `roles/run.builder`. No downloadable service-account key is needed.

Firestore `(default)` is Native mode in `asia-northeast3`. Composite indexes: messages (`deviceId ASC`, `cursor ASC`), events (`tripId ASC`, `payload.at ASC`). Enable TTL for `limits.expireAt`.

Secret Manager version 1: `chagok-anthropic`, `chagok-jwt`, `chagok-invite`. Values must be provisioned through a trusted secret flow; they are never part of this repository or container image. Explicit version pinning makes deployments reproducible; update the deployment flags when rotating a secret.

```powershell
./deploy/deploy.ps1 -Gcloud /path/to/gcloud.cmd
```

Cloud Run has application authentication and an internet-reachable HTTPS ingress for mobile clients. Only health/docs/auth/pair-claim are unauthenticated at the application layer. Minimum instances 0, maximum instances 2, 1 CPU, 512 MiB, request timeout 120 seconds. Cloud Run, Firestore, build/storage and Claude usage can incur charges. Scale and per-user quotas are not a hard billing cap.
