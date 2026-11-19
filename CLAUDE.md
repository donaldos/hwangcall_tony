# CLAUDE.md — 마누라프로젝트 (타로 전화상담 보조 웹앱)

이 문서는 Claude Code가 이 저장소에서 작업할 때 따르는 기준이다. 설계 판단이 애매하면 이 문서를 우선한다.

## 1. 프로젝트 개요

타로 전화상담사(사용자 본인, 이하 "상담사")를 돕는 로컬 웹앱.

- 상담사는 안드로이드폰을 **스피커폰**으로 두고 통화한다.
- 맥북 내장 마이크가 통화 소리(고객 + 상담사)를 그대로 녹음한다.
- 녹음하는 동안 음성인식 결과가 화면에 실시간 자막으로 표시된다.
- 상담사가 **[중단]** 을 누르면 그때까지의 전사문(+선택한 타로 카드)을 LLM에 보내고, 답변 초안을 스트리밍으로 화면에 보여준다.
- 상담사는 답변 초안을 참고해 직접 말로 상담한다. 앱이 고객에게 직접 말하지 않는다.

### 핵심 사용 흐름

```
[녹음 시작] → 실시간 자막 표시 → [중단] → STT 최종 결과 확정
           → (타로 카드 선택, 선택사항) → LLM 답변 스트리밍 표시
           → [이어서 녹음] 또는 [새 상담]
```

- 한 상담(Session)은 여러 번의 "녹음 → 중단 → 답변" 라운드(Turn)로 이루어진다.
- LLM에는 **해당 세션의 누적 전사문 전체**와 이전 답변들을 맥락으로 보낸다.

### 의도적으로 하지 않는 것 (현재 범위 밖)

- 통화 음성을 채널 단위로 분리하는 하드웨어 연동 (오디오 인터페이스, 블루투스 믹서 등)
- 화자 분리(diarization) — MVP에서는 하지 않는다. 섞인 전사문을 LLM이 문맥으로 해석한다. (8장 참고)
- 클라우드 배포, 다중 사용자, 로그인
- 네이티브 앱(데스크톱·모바일), Electron 등 앱 패키징 — **앱은 로컬 웹앱(브라우저 + localhost 서버)으로만 만든다**
- TTS(답변 음성 출력)

## 2. 실행 환경

- 운영 기기: **macOS (맥북)**, 브라우저는 **Chrome** 기준.
- 개발은 **Windows 11**에서도 한다. 코드·스크립트는 OS 중립으로 작성하고(경로는 `pathlib`, 셸 전용 명령에 의존 금지), 명령 예시는 macOS/Windows 둘 다 적는다.
- 서버와 브라우저는 같은 기기에서 돈다 (`localhost`). 외부 노출하지 않는다.
- Python 3.12, 패키지/가상환경 관리는 **uv**. 가상환경은 `.venv/`(uv 기본값)를 쓴다. **`.env`는 설정 파일 이름이므로 가상환경 폴더명으로 쓰지 않는다.**
- 저장소 루트 폴더 이름은 무관하다(`hwangclient` 등). 파이썬 패키지 이름은 `manura`로 고정한다.
- 마이크 권한: `localhost`는 보안 컨텍스트라 `getUserMedia`가 동작한다. 다른 호스트로 접속할 일이 생기면 HTTPS가 필요하다.

## 3. 기술 스택

| 영역 | 선택 | 비고 |
|---|---|---|
| 백엔드 | FastAPI + Uvicorn | async 기반, WebSocket/SSE 지원 |
| 프론트엔드 | 정적 HTML + Vanilla JS (빌드 도구 없음) | `web/` 아래를 FastAPI가 정적 서빙 |
| 오디오 캡처 | `getUserMedia` + `AudioWorklet` | 16kHz mono PCM16으로 변환해 WebSocket 전송 |
| 실시간 전송 | WebSocket (`/ws/audio`) | 오디오 업로드 + 자막 이벤트 수신을 한 연결로 |
| LLM 응답 | SSE (`/api/sessions/{id}/advise`) | 토큰 스트리밍 |
| STT | 어댑터로 교체 가능 (기본: OpenAI Realtime API 전사) | 4장 참고 |
| LLM | 어댑터로 교체 가능 (기본: OpenAI) | 4장 참고 |
| 저장소 | SQLite (`aiosqlite`) | 세션·전사·답변 로컬 저장 |
| 설정 | `pydantic-settings` + `.env` | 키·모델명 하드코딩 금지 |
| 품질 | ruff (lint+format), mypy(strict), pytest + pytest-asyncio | |

