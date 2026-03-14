"""
AgenticArmy FastAPI Backend — Skeleton
Agents and memory integration will be wired in Phase 2.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from backend.api.routes import router
from backend.api.v1 import router as v1_router
from backend.api.memory_routes import router as memory_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("AgenticArmy backend starting up...")
    yield
    print("AgenticArmy backend shutting down...")


app = FastAPI(
    title="AgenticArmy API",
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

# v1_router uses the JobRuntime state machine and is registered first so that
# its routes take priority over the simpler mock in routes (which is kept for
# backwards-compatibility with the original main-branch contract).
app.include_router(v1_router)
app.include_router(router)
app.include_router(memory_router)


@app.get("/health")
async def root_health():
    """Root health check ping for compatibility"""
    return {"status": "ok", "service": "agentic-army-root"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, reload=True)
