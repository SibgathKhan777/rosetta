import uuid

from sqlalchemy import ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class UsageCredits(Base):
    __tablename__ = "usage_credits"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True)
    # Credits scale roughly with video duration (see app/services/credits.py for the
    # per-minute cost formula) rather than being a flat per-job charge.
    credits_remaining: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    credits_used_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    user = relationship("User", back_populates="credits")
