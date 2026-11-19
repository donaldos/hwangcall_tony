import asyncio
import logging
import time
import uuid
from datetime import datetime

from manura.domain.errors import LLMError
from manura.domain.models import PromptSet, SaveResult, SessionRecord
from manura.domain.ports import LLMAdvisor, SessionArchive

log = logging.getLogger(__name__)


def new_record_id() -> str:
    return f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"


class SessionService:
    def __init__(
        self,
        archive: SessionArchive,
        llm: LLMAdvisor,
        summary_prompts: PromptSet,
        summary_timeout_s: float,
    ) -> None:
        self._archive = archive
        self._llm = llm
        self._prompts = summary_prompts
        self._timeout_s = summary_timeout_s

    async def save(self, record: SessionRecord) -> SaveResult:
        """최종 세션 정리를 만든 뒤 기록과 함께 저장한다.

        정리 생성이 실패해도 대화 기록은 반드시 저장한다 (정리 없이 저장 + 오류 안내).
        """
        summary, error = await self._summarize(record)
        record_id = record.id or new_record_id()
        saved_at = datetime.now().astimezone().isoformat(timespec="seconds")
        await self._archive.save(record_id, record, summary, saved_at)
        log.info(
            "session saved: %s (%d entries, summary %s)",
            record_id,
            len(record.entries),
            "ok" if summary else "none",
        )
        return SaveResult(id=record_id, saved_at=saved_at, summary=summary, summary_error=error)

    async def _summarize(self, record: SessionRecord) -> tuple[str | None, str | None]:
        conversation = record.conversation_text()
        if not conversation:
            return None, None
        user = self._prompts.render(
            {"profile": record.profile.describe(), "conversation": conversation}
        )
        started = time.perf_counter()
        try:
            async with asyncio.timeout(self._timeout_s):
                parts = [d async for d in self._llm.stream(self._prompts.system, user)]
        except LLMError as e:
            log.error("session summary failed: %s", e)
            return None, str(e)
        except TimeoutError:
            log.error("session summary timed out after %.0f s", self._timeout_s)
            return None, "세션 정리 생성 시간이 초과되었습니다"
        log.info("session summary: %.0f ms", (time.perf_counter() - started) * 1000)
        summary = "".join(parts).strip()
        return (summary or None), None
