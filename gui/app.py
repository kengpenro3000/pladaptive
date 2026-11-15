"""Main GUI application screen: 'Расписание на сегодня' (Schedule for today).

Displays tasks prioritized by urgency using TaskScheduler().
Renders tasks as styled cards using ft.Card and ft.ListTile.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

# Ensure root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import flet as ft

from core.scheduler import ScoredTask, TaskScheduler
from database.models import TaskPriority


class ScheduleScreen:
    """Renders and manages the 'Расписание на сегодня' screen."""

    def __init__(self, page: ft.Page) -> None:
        self.page = page
        self.scheduler = TaskScheduler()
        self.tasks_column = ft.Column(spacing=12, scroll=ft.ScrollMode.AUTO)

    def _get_priority_details(
        self, priority: TaskPriority
    ) -> tuple[str, str, int]:
        """Return (label, color, icon) for a priority level."""
        mapping = {
            TaskPriority.CRITICAL: (
                "Критический",
                ft.Colors.RED_400,
                ft.Icons.WARNING_ROUNDED,
            ),
            TaskPriority.HIGH: (
                "Высокий",
                ft.Colors.ORANGE_400,
                ft.Icons.PRIORITY_HIGH_ROUNDED,
            ),
            TaskPriority.MEDIUM: (
                "Средний",
                ft.Colors.AMBER_400,
                ft.Icons.SCHEDULE_ROUNDED,
            ),
            TaskPriority.LOW: (
                "Низкий",
                ft.Colors.BLUE_300,
                ft.Icons.ARROW_DOWNWARD_ROUNDED,
            ),
        }
        return mapping.get(
            priority,
            ("Обычный", ft.Colors.GREY_400, ft.Icons.LABEL_OUTLINE_ROUNDED),
        )

    def _format_time(self, expected_time: float | None) -> str:
        """Format expected time in minutes or hours."""
        if expected_time is None:
            return "Не указано"
        minutes = expected_time * 60
        r = round(minutes, 1)
        if r.is_integer():
            return f"{int(r)} мин"
        return f"{r:.1f} мин"

    def _format_deadline(
        self, deadline: datetime | None, days_left: int | None
    ) -> tuple[str, str]:
        """Return (formatted_text, color) for task deadline."""
        if deadline is None:
            return "Без дедлайна", ft.Colors.GREY_500

        date_str = deadline.strftime("%d.%m.%Y %H:%M")
        if days_left is None:
            return date_str, ft.Colors.ON_SURFACE_VARIANT

        if days_left < 0:
            return f"{date_str} (просрочено на {-days_left} дн.)", ft.Colors.RED_400
        elif days_left == 0:
            return f"{date_str} (сегодня!)", ft.Colors.DEEP_ORANGE_400
        elif days_left == 1:
            return f"{date_str} (завтра)", ft.Colors.AMBER_400
        else:
            return f"{date_str} (осталось {days_left} дн.)", ft.Colors.GREEN_400

    def build_task_card(self, scored: ScoredTask, rank: int) -> ft.Card:
        """Render a single prioritized task card using ft.Card and ft.ListTile."""
        task = scored.task
        subject_name = task.subject.name if task.subject else "Без предмета"
        priority_label, priority_color, priority_icon = self._get_priority_details(
            task.priority
        )
        time_str = self._format_time(task.expected_time)
        deadline_str, deadline_color = self._format_deadline(
            task.deadline, scored.days_left
        )

        return ft.Card(
            elevation=3,
            content=ft.Container(
                padding=14,
                border_radius=12,
                content=ft.Column(
                    spacing=10,
                    controls=[
                        # Main ListTile with title, priority icon, rank, and score
                        ft.ListTile(
                            leading=ft.Container(
                                content=ft.Icon(
                                    priority_icon,
                                    color=priority_color,
                                    size=28,
                                ),
                                padding=4,
                            ),
                            title=ft.Text(
                                f"#{rank} {task.name}",
                                size=16,
                                weight=ft.FontWeight.W_600,
                            ),
                            subtitle=ft.Text(
                                task.description or "Без дополнительного описания",
                                size=13,
                                color=ft.Colors.GREY_400,
                                max_lines=2,
                                overflow=ft.TextOverflow.ELLIPSIS,
                            ),
                            trailing=ft.Container(
                                content=ft.Text(
                                    f"Вес: {scored.score:.1f}",
                                    size=12,
                                    weight=ft.FontWeight.BOLD,
                                    color=ft.Colors.WHITE,
                                ),
                                bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                                padding=ft.Padding(left=8, top=4, right=8, bottom=4),
                                border_radius=8,
                            ),
                        ),
                        ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                        # Metadata row: Subject, Priority, Expected Time, Deadline
                        ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            wrap=True,
                            spacing=12,
                            run_spacing=8,
                            controls=[
                                # Subject
                                ft.Row(
                                    [
                                        ft.Icon(
                                            ft.Icons.MENU_BOOK_ROUNDED,
                                            size=16,
                                            color=ft.Colors.LIGHT_BLUE_400,
                                        ),
                                        ft.Text(
                                            f"Предмет: {subject_name}",
                                            size=13,
                                            weight=ft.FontWeight.W_500,
                                        ),
                                    ],
                                    spacing=4,
                                ),
                                # Priority Badge
                                ft.Row(
                                    [
                                        ft.Icon(
                                            ft.Icons.FLAG_ROUNDED,
                                            size=16,
                                            color=priority_color,
                                        ),
                                        ft.Text(
                                            f"Приоритет: {priority_label}",
                                            size=13,
                                            color=priority_color,
                                            weight=ft.FontWeight.W_600,
                                        ),
                                    ],
                                    spacing=4,
                                ),
                                # Expected Time
                                ft.Row(
                                    [
                                        ft.Icon(
                                            ft.Icons.ACCESS_TIME_ROUNDED,
                                            size=16,
                                            color=ft.Colors.CYAN_300,
                                        ),
                                        ft.Text(
                                            f"Время: {time_str}",
                                            size=13,
                                        ),
                                    ],
                                    spacing=4,
                                ),
                                # Deadline
                                ft.Row(
                                    [
                                        ft.Icon(
                                            ft.Icons.CALENDAR_TODAY_ROUNDED,
                                            size=16,
                                            color=deadline_color,
                                        ),
                                        ft.Text(
                                            f"Дедлайн: {deadline_str}",
                                            size=13,
                                            color=deadline_color,
                                        ),
                                    ],
                                    spacing=4,
                                ),
                            ],
                        ),
                    ],
                ),
            ),
        )

    def load_tasks(self) -> None:
        """Fetch prioritized tasks and populate the tasks column."""
        self.tasks_column.controls.clear()
        scored_tasks = self.scheduler.get_prioritized_tasks()

        if not scored_tasks:
            # Empty state
            self.tasks_column.controls.append(
                ft.Card(
                    elevation=1,
                    content=ft.Container(
                        padding=30,
                        alignment=ft.Alignment(0, 0),
                        content=ft.Column(
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            spacing=12,
                            controls=[
                                ft.Icon(
                                    ft.Icons.TASK_ALT_ROUNDED,
                                    size=48,
                                    color=ft.Colors.GREEN_400,
                                ),
                                ft.Text(
                                    "Все задачи выполнены!",
                                    size=18,
                                    weight=ft.FontWeight.BOLD,
                                ),
                                ft.Text(
                                    "На сегодня нет активных или просроченных задач. Отличная работа!",
                                    size=14,
                                    color=ft.Colors.GREY_400,
                                    text_align=ft.TextAlign.CENTER,
                                ),
                            ],
                        ),
                    ),
                )
            )
        else:
            for rank, scored in enumerate(scored_tasks, 1):
                self.tasks_column.controls.append(self.build_task_card(scored, rank))

    def render(self) -> None:
        """Assemble the complete screen on the page."""
        self.page.title = "ПланАдаптив — Расписание на сегодня"
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.padding = 20

        # Header bar
        header = ft.Row(
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            controls=[
                ft.Column(
                    spacing=4,
                    controls=[
                        ft.Row(
                            [
                                ft.Icon(
                                    ft.Icons.TODAY_ROUNDED,
                                    color=ft.Colors.PRIMARY,
                                    size=30,
                                ),
                                ft.Text(
                                    "Расписание на сегодня",
                                    size=24,
                                    weight=ft.FontWeight.BOLD,
                                ),
                            ],
                            spacing=10,
                        ),
                        ft.Text(
                            "Задачи автоматически отсортированы по адаптивной формуле срочности",
                            size=13,
                            color=ft.Colors.GREY_400,
                        ),
                    ],
                ),
                ft.IconButton(
                    icon=ft.Icons.REFRESH_ROUNDED,
                    tooltip="Обновить расписание",
                    icon_color=ft.Colors.PRIMARY,
                    on_click=lambda _: self.refresh(),
                ),
            ],
        )

        self.load_tasks()

        self.page.controls.clear()
        self.page.add(
            ft.Column(
                spacing=16,
                expand=True,
                controls=[
                    header,
                    ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                    self.tasks_column,
                ],
            )
        )
        self.page.update()

    def refresh(self) -> None:
        """Reload tasks and update page."""
        self.load_tasks()
        self.page.update()


def main_view(page: ft.Page) -> None:
    """Convenience functional entry point for rendering the schedule screen."""
    app = ScheduleScreen(page)
    app.render()
