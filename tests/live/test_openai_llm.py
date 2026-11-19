"""실제 OpenAI LLM 스트리밍 확인. `uv run pytest -m live`로만 실행된다."""

import asyncio
from pathlib import Path

import pytest

from manura.adapters.llm.openai_chat import OpenAIChatAdvisor
from manura.adapters.repo.sqlite import SqliteSessionArchive
from manura.config import PROJECT_ROOT, Settings
from manura.domain.models import AdviceContext, ClientProfile, SessionEntry, SessionRecord
from manura.services.advice import load_prompts, render_advice
from manura.services.sessions import SessionService

pytestmark = pytest.mark.live

PROMPTS = PROJECT_ROOT / "prompts"


async def test_openai_llm_streams_answer() -> None:
    settings = Settings()
    if settings.openai_api_key is None:
        pytest.skip("OPENAI_API_KEY 없음")
    llm = OpenAIChatAdvisor(settings)
    prompts = load_prompts(PROMPTS / "system.md", PROMPTS / "user_template.md")
    ctx = AdviceContext(
        transcript="요즘 회사 일 때문에 너무 힘들어서요\n이직을 해야 할지 모르겠어요"
    )

    async def collect() -> list[str]:
        return [t async for t in llm.stream(prompts.system, render_advice(prompts, ctx))]

    deltas = await asyncio.wait_for(collect(), timeout=60)
    answer = "".join(deltas)
    print(f"\n[{settings.openai_llm_model}] {len(deltas)} deltas\n{answer}")
    assert len(deltas) > 1
    assert answer.strip()


async def test_openai_session_summary(tmp_path: Path) -> None:
    settings = Settings()
    if settings.openai_api_key is None:
        pytest.skip("OPENAI_API_KEY 없음")
    service = SessionService(
        archive=SqliteSessionArchive(tmp_path / "t.db"),
        llm=OpenAIChatAdvisor(settings),
        summary_prompts=load_prompts(PROMPTS / "summary_system.md", PROMPTS / "summary_user.md"),
        summary_timeout_s=90,
    )
    at = "2026-11-19T10:00:00Z"
    record = SessionRecord(
        profile=ClientProfile(name="김○○", age="30대", gender="여성", concern="이직"),
        entries=[
            SessionEntry(
                kind="transcript", turn=1, text="요즘 회사 상사 때문에 너무 힘들어요", at=at
            ),
            SessionEntry(kind="advice", turn=1, text="상사와의 관계부터 들어주세요.", at=at),
            SessionEntry(
                kind="transcript", turn=2, text="이직하면 나아질까요 카드 봐주세요", at=at
            ),
        ],
    )
    result = await service.save(record)
    print(f"\n[{settings.openai_llm_model}] summary\n{result.summary}")
    assert result.summary
    assert result.summary_error is None
