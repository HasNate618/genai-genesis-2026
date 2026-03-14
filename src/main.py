"""
Application entry-point.

Run the FastAPI server:
    python -m src.main
    # or
    uvicorn src.main:app --reload
"""

from __future__ import annotations

import uvicorn

from src.api.server import app  # noqa: F401  (re-export for uvicorn)
from src.config import settings


def main() -> None:
    uvicorn.run(
        "src.api.server:app",
        host=settings.api_host,
        port=settings.api_port,
        log_level=settings.api_log_level,
        reload=False,
    )


if __name__ == "__main__":
    main()
