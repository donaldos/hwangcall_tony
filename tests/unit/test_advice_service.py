from collections.abc import AsyncIterator

import pytest

from manura.adapters.llm.fake import FakeLLMAdvisor
from manura.adapters.repo.memory import InMemoryTranscriptStore
from manura.domain.errors import (
    AdviceInProgressError,
    EmptyTranscriptError,
    TurnNotFoundError,
)
from manura.domain.models import PromptSet
from manura.services.advice import AdviceService

PROMPTS = PromptSet(system="시스템", user_template="[통화]\n{{transcript}}\n어떻게 생각해?")


class RecordingLLM:
    def __init__(self) -> None:
        self.inputs: list[str] = []

    async def stream(self, system: str, user: str) -> AsyncIterator[str]:
        self.inputs.append(user)
        yield "좋아요"


async def _store_with(turn_id: str, *finals: str) -> InMemoryTranscriptStore:
    store = InMemoryTranscriptStore(max_turns=10)
    await store.open_turn(turn_id)
    for text in finals:
        await store.add_final(turn_id, text)
    return store


async def test_transcript_is_rendered_into_prompt() -> None:
    llm = RecordingLLM()
    service = AdviceService(llm, await _store_with("t1", "회사가 힘들어요", "이직할까요"), PROMPTS)
    tokens = [t async for t in await service.begin("t1")]
    assert tokens == ["좋아요"]
    assert llm.inputs == ["[통화]\n회사가 힘들어요\n이직할까요\n어떻게 생각해?"]


async def test_unknown_turn() -> None:
    service = AdviceService(FakeLLMAdvisor(delay_s=0), InMemoryTranscriptStore(10), PROMPTS)
    with pytest.raises(TurnNotFoundError):
        await service.begin("없음")


async def test_empty_transcript() -> None:
    service = AdviceService(FakeLLMAdvisor(delay_s=0), await _store_with("t1"), PROMPTS)
    with pytest.raises(EmptyTranscriptError):
        await service.begin("t1")


async def test_duplicate_request_rejected_until_finished() -> None:
    service = AdviceService(FakeLLMAdvisor(delay_s=0), await _store_with("t1", "안녕"), PROMPTS)
    first = await service.begin("t1")
    with pytest.raises(AdviceInProgressError):
        await service.begin("t1")
    _ = [t async for t in first]
    second = await service.begin("t1")  # 끝난 뒤에는 다시 요청 가능
    assert "".join([t async for t in second])


async def test_store_evicts_oldest_turn() -> None:
    store = InMemoryTranscriptStore(max_turns=2)
    for turn_id in ("a", "b", "c"):
        await store.open_turn(turn_id)
    assert await store.turn_text("a") is None
    assert await store.turn_text("c") == ""
