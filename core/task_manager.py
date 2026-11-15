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
from ai.predictor import Prediction, TimePredictor


_UNSET = object()


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
    # Subject / Tag CRUD
    # ──────────────────────────────────────────
    def add_subject(
        self,
        name: str,
        color: str = "#4CAF50",
        icon: str = "🏷️",
    ) -> Subject:
        """Create a new subject/tag and return the persisted instance.

        Raises:
            sqlalchemy.exc.IntegrityError: if a subject with the same name
                already exists.
        """
        with self._session() as session:
            subject = Subject(name=name, color=color, icon=icon)
            session.add(subject)
            session.flush()          # populate subject.id before commit
            return subject

    def update_subject(
        self,
        subject_id: int,
        *,
        name: str | None = None,
        color: str | None = None,
        icon: str | None = None,
    ) -> Subject:
        """Update an existing subject/tag's properties."""
        with self._session() as session:
            subject = session.get(Subject, subject_id)
            if subject is None:
                raise ValueError(f"Subject with id={subject_id} not found.")

            if name is not None:
                subject.name = name
            if color is not None:
                subject.color = color
            if icon is not None:
                subject.icon = icon

            session.flush()
            return subject

    def delete_subject(self, subject_id: int) -> bool:
        """Delete a subject/tag by its ID (cascades to related tasks)."""
        with self._session() as session:
            subject = session.get(Subject, subject_id)
            if subject is None:
                return False
            session.delete(subject)
            return True

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
        scheduled_date: date | None = None,
    ) -> Task:
        """Create a new task linked to an existing subject.

        If *expected_time* is provided, the method runs it through
        :class:`TimePredictor` to produce a corrected estimate and prints
        a human-readable notification to stdout.

        Returns:
            The persisted :class:`Task` instance.

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
                subject=subject,
                priority=priority,
                expected_time=expected_time,
                deadline=deadline,
                scheduled_date=scheduled_date,
                status=TaskStatus.PENDING,
            )
            session.add(task)
            session.flush()
            _ = task.subject

        # Run prediction after session closes to avoid nested transactions
        if expected_time is not None:
            predictor = TimePredictor()
            prediction = predictor.predict_time(subject_id, expected_time)

            expected_min = prediction.expected_time * 60
            predicted_min = prediction.predicted_time * 60

            def _fmt(val: float) -> str:
                r = round(val, 1)
                return str(int(r)) if r.is_integer() else f"{r:.1f}"

            msg = (
                f"Задача добавлена. Ожидаемое время: {_fmt(expected_min)} мин. "
                f"С учетом вашей истории, предсказанное время: {_fmt(predicted_min)} мин."
            )
            print(msg)
            task.prediction = prediction
            task.prediction_message = msg
        else:
            msg = "Задача добавлена."
            print(msg)
            task.prediction = None
            task.prediction_message = msg

        return task

    def get_all_tasks(self) -> list[Task]:
        """Return every task ordered by deadline (nulls last), then priority."""
        with self._session() as session:
            tasks = (
                session.query(Task)
                .order_by(
                    Task.deadline.is_(None),   # NULLs go last
                    Task.deadline,
                    Task.priority,
                )
                .all()
            )
            for t in tasks:
                _ = t.subject
            return tasks

    def get_tasks_by_subject(self, subject_id: int) -> list[Task]:
        """Return all tasks belonging to a given subject."""
        with self._session() as session:
            tasks = (
                session.query(Task)
                .filter(Task.subject_id == subject_id)
                .order_by(Task.deadline)
                .all()
            )
            for t in tasks:
                _ = t.subject
            return tasks

    def get_task_by_id(self, task_id: int) -> Task | None:
        """Return a single task or ``None``."""
        with self._session() as session:
            task = session.get(Task, task_id)
            if task is not None:
                _ = task.subject
            return task

    def get_today_tasks(self, target_date: date | None = None) -> list[Task]:
        """Return incomplete tasks scheduled for target_date (default today) or overdue."""
        target = target_date or date.today()
        with self._session() as session:
            tasks = (
                session.query(Task)
                .filter(
                    Task.status.notin_([TaskStatus.COMPLETED, TaskStatus.CANCELLED]),
                    (
                        (Task.scheduled_date == target)
                        | (Task.scheduled_date < target)
                        | (
                            Task.scheduled_date.is_(None)
                            & (Task.deadline <= datetime.combine(target, datetime.max.time()))
                        )
                    ),
                )
                .order_by(
                    Task.deadline.is_(None),
                    Task.deadline,
                    Task.priority,
                )
                .all()
            )
            for t in tasks:
                _ = t.subject
            return tasks

    def update_task(
        self,
        task_id: int,
        *,
        name: str | None = None,
        subject_id: int | None = None,
        description: str | None = None,
        priority: TaskPriority | None = None,
        expected_time: float | None = None,
        deadline: datetime | None | object = _UNSET,
        scheduled_date: date | None | object = _UNSET,
    ) -> Task:
        """Update fields of an existing task and refresh AI prediction.

        Returns the updated :class:`Task`.

        Raises:
            ValueError: if task or subject does not exist.
        """
        with self._session() as session:
            task = session.get(Task, task_id)
            if task is None:
                raise ValueError(f"Task with id={task_id} not found.")

            if subject_id is not None:
                subject = session.get(Subject, subject_id)
                if subject is None:
                    raise ValueError(f"Subject with id={subject_id} not found.")
                task.subject = subject

            if name is not None:
                task.name = name
            if description is not None:
                task.description = description
            if priority is not None:
                task.priority = priority
            if expected_time is not None:
                task.expected_time = expected_time
            if deadline is not _UNSET:
                task.deadline = deadline  # type: ignore[assignment]
            if scheduled_date is not _UNSET:
                task.scheduled_date = scheduled_date  # type: ignore[assignment]

            session.flush()
            _ = task.subject

        # Update prediction if expected_time is available
        if task.expected_time is not None:
            predictor = TimePredictor()
            prediction = predictor.predict_time(task.subject_id, task.expected_time)

            expected_min = prediction.expected_time * 60
            predicted_min = prediction.predicted_time * 60

            def _fmt(val: float) -> str:
                r = round(val, 1)
                return str(int(r)) if r.is_integer() else f"{r:.1f}"

            msg = (
                f"Задача обновлена. Ожидаемое время: {_fmt(expected_min)} мин. "
                f"С учетом вашей истории, предсказанное время: {_fmt(predicted_min)} мин."
            )
            print(msg)
            task.prediction = prediction
            task.prediction_message = msg
        else:
            msg = "Задача обновлена."
            print(msg)
            task.prediction = None
            task.prediction_message = msg

        return task

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
            task.completed_at = completed_at

            history = History(
                task_id=task.id,
                actual_time=actual_time,
                completed_at=completed_at,
            )
            session.add(history)
            session.flush()
            _ = task.subject
            return task

    def reopen_task(self, task_id: int) -> Task:
        """Reopen a completed task back to PENDING status."""
        with self._session() as session:
            task = session.get(Task, task_id)
            if task is None:
                raise ValueError(f"Task with id={task_id} not found.")

            task.status = TaskStatus.PENDING
            task.completed_at = None
            session.flush()
            _ = task.subject
            return task

    def complete_all_active_tasks(self, task_ids: list[int] | None = None) -> int:
        """Mark all (or specified) incomplete tasks as completed and record them into History.

        Uses each task's expected_time (or a default of 0.5 hours) as the
        actual_time recorded in history.

        Returns:
            The number of tasks completed.
        """
        with self._session() as session:
            query = session.query(Task).filter(
                Task.status.notin_([TaskStatus.COMPLETED, TaskStatus.CANCELLED])
            )
            if task_ids is not None:
                query = query.filter(Task.id.in_(task_ids))
            tasks = query.all()
            count = 0
            today = date.today()
            for t in tasks:
                t.status = TaskStatus.COMPLETED
                t.completed_at = today
                act_time = t.expected_time if t.expected_time is not None else 0.5
                hist = History(
                    task_id=t.id,
                    actual_time=act_time,
                    completed_at=today,
                )
                session.add(hist)
                count += 1
            session.flush()
            return count

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
