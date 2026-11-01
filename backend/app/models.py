import uuid
from datetime import datetime

from geoalchemy2 import Geometry
from geoalchemy2.elements import WKBElement, WKTElement
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    jurisdiction: Mapped[str] = mapped_column(String(50), nullable=False, default="DISTRICT")
    contact_email: Mapped[str | None] = mapped_column(String(255))
    escalation_email: Mapped[str | None] = mapped_column(String(255))


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="citizen")
    department_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("departments.id"))
    jurisdiction_area: Mapped[str | None] = mapped_column(String(255))
    location: Mapped[WKBElement | WKTElement | None] = mapped_column(Geometry("POINT", srid=4326))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Grievance(Base):
    __tablename__ = "grievances"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tracking_id: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    raw_transcript: Mapped[str | None] = mapped_column(Text)
    raw_language: Mapped[str | None] = mapped_column(String(10))
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="OTHER", index=True)
    sub_category: Mapped[str | None] = mapped_column(String(100))
    location: Mapped[WKBElement | WKTElement | None] = mapped_column(Geometry("POINT", srid=4326, spatial_index=True))
    address: Mapped[str | None] = mapped_column(Text)
    district: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(100))
    image_urls: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    audio_url: Mapped[str | None] = mapped_column(Text)
    severity_score: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    severity_label: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    severity_explanation: Mapped[str | None] = mapped_column(Text)
    severity_signals: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    assigned_department_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("departments.id"))
    assigned_authority_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PROCESSING", index=True)
    sla_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    escalation_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_duplicate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    parent_grievance_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("grievances.id"))
    report_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    reporter_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    reporter_phone: Mapped[str | None] = mapped_column(String(15))
    description_embedding: Mapped[list[float] | None] = mapped_column(JSONB)
    processing_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    department: Mapped[Department | None] = relationship()


class TimelineEntry(Base):
    __tablename__ = "grievance_timeline"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    grievance_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("grievances.id"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    performed_by: Mapped[str] = mapped_column(String(50), nullable=False, default="SYSTEM")
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VerificationResponse(Base):
    __tablename__ = "verification_responses"
    __table_args__ = (
        UniqueConstraint("grievance_id", "user_id", name="uq_verification_grievance_user"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    grievance_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("grievances.id"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    is_resolved: Mapped[bool] = mapped_column(Boolean, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    responded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
