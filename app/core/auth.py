"""
FastAPI dependencies for authentication and authorization.

Usage in endpoints:

    @router.post("/v1/rm/payments")
    async def post_payment(
        auth: AuthContext = Depends(require_auth("post_payment")),
        db: AsyncSession = Depends(get_db),
    ):
        ...

The auth context carries platform identity and company_id without
the endpoint needing to know anything about key validation.
"""

import structlog
from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_db
from app.models.api_key import ServiceApiKey
from app.schemas.errors import ErrorCode
from app.services.api_key import is_operation_permitted, lookup_api_key, update_last_used

logger = structlog.get_logger(__name__)
settings = get_settings()


class AuthContext:
    """
    Resolved auth context — passed to every authenticated endpoint.
    Contains the validated platform identity and the company_id from the request body.
    """

    def __init__(self, api_key_row: ServiceApiKey):
        self.platform: str = api_key_row.platform
        self.api_key_id = api_key_row.id
        # company_id is extracted from the request body later, not here
        # It's added to request.state by the middleware once the body is parsed


async def _extract_bearer_token(authorization: str | None) -> str:
    """Pull the raw token out of 'Bearer <token>'."""
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail={
                "success": False,
                "error_code": ErrorCode.INVALID_API_KEY,
                "error_message": "Missing Authorization header",
                "retryable": False,
            },
        )
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail={
                "success": False,
                "error_code": ErrorCode.INVALID_API_KEY,
                "error_message": "Authorization header must be: Bearer <key>",
                "retryable": False,
            },
        )
    return parts[1]


def require_auth(operation: str):
    """
    Returns a FastAPI dependency that:
      1. Validates the Bearer API key (SHA-256 hash lookup)
      2. Confirms the key is active
      3. Confirms the key has permission for `operation`
      4. Updates last_used_at (best-effort)
      5. Binds platform to structlog context for this request
      6. Sets request.state.platform for the request logging middleware

    Usage:
        Depends(require_auth("post_payment"))
        Depends(require_auth("create_prospect"))
    """

    async def _auth_dependency(
        request: Request,
        authorization: str | None = Header(default=None),
        db: AsyncSession = Depends(get_db),
    ) -> AuthContext:
        raw_key = await _extract_bearer_token(authorization)

        api_key_row = await lookup_api_key(db, raw_key)

        if api_key_row is None:
            logger.warning(
                "auth_rejected",
                reason="key_not_found",
                path=request.url.path,
            )
            raise HTTPException(
                status_code=401,
                detail={
                    "success": False,
                    "error_code": ErrorCode.INVALID_API_KEY,
                    "error_message": "Invalid or inactive API key",
                    "retryable": False,
                },
            )

        if not is_operation_permitted(api_key_row, operation):
            logger.warning(
                "auth_rejected",
                reason="operation_not_permitted",
                platform=api_key_row.platform,
                operation=operation,
                path=request.url.path,
            )
            raise HTTPException(
                status_code=403,
                detail={
                    "success": False,
                    "error_code": ErrorCode.OPERATION_NOT_PERMITTED,
                    "error_message": (
                        f"Platform '{api_key_row.platform}' does not have "
                        f"permission for operation '{operation}'"
                    ),
                    "retryable": False,
                },
            )

        # Bind platform to structlog context so it appears in all log lines
        structlog.contextvars.bind_contextvars(platform=api_key_row.platform)

        # Expose on request.state for the logging middleware
        request.state.platform = api_key_row.platform

        # Best-effort last_used_at update
        await update_last_used(db, api_key_row.id)

        logger.info(
            "auth_ok",
            platform=api_key_row.platform,
            operation=operation,
        )

        return AuthContext(api_key_row)

    return _auth_dependency


def require_admin():
    """
    Dependency for admin endpoints — validated against the ADMIN_API_KEY secret,
    not the platform API keys table. Completely separate auth path.
    """

    async def _admin_dependency(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> None:
        raw_key = await _extract_bearer_token(authorization)
        if raw_key != settings.admin_api_key:
            logger.warning("admin_auth_rejected", path=request.url.path)
            raise HTTPException(
                status_code=401,
                detail={
                    "success": False,
                    "error_code": ErrorCode.INVALID_API_KEY,
                    "error_message": "Invalid admin API key",
                    "retryable": False,
                },
            )
        structlog.contextvars.bind_contextvars(platform="admin")
        request.state.platform = "admin"

    return _admin_dependency