새 의존성을 추가할 때는 이유를 커밋 메시지에 한 줄 남긴다. 무거운 프레임워크(React, Celery 등)는 도입하지 않는다.

## 4. 아키텍처 — 포트와 어댑터

도메인 로직은 외부 엔진(STT, LLM, DB)을 모른다. 외부 엔진은 **Protocol(포트)** 뒤에 숨기고, 구현체(어댑터)는 설정으로 고른다.

```
web (브라우저)
  │  WebSocket: PCM 업로드 / 자막 이벤트
  │  REST + SSE: 세션·카드·답변
  ▼
api (FastAPI 라우터)        ← 입출력 변환만. 비즈니스 로직 금지
  ▼
services (유스케이스)       ← RecordingService, AdviceService
  ▼
domain (모델 + 포트)        ← Session, Turn, Utterance, TarotCard / STTEngine, LLMAdvisor, SessionRepository
  ▲
adapters (구현체)           ← stt/openai_realtime.py, stt/fake.py, llm/openai.py, llm/fake.py, repo/sqlite.py
```

### 포트 정의 (domain/ports.py)

```python
from typing import AsyncIterator, Protocol


# 스트리밍 메서드는 Protocol에서 `async def`가 아니라 `def ... -> AsyncIterator`로 선언한다.
# 구현체는 `async def` + `yield`(async generator)로 쓰며, 이렇게 해야 mypy --strict에서 타입이 맞는다.
class STTEngine(Protocol):
    def transcribe(self, pcm: AsyncIterator[bytes]) -> AsyncIterator[TranscriptEvent]:
        """16kHz mono PCM16 청크를 받아 부분(partial)/최종(final) 결과를 흘려보낸다.
        입력 스트림이 끝나면 남은 최종 결과를 모두 내보낸 뒤 종료한다."""


class LLMAdvisor(Protocol):
    def advise(self, ctx: AdviceContext) -> AsyncIterator[str]:
        """세션 전사문·카드·이전 답변을 받아 답변 텍스트를 토큰 단위로 스트리밍한다."""


class SessionRepository(Protocol):
    async def create_session(self) -> Session: ...
    async def append_utterances(self, session_id: str, items: list[Utterance]) -> None: ...
    async def save_turn(self, session_id: str, turn: Turn) -> None: ...
    async def get_session(self, session_id: str) -> Session: ...
```

### 규칙

- `api/`는 `services/`만 호출한다. 어댑터를 직접 import하지 않는다.
- 어댑터 선택과 조립은 `src/manura/container.py` 한 곳에서만 한다 (`STT_ENGINE=openai|fake`, `LLM_PROVIDER=openai|fake`). 다른 공급자가 필요해지면 어댑터 파일 하나와 선택지 하나만 추가한다.
- 모든 어댑터는 fake 구현을 함께 둔다. 테스트와 오프라인 개발은 fake로 한다.
- 외부 SDK 예외는 어댑터 안에서 도메인 예외(`STTError`, `LLMError`)로 바꿔서 올린다.

### STT 어댑터 메모

