"""Declarative ORM models (SQLAlchemy 2.0 style)."""

from __future__ import annotations

import enum
from datetime import datetime, date

from sqlalchemy import (
    String,
    Text,
    Integer,
    Float,
    Date,
    DateTime,
    Enum,
    ForeignKey,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)


# ──────────────────────────────────────────────
# Base class
# ──────────────────────────────────────────────
class Base(DeclarativeBase):
    """Shared declarative base for every model."""


# ──────────────────────────────────────────────
# Enums
# ──────────────────────────────────────────────
class TaskStatus(str, enum.Enum):
    """Allowed statuses for a task."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TaskPriority(str, enum.Enum):
    """Priority levels from low to critical."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ──────────────────────────────────────────────
# Subject
# ──────────────────────────────────────────────
class Subject(Base):
    """University subject (or any category) that groups tasks."""

    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)

    # one-to-many → Task
    tasks: Mapped[list[Task]] = relationship(
        back_populates="subject",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Subject(id={self.id}, name={self.name!r})>"


# ──────────────────────────────────────────────
# Task
# ──────────────────────────────────────────────
class Task(Base):
    """A single task / assignment linked to a subject."""

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"),
        nullable=False,
    )

    priority: Mapped[TaskPriority] = mapped_column(
        Enum(TaskPriority, native_enum=False, length=20),
        default=TaskPriority.MEDIUM,
        nullable=False,
    )

    expected_time: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="Expected time to complete (hours)",
    )

    deadline: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, native_enum=False, length=20),
        default=TaskStatus.PENDING,
        nullable=False,
    )

    # many-to-one → Subject
    subject: Mapped[Subject] = relationship(back_populates="tasks", lazy="joined")

    # one-to-many → History
    history_entries: Mapped[list[History]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return (
            f"<Task(id={self.id}, name={self.name!r}, "
            f"status={self.status.value!r})>"
        )


# ──────────────────────────────────────────────
# History
# ──────────────────────────────────────────────
class History(Base):
    """Record of a completed task — stores actual time spent and completion date."""

    __tablename__ = "history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    task_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )

    actual_time: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        comment="Actual time spent (hours)",
    )

    completed_at: Mapped[date] = mapped_column(
        Date,
        default=date.today,
        nullable=False,
    )

    # many-to-one → Task
    task: Mapped[Task] = relationship(back_populates="history_entries")

    def __repr__(self) -> str:
        return (
            f"<History(id={self.id}, task_id={self.task_id}, "
            f"actual_time={self.actual_time}, "
            f"completed_at={self.completed_at})>"
        )
