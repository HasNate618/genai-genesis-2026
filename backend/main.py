"""FastAPI app entrypoint for orchestration backend."""

from fastapi import FastAPI

from backend.api.v1 import router as api_v1_router


def create_app() -> FastAPI:
    app = FastAPI(title="AgenticArmy Backend", version="0.1.0")
    app.include_router(api_v1_router)
    return app


app = create_app()
