"""Core CRUD operations for the planner application.

Provides :class:`TaskManager` — a single entry-point that the future UI layer
(Flet) will use to talk to the database.  Every public method opens its own
session via a context manager and commits / rolls back automatically.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime
from typing import Generator

from sqlalchemy.orm import Session

from database.db_config import SessionLocal, init_db as _init_db
from database.models import (
    History,
    Subject,
    Task,
    TaskPriority,
    TaskStatus,
)


class TaskManager:
    """Facade that wraps all database interactions behind typed methods."""

    # ──────────────────────────────────────────
    # Session helper
    # ──────────────────────────────────────────
    @staticmethod
    @contextmanager
    def _session() -> Generator[Session, None, None]:
        """Yield a transactional session; commit on success, rollback on error."""
        session: Session = SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # ──────────────────────────────────────────
    # Initialisation
    # ──────────────────────────────────────────
    @staticmethod
    def init_db() -> None:
        """Create all tables in *planner.db* if they don't yet exist."""
        _init_db()

    # ──────────────────────────────────────────
    # Subject CRUD
    # ──────────────────────────────────────────
    def add_subject(self, name: str) -> Subject:
        """Create a new subject and return the persisted instance.

        Raises:
            sqlalchemy.exc.IntegrityError: if a subject with the same name
                already exists.
        """
        with self._session() as session:
            subject = Subject(name=name)
            session.add(subject)
            session.flush()          # populate subject.id before commit
            return subject

    def get_all_subjects(self) -> list[Subject]:
        """Return every subject ordered by name."""
        with self._session() as session:
            return (
                session.query(Subject)
                .order_by(Subject.name)
                .all()
            )

    def get_subject_by_id(self, subject_id: int) -> Subject | None:
        """Return a single subject or ``None``."""
        with self._session() as session:
            return session.get(Subject, subject_id)

    # ──────────────────────────────────────────
    # Task CRUD
    # ──────────────────────────────────────────
    def add_task(
        self,
        name: str,
        subject_id: int,
        *,
        description: str | None = None,
        priority: TaskPriority = TaskPriority.MEDIUM,
        expected_time: float | None = None,
        deadline: datetime | None = None,
    ) -> Task:
        """Create a new task linked to an existing subject.

        Returns the persisted :class:`Task` instance.

        Raises:
            ValueError: if *subject_id* does not match any subject.
        """
        with self._session() as session:
            subject = session.get(Subject, subject_id)
            if subject is None:
                raise ValueError(
                    f"Subject with id={subject_id} not found."
                )

            task = Task(
                name=name,
                description=description,
                subject_id=subject_id,
                priority=priority,
                expected_time=expected_time,
                deadline=deadline,
                status=TaskStatus.PENDING,
            )
            session.add(task)
            session.flush()
            return task

    def get_all_tasks(self) -> list[Task]:
        """Return every task ordered by deadline (nulls last), then priority."""
        with self._session() as session:
            return (
                session.query(Task)
                .order_by(
                    Task.deadline.is_(None),   # NULLs go last
                    Task.deadline,
                    Task.priority,
                )
                .all()
            )

    def get_tasks_by_subject(self, subject_id: int) -> list[Task]:
        """Return all tasks belonging to a given subject."""
        with self._session() as session:
            return (
                session.query(Task)
                .filter(Task.subject_id == subject_id)
                .order_by(Task.deadline)
                .all()
            )

    def get_task_by_id(self, task_id: int) -> Task | None:
        """Return a single task or ``None``."""
        with self._session() as session:
            return session.get(Task, task_id)

    # ──────────────────────────────────────────
    # Task status transitions
    # ──────────────────────────────────────────
    def update_task_status(self, task_id: int, new_status: TaskStatus) -> Task:
        """Change a task's status to *new_status*.

        For marking a task as completed **with** time tracking, use
        :meth:`complete_task` instead.

        Raises:
            ValueError: if the task does not exist.
        """
        with self._session() as session:
            task = session.get(Task, task_id)
            if task is None:
                raise ValueError(f"Task with id={task_id} not found.")

            task.status = new_status
            session.flush()
            return task

    def complete_task(
        self,
        task_id: int,
        actual_time: float,
        completed_at: date | None = None,
    ) -> Task:
        """Mark a task as completed and write a :class:`History` record.

        Args:
            task_id: Primary key of the task.
            actual_time: Hours actually spent on the task.
            completed_at: Date of completion (defaults to today).

        Returns:
            The updated :class:`Task` (with ``status == COMPLETED``).

        Raises:
            ValueError: if the task does not exist.
        """
        if completed_at is None:
            completed_at = date.today()

        with self._session() as session:
            task = session.get(Task, task_id)
            if task is None:
                raise ValueError(f"Task with id={task_id} not found.")

            task.status = TaskStatus.COMPLETED

            history = History(
                task_id=task.id,
                actual_time=actual_time,
                completed_at=completed_at,
            )
            session.add(history)
            session.flush()
            return task

    # ──────────────────────────────────────────
    # History read
    # ──────────────────────────────────────────
    def get_history(self, task_id: int | None = None) -> list[History]:
        """Return history records, optionally filtered by *task_id*."""
        with self._session() as session:
            query = session.query(History).order_by(History.completed_at.desc())
            if task_id is not None:
                query = query.filter(History.task_id == task_id)
            return query.all()
