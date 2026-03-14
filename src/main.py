"""
SPM entrypoint — starts the FastAPI server via uvicorn.
"""

from __future__ import annotations

import argparse
import logging

import structlog
import uvicorn


def _configure_logging(log_level: str) -> None:
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, log_level.upper(), logging.INFO),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="SPM API Server")
    parser.add_argument("--host", default=None, help="Bind host")
    parser.add_argument("--port", type=int, default=None, help="Bind port")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    args = parser.parse_args()

    from src.config import get_settings

    settings = get_settings()
    host = args.host or settings.api_host
    port = args.port or settings.api_port

    _configure_logging(settings.spm_log_level)

    uvicorn.run(
        "src.api.server:app",
        host=host,
        port=port,
        reload=args.reload,
        log_config=None,  # use structlog
    )


if __name__ == "__main__":
    main()
