"""
Unit tests for app.services.rm_mapper and app.schemas.rm_types.

Pure logic — no DB, Redis, or network required.
"""

import pytest

from app.schemas.rm_types import ContactTypeID, EntityType, PaginationMeta
from app.services.rm_mapper import (
    BillDetailMapper,
    BillMapper,
    ContactMapper,
    HistoryNoteMapper,
    LocationMapper,
    PaymentMapper,
    ProspectMapper,
    PropertyMapper,
    RMMapper,
    TenantMapper,
    UnitMapper,
    VendorMapper,
    parse_pagination,
)


# ---------------------------------------------------------------------------
# Minimal mapper used to exercise base class behaviour in isolation
# ---------------------------------------------------------------------------

class _TestMapper(RMMapper):
    _FIELD_MAP = {
        "our_id": "OurID",
        "full_name": "FullName",
    }
    _DEPRECATED_ALIASES = {"OldID": "our_id"}


# ---------------------------------------------------------------------------
# RMMapper.to_rm
# ---------------------------------------------------------------------------

def test_to_rm_translates_known_fields():
    result = _TestMapper().to_rm({"our_id": 1, "full_name": "Alice"})
    assert result == {"OurID": 1, "FullName": "Alice"}


def test_to_rm_passes_through_unknown_field():
    result = _TestMapper().to_rm({"our_id": 1, "extra_field": "x"})
    assert result == {"OurID": 1, "extra_field": "x"}


def test_to_rm_preserves_none_value():
    """None is kept — RM may need explicit null to clear a field."""
    result = _TestMapper().to_rm({"our_id": None, "full_name": "Bob"})
    assert result == {"OurID": None, "FullName": "Bob"}


def test_to_rm_empty_input():
    assert _TestMapper().to_rm({}) == {}


def test_to_rm_partial_fields():
    result = _TestMapper().to_rm({"our_id": 5})
    assert result == {"OurID": 5}
    assert "FullName" not in result


# ---------------------------------------------------------------------------
# RMMapper.from_rm
# ---------------------------------------------------------------------------

def test_from_rm_translates_known_fields():
    result = _TestMapper().from_rm({"OurID": 1, "FullName": "Alice"})
    assert result == {"our_id": 1, "full_name": "Alice"}


def test_from_rm_passes_through_unknown_field():
    result = _TestMapper().from_rm({"OurID": 1, "NewRMField": "future"})
    assert result["our_id"] == 1
    assert result["NewRMField"] == "future"


def test_from_rm_preserves_none_value():
    result = _TestMapper().from_rm({"OurID": None})
    assert "our_id" in result
    assert result["our_id"] is None


def test_from_rm_empty_input():
    assert _TestMapper().from_rm({}) == {}


def test_from_rm_partial_fields():
    result = _TestMapper().from_rm({"OurID": 7})
    assert result == {"our_id": 7}
    assert "full_name" not in result


# ---------------------------------------------------------------------------
# Deprecated / stripped fields
# ---------------------------------------------------------------------------

def test_from_rm_strips_api_uri():
    result = _TestMapper().from_rm({"OurID": 1, "ApiUri": "https://rm.api/..."})
    assert "ApiUri" not in result
    assert result == {"our_id": 1}


def test_from_rm_strips_color_id():
    result = _TestMapper().from_rm({"OurID": 1, "ColorID": "red"})
    assert "ColorID" not in result
    assert "color_id" not in result


def test_from_rm_strips_primary_contact():
    result = _TestMapper().from_rm({"OurID": 1, "PrimaryContact": {"id": 2}})
    assert "PrimaryContact" not in result


def test_from_rm_strips_avid_invoice_url():
    result = _TestMapper().from_rm({"OurID": 1, "AvidInvoiceURL": "https://avid.com/inv/1"})
    assert "AvidInvoiceURL" not in result


def test_from_rm_strips_do_not_print_statements():
    result = _TestMapper().from_rm({"OurID": 1, "DoNotPrintStatements": True})
    assert "DoNotPrintStatements" not in result


def test_from_rm_strips_attachments():
    result = _TestMapper().from_rm({"OurID": 1, "Attachments": [{"id": 9}]})
    assert "Attachments" not in result


def test_from_rm_strips_all_deprecated_fields_together():
    data = {
        "OurID": 5,
        "ApiUri": "/uri",
        "ColorID": "blue",
        "PrimaryContact": {},
        "AvidInvoiceURL": "url",
        "DoNotPrintStatements": False,
        "Attachments": [],
    }
    assert _TestMapper().from_rm(data) == {"our_id": 5}


