import logging
import structlog
from app.core.config import get_settings


def configure_logging() -> None:
    settings = get_settings()

    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if settings.app_env == "production":
        # JSON output for Railway log aggregation
        processors = shared_processors + [
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ]
    else:
        # Human-readable for local dev
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Silence noisy libs
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str = __name__):
    return structlog.get_logger(name)
