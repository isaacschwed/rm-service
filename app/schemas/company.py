"""
Pydantic schemas for company registration request and response.
"""
import uuid
from typing import Literal

from pydantic import BaseModel, Field


class LocationInput(BaseModel):
    rm_location_id: str = Field(..., min_length=1)
    friendly_name: str = Field(..., min_length=1)
    exclude_from_ops: bool = False


class RegisterCompanyRequest(BaseModel):
    name: str = Field(..., min_length=1)
    platform_source: Literal["resira", "subsidy", "ap", "unified"]
    rm_username: str = Field(..., min_length=1)
    rm_password: str = Field(..., min_length=1)
    locations: list[LocationInput] = Field(..., min_length=1)


class LocationResponse(BaseModel):
    location_id: uuid.UUID
    rm_location_id: str
    friendly_name: str
    exclude_from_ops: bool


class RegisterCompanyResponse(BaseModel):
    success: bool = True
    company_id: uuid.UUID
    locations: list[LocationResponse]
