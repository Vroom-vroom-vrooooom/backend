# 2026-11-13 검증 결과

**판정: BE·Claude API 검증 통과. Phone → BE → Pleos 전체 연동은 미완료이며, 차량 앱에서 결함을 재현했다.**

앱·FE 소스는 수정하지 않았다. `phone`과 `pleos`는 검증 후에도 `git status --porcelain` 출력이 없고 HEAD가 동일하다. 이번 변경은 이 BE 저장소의 검증 스크립트·결과·문서에 한정된다. BE 런타임도 변경하거나 재배포하지 않았다.

## 검증 대상

| 대상 | 버전 |
| --- | --- |
| BE 소스 / 배포 | `717ca52` / API 1.0.1 / Cloud Run `chagok-api-00003-nbf` |
| Phone 소스 | `57804193a0b48e3c83fd591d32c734137820d8c0` |
| Pleos 소스 | `0620e6a97d3e0baeaf410b6409558fa04fd36499` |
| 빌드 | Gradle 8.9, AGP 8.5.2, JDK 21.0.10, Android API 34 / Build Tools 34.0.0 |
| 에뮬레이터 | 공식 Pleos Connect 2.1.0, Android 14, 2560×1440, RAM 4GB, WHPX, cold boot |
| SDK | NaviHelper 3.0.5, TextToSpeech 3.3.1 / ON_DEVICE |

