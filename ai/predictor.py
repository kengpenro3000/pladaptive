"""AI predictor layer — cold-start time prediction.

Uses a simple ratio-based heuristic (no ML).  Once enough history is
available per subject, it calculates::

    coefficient = Σ actual_time / Σ expected_time

and multiplies new *expected_time* by that coefficient to produce a more
realistic estimate.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

# Ensure project root is importable when running as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db_config import SessionLocal
from database.models import History, Task, TaskStatus


# ──────────────────────────────────────────────
# Result container
# ──────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class Prediction:
    """Holds the prediction result together with debug info."""

    expected_time: float        # original estimate (hours)
    predicted_time: float       # adjusted estimate (hours)
    coefficient: float          # multiplier that was applied
    completed_tasks: int        # how many tasks the coefficient is based on
    cold_start: bool            # True when data was insufficient


# ──────────────────────────────────────────────
# Predictor
# ──────────────────────────────────────────────
class TimePredictor:
    """Calculate a time-correction coefficient per subject from History data.

    Caches calculated coefficients in memory to prevent executing redundant
    aggregate SQL queries during list renders.

    Parameters
    ----------
    min_history : int
        Minimum number of completed tasks required before the coefficient
        is used.  Below this threshold the predictor returns *expected_time*
        unchanged (cold-start fallback, coefficient = 1.0).
    """

    _cache: dict[int, tuple[float, int, bool]] = {}

    def __init__(self, min_history: int = 3) -> None:
        self.min_history = min_history

    @classmethod
    def clear_cache(cls) -> None:
        """Invalidate cached coefficients when task completions or actual times change."""
        cls._cache.clear()

    def get_subject_coefficient(self, subject_id: int) -> tuple[float, int, bool]:
        """Fetch or calculate (coefficient, completed_tasks, cold_start) for a subject."""
        if subject_id in self._cache:
            return self._cache[subject_id]

        session: Session = SessionLocal()
        try:
            row = (
                session.query(
                    func.count(History.id).label("cnt"),
                    func.sum(History.actual_time).label("sum_actual"),
                    func.sum(Task.expected_time).label("sum_expected"),
                )
                .join(Task, Task.id == History.task_id)
                .filter(
                    Task.subject_id == subject_id,
                    Task.status == TaskStatus.COMPLETED,
                    Task.expected_time.isnot(None),
                )
                .one()
            )

            completed: int = row.cnt or 0
            sum_actual: float = row.sum_actual or 0.0
            sum_expected: float = row.sum_expected or 0.0

            if completed < self.min_history or sum_expected == 0:
                res = (1.0, completed, True)
            else:
                coefficient = round(sum_actual / sum_expected, 4)
                res = (coefficient, completed, False)

            self._cache[subject_id] = res
            return res
        finally:
            session.close()

    # ── core logic ────────────────────────────
    def predict_time(
        self,
        subject_id: int,
        expected_time: float,
    ) -> Prediction:
        """Return a corrected time estimate for a new task using cached coefficients.

        Args:
            subject_id: FK to the subject the task belongs to.
            expected_time: The user's raw estimate (hours).

        Returns:
            A :class:`Prediction` with the adjusted time and metadata.
        """
        coefficient, completed, cold_start = self.get_subject_coefficient(subject_id)
        predicted = round(expected_time * coefficient, 4) if not cold_start else expected_time

        return Prediction(
            expected_time=expected_time,
            predicted_time=predicted,
            coefficient=coefficient,
            completed_tasks=completed,
            cold_start=cold_start,
        )


# ──────────────────────────────────────────────
# Quick demo / manual test
# ──────────────────────────────────────────────
if __name__ == "__main__":
    from database.db_config import init_db
    from database.models import Subject

    init_db()
    predictor = TimePredictor(min_history=3)

    session = SessionLocal()
    subjects = session.query(Subject).order_by(Subject.name).all()
    session.close()

    if not subjects:
        print("⚠  БД пуста. Сначала запустите:  python generate_mock_data.py --clean")
        sys.exit(1)

    print("=" * 72)
    print(f"{'Предмет':<25} {'Коэф.':<8} {'Ожид.':<10} {'Предикт.':<10} {'История':<8} {'Cold?'}")
    print("=" * 72)

    test_expected = 1.5  # часа — гипотетическое время новой задачи

    for subj in subjects:
        p = predictor.predict_time(subj.id, expected_time=test_expected)
        print(
            f"{subj.name:<25} "
            f"{p.coefficient:<8.4f} "
            f"{p.expected_time:<10.2f} "
            f"{p.predicted_time:<10.2f} "
            f"{p.completed_tasks:<8} "
            f"{'да' if p.cold_start else 'нет'}"
        )

    print("=" * 72)
    print(
        f"\nТест: если пользователь оценивает задачу в {test_expected} ч, "
        f"предиктор корректирует время по истории каждого предмета."
    )
