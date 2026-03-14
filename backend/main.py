"""FastAPI app entrypoint for orchestration backend."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.v1 import router as api_v1_router
from backend.api.routes import router as memory_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("AgenticArmy backend starting up...")
    yield
    print("AgenticArmy backend shutting down...")


def create_app() -> FastAPI:
    app = FastAPI(
        title="AgenticArmy Backend",
        description="Multi-agent collaboration backend",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:*", "vscode-webview://*"],
        allow_origin_regex=r"http://localhost:\d+",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_v1_router)
    app.include_router(memory_router)
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, reload=True)
