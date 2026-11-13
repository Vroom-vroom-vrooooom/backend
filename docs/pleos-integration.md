# Pleos 공모전 공식 가이드 대조와 FE 연동

확인일: 2026-11-13. 서버 최초 구현은 팀의 `BACKEND.md`·`CONTRACT.md`를 기준으로 했고, 이후 아래 공식 문서와 대조했다. 이 문서는 구현 현황이며 공모전 심사 통과나 차량 동작 인증을 뜻하지 않는다.

## API의 역할

[공모전 개발 환경 가이드](https://appdevchallenge.auto-hmg.io/guide/development)는 차량 앱의 Pleos SDK 사용과 개발 환경을 안내한다. 검토한 문서에 차곡의 로그인·여행·Claude용 REST URL이나 JSON 규격은 정의되어 있지 않다. 이 저장소의 `/v1/*` 및 `TripPlan`, `SpeakCommand`, `DriveEvent`는 **차곡 자체 규격**이다.

흐름은 `Phone → 차곡 BE/Claude → Pleos 차량 앱 → Pleos SDK`이다. BE는 여행 저장, AI 대사 생성, 기기별 메시지 전달을 담당한다. 차량 앱이 실제 내비게이션·음성 재생·차량 UX 제한을 처리한다. HTTP 200이나 `messageId`는 차량에서 실행됐다는 확인이 아니다.

## 공식 문서와 현재 구현

Android 소스 검토 기준: [pleos 0620e6a](https://github.com/Vroom-vroom-vrooooom/pleos/tree/0620e6a97d3e0baeaf410b6409558fa04fd36499). 서버의 자동 테스트와 Cloud Run 검증은 Android/SDK 검증을 대신하지 않는다.

후속 [실행 검증 보고서](verification-2026-11-13.md): 앱 소스 변경 없이 두 APK를 빌드하고 Pleos 에뮬레이터에서 Claude 대사 표시·TTS 콜백을 확인했다. 다른 여행 메시지 처리 버그와 Lint 오류를 재현했으며, 실제 HTTP 종단 간 연결과 주행 안전 시나리오는 여전히 미완료다.

| 항목 | 공식 기준 | 현재 상태 및 후속 작업 |
| --- | --- | --- |
| 개발 환경 | 공모전 가이드: Android API 28+, Gradle 8+, Java/Kotlin | 차량 앱 `minSdk 28`, Kotlin. 후속 검증에서 Gradle 8.9 APK 빌드와 공식 에뮬레이터 실행 확인. Lint는 오류 4개로 실패했다. |
| 내비게이션 | [NaviHelper 3.0.5](https://document.pleos.ai/docs/pleos-only/connect-sdk-pleos/NaviHelper/intro), [경로 요청 결과는 콜백으로 확인](https://document.pleos.ai/docs/pleos-only/connect-sdk-pleos/NaviHelper/route-with-waypoints) | 앱 의존성 버전은 일치한다. BE는 TripPlan을 전달한다. `PleosNavi.kt`는 좌표를 SDK에 전달하지만, `addWaypoint()` 호출 반환 직후 표시하는 성공 문구·경유지 수는 실제 SDK 결과와 일치하도록 후속 보완이 필요하다. |
| 활성 경유지 | [최대 2개, FIRST/SECOND](https://document.pleos.ai/docs/pleos-only/connect-sdk-pleos/NaviHelper/waypoint-settings) | 전체 여행 목록은 BE에 최대 100개 저장 가능하다. 이를 SDK 활성 경유지로 그대로 보내지 않는다. 앱은 현재 좌표 있는 장소 중 마지막을 목적지, 앞의 최대 두 곳을 경유지로 선택한다. 그 밖의 장소가 자동으로 모두 안내되지는 않는다. |
| 음성 합성 | [TTS 3.3.1의 ON_DEVICE는 서버 앱 등록 불필요; HYBRID/SERVER는 등록 필요](https://document.pleos.ai/docs/pleos-only/connect-sdk-pleos/TextToSpeech/intro) | 차량 앱은 3.3.1 / ON_DEVICE를 사용한다. Claude는 대사 생성용이고 Pleos TTS 자격 증명을 대체하지 않는다. 서버 합성으로 전환하면 별도 Playground 등록이 필요하다. |
| 주행 UX 제한 | [CarUxRestrictionsManager와 ActiveRestrictions 적용](https://document.pleos.ai/docs/pleos-only/vehicle-app-developer-guide/driving-restriction-development-guide) | 앱에 해당 처리와 distraction-optimized 선언이 없다. 현재 주차 상태 프로토타입이다. 주행 중 사용 가능한 앱이라고 표현하면 안 된다. 선언만 추가하는 것으로 충족되지 않는다. |
| 오디오 포커스 | [재생 전 포커스 요청 및 상실·획득 처리](https://document.pleos.ai/docs/pleos-only/vehicle-app-developer-guide/audio-focus-development-guide/audio-focus-development) | 앱은 통화 모드·마이크 사용을 관찰하지만 AudioFocusRequest 처리는 없다. Gleo·통화·긴급 안내와의 실제 포커스 상호작용을 구현·검증해야 한다. |
| Gleo 음성 명령 | [App Schema와 Action/Callback 연동](https://document.pleos.ai/docs/pleos-only/app-integration-guide/guide/core-concepts) | 미구현. Claude REST 호출이나 마이크 감시는 Gleo 연동 완료가 아니다. |
| 음성 출력 시작 | [선행 묵음 150–200ms 권장](https://document.pleos.ai/docs/pleos-only/vehicle-app-developer-guide/voice-guidance-preroll-silence-guide) | BE는 텍스트만 생성한다. 차량 TTS 출력 경로에서 적용 여부와 첫 음절 손실을 확인해야 한다. 임의 공백·문장 부호 추가로 처리하지 않는다. |
| 계정·개인정보 | [계정 전환·안전한 토큰 저장·최소 수집](https://document.pleos.ai/docs/pleos-only/vehicle-app-planning-guide/security-privacy) | BE는 계정별 접근 제어, 기기 철회, 서버 측 Secret Manager를 사용한다. 위치 이력을 수집하지 않는다. 차량 Keystore 저장·로그아웃·동의 UI는 아직 연결되지 않았다. |

## FE에서 지켜야 할 계약

1. `/docs`의 Authorize에 로그인 `access_token`을 넣는다. 계정 토큰은 여행·기기·AI 관리용, 기기 토큰은 허용된 조회·이벤트용이다. 차량에 계정 관리자 토큰이나 Claude 키를 넣지 않는다.
2. `/stage` 성공 후 차량이 자신의 `/messages`를 폴링한다. `id`로 중복을 제거하고 처리 후 `nextCursor`를 저장한다. `cursor`는 그대로 전달하는 문자열이다. `created`는 Unix nanoseconds이므로 JavaScript Number로 커서를 재구성하지 않는다.
3. `TripPlan.places`의 `lat`/`lng`는 함께 있어야 한다. 없는 좌표는 생성해서 채우지 않는다. 좌표 없는 장소는 목록 표시·저장용이다. SDK에 전달할 목적지와 활성 경유지는 차량에서 선택한다.
4. `SpeakCommand`는 재생 요청 데이터다. 서버에는 현재 메시지 만료 기능이 없다. 재접속·여행 변경 후 오래된 대사를 일괄 재생하지 않도록 현재 여행과 맥락을 확인한다. 재생 시점의 Audio Focus와 차량 제한은 로컬에서 처리한다.
5. `/radio` 응답의 `command`와 메시지 큐에는 같은 대사가 들어간다. 응답의 `messageId`와 큐의 `id`로 중복 재생을 막는다.
6. `WAYPOINT_APPROVED`는 사용자의 승인이다. SDK 경로 설정 성공이나 실제 방문으로 표시하지 않는다. v1 이벤트에는 SDK 성공/실패 전용 타입이 없으므로 임의 타입을 보내면 422가 된다. 앱에서는 SDK 콜백으로 성공·실패를 처리하고, 서버에 필요해지면 별도 계약을 합의한다.
7. `recordRoute=true`는 현재 저장된 선호값일 뿐이며 위치 기록은 작동하지 않는다. `visibility=link`도 저장만 하며 공유 URL 기능은 아직 없다.

## 제출 전 남은 차량 검증

- Phone/차량 앱의 HTTP 연결과 INTERNET 권한, 토큰 저장·재인증·기기 철회·로그아웃.
- 실제 SDK 콜백에 따른 경로 성공/실패, 좌표 누락·경유지 초과·네트워크 재접속 처리.
- 주차/주행 전환 시 UX 제한, Gleo·통화·긴급 안내 시 오디오 정지와 복귀, suspend/resume 시 오래된 음성 처리.
- [공식 폼팩터 테스트 가이드](https://document.pleos.ai/docs/pleos-only/app-test-guide/form-factor-test-guide)에 따른 에뮬레이터 검증 및 결과 기록.

[공모전 FAQ](https://appdevchallenge.auto-hmg.io/faq)는 2차 PT 전 실제 동작하는 앱을 요구한다. 현재 BE 테스트 통과만으로 이 조건을 충족했다고 볼 수 없다. GitHub를 개발 산출물로 제출할 경우 공개 기간·커밋 지정 또는 소스/APK 압축파일 대안도 FAQ를 확인한다.
