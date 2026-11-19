"""OpenAI Responses API 스트리밍 어댑터.

사양 출처: https://developers.openai.com/api/docs/guides/streaming-responses (2026-11 확인)
- client.responses.create(..., stream=True)
- 이벤트: response.output_text.delta / response.completed / error
"""

from collections.abc import AsyncIterator
from typing import Any

import openai
from openai import AsyncOpenAI
from openai.types.responses import (
    ResponseErrorEvent,
    ResponseFailedEvent,
    ResponseTextDeltaEvent,
)

from manura.config import Settings
from manura.domain.errors import LLMError


class OpenAIChatAdvisor:
    def __init__(self, settings: Settings) -> None:
        if settings.openai_api_key is None:
            raise LLMError("OPENAI_API_KEY가 설정되지 않았습니다 (.env 확인)")
        self._client = AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value())
        self._model = settings.openai_llm_model
        self._max_output_tokens = settings.openai_llm_max_output_tokens

    async def stream(self, system: str, user: str) -> AsyncIterator[str]:
        options: dict[str, Any] = {}
        if self._max_output_tokens is not None:
            options["max_output_tokens"] = self._max_output_tokens
        try:
            stream = await self._client.responses.create(
                model=self._model,
                instructions=system,
                input=user,
                stream=True,
                **options,
            )
            async for event in stream:
                if isinstance(event, ResponseTextDeltaEvent):
                    yield event.delta
                elif isinstance(event, ResponseErrorEvent):
                    raise LLMError(f"OpenAI LLM 오류 [{event.code}]: {event.message}")
                elif isinstance(event, ResponseFailedEvent):
                    error = event.response.error
                    raise LLMError(f"OpenAI LLM 실패: {error.message if error else '알 수 없음'}")
        except openai.OpenAIError as e:
            raise LLMError(f"OpenAI LLM 호출 실패: {type(e).__name__}: {e}") from e