- 기본 엔진은 **OpenAI Realtime API의 전사(transcription) 전용 세션**이다. 서버(파이썬)가 OpenAI에 WebSocket으로 붙는다. 브라우저가 OpenAI에 직접 붙지 않는다 (API 키를 브라우저에 노출하지 않기 위해서다).
- 엔드포인트, 이벤트 이름, 세션 설정 필드는 **구현 시점의 OpenAI 공식 문서를 확인해서 따른다.** 기억에 의존해 추측하지 않는다. 확인하지 못한 부분은 `TODO(openai-stt)`로 표시한다.
- 모델명은 `.env`의 `OPENAI_STT_MODEL`에서 읽는다 (기본 `gpt-live-transcribe` — 스트리밍 권장 모델, 2026-11 확인). 언어는 `OPENAI_STT_LANGUAGE=ko`로 전달한다. 키는 LLM과 같은 `OPENAI_API_KEY`를 쓴다.
- 이벤트 매핑: 전사 delta 이벤트는 `partial`, completed 이벤트는 `final`로 바꾼다. partial은 아직 확정되지 않은 텍스트 전체를 누적해서 보낸다.
- 서로 다른 commit의 completed는 순서가 뒤바뀌어 올 수 있다. `item_id`로 맞추고 **commit 순서대로** final을 내보낸다 (`TranscriptAssembler`).
- Realtime 입력 오디오는 **24kHz PCM16 mono**다. 브라우저는 계속 16kHz를 보내고, 16k→24k 리샘플링은 어댑터 안에서 한다 (포트 계약은 16kHz 고정).
- `gpt-live-transcribe`는 **서버 VAD를 지원하지 않는다** (`turn_detection: null`). 그래서 어댑터 안의 `Segmenter`가 에너지 기반으로 commit 시점을 정한다: 발화 뒤 무음이 `STT_VAD_SILENCE_MS` 이어지거나, 구간이 `STT_MAX_SEGMENT_MS`를 넘으면 commit한다. 스피커폰 음성은 작으므로 `STT_VAD_THRESHOLD_DBFS`는 실측으로 조정한다.
- 입력 스트림이 끝나면 남은 오디오를 commit하고(`STT_MIN_COMMIT_MS` 이상일 때), 보낸 commit이 모두 completed/failed될 때까지 받은 뒤 종료한다.
- 엔진이 요구하는 샘플레이트가 16kHz가 아니면 리샘플링은 어댑터 안에서 처리한다 (브라우저는 항상 16kHz PCM16을 보낸다).
- WebSocket 연결 하나에서 start/stop을 여러 번 반복할 수 있다. **`start`마다 새 Turn을 열고 `transcribe()`를 새로 호출**한다 (한 번의 transcribe = 한 번의 녹음 구간).
- Realtime 세션에는 최대 길이 제한이 있다. 녹음 구간이 그보다 길면 어댑터 안에서 엔진 연결을 이어 붙인다 (서비스 계층은 모른다). 제한값은 공식 문서를 확인한 뒤 `config.py`에 둔다.
- 중단 시: 브라우저가 `{"type":"stop"}`을 보낸다 → 서버는 오디오 입력 스트림을 닫는다 → 엔진의 최종 결과를 모두 받는다 → `{"type":"stopped","turn_id":"..."}`를 보낸 뒤 LLM 요청이 가능해진다. **최종 결과를 다 받기 전에 LLM을 호출하지 않는다.**
- 최종 결과 대기는 `STT_FINALIZE_TIMEOUT_MS`를 넘기면 받은 데까지만 확정하고 `stopped`를 보낸다 (통화 중 화면이 멈추는 것이 최악의 실패다).

### LLM 어댑터 메모

- STT와 LLM 모두 OpenAI를 쓰고, 키는 `OPENAI_API_KEY` 하나다. 모델명·온도·최대 토큰은 전부 `.env`에서 읽는다 (`OPENAI_LLM_MODEL`, `OPENAI_STT_MODEL`, ...).
- 공식 `openai` 파이썬 SDK의 async 클라이언트(`AsyncOpenAI`)로 스트리밍 호출한다. API 형태(Responses / Chat Completions)와 파라미터 이름은 구현 시점의 공식 문서를 확인한다.
- 프롬프트는 코드에 문자열로 박지 않고 `prompts/` 아래 파일(`system.md`, `user_template.md`)로 관리한다. 템플릿 렌더링은 `AdviceService`가 한다.
- 스트리밍 도중 오류가 나면 지금까지 받은 텍스트는 보존하고, SSE로 `event: error`를 보낸다.
- 매 요청마다 누적 전사문 전체를 보내므로 상담이 길어질수록 첫 토큰 지연·비용이 커진다. OpenAI의 **prompt caching**은 요청 앞부분(prefix)이 이전 요청과 같을 때 자동으로 적용된다. 그래서 메시지 순서를 "시스템 프롬프트 → 이전 턴까지의 전사문·답변 → 이번 턴 전사문·카드"로 고정하고, 앞부분에는 매번 바뀌는 값(시각, 랜덤 ID 등)을 넣지 않는다. `user_template.md`도 이 순서를 지킨다.

