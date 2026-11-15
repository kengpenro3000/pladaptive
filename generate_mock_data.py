#!/usr/bin/env python3
"""Generate 50 fake completed tasks spread across several subjects.

Usage::

    python generate_mock_data.py          # from project root
    python generate_mock_data.py --clean  # wipe planner.db first
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Ensure project root is on sys.path so `core` / `database` are importable.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.task_manager import TaskManager
from database.models import TaskPriority

# ────────────────────────────────────────────
# Configuration
# ────────────────────────────────────────────
SUBJECTS: list[str] = [
    "Математика",
    "Программирование",
    "Физика",
    "Английский язык",
]

TASK_TEMPLATES: dict[str, list[str]] = {
    "Математика": [
        "Решить интегралы",
        "Домашка по линейной алгебре",
        "Контрольная по мат. анализу",
        "Задачи на ряды Фурье",
        "Подготовка к коллоквиуму",
    ],
    "Программирование": [
        "Лабораторная по Python",
        "Код-ревью проекта",
        "Рефакторинг модуля",
        "Написать юнит-тесты",
        "Реализовать REST API",
    ],
    "Физика": [
        "Лабораторная по механике",
        "Расчёт электрических цепей",
        "Задачи по термодинамике",
        "Подготовка к экзамену",
        "Конспект по оптике",
    ],
    "Английский язык": [
        "Эссе на тему Technology",
        "Грамматические упражнения",
        "Чтение и перевод статьи",
        "Подготовка презентации",
        "Аудирование — Unit 7",
    ],
}

PRIORITIES: list[TaskPriority] = list(TaskPriority)

TOTAL_TASKS: int = 50

# Expected time range (minutes)
EXPECTED_MIN: int = 30
EXPECTED_MAX: int = 120

# How far in the past deadlines / completion dates can be (days)
HISTORY_DEPTH_DAYS: int = 90

# Deviation of actual_time from expected_time
DEVIATION_MIN: float = 0.10  # −10 %
DEVIATION_MAX: float = 0.30  # +30 %

random.seed(42)  # reproducible, but feel free to remove


# ────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────

def _random_deadline() -> datetime:
    """Return a random datetime within the last HISTORY_DEPTH_DAYS days."""
    days_ago = random.randint(1, HISTORY_DEPTH_DAYS)
    hour = random.randint(8, 22)
    return datetime.now().replace(hour=hour, minute=0, second=0, microsecond=0) - timedelta(days=days_ago)


def _actual_time(expected_minutes: float) -> float:
    """Deviate expected time by ±10-30 %, return result in **hours**."""
    factor = random.uniform(1 - DEVIATION_MIN, 1 + DEVIATION_MAX)
    return round((expected_minutes * factor) / 60, 2)


# ────────────────────────────────────────────
# Main
# ────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate mock planner data.")
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Delete planner.db before generating data.",
    )
    args = parser.parse_args()

    if args.clean:
        db_path = Path(__file__).resolve().parent / "planner.db"
        if db_path.exists():
            db_path.unlink()
            print(f"🗑  Удалён старый {db_path.name}")

    mgr = TaskManager()
    mgr.init_db()
    print("✅ База данных инициализирована\n")

    # --- subjects ---
    subject_map: dict[str, int] = {}
    for name in SUBJECTS:
        subj = mgr.add_subject(name)
        subject_map[name] = subj.id
        print(f"  📚 Предмет: {name}  (id={subj.id})")

    print()

    # --- tasks ---
    created = 0
    for i in range(1, TOTAL_TASKS + 1):
        subj_name = random.choice(SUBJECTS)
        templates = TASK_TEMPLATES[subj_name]
        task_name = f"{random.choice(templates)} #{i}"

        expected_minutes = random.randint(EXPECTED_MIN, EXPECTED_MAX)
        deadline = _random_deadline()
        priority = random.choice(PRIORITIES)

        task = mgr.add_task(
            name=task_name,
            subject_id=subject_map[subj_name],
            description=f"Автоматически сгенерированная задача #{i}",
            priority=priority,
            expected_time=round(expected_minutes / 60, 2),   # store in hours
            deadline=deadline,
        )

        # Complete the task with a realistic actual_time
        actual_hours = _actual_time(expected_minutes)
        # Completion date: between deadline and a few days before it
        days_before = random.randint(0, 5)
        completed_at = (deadline - timedelta(days=days_before)).date()

        mgr.complete_task(task.id, actual_time=actual_hours, completed_at=completed_at)
        created += 1

        print(
            f"  ✏️  [{i:>2}/{TOTAL_TASKS}] {task_name:<45} "
            f"| {subj_name:<20} "
            f"| ожид. {expected_minutes:>3} мин → факт. {actual_hours * 60:>6.1f} мин "
            f"| {priority.value:<8} "
            f"| завершена {completed_at}"
        )

    print(f"\n🎉 Готово!  Создано предметов: {len(SUBJECTS)}, задач: {created}, записей в History: {created}")


if __name__ == "__main__":
    main()
