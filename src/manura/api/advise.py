import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from manura.container import Container
from manura.domain.errors import (
    AdviceInProgressError,
    EmptyTranscriptError,
    LLMError,
    TurnNotFoundError,
)
from manura.domain.models import AdviceErrorData, AdviceRequest, TokenData

log = logging.getLogger(__name__)
router = APIRouter()


def _sse(event: str, data: str) -> str:
    return f"event: {event}\ndata: {data}\n\n"


async def _events(tokens: AsyncIterator[str]) -> AsyncIterator[str]:
    try:
        async for text in tokens:
            yield _sse("token", TokenData(text=text).model_dump_json())
        yield _sse("done", "{}")
    except LLMError as e:
        log.error("advice failed: %s", e)
        yield _sse(
            "error", AdviceErrorData(code="LLM_UNAVAILABLE", message=str(e)).model_dump_json()
        )
    except Exception:
        log.exception("advice failed unexpectedly")
        error = AdviceErrorData(code="INTERNAL", message="답변 생성 중 오류가 발생했습니다")
        yield _sse("error", error.model_dump_json())


# 세션 개념(SQLite)이 들어오면 /api/sessions/{id}/turns/{turn_id}/advise로 옮긴다
@router.post("/api/turns/{turn_id}/advise")
async def advise(
    turn_id: str, request: Request, body: AdviceRequest | None = None
) -> StreamingResponse:
    container: Container = request.app.state.container
    profile = body.profile if body is not None else None
    try:
        tokens = await container.advice.begin(turn_id, profile)
    except TurnNotFoundError as e:
        raise HTTPException(404, "녹음 구간을 찾을 수 없습니다") from e
    except EmptyTranscriptError as e:
        raise HTTPException(422, "인식된 내용이 없습니다") from e
    except AdviceInProgressError as e:
        raise HTTPException(409, "이미 답변을 만드는 중입니다") from e
    return StreamingResponse(
        _events(tokens),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
