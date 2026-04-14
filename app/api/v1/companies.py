"""
Company registration endpoint.
"""
import structlog
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext, require_auth
from app.db.session import get_db
from app.models.company import Company
from app.models.location import RMLocation
from app.schemas.company import (
    LocationResponse,
    RegisterCompanyRequest,
    RegisterCompanyResponse,
)
from app.services.credentials import store_credentials

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["companies"])


@router.post("/register", status_code=201, response_model=RegisterCompanyResponse)
async def register_company(
    body: RegisterCompanyRequest,
    auth: AuthContext = Depends(require_auth("register_company")),
    db: AsyncSession = Depends(get_db),
) -> RegisterCompanyResponse:
    """
    Register a new company with Rent Manager credentials and locations.

    Creates the company row, stores encrypted credentials, and creates all
    location rows in a single transaction.
    """
    # Create company
    company = Company(
        name=body.name,
        platform_source=body.platform_source,
        credential_status="unchecked",
    )
    db.add(company)
    await db.flush()  # Materialises company.id via uuid_generate_v4()

    # Store encrypted credentials (never logged, never returned)
    await store_credentials(db, company.id, body.rm_username, body.rm_password)

    # Create location rows
    location_rows: list[RMLocation] = []
    for loc in body.locations:
        rm_loc = RMLocation(
            company_id=company.id,
            rm_location_id=loc.rm_location_id,
            friendly_name=loc.friendly_name,
            exclude_from_ops=loc.exclude_from_ops,
        )
        db.add(rm_loc)
        location_rows.append(rm_loc)

    await db.flush()  # Materialises location IDs

    logger.info(
        "company_registered",
        company_id=str(company.id),
        name=company.name,
        platform=body.platform_source,
        location_count=len(location_rows),
    )

    return RegisterCompanyResponse(
        company_id=company.id,
        locations=[
            LocationResponse(
                location_id=loc.id,
                rm_location_id=loc.rm_location_id,
                friendly_name=loc.friendly_name,
                exclude_from_ops=loc.exclude_from_ops,
            )
            for loc in location_rows
        ],
    )
