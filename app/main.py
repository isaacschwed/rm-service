import signal
from contextlib import asynccontextmanager

import sentry_sdk
import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.redis import init_redis, close_redis
from app.db.session import engine
from app.middleware.logging import RequestLoggingMiddleware
from app.api.v1.health import router as health_router

settings = get_settings()
configure_logging()
logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Sentry
# ---------------------------------------------------------------------------
if settings.sentry_dsn:
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.app_env,
        integrations=[
            FastApiIntegration(transaction_style="endpoint"),
            SqlalchemyIntegration(),
        ],
        traces_sample_rate=0.1,
        send_default_pii=False,
    )

# ---------------------------------------------------------------------------
# Graceful shutdown handler
# Railway sends SIGTERM before killing the container.
# uvicorn --timeout-graceful-shutdown 30 lets in-flight requests finish.
# ---------------------------------------------------------------------------
def _handle_sigterm(*_):
    logger.info("sigterm_received", msg="Draining in-flight requests before shutdown")
    raise SystemExit(0)


signal.signal(signal.SIGTERM, _handle_sigterm)

# ---------------------------------------------------------------------------
# Lifespan — startup + shutdown in one place (modern FastAPI pattern)
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("service_starting", version=settings.app_version, env=settings.app_env)
    await init_redis()
    logger.info("service_started")

    yield  # App runs here

    # Shutdown
    logger.info("service_stopping")
    await close_redis()
    await engine.dispose()
    logger.info("service_stopped")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Rent Manager Connector Service",
    description="Single point of contact for all Rent Manager API operations across all platforms.",
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/docs" if settings.app_env != "production" else None,
    redoc_url="/redoc" if settings.app_env != "production" else None,
    openapi_url="/openapi.json" if settings.app_env != "production" else None,
)

# ---------------------------------------------------------------------------
# Middleware (order matters — outermost first)
# ---------------------------------------------------------------------------
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[],   # Internal service — no browser clients
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(health_router)          # GET /health — no prefix, no auth
# Future routers added here as each step is built:
# app.include_router(company_router, prefix="/v1/companies", ...)
# app.include_router(payments_router, prefix="/v1/rm", ...)
# etc.
