import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    operation: Mapped[str] = mapped_column(String, nullable=False)
    rm_entity_id: Mapped[str | None] = mapped_column(String, nullable=True)

    # Snapshot of what was returned — returned verbatim on duplicate calls
    response_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    company: Mapped["Company"] = relationship("Company", back_populates="idempotency_records")

    def __repr__(self) -> str:
        return (
            f"<IdempotencyRecord key={self.idempotency_key!r} "
            f"operation={self.operation!r} company_id={self.company_id}>"
        )