[공식 설치 가이드](https://document.pleos.ai/docs/connect/guide/getting-started/application-development/setup-connect-sdk-emulator)의 이미지 저장소를 사용했고, 다운로드 SHA-1 `b4f858d5bcc6c71506d7edfc872bcb9e5a11acaa`를 공식 메타데이터와 대조했다. Windows 창 캡처는 화면 영역 오류로 실패하여 Android의 ADB 캡처·UI hierarchy·앱 로그로 실행 결과를 확인했다.

## 실행 결과

| 검사 | 결과 | 증거 / 범위 |
| --- | --- | --- |
| BE 자동 테스트 | 통과: 13개 | `python -m pytest -q`; 테스트 내 AI는 mock |
| 배포 서버 인증·저장·중계 | 통과 | 가입/로그인, 페어링 재사용 거부, 여행 저장, 메시지 폴링·커서, 이벤트 중복 제거·잘못된 이벤트 거부 |
| 기기 토큰 권한·철회 | 통과 | 기기 토큰의 계정 관리·AI 호출 403, 기기 철회 후 토큰 401 |
| 실제 Claude 호출 | 통과 | 추천, 라디오 대사, 장소 추출, 여행 요약. [실서버 결과](../deploy/smoke-results.json) |
| Swagger | 통과 | GPT 내장 브라우저에서 문서 표시 및 Try it out → `/health` HTTP 200 확인 |
| Cloud Run 오류 로그 | 없음 | 테스트 후 해당 revision의 최근 30분 ERROR 이상 조회 결과 `[]` |
| Phone APK / Lint | APK 생성 성공; Lint 오류 0·경고 15 | [Lint 원문](qa/2026-11-13/phone-lint.txt) |
| Pleos APK / Lint | APK 생성 성공; **Lint 오류 4·경고 9** | [Lint 원문](qa/2026-11-13/pleos-lint.txt) |
| Pleos 설치·cold launch | 통과 | `adb install` Success, `am start -W` Status ok. [실행 화면](qa/2026-11-13/01-launch.png) |
| 실제 Claude 대사 → 차량 표시 | 통과 | 실서버 응답을 ADB broadcast로 주입. [화면](qa/2026-11-13/02-live-claude.png) |
| Pleos TTS | SDK 재생 시작·완료 콜백 통과 | `doSpeak`, `onStart`, `onDone` 관측. 청취 품질·첫 음절 손실은 검증하지 않음 |
| NaviHelper | 서비스 연결 통과 | `onServiceConnected`, 서비스 버전 3.0.4, callback/listener 등록 관측. 경로 안내 실행은 미검증 |
| 잘못된 음성 메시지 | 통과: 3/3 거부 | 빈 문장, 버전 9, 깨진 JSON에 `Ignoring invalid SpeakCommand` |
| 다른 여행의 음성 메시지 | **실패** | 다른 tripId인데 표시·`doSpeak` 발생. [재현 화면](qa/2026-11-13/03-wrong-trip.png), [SDK 로그](qa/2026-11-13/pleos-runtime.txt) |

ADB는 아직 없는 앱의 HTTP 전달 계층을 테스트 목적으로 대신했다. 따라서 Claude 응답 표시와 TTS 콜백 성공을 앱·BE 종단 간 연결 성공으로 해석하면 안 된다. 테스트 계정·여행·기기는 정리했고 에뮬레이터도 종료했다.

## 확인된 문제와 남은 검증

1. **다른 여행의 SpeakCommand가 적용됨.** `CarActivity.kt:209–212`는 파싱 후 현재 `tripId`와 비교하지 않고 `showLine()`을 호출한다. 실제로 `tripId=different-trip-should-be-ignored`, `text=WRONG TRIP MESSAGE SHOULD NOT PLAY`를 보냈더니 화면과 TTS에 전달됐다. 재접속·여행 전환 시 잘못된 대사가 재생될 수 있다.
2. **앱의 HTTP 전달 계층이 없음.** Phone `DemoTripRepository.stageTrip()`은 logcat에 출력하고, Pleos `emit()`도 이벤트를 logcat에만 남긴다. 계정·페어링·큐 폴링·이벤트 POST가 연결되어 있지 않다. 최종 APK의 INTERNET 권한은 Phone에 없고 Pleos에는 SDK manifest 병합으로 존재한다.
3. **Pleos Lint 오류 4개.** `values/strings.xml:13,34`의 API 33 속성 `lineBreakWordStyle`, `CarActivity.kt:104`의 receiver flag 검사, `activity_car.xml:31`의 orientation 누락이다. receiver 오류는 API 버전 분기가 있는 코드에 대한 Lint 결과이며, Android 14 실행에서 해당 위치의 crash는 관찰하지 않았다.
4. **기존 장소 분류와 BE 검증 규칙 불일치.** 앱/QA fixture는 `저장`·`이야기`도 사용하지만 BE `Place.group`은 이를 거부한다. 현재 `좋아요`·`재생목록`·`구독`·`공유`·빈 문자열만 허용한다. [재현 결과](qa/2026-11-13/integration-checks.json)
5. **외부 웹 FE에서 직접 호출하려면 CORS 보완 필요.** `Origin: http://localhost:5173`, 요청 메서드 POST, 요청 헤더 authorization/content-type의 OPTIONS는 HTTP 405였고 Allow-Origin 헤더가 없었다. 같은 출처인 Swagger 및 네이티브 Android 호출과는 별도 문제다.
6. **내비 성공 표시를 SDK 결과와 구분해야 함.** `PleosNavi.addWaypoint()`는 요청 직후 경유지 수를 늘리고 true를 반환하며, `CarActivity`는 추가 성공 문구를 표시한다. 실제 SDK 결과에 따른 성공/실패 일치는 아직 검증하지 않았다.
7. **공식 주행 동작 검증은 남아 있음.** 앱에 CarUxRestrictions 처리가 없고 Gleo App Schema 연동도 없다. 앱 코드의 AudioFocusRequest/포커스 상실 처리는 확인되지 않았으며, SDK 내부 포커스 동작을 포함한 통화·Gleo·긴급 안내·suspend/resume 테스트는 수행하지 못했다. TTS 콜백 성공만으로 이 항목들을 통과 처리하지 않았다. [공식 가이드 대조표](pleos-integration.md)

## APK 식별 정보

APK는 로컬 검증 산출물이며 이 저장소에 업로드하지 않았다.

| APK | SHA-256 |
| --- | --- |
| Pleos debug | `eb50200f6871b5b36ee0effb8de53cd95187fa6f9b4f622a7be4403ff57a4c6a` |
| Phone debug | `2a81cb3b510fc8dba8fe25bfefca111b177f8844717bc7c9b56bfa6a54d000e1` |
