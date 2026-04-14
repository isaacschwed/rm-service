"""
Shared types for the RM API layer.

PaginationMeta — structured result of parsing X-Total-Results / Link headers
EntityType     — canonical entity names used throughout the service
ContactTypeID  — RM's integer enum for contact relationship roles
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


@dataclass
class PaginationMeta:
    """Structured pagination metadata parsed from RM response headers."""

    total: int          # X-Total-Results: total records matching the query
    has_next: bool      # True when a rel="next" Link header is present
    next_url: str | None  # The URL from rel="next", or None


class EntityType(str, Enum):
    PROSPECT = "prospect"
    TENANT = "tenant"
    BILL = "bill"
    VENDOR = "vendor"
    UNIT = "unit"
    PROPERTY = "property"


class ContactTypeID(int, Enum):
    """RM integer codes for contact relationship roles."""

    PRIMARY = 6
    OCCUPANT = 7
    CO_APPLICANT = 8
    GUARANTOR = 9
    CASE_WORKER = 10
    HASA_SUPERVISOR = 11
