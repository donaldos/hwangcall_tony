import asyncio
from collections.abc import AsyncIterator

DEFAULT_ANSWER = (
    "고객은 직장 문제로 지쳐 있고, 이직을 고민하는 것 같아요. "
    "지금 당장 결정을 재촉하기보다는 무엇이 가장 힘든지 먼저 들어주면 좋겠어요."
)


class FakeLLMAdvisor:
    """네트워크 없이 동작하는 LLM. 정해진 답을 단어 단위로 흘려보낸다."""

    def __init__(self, answer: str = DEFAULT_ANSWER, delay_s: float = 0.03) -> None:
        self._answer = answer
        self._delay_s = delay_s

    async def stream(self, system: str, user: str) -> AsyncIterator[str]:
        for i, word in enumerate(self._answer.split(" ")):
            await asyncio.sleep(self._delay_s)
            yield word if i == 0 else f" {word}"
