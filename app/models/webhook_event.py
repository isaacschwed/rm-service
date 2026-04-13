import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class RMWebhookEvent(Base):
    """
    Inbound RM webhook events. Table is built now, endpoint comes in a later phase.
    """

    __tablename__ = "rm_webhook_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="SET NULL"),
        nullable=True,
    )
    rm_location_id: Mapped[str | None] = mapped_column(String, nullable=True)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String, nullable=True)
    parent_entity_id: Mapped[str | None] = mapped_column(String, nullable=True)
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    forwarded_to: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # which platform received this event
    forwarded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    company: Mapped["Company | None"] = relationship("Company")

    def __repr__(self) -> str:
        return f"<RMWebhookEvent event_type={self.event_type!r} location={self.rm_location_id}>"