## 5. 디렉터리 구조

```
(저장소 루트)/
├── CLAUDE.md
├── pyproject.toml
├── .env                      # 설정 파일 (git 제외)
├── .env.example              # 키는 비워둔 예시만 커밋
├── .venv/                    # uv 가상환경 (git 제외)
├── prompts/
│   ├── system.md             # 상담 보조 역할, 출력 형식, 금지사항
│   └── user_template.md      # 전사문·카드·이전 답변을 끼워 넣는 템플릿
├── src/manura/
│   ├── main.py               # FastAPI 앱 생성, 정적 파일 마운트
│   ├── config.py             # pydantic-settings
│   ├── container.py          # 어댑터 조립 (DI)
│   ├── domain/
│   │   ├── models.py         # Session, Turn, Utterance, TarotCard, TranscriptEvent, AdviceContext
│   │   ├── ports.py
│   │   └── errors.py
│   ├── services/
│   │   ├── recording.py      # 오디오 스트림 ↔ STT ↔ 저장 ↔ 자막 이벤트
│   │   └── advice.py         # 컨텍스트 구성 → LLM 스트리밍 → 저장
│   ├── adapters/
│   │   ├── stt/{openai_realtime.py, segmenter.py, resample.py, fake.py}
│   │   ├── llm/{openai.py, fake.py}
│   │   └── repo/sqlite.py
│   └── api/
│       ├── ws_audio.py       # /ws/audio
│       ├── client_config.py  # GET /api/client-config (마이크 설정·샘플레이트를 브라우저에 전달)
│       ├── sessions.py       # 세션 생성·조회, 카드 선택
│       └── advise.py         # SSE
├── web/
│   ├── index.html
│   ├── app.js                # UI 상태 머신
│   ├── audio/pcm-worklet.js  # 장치 샘플레이트→16k 다운샘플 + Int16 변환
│   └── style.css
├── data/                     # SQLite DB, (선택) 녹음 wav — git 제외
└── tests/
    ├── fixtures/*.wav        # 테스트용 녹음 (실제 고객 음성 금지)
    ├── unit/
    └── integration/
```

## 6. 프론트엔드 규칙

### UI 상태 머신 (app.js)

오디오 상태와 AI 의견 요청은 **따로 돈다.** AI가 답하는 동안에도 다음 녹음을 시작할 수 있다 (통화는 계속 이어지므로).

```
오디오: idle ──[녹음]──▶ recording ──[중단]──▶ finalizing ──(stopped 수신)──▶ idle
        recording/finalizing ──(WS 끊김·error 이벤트·타임아웃)──▶ idle + 오류 토스트
AI 의견: stopped(확정 문장 있음) ──▶ 요청 (턴마다 독립, 여러 개 동시 진행 가능)
[신규상담]: 오디오 idle일 때만. 진행 중 AI 요청은 취소, 저장 안 한 내용이 있으면 확인
```

- 버튼 활성/비활성은 상태로만 결정한다. 녹음/중단은 버튼 하나로 토글하고, finalizing 동안은 비활성.
- 오류가 나도 그때까지의 대화는 화면에 남긴다. 무엇이 실패했는지 토스트로 한 줄 보여준다.
- 기본 동작: **[중단]을 누르면 STT 확정 후 자동으로 답변 요청**까지 이어진다 (설정으로 끌 수 있게 `autoAdvise` 플래그).
- 자동 답변 뒤에 카드를 고르거나 바꾸면 **[카드 반영해 다시 답변]** 버튼으로 같은 턴에 답변을 재요청한다 (새 답변이 이전 답변을 대체한다).

