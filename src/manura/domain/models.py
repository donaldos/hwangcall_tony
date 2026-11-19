from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TranscriptEvent(BaseModel):
    """STT 엔진이 내보내는 인식 결과.

    partial: 아직 확정되지 않은 진행 중 텍스트 전체(누적). 빈 문자열이면 진행 중 텍스트 없음.
    final: 확정된 한 구간의 텍스트. start_ms/end_ms는 녹음 구간 시작 기준.
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal["partial", "final"]
    text: str
    start_ms: int = 0
    end_ms: int = 0


# --- WebSocket 메시지 (CLAUDE.md 7장) ---


class ClientControl(BaseModel):
    type: Literal["start", "stop"]


class StartedMessage(BaseModel):
    type: Literal["started"] = "started"
    turn_id: str


class PartialMessage(BaseModel):
    type: Literal["partial"] = "partial"
    text: str


class FinalMessage(BaseModel):
    type: Literal["final"] = "final"
    text: str
    start_ms: int
    end_ms: int


class StoppedMessage(BaseModel):
    type: Literal["stopped"] = "stopped"
    turn_id: str


class ErrorMessage(BaseModel):
    type: Literal["error"] = "error"
    code: str
    message: str


ServerMessage = StartedMessage | PartialMessage | FinalMessage | StoppedMessage | ErrorMessage


class MicSettings(BaseModel):
    echo_cancellation: bool
    noise_suppression: bool
    auto_gain_control: bool


class ClientConfig(BaseModel):
    sample_rate: int
    chunk_ms: int
    auto_advise: bool
    mic: MicSettings


# --- 답변 (LLM) ---


class ClientProfile(BaseModel):
    """상담자(고객) 정보. 상담사가 화면 위쪽에 입력하고 [적용]한 값."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    name: str = Field("", max_length=50)
    age: str = Field("", max_length=20)
    gender: str = Field("", max_length=10)
    concern: str = Field("", max_length=2000)
    traits: str = Field("", max_length=2000)

    def describe(self) -> str:
        fields = [
            ("호칭", self.name),
            ("나이", self.age),
            ("성별", self.gender),
            ("고민", self.concern),
            ("특징", self.traits),
        ]
        lines = [f"- {label}: {value}" for label, value in fields if value]
        return "\n".join(lines) if lines else "(입력된 정보 없음)"


class AdviceRequest(BaseModel):
    profile: ClientProfile = ClientProfile()


class AdviceContext(BaseModel):
    """LLM에 보낼 맥락. 카드·이전 답변은 다음 단계에서 추가한다."""

    model_config = ConfigDict(frozen=True)

    transcript: str
    profile: ClientProfile = ClientProfile()


class PromptSet(BaseModel):
    """시스템 프롬프트 + `{{이름}}` 자리표시자가 있는 사용자 템플릿."""

    model_config = ConfigDict(frozen=True)

    system: str
    user_template: str

    def render(self, values: dict[str, str]) -> str:
        text = self.user_template
        for key, value in values.items():
            text = text.replace(f"{{{{{key}}}}}", value)
        return text


# --- 상담 저장 ---

RECORD_ID_PATTERN = r"^\d{8}-\d{6}-[0-9a-f]{6}$"


class SessionEntry(BaseModel):
    kind: Literal["transcript", "advice", "note"]
    turn: int | None = None
    text: str = Field(max_length=20000)
    at: str = Field(max_length=40)  # 브라우저 기준 ISO 시각


class SessionRecord(BaseModel):
    # 같은 상담을 다시 저장하면 이 ID로 기존 기록을 갱신한다 (처음 저장 시 None)
    id: str | None = Field(None, pattern=RECORD_ID_PATTERN)
    started_at: str | None = Field(None, max_length=40)
    profile: ClientProfile
    entries: list[SessionEntry] = Field(max_length=5000)

    def conversation_text(self) -> str:
        """정리용 대화 텍스트. 상담자 정보 적용 안내(note)는 뺀다."""
        labels = {"transcript": "통화", "advice": "AI 의견"}
        blocks = [
            f"[녹음 {e.turn} · {labels[e.kind]}]\n{e.text}"
            for e in self.entries
            if e.kind in labels and e.text.strip()
        ]
        return "\n\n".join(blocks)


class SaveResult(BaseModel):
    id: str
    saved_at: str
    summary: str | None
    summary_error: str | None = None


# SSE 이벤트 데이터 (event: token / done / error)
class TokenData(BaseModel):
    text: str


class AdviceErrorData(BaseModel):
    code: str
    message: str
