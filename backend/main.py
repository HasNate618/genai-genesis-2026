"""FastAPI app entrypoint for orchestration backend."""

from fastapi import FastAPI

from backend.api.routes import router as memory_router


def create_app() -> FastAPI:
    app = FastAPI(title="AgenticArmy Backend", version="0.1.0")
    app.include_router(memory_router)
    return app


app = create_app()

