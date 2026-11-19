"""어댑터 선택과 조립은 이 파일에서만 한다 (CLAUDE.md 4장)."""

from dataclasses import dataclass

from manura.adapters.llm.fake import FakeLLMAdvisor
from manura.adapters.llm.openai_chat import OpenAIChatAdvisor
from manura.adapters.repo.memory import InMemoryTranscriptStore
from manura.adapters.repo.sqlite import SqliteSessionArchive
from manura.adapters.stt.fake import FakeSTTEngine
from manura.adapters.stt.openai_realtime import OpenAIRealtimeSTT
from manura.config import Settings
from manura.domain.models import ClientConfig, MicSettings
from manura.domain.ports import LLMAdvisor, STTEngine
from manura.services.advice import AdviceService, load_prompts
from manura.services.recording import RecordingService
from manura.services.sessions import SessionService


@dataclass(frozen=True)
class Container:
    recording: RecordingService
    advice: AdviceService
    sessions: SessionService
    client_config: ClientConfig


def _build_stt(settings: Settings) -> STTEngine:
    if settings.stt_engine == "openai":
        return OpenAIRealtimeSTT(settings)
    return FakeSTTEngine(sample_rate=settings.input_sample_rate)


def _build_llm(settings: Settings) -> LLMAdvisor:
    if settings.llm_provider == "openai":
        return OpenAIChatAdvisor(settings)
    return FakeLLMAdvisor()


def build_container(settings: Settings) -> Container:
    store = InMemoryTranscriptStore(max_turns=settings.memory_max_turns)
    llm = _build_llm(settings)
    prompts_dir = settings.prompts_dir
    recording = RecordingService(
        stt=_build_stt(settings),
        store=store,
        finalize_timeout_s=settings.stt_finalize_timeout_ms / 1000,
    )
    advice = AdviceService(
        llm=llm,
        store=store,
        prompts=load_prompts(prompts_dir / "system.md", prompts_dir / "user_template.md"),
    )
    sessions = SessionService(
        archive=SqliteSessionArchive(settings.db_path),
        llm=llm,
        summary_prompts=load_prompts(
            prompts_dir / "summary_system.md", prompts_dir / "summary_user.md"
        ),
        summary_timeout_s=settings.summary_timeout_s,
    )
    client_config = ClientConfig(
        sample_rate=settings.input_sample_rate,
        chunk_ms=settings.chunk_ms,
        auto_advise=settings.auto_advise,
        mic=MicSettings(
            echo_cancellation=settings.mic_echo_cancellation,
            noise_suppression=settings.mic_noise_suppression,
            auto_gain_control=settings.mic_auto_gain_control,
        ),
    )
    return Container(
        recording=recording, advice=advice, sessions=sessions, client_config=client_config
    )
