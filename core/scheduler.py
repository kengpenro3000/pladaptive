"""Task scheduling layer — urgency-based prioritisation.

Ranks **incomplete** tasks by combining a priority score with a deadline
proximity score so the most urgent / important tasks float to the top.

Scoring formula
---------------
::

    score = priority_weight + deadline_weight

* **priority_weight** — static score per ``TaskPriority`` level:
  LOW = 1, MEDIUM = 2, HIGH = 4, CRITICAL = 8.

* **deadline_weight** — dynamic, grows as the deadline approaches::

      days_left = (deadline − now).days

      if days_left ≤ 0 (overdue):   10          ← maximum urgency
      else:                        10 / days_left

  Tasks without a deadline receive ``deadline_weight = 0`` (lowest urgency).

Higher ``score`` → higher urgency → appears earlier in the list.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session, joinedload

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db_config import SessionLocal
from database.models import Task, TaskPriority, TaskStatus


# ──────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────
PRIORITY_WEIGHTS: dict[TaskPriority, float] = {
    TaskPriority.LOW: 1.0,
    TaskPriority.MEDIUM: 2.0,
    TaskPriority.HIGH: 4.0,
    TaskPriority.CRITICAL: 8.0,
}

DEADLINE_MAX_SCORE: float = 10.0   # score when overdue or due today


# ──────────────────────────────────────────────
# Result container
# ──────────────────────────────────────────────
@dataclass
class ScoredTask:
    """A task annotated with its computed urgency score."""

    task: Task
    score: float
    priority_weight: float
    deadline_weight: float
    days_left: int | None          # None when deadline is not set


# ──────────────────────────────────────────────
# Scheduler
# ──────────────────────────────────────────────
class TaskScheduler:
    """Fetch and rank incomplete tasks by urgency."""

    # ── scoring helpers ───────────────────────

    @staticmethod
    def _priority_score(priority: TaskPriority) -> float:
        return PRIORITY_WEIGHTS.get(priority, PRIORITY_WEIGHTS[TaskPriority.MEDIUM])

    @staticmethod
    def _deadline_score(deadline: datetime | None, now: datetime) -> tuple[float, int | None]:
        """Return ``(score, days_left)``."""
        if deadline is None:
            return 0.0, None

        days_left = (deadline - now).days

        if days_left <= 0:
            return DEADLINE_MAX_SCORE, days_left

        return round(DEADLINE_MAX_SCORE / days_left, 4), days_left

    def _score_task(self, task: Task, now: datetime) -> ScoredTask:
        p_weight = self._priority_score(task.priority)
        d_weight, days_left = self._deadline_score(task.deadline, now)

        return ScoredTask(
            task=task,
            score=round(p_weight + d_weight, 4),
            priority_weight=p_weight,
            deadline_weight=d_weight,
            days_left=days_left,
        )

    # ── public API ────────────────────────────

    def get_prioritized_tasks(self) -> list[ScoredTask]:
        """Return all incomplete tasks sorted by descending urgency score.

        Uses a fresh session internally (context-managed).
        """
        session: Session = SessionLocal()
        try:
            tasks: list[Task] = (
                session.query(Task)
                .options(joinedload(Task.subject))
                .filter(Task.status.notin_([
                    TaskStatus.COMPLETED,
                    TaskStatus.CANCELLED,
                ]))
                .all()
            )

            now = datetime.now()
            scored = [self._score_task(t, now) for t in tasks]
            scored.sort(key=lambda s: s.score, reverse=True)
            return scored
        finally:
            session.close()


# ──────────────────────────────────────────────
# Console demo / test
# ──────────────────────────────────────────────
if __name__ == "__main__":
    from datetime import timedelta

    from core.task_manager import TaskManager
    from database.db_config import init_db

    init_db()
    mgr = TaskManager()

    # ── Seed a few incomplete tasks for testing ──
    # Reuse existing subjects; if DB is empty, create them.
    subjects = mgr.get_all_subjects()
    if not subjects:
        print("⚠  БД пуста. Сначала запустите:  python generate_mock_data.py --clean")
        sys.exit(1)

    subj_map = {s.name: s.id for s in subjects}
    now = datetime.now()

    test_tasks: list[dict] = [
        dict(name="[TEST] Просроченная контрольная",   subject="Математика",       priority=TaskPriority.HIGH,     deadline=now - timedelta(days=2)),
        dict(name="[TEST] Сдать завтра — лаба",        subject="Программирование", priority=TaskPriority.CRITICAL, deadline=now + timedelta(days=1)),
        dict(name="[TEST] Эссе через 3 дня",           subject="Английский язык",  priority=TaskPriority.MEDIUM,   deadline=now + timedelta(days=3)),
        dict(name="[TEST] Курсовая через 2 недели",    subject="Физика",           priority=TaskPriority.LOW,      deadline=now + timedelta(days=14)),
        dict(name="[TEST] Без дедлайна — почитать",    subject="Английский язык",  priority=TaskPriority.LOW,      deadline=None),
        dict(name="[TEST] Сдать через неделю",         subject="Математика",       priority=TaskPriority.MEDIUM,   deadline=now + timedelta(days=7)),
        dict(name="[TEST] Срочный баг-фикс, сегодня", subject="Программирование", priority=TaskPriority.CRITICAL, deadline=now),
    ]

    created_ids: list[int] = []
    for t in test_tasks:
        task = mgr.add_task(
            name=t["name"],
            subject_id=subj_map[t["subject"]],
            priority=t["priority"],
            expected_time=1.5,
            deadline=t["deadline"],
        )
        created_ids.append(task.id)

    # ── Run the scheduler ──
    scheduler = TaskScheduler()
    ranked = scheduler.get_prioritized_tasks()

    print("=" * 90)
    print(f"{'#':<4} {'Score':<8} {'Prior.':<10} {'Deadline':<12} {'Days':<6} {'Task name'}")
    print("=" * 90)

    for i, s in enumerate(ranked, 1):
        dl_str = s.task.deadline.strftime("%Y-%m-%d") if s.task.deadline else "—"
        days_str = str(s.days_left) if s.days_left is not None else "—"
        print(
            f"{i:<4} "
            f"{s.score:<8.2f} "
            f"{s.task.priority.value:<10} "
            f"{dl_str:<12} "
            f"{days_str:<6} "
            f"{s.task.name}"
        )

    print("=" * 90)
    print(f"\nВсего незавершённых задач: {len(ranked)}")

    # ── Cleanup test tasks ──
    session = SessionLocal()
    try:
        session.query(Task).filter(Task.id.in_(created_ids)).delete()
        session.commit()
        print(f"🧹 Удалены {len(created_ids)} тестовых задач.")
    finally:
        session.close()
