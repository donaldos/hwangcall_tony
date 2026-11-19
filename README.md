# 마누라프로젝트 — 타로 전화상담 보조 웹앱

타로 전화상담사가 통화하는 동안 옆에 띄워 두는 **로컬 웹앱**입니다.
스피커폰 통화 소리를 노트북 마이크로 받아 **실시간 자막**으로 보여 주고, [중단]을 누르면 그 구간의 내용을 AI에 보내 **상담사가 참고할 의견**을 받아 옵니다. 상담이 끝나면 대화 전체와 AI가 만든 **세션 정리**를 로컬 SQLite에 저장합니다.

> 앱이 고객에게 직접 말하지 않습니다. AI 의견은 상담사가 읽고 자기 말로 전하기 위한 참고용입니다.

---

## 주요 기능

| 기능 | 설명 |
|---|---|
| 실시간 자막 | 말하는 동안 인식 중인 텍스트가 회색으로 보이다가, 확정되면 검정으로 바뀝니다 |
| AI 의견 | [중단]을 누르면 그 녹음 구간의 확정 문장과 상담자 정보를 LLM에 보내고, 답변을 스트리밍으로 보여 줍니다 |
| 상담자 정보 | 호칭·나이·성별·특징·고민 내역을 입력하고 [적용]하면 이후 AI 요청에 함께 들어갑니다 |
| 카톡형 대화 화면 | 통화 인식(왼쪽)과 AI 의견(오른쪽)이 차례로 쌓입니다. 위로 스크롤해 읽는 중이면 [새 내용 ↓]만 띄웁니다 |
| 세션 저장 | [저장]하면 AI가 상담을 정리(고민 요약 / 상담 흐름 / 고객 특징 / 다음 참고점)하고, 정보·대화·정리를 SQLite에 저장합니다 |
| 입력 레벨 미터 | 폰 위치와 볼륨을 맞출 수 있게 마이크 입력을 dB로 보여 줍니다 |

## 화면 구성

```
┌──────────────────────────────────────────────────────────────┐
│ 호칭 | 나이 | 성별 | 특징 | 고민 내역      [적용][신규상담][저장] │ 15%
├──────────────────────────────────────────────────────────────┤
│ ┌ 통화 · 녹음 1 · 14:03 ─────────┐                             │
│ │ 요즘 회사 일 때문에 힘들어서요  │                             │
│ └────────────────────────────────┘                             │
│                             ┌ AI 의견 · 녹음 1 ───────────────┐│ 70%
│                             │ 당장 결정을 재촉하기보다…       ││
│                             └─────────────────────────────────┘│
├──────────────────────────────────────────────────────────────┤
│ ● 녹음 중      ▮▮▮▮▮▮▮▮▯▯▯▯▯▯  -28 dB          [ ■ 중단 ]      │ 15%
└──────────────────────────────────────────────────────────────┘
```

## 동작 방식

```
고객 ─전화─▶ 안드로이드(스피커폰) ─공기─▶ 노트북 마이크
                                              │ 16kHz PCM (WebSocket)
                                              ▼
            브라우저(Chrome) ◀──자막── 로컬 서버(FastAPI, 127.0.0.1)
                 ▲                      │        │
                 │ AI 의견(SSE)          │ 24kHz  │ 전사문 + 상담자 정보
                 └──────────────────────┤        ▼
                                OpenAI Realtime 전사   OpenAI LLM
                                (gpt-live-transcribe)  (gpt-6.2-sol)
```

- 브라우저가 OpenAI에 직접 붙지 않습니다. API 키는 로컬 서버만 가지고 있습니다.
- 서버는 `127.0.0.1`에만 열려 있어 같은 컴퓨터에서만 접속됩니다.
- 고객과 상담사 목소리가 한 마이크에 섞이므로 화자 구분은 하지 않고, AI가 문맥으로 해석합니다.

## 요구 사항

