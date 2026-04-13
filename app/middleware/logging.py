import time
import uuid

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = structlog.get_logger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Logs every request with:
    - request_id (UUID, added to response headers)
    - method, path, status_code
    - duration_ms
    - platform and company_id if present in request state
    """

    SKIP_PATHS = {"/health"}

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in self.SKIP_PATHS:
            return await call_next(request)

        request_id = str(uuid.uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        start = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = int((time.perf_counter() - start) * 1000)
            logger.error(
                "request_failed",
                method=request.method,
                path=request.url.path,
                duration_ms=duration_ms,
                error=str(exc),
            )
            raise

        duration_ms = int((time.perf_counter() - start) * 1000)

        # platform + company_id are set on request.state by the auth middleware
        logger.info(
            "request_completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
            platform=getattr(request.state, "platform", None),
            company_id=getattr(request.state, "company_id", None),
        )

        response.headers["X-Request-ID"] = request_id
        return response
