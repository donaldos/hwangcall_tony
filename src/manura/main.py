import logging

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from manura.api import advise, client_config, sessions, ws_audio
from manura.config import Settings
from manura.container import build_container


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    logger = logging.getLogger(__name__)
    logger.info(
        "STT engine: %s%s",
        settings.stt_engine,
        f" ({settings.openai_stt_model})"
        if settings.stt_engine == "openai"
        else " — 가짜 대본 출력",
    )
    logger.info(
        "LLM provider: %s%s",
        settings.llm_provider,
        f" ({settings.openai_llm_model})" if settings.llm_provider == "openai" else " — 가짜 답변",
    )
    app = FastAPI(title="manura")
    app.state.container = build_container(settings)
    app.include_router(ws_audio.router)
    app.include_router(client_config.router)
    app.include_router(advise.router)
    app.include_router(sessions.router)
    # 라우터 뒤에 마운트해야 /api, /ws 경로를 가리지 않는다
    app.mount("/", StaticFiles(directory=settings.web_dir, html=True), name="web")
    return app


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app = create_app()
