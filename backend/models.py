from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    name: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
    )

    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
    )

    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    sessions: Mapped[list["LoginSession"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class LoginSession(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(
        String(128),
        primary_key=True,
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
    )

    user: Mapped[User] = relationship(
        back_populates="sessions",
    )


class VulnerabilityReport(Base):
    __tablename__ = "vulnerability_reports"
    __table_args__ = (
        UniqueConstraint("report_code", name="uq_vulnerability_reports_report_code"),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    report_code: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
    )

    package_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    affected_version: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    submitter_email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    severity: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    agreed_to_terms: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )

    submission_date: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    advisory_id: Mapped[int | None] = mapped_column(
        ForeignKey("advisories.id", ondelete="RESTRICT"),
        nullable=True,
    )

    available_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )

    advisory: Mapped["Advisory | None"] = relationship(
        back_populates="reports",
    )

    advisories: Mapped[list["RelatedAdvisory"]] = relationship(
        back_populates="report",
        cascade="all, delete-orphan",
    )


class RelatedAdvisory(Base):
    __tablename__ = "related_advisories"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    report_id: Mapped[int] = mapped_column(
        ForeignKey("vulnerability_reports.id"),
        nullable=False,
    )

    advisory_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    report: Mapped[VulnerabilityReport] = relationship(
        back_populates="advisories",
    )


class Advisory(Base):
    """The HW5 related entity for vulnerability reports."""

    __tablename__ = "advisories"
    __table_args__ = (
        UniqueConstraint("advisory_code", name="uq_advisories_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    publisher: Mapped[str] = mapped_column(String(255), nullable=False)
    advisory_code: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    reports: Mapped[list[VulnerabilityReport]] = relationship(
        back_populates="advisory",
    )