# ---------------------------------------------------------------------------
# Deprecated alias resolution
# ---------------------------------------------------------------------------

def test_from_rm_deprecated_alias_used_when_canonical_absent():
    result = _TestMapper().from_rm({"OldID": 99})
    assert result["our_id"] == 99


def test_from_rm_canonical_wins_over_deprecated_alias():
    """OurID (canonical) must overwrite OldID (alias) when both present."""
    result = _TestMapper().from_rm({"OldID": 1, "OurID": 2})
    assert result["our_id"] == 2


def test_from_rm_alias_key_not_kept_in_output():
    """The raw deprecated key must not appear alongside the canonical key."""
    result = _TestMapper().from_rm({"OldID": 99})
    assert "OldID" not in result


# ---------------------------------------------------------------------------
# ProspectMapper
# ---------------------------------------------------------------------------

def test_prospect_mapper_to_rm():
    result = ProspectMapper().to_rm({
        "prospect_id": 10,
        "property_id": 20,
        "first_name": "Jane",
        "last_name": "Doe",
        "update_date": "2024-01-01",
    })
    assert result == {
        "ProspectID": 10,
        "PropertyID": 20,
        "FirstName": "Jane",
        "LastName": "Doe",
        "UpdateDate": "2024-01-01",
    }


def test_prospect_mapper_from_rm():
    result = ProspectMapper().from_rm({
        "ProspectID": 10,
        "PropertyID": 20,
        "FirstName": "Jane",
        "LastName": "Doe",
        "UpdateDate": "2024-01-01",
        "ApiUri": "/api/prospects/10",
    })
    assert result == {
        "prospect_id": 10,
        "property_id": 20,
        "first_name": "Jane",
        "last_name": "Doe",
        "update_date": "2024-01-01",
    }


# ---------------------------------------------------------------------------
# ContactMapper
# ---------------------------------------------------------------------------

def test_contact_mapper_to_rm():
    result = ContactMapper().to_rm({
        "contact_id": 5,
        "first_name": "Bob",
        "contact_type_id": 6,
    })
    assert result == {"ContactID": 5, "FirstName": "Bob", "ContactTypeID": 6}


def test_contact_mapper_from_rm():
    result = ContactMapper().from_rm({
        "ContactID": 5,
        "FirstName": "Bob",
        "ContactTypeID": 6,
        "ApiUri": "/contacts/5",
    })
    assert result == {"contact_id": 5, "first_name": "Bob", "contact_type_id": 6}


# ---------------------------------------------------------------------------
# TenantMapper
# ---------------------------------------------------------------------------

def test_tenant_mapper_to_rm():
    result = TenantMapper().to_rm({"tenant_id": 100, "first_name": "Alice"})
    assert result == {"TenantID": 100, "FirstName": "Alice"}


def test_tenant_mapper_from_rm():
    result = TenantMapper().from_rm({
        "TenantID": 100,
        "LastName": "Smith",
        "ApiUri": "/t/100",
        "ColorID": 3,
    })
    assert result == {"tenant_id": 100, "last_name": "Smith"}


def test_tenant_mapper_move_dates():
    result = TenantMapper().from_rm({
        "TenantID": 1,
        "MoveInDate": "2022-06-01",
        "MoveOutDate": "2024-01-31",
    })
    assert result["move_in_date"] == "2022-06-01"
    assert result["move_out_date"] == "2024-01-31"


# ---------------------------------------------------------------------------
# UnitMapper
# ---------------------------------------------------------------------------

def test_unit_mapper_to_rm():
    result = UnitMapper().to_rm({
        "unit_id": 7,
        "is_vacant": True,
        "current_market_rent": 1200.0,
    })
    assert result == {"UnitID": 7, "IsVacant": True, "CurrentMarketRent": 1200.0}


def test_unit_mapper_from_rm():
    result = UnitMapper().from_rm({
        "UnitID": 7,
        "IsVacant": True,
        "CurrentMarketRent": 1200.0,
    })
    assert result == {"unit_id": 7, "is_vacant": True, "current_market_rent": 1200.0}


def test_unit_mapper_none_rent():
    """None market rent must not raise and must appear in output."""
    result = UnitMapper().from_rm({"UnitID": 7, "CurrentMarketRent": None})
    assert result["current_market_rent"] is None


def test_unit_mapper_vacant_false():
    result = UnitMapper().from_rm({"UnitID": 3, "IsVacant": False})
    assert result["is_vacant"] is False


# ---------------------------------------------------------------------------
# PropertyMapper
# ---------------------------------------------------------------------------

