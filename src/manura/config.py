from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # 엔진 선택
    stt_engine: Literal["openai", "fake"] = "fake"
    llm_provider: Literal["openai", "fake"] = "fake"

    # [중단] 후 STT 확정되면 자동으로 답변 요청
    auto_advise: bool = True

    # 브라우저 → 서버 오디오 계약 (포트 계약: 16kHz mono PCM16)
    input_sample_rate: int = 16000
    chunk_ms: int = 100

    # 브라우저 마이크 처리 (스피커폰 실측으로 조정)
    mic_echo_cancellation: bool = False
    mic_noise_suppression: bool = False
    mic_auto_gain_control: bool = True

    # 중단 후 최종 결과 대기 상한 — 넘기면 받은 데까지만 확정한다
    stt_finalize_timeout_ms: int = 8000

    # 클라이언트 측 발화 분할 (gpt-live-transcribe는 서버 VAD를 지원하지 않는다)
    stt_vad_threshold_dbfs: float = -45.0
    stt_vad_silence_ms: int = 600
    stt_max_segment_ms: int = 15000
    stt_min_commit_ms: int = 100

    # OpenAI Realtime 전사
    openai_api_key: SecretStr | None = None
    openai_realtime_url: str = "wss://api.openai.com/v1/realtime?intent=transcription"
    openai_stt_model: str = "gpt-live-transcribe"
    openai_stt_sample_rate: int = 24000
    openai_stt_language: str | None = "ko"
    openai_stt_prompt: str | None = None
    openai_stt_delay: str | None = None
    openai_stt_connect_timeout_s: float = 10.0

    # OpenAI LLM
    openai_llm_model: str = "gpt-6.2-sol"
    openai_llm_max_output_tokens: int | None = None

    # 메모리에 보관할 최근 녹음 구간 수 (SQLite 도입 전 임시 저장)
    memory_max_turns: int = 200

    # 경로
    web_dir: Path = PROJECT_ROOT / "web"
    prompts_dir: Path = PROJECT_ROOT / "prompts"
    data_dir: Path = PROJECT_ROOT / "data"  # 민감정보 — git 제외
    db_filename: str = "manura.db"

    # [저장] 시 최종 세션 정리 생성 상한 — 넘기면 정리 없이 저장한다
    summary_timeout_s: float = 90.0

    @property
    def db_path(self) -> Path:
        return self.data_dir / self.db_filename
