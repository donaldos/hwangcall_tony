from fastapi import APIRouter, Request

from manura.container import Container
from manura.domain.models import SaveResult, SessionRecord

router = APIRouter()


@router.post("/api/sessions/save")
async def save_session(record: SessionRecord, request: Request) -> SaveResult:
    container: Container = request.app.state.container
    return await container.sessions.save(record)