def test_property_mapper_to_rm():
    result = PropertyMapper().to_rm({"property_id": 3, "name": "Maple Apts"})
    assert result == {"PropertyID": 3, "Name": "Maple Apts"}


def test_property_mapper_from_rm():
    result = PropertyMapper().from_rm({
        "PropertyID": 3,
        "Name": "Maple Apts",
        "LocationID": "loc-1",
        "ApiUri": "/p/3",
    })
    assert result == {"property_id": 3, "name": "Maple Apts", "location_id": "loc-1"}


# ---------------------------------------------------------------------------
# BillMapper — including deprecated ID alias
# ---------------------------------------------------------------------------

def test_bill_mapper_to_rm():
    result = BillMapper().to_rm({
        "bill_id": 500,
        "gl_account_id": 101,
        "transaction_date": "2024-03-15",
        "amount": 250.00,
    })
    assert result == {
        "BillID": 500,
        "GLAccountID": 101,
        "TransactionDate": "2024-03-15",
        "Amount": 250.00,
    }


def test_bill_mapper_from_rm_canonical():
    result = BillMapper().from_rm({"BillID": 500, "GLAccountID": 101})
    assert result["bill_id"] == 500
    assert result["gl_account_id"] == 101


def test_bill_mapper_deprecated_id_used_as_fallback():
    """Old 'ID' field maps to bill_id when no BillID is present."""
    result = BillMapper().from_rm({"ID": 500, "GLAccountID": 101})
    assert result["bill_id"] == 500
    assert "ID" not in result


def test_bill_mapper_canonical_bill_id_wins_over_deprecated_id():
    """When both BillID and ID are present, BillID (canonical) must win."""
    result = BillMapper().from_rm({"BillID": 500, "ID": 999, "GLAccountID": 101})
    assert result["bill_id"] == 500


def test_bill_mapper_strips_deprecated_global_fields():
    result = BillMapper().from_rm({"BillID": 1, "AvidInvoiceURL": "url", "ApiUri": "/"})
    assert "AvidInvoiceURL" not in result
    assert "ApiUri" not in result


# ---------------------------------------------------------------------------
# BillDetailMapper
# ---------------------------------------------------------------------------

def test_bill_detail_mapper_to_rm():
    result = BillDetailMapper().to_rm({
        "bill_detail_id": 200,
        "bill_id": 500,
        "gl_account_id": 101,
    })
    assert result == {"BillDetailID": 200, "BillID": 500, "GLAccountID": 101}


def test_bill_detail_mapper_from_rm():
    result = BillDetailMapper().from_rm({
        "BillDetailID": 200,
        "BillID": 500,
        "TransactionDate": "2024-03-15",
        "ApiUri": "/bd/200",
    })
    assert result == {
        "bill_detail_id": 200,
        "bill_id": 500,
        "transaction_date": "2024-03-15",
    }


# ---------------------------------------------------------------------------
# VendorMapper
# ---------------------------------------------------------------------------

def test_vendor_mapper_to_rm():
    result = VendorMapper().to_rm({"vendor_id": 77, "is_active": True})
    assert result == {"VendorID": 77, "IsActive": True}


def test_vendor_mapper_from_rm():
    result = VendorMapper().from_rm({
        "VendorID": 77,
        "Name": "ACME Supplies",
        "IsActive": False,
        "ApiUri": "/v/77",
    })
    assert result == {"vendor_id": 77, "name": "ACME Supplies", "is_active": False}


def test_vendor_mapper_none_email():
    result = VendorMapper().from_rm({"VendorID": 1, "Email": None})
    assert result["email"] is None


# ---------------------------------------------------------------------------
# PaymentMapper
# ---------------------------------------------------------------------------

def test_payment_mapper_to_rm():
    result = PaymentMapper().to_rm({
        "payment_id": 300,
        "tenant_id": 100,
        "amount": 950.0,
    })
    assert result == {"PaymentID": 300, "TenantID": 100, "Amount": 950.0}


def test_payment_mapper_from_rm():
    result = PaymentMapper().from_rm({
        "PaymentID": 300,
        "TenantID": 100,
        "TransactionDate": "2024-03-01",
        "ApiUri": "/pay/300",
    })
    assert result == {
        "payment_id": 300,
        "tenant_id": 100,
        "transaction_date": "2024-03-01",
    }


# ---------------------------------------------------------------------------
# HistoryNoteMapper
# ---------------------------------------------------------------------------

