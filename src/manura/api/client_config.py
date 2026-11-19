from fastapi import APIRouter, Request

from manura.container import Container
from manura.domain.models import ClientConfig

router = APIRouter()


@router.get("/api/client-config")
async def client_config(request: Request) -> ClientConfig:
    container: Container = request.app.state.container
    return container.client_config