### 오디오 캡처 설정

스피커폰 소리는 멀리서 작게 들어오므로 브라우저 음성처리가 오히려 해가 될 수 있다. 기본값:

```js
navigator.mediaDevices.getUserMedia({
  audio: {
    channelCount: 1,
    echoCancellation: false,  // 맥이 재생하는 소리가 없으므로 불필요
    noiseSuppression: false,  // 먼 거리 음성을 잡음으로 지울 위험
    autoGainControl: true,    // 스피커폰 볼륨 편차 보정 — 실측 후 조정
  },
});
```

- 이 값들은 `config`로 노출해서 실제 통화로 비교하며 조정한다.
- 화면에 **입력 레벨 미터**를 둔다. 상담사가 폰 위치와 볼륨을 맞출 수 있게.
- AudioWorklet은 100ms(1,600 샘플) 단위로 PCM16을 WebSocket에 바이너리 프레임으로 보낸다.
- 장치 샘플레이트를 48kHz로 가정하지 않는다 (맥은 44.1kHz도 흔하다). 우선 `new AudioContext({ sampleRate: 16000 })`로 브라우저에 리샘플링을 맡기고, 안 되면 worklet 전역 `sampleRate`로 비율을 계산해 다운샘플한다.

### 화면 구성

화면 높이를 세로 세 칸으로 나눈다.

1. **위 15% — 상담자(고객) 정보**: 호칭·나이·성별·특징·고민 내역 입력, [적용] [신규상담] [저장].
   - [적용]한 값만 프롬프트(`{{profile}}`)에 들어간다. 적용 후 고치면 "변경됨 · 적용 필요"로 표시한다.
   - [저장]은 LLM으로 **최종 세션 정리**(고민 요약 / 상담 흐름 / 고객 특징 / 다음 참고점, `prompts/summary_*.md`)를 만든 뒤, 상담자 정보 + 시간 + 대화 전체 + 정리를 SQLite(`data/manura.db`)의 `sessions` / `session_entries` 테이블에 저장한다.
   - 같은 상담을 다시 저장하면 같은 기록을 갱신한다 (ID: `{시각}-{임의6자}`, 고객 정보 금지). 정리 생성이 실패하거나 `SUMMARY_TIMEOUT_S`를 넘겨도 대화 기록은 저장한다.
2. **가운데 65% — 대화(카톡형)**: 녹음 구간마다 왼쪽 말풍선(통화 인식, partial은 회색), 그 뒤에 오른쪽 말풍선(AI 의견, 스트리밍)을 차례로 쌓는다.
   - 바닥 근처를 보고 있을 때만 자동 스크롤한다. 위로 올려 읽는 중이면 [새 내용 ↓] 버튼만 띄운다.
3. **아래 20% — 오디오 컨트롤**: 상태, dB 레벨 미터, 녹음/중단 토글 버튼, 고지 문구.

- 타로 카드 선택 UI(78장, 정/역방향)는 로드맵 7단계에서 이 구조 안에 넣는다.
- 글자는 크게. 상담 중 한눈에 읽혀야 한다.

## 7. WebSocket / API 계약

### `/ws/audio?session_id=...`

- 클라이언트 → 서버: 바이너리 프레임 = PCM16 16kHz mono, 텍스트 프레임 = `{"type":"start"}` / `{"type":"stop"}`
- 서버 → 클라이언트 (텍스트 JSON):
  - `{"type":"partial","text":"..."}`
  - `{"type":"final","text":"...","start_ms":0,"end_ms":0}`
  - `{"type":"started","turn_id":"..."}` — `start` 수신 시 새 Turn 생성
  - `{"type":"stopped","turn_id":"..."}` — 해당 Turn의 최종 결과 전송 완료
  - `{"type":"error","code":"STT_UNAVAILABLE","message":"..."}`

### Turn

- Turn은 서버가 `start` 시점에 만들고 `turn_id`를 돌려준다. 그 녹음 구간의 발화(Utterance), 선택 카드, 답변은 모두 이 `turn_id`에 묶인다.
- 클라이언트는 `stopped`로 받은 `turn_id`로 카드 지정과 답변 요청을 한다. "현재 라운드" 같은 암묵적 상태에 기대지 않는다.

