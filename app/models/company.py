import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    platform_source: Mapped[str] = mapped_column(
        String, nullable=False
    )  # 'resira' | 'subsidy' | 'ap' | 'unified'
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Credential health check fields
    credential_status: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # 'ok' | 'failed' | 'unchecked'
    credential_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Soft delete + credential purge
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    purge_credentials_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )  # deleted_at + 30 days

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    credentials: Mapped["RMCredentials"] = relationship(
        "RMCredentials", back_populates="company", uselist=False
    )
    locations: Mapped[list["RMLocation"]] = relationship(
        "RMLocation", back_populates="company"
    )
    auth_token: Mapped["RMAuthToken"] = relationship(
        "RMAuthToken", back_populates="company", uselist=False
    )
    operation_logs: Mapped[list["OperationLog"]] = relationship(
        "OperationLog", back_populates="company"
    )
    idempotency_records: Mapped[list["IdempotencyRecord"]] = relationship(
        "IdempotencyRecord", back_populates="company"
    )

    def __repr__(self) -> str:
        return f"<Company id={self.id} name={self.name!r} platform={self.platform_source}>"
