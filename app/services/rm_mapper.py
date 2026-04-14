"""
RM field mapping / transformation layer.

Translates between our clean snake_case field names and RM's PascalCase API
field names. Each entity type has a concrete mapper that inherits RMMapper.

Design
------
_FIELD_MAP          {our_name: "RMName"} — canonical bidirectional mapping
_DEPRECATED_ALIASES {"OldRMName": "our_name"} — lower-priority fallback used
                    in from_rm only; if the canonical RM name is also present
                    the canonical value wins

_GLOBAL_STRIP is applied by from_rm on every mapper:
  ApiUri               — internal RM routing field, never expose to platforms
  ColorID              — deprecated UI hint, no replacement
  PrimaryContact       — deprecated nested object, replaced by Contacts list
  AvidInvoiceURL       — deprecated AP field
  DoNotPrintStatements — deprecated billing flag
  Attachments          — deprecated inline attachment list

Usage
-----
    mapper = ProspectMapper()

    # Our data → RM payload
    rm_body = mapper.to_rm({"prospect_id": 42, "first_name": "Jane"})
    # {"ProspectID": 42, "FirstName": "Jane"}

    # RM response → clean dict
    clean = mapper.from_rm({"ProspectID": 42, "FirstName": "Jane", "ApiUri": "..."})
    # {"prospect_id": 42, "first_name": "Jane"}

    # Parse pagination headers
    meta = parse_pagination(response.headers)
    # PaginationMeta(total=150, has_next=True, next_url="https://...")
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from app.schemas.rm_types import PaginationMeta

# RM field names stripped from every from_rm result regardless of mapper
_GLOBAL_STRIP: frozenset[str] = frozenset({
    "ApiUri",
    "ColorID",
    "PrimaryContact",
    "AvidInvoiceURL",
    "DoNotPrintStatements",
    "Attachments",
})


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class RMMapper:
    """
    Base mapper. Subclasses override _FIELD_MAP (and optionally
    _DEPRECATED_ALIASES) to declare their field translations.
    """

    # {our_clean_name: "RMFieldName"} — canonical bidirectional mapping
    _FIELD_MAP: dict[str, str] = {}

    # {"OldRMName": "our_clean_name"} — used in from_rm as lower-priority
    # fallback; canonical _FIELD_MAP always wins if the same target key exists
    _DEPRECATED_ALIASES: dict[str, str] = {}

    def to_rm(self, data: dict) -> dict:
        """
        Translate our normalized field names to RM API field names.
        Unknown fields pass through unchanged.
        None values are preserved — RM may require explicit null to clear a field.
        """
        if not data:
            return {}
        return {self._FIELD_MAP.get(k, k): v for k, v in data.items()}

    def from_rm(self, data: dict) -> dict:
        """
        Translate raw RM field names to our normalized names.

        Processing order (later steps win):
          1. Deprecated aliases (_DEPRECATED_ALIASES) — lowest priority
          2. Canonical field map (_FIELD_MAP reversed)
          3. Unknown fields — passed through as-is for forward compatibility

        ApiUri and all _GLOBAL_STRIP fields are silently dropped.
        None values are preserved; missing fields never raise.
        """
        if not data:
            return {}

        canonical_reverse: dict[str, str] = {v: k for k, v in self._FIELD_MAP.items()}
        result: dict = {}

        # Pass 1: deprecated aliases (lowest priority — canonical may overwrite)
        for rm_key, value in data.items():
            if rm_key in self._DEPRECATED_ALIASES:
                result[self._DEPRECATED_ALIASES[rm_key]] = value

        # Pass 2: canonical mappings + unknown pass-throughs
        for rm_key, value in data.items():
            if rm_key in _GLOBAL_STRIP:
                continue
            if rm_key in canonical_reverse:
                # Canonical mapping — overwrites any deprecated alias for same target
                result[canonical_reverse[rm_key]] = value
            elif rm_key not in self._DEPRECATED_ALIASES:
                # Unknown field — pass through unchanged for forward compatibility
                result[rm_key] = value

        return result


# ---------------------------------------------------------------------------
# Concrete mappers
# ---------------------------------------------------------------------------

class ProspectMapper(RMMapper):
    _FIELD_MAP = {
        "prospect_id": "ProspectID",
        "property_id": "PropertyID",
        "unit_id": "UnitID",
        "first_name": "FirstName",
        "last_name": "LastName",
        "email": "Email",
        "phone": "Phone",
        "update_date": "UpdateDate",
    }


class ContactMapper(RMMapper):
    _FIELD_MAP = {
        "contact_id": "ContactID",
        "first_name": "FirstName",
        "last_name": "LastName",
        "email": "Email",
        "phone": "Phone",
        "contact_type_id": "ContactTypeID",
    }


class TenantMapper(RMMapper):
    _FIELD_MAP = {
        "tenant_id": "TenantID",
        "property_id": "PropertyID",
        "unit_id": "UnitID",
        "first_name": "FirstName",
        "last_name": "LastName",
        "email": "Email",
        "phone": "Phone",
        "move_in_date": "MoveInDate",
        "move_out_date": "MoveOutDate",
        "update_date": "UpdateDate",
    }


class UnitMapper(RMMapper):
    _FIELD_MAP = {
        "unit_id": "UnitID",
        "property_id": "PropertyID",
        "unit_number": "UnitNumber",
        "is_vacant": "IsVacant",
        "current_market_rent": "CurrentMarketRent",
    }


class PropertyMapper(RMMapper):
    _FIELD_MAP = {
        "property_id": "PropertyID",
        "name": "Name",
        "location_id": "LocationID",
    }


class BillMapper(RMMapper):
    _FIELD_MAP = {
        "bill_id": "BillID",
        "property_id": "PropertyID",
        "vendor_id": "VendorID",
        "gl_account_id": "GLAccountID",
        "transaction_date": "TransactionDate",
        "amount": "Amount",
        "memo": "Memo",
        "update_date": "UpdateDate",
    }
    # RM previously returned "ID" instead of "BillID"; accept as fallback
    _DEPRECATED_ALIASES: dict[str, str] = {"ID": "bill_id"}


class BillDetailMapper(RMMapper):
    _FIELD_MAP = {
        "bill_detail_id": "BillDetailID",
        "bill_id": "BillID",
        "gl_account_id": "GLAccountID",
        "transaction_date": "TransactionDate",
        "amount": "Amount",
        "memo": "Memo",
    }


class VendorMapper(RMMapper):
    _FIELD_MAP = {
        "vendor_id": "VendorID",
        "name": "Name",
        "is_active": "IsActive",
        "email": "Email",
        "phone": "Phone",
        "address": "Address",
    }


class PaymentMapper(RMMapper):
    _FIELD_MAP = {
        "payment_id": "PaymentID",
        "tenant_id": "TenantID",
        "property_id": "PropertyID",
        "unit_id": "UnitID",
        "transaction_date": "TransactionDate",
        "amount": "Amount",
        "memo": "Memo",
    }


class HistoryNoteMapper(RMMapper):
    _FIELD_MAP = {
        "history_id": "HistoryID",
        "history_category_id": "HistoryCategoryID",
        "history_date": "HistoryDate",
        "property_id": "PropertyID",
        "tenant_id": "TenantID",
        "note": "Note",
    }


class LocationMapper(RMMapper):
    _FIELD_MAP = {
        "location_id": "LocationID",
        "friendly_name": "FriendlyName",
    }


# ---------------------------------------------------------------------------
# Pagination helpers
# ---------------------------------------------------------------------------

def _extract_next_link(link_header: str) -> str | None:
    """Return the URL for rel="next" from an RFC 5988 Link header, or None."""
    for segment in link_header.split(","):
        if 'rel="next"' in segment:
            m = re.search(r"<([^>]+)>", segment)
            if m:
                return m.group(1)
    return None


def parse_pagination(headers: Mapping[str, str]) -> PaginationMeta:
    """
    Parse RM API response headers into a PaginationMeta.

    X-Total-Results  integer count of all records matching the query
    Link             RFC 5988 link relations; rel="next" signals a following page
    """
    total_raw = headers.get("X-Total-Results") or headers.get("x-total-results") or "0"
    total = int(total_raw)

    link_raw = headers.get("Link") or headers.get("link") or ""
    next_url = _extract_next_link(link_raw)

    return PaginationMeta(total=total, has_next=next_url is not None, next_url=next_url)
