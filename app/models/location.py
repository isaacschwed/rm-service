import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class RMLocation(Base):
    __tablename__ = "rm_locations"

    __table_args__ = (
        UniqueConstraint("company_id", "rm_location_id", name="uq_rm_locations_company_location"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    rm_location_id: Mapped[str] = mapped_column(String, nullable=False)
    friendly_name: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    exclude_from_ops: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )  # TRUE = never use this location (e.g. MSK/Loc6 for AP)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    company: Mapped["Company"] = relationship("Company", back_populates="locations")

    def __repr__(self) -> str:
        return (
            f"<RMLocation company_id={self.company_id} "
            f"rm_location_id={self.rm_location_id!r} "
            f"friendly_name={self.friendly_name!r} "
            f"excluded={self.exclude_from_ops}>"
        )