### REST

- `POST /api/sessions` → 새 세션
- `GET /api/sessions/{id}` → 턴별 전사문·카드·답변 이력
- `PUT /api/sessions/{id}/turns/{turn_id}/cards` → 해당 턴의 선택 카드
- `POST /api/sessions/{id}/turns/{turn_id}/advise` (SSE 응답) → `event: token` / `event: done` / `event: error`
  - **현재(세션·SQLite 도입 전)는 `POST /api/turns/{turn_id}/advise`** 이고, 전사문은 메모리(`adapters/repo/memory.py`)에만 있다. 세션이 들어오면 위 경로로 옮긴다.
- `GET /api/client-config` → 브라우저용 설정 (샘플레이트, 청크 길이, `auto_advise`, 마이크 처리 옵션)

### 답변 스트리밍 규칙

- 답변 요청은 LLM 호출·저장이라는 부작용이 있으므로 **POST**다. 브라우저는 `EventSource`가 아니라 **`fetch` + `ReadableStream`** 으로 SSE 본문을 읽는다. (`EventSource`는 끊기면 자동 재연결해서 LLM을 중복 호출한다.)
- 같은 턴에 답변 생성이 진행 중이면 새 요청은 `409`로 거절한다. 완료된 턴에 다시 요청하면(카드 변경 후 재요청) 새 답변으로 대체 저장한다.

메시지 스키마는 `domain/models.py`의 Pydantic 모델로 정의하고 api 계층에서 그대로 쓴다. 문자열 dict를 손으로 만들지 않는다.

## 8. 화자 혼재 처리 (MVP 방침)

스피커폰 + 맥북 마이크 한 개라서 고객과 상담사 목소리가 **한 채널에 섞인다.** MVP에서는 이렇게 처리한다.

1. 전사문은 화자 구분 없이 시간순으로 저장한다.
2. 시스템 프롬프트에 "전사문에는 상담사와 고객의 발화가 섞여 있고 화자 표시가 없다. 문맥으로 고객의 고민을 추려서 답하라"고 명시한다.
3. LLM 출력 형식 맨 앞에 **"고객 고민 요약 (1~2줄)"** 을 두어 상담사가 LLM이 제대로 이해했는지 바로 확인할 수 있게 한다.

나중에 정확도가 문제가 되면 아래 순서로 확장한다 (지금은 구현하지 않는다).
- 상담사 음성을 미리 등록해 두고, 화자 임베딩으로 상담사 구간에 표시하기 (`Utterance.speaker` 필드는 지금부터 두되 기본값은 `"unknown"`)
- 하드웨어로 채널 분리 (오디오 인터페이스) — `STTEngine` 포트는 그대로 둔 채 입력만 교체

## 9. LLM 프롬프트 원칙 (prompts/system.md에 반영)

- 역할: 타로 상담사를 돕는 보조자. 고객에게 직접 말하는 것이 아니라 **상담사가 읽고 자기 말로 전할 초안**을 쓴다.
- 출력 형식 (고정):
  1. 고객 고민 요약 (1~2줄)
  2. 카드 해석 (선택된 카드가 있을 때, 카드별 1~2줄)
  3. 상담 답변 초안 (말하듯이, 3~6문장)
  4. 이어서 물어볼 질문 1~2개
- 짧게. 상담사가 통화 중에 10초 안에 읽을 수 있는 분량을 목표로 한다.
- 금지: 의료·법률·투자에 대한 단정적 조언, 공포를 주는 표현, 추가 결제·상품 유도. 자해·위기 신호가 전사문에 보이면 답변 맨 위에 **[주의]** 표시와 함께 전문기관 안내를 권하는 문구를 넣는다.
- 프롬프트를 수정할 때는 `tests/fixtures/`의 샘플 전사문으로 결과를 비교해 본다.

## 10. 개인정보·보안