- **Python 3.12+** — [uv](https://docs.astral.sh/uv/)가 자동으로 받아 줍니다
- **uv** (패키지·가상환경 관리)
- **Chrome** 브라우저
- **OpenAI API 키** (음성 인식 + LLM)
- 운영: macOS(맥북). 개발은 Windows / WSL에서도 됩니다.

## 설치와 실행

### 1. uv 설치 (처음 한 번)

```bash
# macOS / Linux / WSL
curl -LsSf https://astral.sh/uv/install.sh | sh
```
```powershell
# Windows (PATH에 안 잡히면 이후 명령을 `py -m uv ...`로 실행)
py -m pip install --user uv
```

### 2. 의존성 설치

```bash
uv sync            # .venv 가상환경을 만들고 uv.lock 버전 그대로 설치
```

> 가상환경은 OS별로 다릅니다. 다른 컴퓨터로 옮길 때 `.venv`를 복사하지 말고, 그 컴퓨터에서 `uv sync`를 다시 실행하세요.
> 같은 폴더를 Windows와 WSL에서 함께 쓴다면 한쪽은 `UV_PROJECT_ENVIRONMENT=.venv-win`처럼 다른 폴더를 쓰세요.

### 3. 설정 파일

```bash
cp .env.example .env     # Windows: Copy-Item .env.example .env
```
`.env`를 열어 `OPENAI_API_KEY=`에 키를 넣습니다. **키는 `.env`에만 넣고 `.env.example`에는 넣지 마세요** (`.env.example`은 커밋되는 파일입니다).

### 4. 실행

```bash
uv run uvicorn manura.main:app --reload --host 127.0.0.1 --port 8000
```
Chrome에서 **http://localhost:8000** 을 엽니다.

서버 시작 로그에서 실제 엔진이 연결됐는지 확인하세요.
```
STT engine: openai (gpt-live-transcribe)
LLM provider: openai (gpt-6.2-sol)
```
`fake`로 나오면 `.env`를 읽지 못한 것입니다 (가짜 대본·가짜 답변이 나옵니다).

### macOS 처음 실행 시

**시스템 설정 → 개인정보 보호 및 보안 → 마이크**에서 Chrome을 허용해야 합니다.

## 사용 순서

1. 통화 시작 시 고객에게 **녹음과 AI 처리(외부 전송)를 고지하고 동의**를 받습니다.
2. 위쪽에 상담자 정보를 입력하고 **[적용]** 합니다. 고친 뒤 다시 적용하지 않으면 "변경됨 · 적용 필요"로 표시됩니다.
3. 아래쪽 **[녹음]** 을 누르고, 레벨 미터를 보며 폰 위치를 맞춥니다.
4. 의견이 필요할 때 **[중단]** → 자막이 확정되고 AI 의견이 오른쪽에 나타납니다.
5. **[이어서 녹음]** 으로 계속합니다. AI가 답하는 중에도 다음 녹음을 시작할 수 있습니다.
6. 상담이 끝나면 **[저장]** → 세션 정리가 대화창 맨 아래에 붙고 SQLite에 저장됩니다. 같은 상담에서 다시 저장하면 같은 기록이 갱신됩니다.
7. 다음 고객은 **[신규상담]** 으로 화면을 비웁니다 (저장 안 한 내용이 있으면 확인을 묻습니다).

## 설정 (`.env`)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `STT_ENGINE` | `fake` | `openai` \| `fake` |
| `LLM_PROVIDER` | `fake` | `openai` \| `fake` |
| `OPENAI_API_KEY` | — | STT·LLM 공용 키 |
| `AUTO_ADVISE` | `true` | [중단] 후 자동으로 AI 의견 요청 |
| `OPENAI_STT_MODEL` | `gpt-live-transcribe` | 실시간 전사 모델 |
| `OPENAI_STT_LANGUAGE` | `ko` | 인식 언어 |
| `OPENAI_STT_PROMPT` | (없음) | 인식 힌트. 예: `타로 전화상담 통화. 스피커폰으로 녹음된 한국어 대화.` |
| `OPENAI_STT_DELAY` | (없음) | `minimal`~`xhigh`. 높을수록 늦게 뜨지만 정확도↑ |
| `OPENAI_LLM_MODEL` | `gpt-6.2-sol` | AI 의견·세션 정리 모델. 응답 속도가 중요하면 `gpt-6.1-terra` |
| `STT_VAD_THRESHOLD_DBFS` | `-45` | 이 크기 이상을 "말소리"로 봅니다. 고객 목소리가 잘리면 낮추기(예: `-50`) |
| `STT_VAD_SILENCE_MS` | `600` | 말 뒤 이만큼 조용하면 한 문장으로 확정 |
| `STT_MAX_SEGMENT_MS` | `15000` | 계속 말해도 이 길이마다 확정 |
| `STT_FINALIZE_TIMEOUT_MS` | `8000` | [중단] 후 최종 결과 대기 상한 |
| `SUMMARY_TIMEOUT_S` | `90` | 세션 정리 생성 상한 (넘기면 정리 없이 저장) |
| `MIC_ECHO_CANCELLATION` / `MIC_NOISE_SUPPRESSION` / `MIC_AUTO_GAIN_CONTROL` | `false` / `false` / `true` | 브라우저 마이크 처리. 스피커폰은 먼 소리라 잡음 제거를 끄는 것이 기본 |

> `gpt-live-transcribe`는 서버 측 음성 구간 감지(VAD)를 지원하지 않아, 서버가 소리 크기로 문장 끝을 판단합니다. 그래서 `STT_VAD_*` 값을 실제 통화로 맞추는 것이 인식 품질에 중요합니다.

## 프롬프트 수정

코드 수정 없이 `prompts/` 파일만 고치고 서버를 재시작하면 됩니다.

| 파일 | 용도 | 자리표시자 |
|---|---|---|
| `prompts/system.md` | AI 의견: 역할·말투·분량 | — |
| `prompts/user_template.md` | AI 의견: 요청 본문 | `{{profile}}`, `{{transcript}}` |
| `prompts/summary_system.md` | 세션 정리: 형식 | — |
| `prompts/summary_user.md` | 세션 정리: 요청 본문 | `{{profile}}`, `{{conversation}}` |

## 저장 데이터

`data/manura.db` (SQLite, git 제외)

| 테이블 | 내용 |
|---|---|
| `sessions` | ID, 처음/마지막 저장 시각, 상담 시작 시각, 호칭·나이·성별·특징·고민, 세션 정리 |
| `session_entries` | 순서대로의 대화 — 종류(`transcript` / `advice` / `note`), 녹음 번호, 내용, 시각 |

[DB Browser for SQLite](https://sqlitebrowser.org/) 등으로 열어 볼 수 있습니다.

## 프로젝트 구조

```
├── prompts/                 # LLM 프롬프트 (코드에 박지 않음)
├── src/manura/
│   ├── main.py              # FastAPI 앱, 정적 파일
│   ├── config.py            # .env 설정
│   ├── container.py         # 어댑터 조립 (엔진 선택은 여기서만)
│   ├── domain/              # 모델, 포트(Protocol), 예외
│   ├── services/            # recording(녹음↔STT), advice(AI 의견), sessions(정리·저장)
│   ├── adapters/
│   │   ├── stt/             # openai_realtime, segmenter(발화 분할), resample, fake
│   │   ├── llm/             # openai_chat, fake
│   │   └── repo/            # memory(전사문), sqlite(상담 기록)
│   └── api/                 # ws_audio, advise(SSE), sessions, client_config
├── web/                     # index.html, app.js, style.css, audio/pcm-worklet.js
└── tests/                   # unit / integration / live
```

**포트와 어댑터** 구조라 STT·LLM·저장소는 `.env` 설정만으로 바꿀 수 있고, 모든 외부 엔진에 네트워크 없이 도는 `fake` 구현이 있습니다. 설계 기준과 규칙은 [CLAUDE.md](CLAUDE.md)에 있습니다.

### API

| 경로 | 설명 |
|---|---|
| `WS /ws/audio` | PCM16 업로드 + `started` / `partial` / `final` / `stopped` / `error` 이벤트 |
| `POST /api/turns/{turn_id}/advise` | AI 의견 SSE 스트림 (`token` / `done` / `error`). 본문: `{"profile": {...}}` |
| `POST /api/sessions/save` | 세션 정리 생성 + SQLite 저장 |
| `GET /api/client-config` | 브라우저용 설정 (샘플레이트, 마이크 옵션 등) |

## 개발

```bash
uv run pytest                 # 단위·통합 테스트 (네트워크 없이 fake 엔진)
uv run pytest -m live         # 실제 OpenAI 연결 확인 (.env의 키 사용, 과금 발생)
uv run ruff check . && uv run ruff format .
uv run mypy src               # strict
```

pip만 쓰는 환경용 `requirements.txt`가 필요하면:
```bash
uv export --format requirements-txt --no-dev --no-hashes -o requirements.txt
```

## 개인정보·보안

- 고객 음성은 **OpenAI 음성 인식**으로, 전사문과 상담자 정보는 **OpenAI LLM**으로 전송됩니다. 통화 시작 시 고지·동의가 필요합니다.
- 상담 기록은 로컬 `data/`에만 저장되며 git에 올라가지 않습니다 (`.gitignore`).
- 로그에는 전사문이나 키를 남기지 않고, 길이·지연시간 같은 메타데이터만 남깁니다.
- 테스트에는 실제 고객 통화를 쓰지 않습니다.

## 진행 상황

| 단계 | 상태 |
|---|---|
| 1. 프로젝트 골격 + fake 어댑터 | ✅ |
| 2. 브라우저 녹음 → 실시간 자막 (레벨 미터) | ✅ |
| 3. 중단 → AI 의견 스트리밍 | ✅ |
| 4. SQLite 저장 | 🔶 상담 기록·세션 정리 저장 완료 / 지난 상담 조회 화면 없음, 진행 중 전사문은 메모리 보관 |
| 5. 실제 LLM 어댑터 (OpenAI) + 프롬프트 파일 | ✅ |
| 6. 실시간 STT 어댑터 (OpenAI Realtime) | ✅ |
| 7. 타로 카드 선택 UI | ⬜ |
| 8. 스피커폰 실측 튜닝 (VAD 값, 마이크 설정, 지연시간) | ⬜ |
| — 맥북 설치 자동화 (자동 실행 / 더블클릭 실행 파일) | ⬜ 보류 |