def test_history_note_mapper_to_rm():
    result = HistoryNoteMapper().to_rm({
        "history_id": 400,
        "history_category_id": 5,
        "history_date": "2024-02-10",
    })
    assert result == {
        "HistoryID": 400,
        "HistoryCategoryID": 5,
        "HistoryDate": "2024-02-10",
    }


def test_history_note_mapper_from_rm():
    result = HistoryNoteMapper().from_rm({
        "HistoryID": 400,
        "Note": "Called tenant — no answer",
        "HistoryDate": "2024-02-10",
        "ApiUri": "/h/400",
    })
    assert result == {
        "history_id": 400,
        "note": "Called tenant — no answer",
        "history_date": "2024-02-10",
    }


# ---------------------------------------------------------------------------
# LocationMapper
# ---------------------------------------------------------------------------

def test_location_mapper_to_rm():
    result = LocationMapper().to_rm({"location_id": "1", "friendly_name": "Main Office"})
    assert result == {"LocationID": "1", "FriendlyName": "Main Office"}


def test_location_mapper_from_rm():
    result = LocationMapper().from_rm({
        "LocationID": "1",
        "FriendlyName": "Main Office",
        "ApiUri": "/loc/1",
    })
    assert result == {"location_id": "1", "friendly_name": "Main Office"}


# ---------------------------------------------------------------------------
# parse_pagination
# ---------------------------------------------------------------------------

def test_parse_pagination_full_headers():
    headers = {
        "X-Total-Results": "150",
        "Link": '<https://api.rm.com/residents?page=2>; rel="next", '
                '<https://api.rm.com/residents?page=1>; rel="prev"',
    }
    meta = parse_pagination(headers)
    assert meta.total == 150
    assert meta.has_next is True
    assert meta.next_url == "https://api.rm.com/residents?page=2"


def test_parse_pagination_no_next_link():
    headers = {
        "X-Total-Results": "50",
        "Link": '<https://api.rm.com/residents?page=1>; rel="prev"',
    }
    meta = parse_pagination(headers)
    assert meta.total == 50
    assert meta.has_next is False
    assert meta.next_url is None


def test_parse_pagination_no_link_header():
    headers = {"X-Total-Results": "25"}
    meta = parse_pagination(headers)
    assert meta.total == 25
    assert meta.has_next is False
    assert meta.next_url is None


def test_parse_pagination_empty_headers():
    meta = parse_pagination({})
    assert meta.total == 0
    assert meta.has_next is False
    assert meta.next_url is None


def test_parse_pagination_only_next_link():
    headers = {
        "X-Total-Results": "100",
        "Link": '<https://api.rm.com/bills?page=3>; rel="next"',
    }
    meta = parse_pagination(headers)
    assert meta.has_next is True
    assert meta.next_url == "https://api.rm.com/bills?page=3"


def test_parse_pagination_returns_pagination_meta_instance():
    assert isinstance(parse_pagination({}), PaginationMeta)


def test_parse_pagination_zero_total():
    meta = parse_pagination({"X-Total-Results": "0"})
    assert meta.total == 0
    assert meta.has_next is False


def test_parse_pagination_link_next_url_extracted_correctly():
    """Verify only the URL inside <...> is returned, not surrounding text."""
    headers = {
        "X-Total-Results": "1",
        "Link": '<https://example.com/next?skip=10&top=10>; rel="next"',
    }
    meta = parse_pagination(headers)
    assert meta.next_url == "https://example.com/next?skip=10&top=10"


# ---------------------------------------------------------------------------
# rm_types: EntityType
# ---------------------------------------------------------------------------

def test_entity_type_values():
    assert EntityType.PROSPECT == "prospect"
    assert EntityType.TENANT == "tenant"
    assert EntityType.BILL == "bill"
    assert EntityType.VENDOR == "vendor"
    assert EntityType.UNIT == "unit"
    assert EntityType.PROPERTY == "property"


def test_entity_type_is_str():
    assert isinstance(EntityType.PROSPECT, str)


# ---------------------------------------------------------------------------
# rm_types: ContactTypeID
# ---------------------------------------------------------------------------

def test_contact_type_id_values():
    assert ContactTypeID.PRIMARY == 6
    assert ContactTypeID.OCCUPANT == 7
    assert ContactTypeID.CO_APPLICANT == 8
    assert ContactTypeID.GUARANTOR == 9
    assert ContactTypeID.CASE_WORKER == 10
    assert ContactTypeID.HASA_SUPERVISOR == 11


def test_contact_type_id_is_int():
    assert isinstance(ContactTypeID.PRIMARY, int)
    # Int arithmetic should work naturally
    assert ContactTypeID.PRIMARY + 1 == ContactTypeID.OCCUPANT
