import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class OperationLog(Base):
    """
    Immutable audit log. Every RM operation from every platform is logged here.
    A DB trigger prevents UPDATE and DELETE — rows are write-once.
    Never modify this table outside of INSERT.
    """

    __tablename__ = "operation_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    platform_source: Mapped[str] = mapped_column(
        String, nullable=False
    )  # 'resira' | 'subsidy' | 'ap'
    location_id: Mapped[str | None] = mapped_column(String, nullable=True)
    operation: Mapped[str] = mapped_column(String, nullable=False)  # e.g. 'post_payment'
    rm_endpoint: Mapped[str | None] = mapped_column(String, nullable=True)

    # Summaries — never raw credentials, never full PII
    request_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    rm_response_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rm_response_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    company: Mapped["Company"] = relationship("Company", back_populates="operation_logs")

    def __repr__(self) -> str:
        return (
            f"<OperationLog id={self.id} operation={self.operation!r} "
            f"success={self.success} platform={self.platform_source}>"
        )
