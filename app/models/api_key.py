import uuid
from datetime import datetime

from sqlalchemy import ARRAY, Boolean, DateTime, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class ServiceApiKey(Base):
    __tablename__ = "service_api_keys"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    platform: Mapped[str] = mapped_column(
        String, nullable=False, unique=True
    )  # 'resira' | 'subsidy' | 'ap'
    key_hash: Mapped[str] = mapped_column(
        String, nullable=False, unique=True
    )  # SHA-256 of raw key — raw key given out exactly once
    allowed_operations: Mapped[list[str]] = mapped_column(
        ARRAY(String), nullable=False, server_default=text("'{}'")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<ServiceApiKey platform={self.platform!r} active={self.is_active}>"
