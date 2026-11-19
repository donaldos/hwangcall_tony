from collections import OrderedDict


class InMemoryTranscriptStore:
    """프로세스 메모리에만 두는 전사문 저장소. 서버를 재시작하면 사라진다.

    오래된 구간부터 버려 메모리가 무한히 늘지 않게 한다.
    """

    def __init__(self, max_turns: int) -> None:
        self._max_turns = max_turns
        self._turns: OrderedDict[str, list[str]] = OrderedDict()

    async def open_turn(self, turn_id: str) -> None:
        self._turns[turn_id] = []
        while len(self._turns) > self._max_turns:
            self._turns.popitem(last=False)

    async def add_final(self, turn_id: str, text: str) -> None:
        if turn_id in self._turns:
            self._turns[turn_id].append(text)

    async def turn_text(self, turn_id: str) -> str | None:
        finals = self._turns.get(turn_id)
        return None if finals is None else "\n".join(finals)