- 고객 음성과 전사문은 민감정보다. **로컬(`data/`)에만 저장**하고 git에 절대 올리지 않는다 (`.gitignore`에 `data/`, `.env`, `*.wav` 단 `tests/fixtures/` 예외).
- 원본 오디오 저장은 기본 꺼둔다 (`SAVE_AUDIO=false`). 켜면 세션 폴더에 wav로 저장.
- 로그에 전사문 전체나 API 키를 남기지 않는다. 로그에는 세션 ID, 길이, 지연시간 같은 메타데이터만 남긴다.
- **외부 STT(OpenAI)에는 고객 음성이, 외부 LLM에는 고객 발화 전사문이 전송된다.** 통화 시작 시 고객 고지·동의 절차는 운영상 필요하다 (코드 범위 밖이지만 UI에 상기 문구를 둔다).
- 보관 기간을 둔다: `RETENTION_DAYS`(기본 30)가 지난 세션은 서버 시작 시 전사문·답변·오디오를 삭제한다. 세션 단위 즉시 삭제(`DELETE /api/sessions/{id}`)도 제공한다.
- 서버는 `127.0.0.1`에만 바인딩한다.

## 11. 코딩 컨벤션

- 모든 함수에 타입 힌트. `mypy --strict` 통과.
- I/O는 전부 async. 동기 SDK를 써야 하면 `asyncio.to_thread`로 감싼다.
- 도메인 모델은 Pydantic v2 `BaseModel` (불변이 자연스러운 값 객체는 `frozen=True`).
- 함수는 짧게, 한 가지 일만. 서비스 메서드가 50줄을 넘으면 나눈다.
- 매직 넘버 금지 — 샘플레이트, 청크 크기, 타임아웃은 `config.py`에.
- 주석은 "왜"를 쓴다. "무엇"은 코드로 드러나게.
- 커밋 단위는 작게, 메시지는 한국어 가능: `feat(stt): OpenAI Realtime 전사 어댑터 추가`.

## 12. 테스트

- 단위 테스트: 서비스 계층을 fake 어댑터로 테스트한다 (네트워크 없이).
- 통합 테스트: `tests/fixtures/*.wav`를 청크로 잘라 `/ws/audio`에 흘려보내고, fake STT → fake LLM까지 전체 흐름(시작→중단→stopped→advise)을 검증한다.
- 실제 엔진 테스트는 `@pytest.mark.live`로 분리하고 기본 실행에서 제외한다 (키가 있을 때만 수동 실행).
- fixture 녹음은 직접 녹음한 연기 음성만 쓴다. 실제 고객 통화는 넣지 않는다.

## 13. 자주 쓰는 명령

Windows에서 uv가 PATH에 없으면 `uv` 대신 `py -m uv`로 실행한다.

```bash
uv sync                                   # 의존성 설치 (.venv 생성)
cp .env.example .env                      # 키 설정  (Windows: Copy-Item .env.example .env)
uv run uvicorn manura.main:app --reload --host 127.0.0.1 --port 8000
open http://localhost:8000                # Chrome으로 열기 (Windows: start http://localhost:8000)

uv run ruff check . && uv run ruff format .
uv run mypy src
uv run pytest                             # live 제외
uv run pytest -m live                     # 실제 STT/LLM 연동 확인
```

## 14. 작업 우선순위 (MVP 로드맵)

1. 프로젝트 골격 + config + container + fake 어댑터
2. 브라우저 녹음 → `/ws/audio` → fake STT → 자막 표시 (레벨 미터 포함)
3. 중단 → stopped → fake LLM SSE 스트리밍 표시
4. SQLite 저장, 세션 이력 조회
5. 실제 LLM 어댑터 (OpenAI) + 프롬프트 파일
6. OpenAI Realtime 전사 어댑터 (16k→24k 리샘플, VAD 설정, 중단 시 수동 commit)
7. 타로 카드 선택 UI
8. 스피커폰 실측 튜닝 (마이크 설정값, 폰 위치, 지연시간 측정 — 특히 [중단]부터 답변 첫 토큰까지의 시간)

각 단계는 앞 단계가 fake로 끝까지 동작하는 상태에서 시작한다.
