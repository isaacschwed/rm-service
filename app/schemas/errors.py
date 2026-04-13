from pydantic import BaseModel


class ErrorResponse(BaseModel):
    success: bool = False
    error_code: str
    error_message: str
    retryable: bool = False


# All error codes used across the service — single source of truth
class ErrorCode:
    # RM API errors
    RM_AUTH_FAILED = "RM_AUTH_FAILED"
    RM_TOKEN_EXPIRED = "RM_TOKEN_EXPIRED"
    RM_NOT_FOUND = "RM_NOT_FOUND"
    RM_DUPLICATE = "RM_DUPLICATE"
    RM_VALIDATION_ERROR = "RM_VALIDATION_ERROR"
    RM_RATE_LIMITED = "RM_RATE_LIMITED"
    RM_UNAVAILABLE = "RM_UNAVAILABLE"
    RM_TIMEOUT = "RM_TIMEOUT"

    # Company / credential errors
    CREDENTIAL_MISSING = "CREDENTIAL_MISSING"
    LOCATION_EXCLUDED = "LOCATION_EXCLUDED"
    LOCATION_NOT_FOUND = "LOCATION_NOT_FOUND"

    # Auth errors
    INVALID_API_KEY = "INVALID_API_KEY"
    OPERATION_NOT_PERMITTED = "OPERATION_NOT_PERMITTED"

    # Idempotency
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"


# Which error codes are retryable
RETRYABLE_CODES = {
    ErrorCode.RM_RATE_LIMITED,
    ErrorCode.RM_UNAVAILABLE,
    ErrorCode.RM_TIMEOUT,
}
