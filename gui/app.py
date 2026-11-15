"""Main GUI application screen with Navigation Sidebar and Tab Views.

Features:
- Sidebar with Tabs:
  0. 'Сегодняшние задачи' (Tasks scheduled for today, overdue tasks, and tasks completed today).
  1. 'Все задачи' (All active prioritized tasks and tasks completed today).
  2. 'Теги и предметы' (Tag and subject management).
- Task planned date ('scheduled_date'): Tasks can be scheduled for any day,
  with visual indicators for today, tomorrow, overdue, or unscheduled.
- Tasks completed today stay visible as crossed out (strikethrough) until the end of the day,
  automatically disappearing once the day has passed. Option to restore/reopen task if needed.
- Tasks views: Dynamic colored tag badges, scheduled date badges, whole-card click to edit,
  'Завершить задачу' action, 'Завершить все задачи' header button, no reload button.
- Tags view: Tag cards with UTF icon, color swatch, task count, edit and delete actions.
"""

from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

# Ensure root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import flet as ft

from core.scheduler import ScoredTask, TaskScheduler
from core.task_manager import TaskManager
from database.models import Subject, Task, TaskPriority, TaskStatus
from ai.predictor import TimePredictor
from gui.forms import (
    _close_dialog,
    _show_dialog,
    _show_snack,
    open_task_complete_dialog,
    open_task_create_dialog,
    open_task_edit_dialog,
    open_tag_dialog,
)

# Compatibility helper for FilledButton
FilledBtn = getattr(ft, "FilledButton", getattr(ft, "ElevatedButton", ft.TextButton))


class ScheduleScreen:
    """Renders and manages the main application view with sidebar and tabbed content."""

    MONTHS_RU = [
        "", "января", "февраля", "марта", "апреля", "мая", "июня",
        "июля", "августа", "сентября", "октября", "ноября", "декабря"
    ]
    WEEKDAYS_RU = [
        "понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"
    ]

    def __init__(self, page: ft.Page) -> None:
        self.page = page
        self.scheduler = TaskScheduler()
        self.task_manager = TaskManager()

        # Active tab: 0 = Today's tasks, 1 = All tasks, 2 = Tags
        self.current_tab = 0
        self.sidebar_collapsed = False

        # Containers
        self.today_tasks_column = ft.Column(spacing=12, scroll=ft.ScrollMode.AUTO)
        self.all_tasks_column = ft.Column(spacing=12, scroll=ft.ScrollMode.AUTO)
        self.tags_column = ft.Column(spacing=12, scroll=ft.ScrollMode.AUTO)
        self.content_area = ft.Container(expand=True)
        self.sidebar_area = ft.Container(width=260, animate_size=200)

    # ──────────────────────────────────────────
    # Priority & Formatting Helpers
    # ──────────────────────────────────────────
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

    def _format_scheduled_date(
        self, sched_date: date | None
    ) -> tuple[str, str, int]:
        """Return (formatted_text, color, icon) for scheduled date."""
        if sched_date is None:
            return "Не запланировано", ft.Colors.GREY_500, ft.Icons.EVENT_BUSY_ROUNDED

        today = date.today()
        diff = (sched_date - today).days
        date_str = sched_date.strftime("%d.%m.%Y")

        if diff < 0:
            return f"{date_str} (просрочено на {-diff} дн.)", ft.Colors.RED_400, ft.Icons.EVENT_REPEAT_ROUNDED
        elif diff == 0:
            return f"{date_str} (Сегодня)", ft.Colors.CYAN_300, ft.Icons.TODAY_ROUNDED
        elif diff == 1:
            return f"{date_str} (Завтра)", ft.Colors.BLUE_300, ft.Icons.EVENT_NOTE_ROUNDED
        else:
            return date_str, ft.Colors.GREEN_400, ft.Icons.EVENT_ROUNDED

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
            return f"{date_str} (дедлайн просрочен)", ft.Colors.RED_400
        elif days_left == 0:
            return f"{date_str} (сегодня!)", ft.Colors.DEEP_ORANGE_400
        elif days_left == 1:
            return f"{date_str} (завтра)", ft.Colors.AMBER_400
        else:
            return f"{date_str} (осталось {days_left} дн.)", ft.Colors.GREEN_400

    def _format_today_header(self) -> str:
        """Format today's date in Russian for the header."""
        today = date.today()
        m_name = self.MONTHS_RU[today.month] if 1 <= today.month <= 12 else ""
        w_name = self.WEEKDAYS_RU[today.weekday()] if 0 <= today.weekday() < 7 else ""
        return f"{today.day} {m_name} {today.year}, {w_name}"

    # ──────────────────────────────────────────
    # Tab Switching & Navigation
    # ──────────────────────────────────────────
    def switch_tab(self, tab_index: int) -> None:
        """Switch active tab: 0 (Today), 1 (All Tasks), 2 (Tags)."""
        if self.current_tab != tab_index:
            self.current_tab = tab_index
            self._render_sidebar()
            self._render_content()
            self._update_fab()
            self.page.update()

    def _update_fab(self) -> None:
        """Update floating action button based on active tab."""
        if self.current_tab in (0, 1):
            self.page.floating_action_button = ft.FloatingActionButton(
                icon=ft.Icons.ADD,
                tooltip="Добавить новую задачу",
                bgcolor=ft.Colors.PRIMARY,
                on_click=lambda _: self.open_add_task_dialog(),
            )
        else:
            self.page.floating_action_button = ft.FloatingActionButton(
                icon=ft.Icons.ADD,
                tooltip="Создать новый тег",
                bgcolor=ft.Colors.PRIMARY,
                on_click=lambda _: self.open_add_tag_dialog(),
            )

    # ──────────────────────────────────────────
    # Sidebar Builder
    # ──────────────────────────────────────────
    def toggle_sidebar(self) -> None:
        """Toggle sidebar between collapsed (icons only) and expanded."""
        self.sidebar_collapsed = not self.sidebar_collapsed
        self.sidebar_area.width = 68 if self.sidebar_collapsed else 260
        self._render_sidebar()
        self.page.update()

    def _render_sidebar(self) -> None:
        """Render the sidebar with navigation items and statistics."""
        today_tasks = self.scheduler.get_prioritized_tasks(only_today=True)
        today_active = len([s for s in today_tasks if s.task.status != TaskStatus.COMPLETED])
        today_completed = len([s for s in today_tasks if s.task.status == TaskStatus.COMPLETED])

        all_tasks_scored = self.scheduler.get_prioritized_tasks(only_today=False)
        all_active = len([s for s in all_tasks_scored if s.task.status != TaskStatus.COMPLETED])

        all_tags = self.task_manager.get_all_subjects()
        all_tasks = self.task_manager.get_all_tasks()
        completed_total_count = len([t for t in all_tasks if t.status == TaskStatus.COMPLETED])

        # Active indicator styling
        def _nav_button(
            title: str,
            icon_name: str,
            tab_idx: int,
            badge_text: str | None = None,
        ) -> ft.Container:
            is_active = self.current_tab == tab_idx
            bg_color = (
                ft.Colors.with_opacity(0.18, ft.Colors.PRIMARY)
                if is_active
                else ft.Colors.TRANSPARENT
            )
            border_style = (
                ft.Border.all(width=1, color=ft.Colors.PRIMARY)
                if is_active
                else None
            )
            text_color = ft.Colors.PRIMARY if is_active else ft.Colors.ON_SURFACE
            icon_color = ft.Colors.PRIMARY if is_active else ft.Colors.GREY_400

            if self.sidebar_collapsed:
                return ft.Container(
                    content=ft.Icon(icon_name, color=icon_color, size=22),
                    bgcolor=bg_color,
                    border=border_style,
                    border_radius=10,
                    padding=10,
                    alignment=ft.Alignment(0, 0),
                    tooltip=f"{title} ({badge_text})" if badge_text else title,
                    ink=True,
                    on_click=lambda _, idx=tab_idx: self.switch_tab(idx),
                )

            row_controls: list[ft.Control] = [
                ft.Icon(icon_name, color=icon_color, size=20),
                ft.Text(
                    title,
                    color=text_color,
                    weight=ft.FontWeight.BOLD if is_active else ft.FontWeight.W_500,
                    size=14,
                    expand=True,
                ),
            ]
            if badge_text is not None:
                row_controls.append(
                    ft.Container(
                        content=ft.Text(
                            badge_text,
                            size=11,
                            weight=ft.FontWeight.BOLD,
                            color=ft.Colors.PRIMARY if is_active else ft.Colors.GREY_300,
                        ),
                        bgcolor=(
                            ft.Colors.with_opacity(0.25, ft.Colors.PRIMARY)
                            if is_active
                            else ft.Colors.SURFACE_CONTAINER_HIGHEST
                        ),
                        padding=ft.Padding(left=8, top=2, right=8, bottom=2),
                        border_radius=10,
                    )
                )

            return ft.Container(
                content=ft.Row(controls=row_controls, spacing=10),
                bgcolor=bg_color,
                border=border_style,
                border_radius=10,
                padding=ft.Padding(left=14, top=10, right=14, bottom=10),
                ink=True,
                on_click=lambda _, idx=tab_idx: self.switch_tab(idx),
            )

        # Header with collapse/expand toggle button (no logo/app name)
        if self.sidebar_collapsed:
            top_header = ft.Container(
                padding=ft.Padding(left=0, top=2, right=0, bottom=6),
                alignment=ft.Alignment(0, 0),
                content=ft.IconButton(
                    icon=ft.Icons.MENU_ROUNDED,
                    tooltip="Развернуть панель",
                    icon_color=ft.Colors.GREY_400,
                    on_click=lambda _: self.toggle_sidebar(),
                ),
            )
        else:
            top_header = ft.Container(
                padding=ft.Padding(left=4, top=2, right=4, bottom=6),
                content=ft.Row(
                    alignment=ft.MainAxisAlignment.END,
                    controls=[
                        ft.IconButton(
                            icon=ft.Icons.MENU_OPEN_ROUNDED,
                            tooltip="Свернуть панель",
                            icon_color=ft.Colors.GREY_400,
                            on_click=lambda _: self.toggle_sidebar(),
                        ),
                    ],
                ),
            )

        # Navigation items
        nav_items = ft.Column(
            spacing=8,
            controls=[
                _nav_button("Сегодняшние задачи", ft.Icons.TODAY_ROUNDED, 0, str(today_active)),
                _nav_button("Все задачи", ft.Icons.CHECKLIST_ROUNDED, 1, str(all_active)),
                _nav_button("Теги и предметы", ft.Icons.LOCAL_OFFER_ROUNDED, 2, str(len(all_tags))),
            ],
        )

        # Bottom stats panel
        stats_panel = ft.Container(
            padding=12,
            border_radius=10,
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            content=ft.Column(
                spacing=6,
                controls=[
                    ft.Text("Статистика", size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.GREY_300),
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Text("На сегодня (активно):", size=11, color=ft.Colors.GREY_400),
                            ft.Text(str(today_active), size=11, weight=ft.FontWeight.BOLD, color=ft.Colors.CYAN_300),
                        ],
                    ),
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Text("Завершено сегодня:", size=11, color=ft.Colors.GREY_400),
                            ft.Text(str(today_completed), size=11, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_400),
                        ],
                    ),
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Text("Всего активных:", size=11, color=ft.Colors.GREY_400),
                            ft.Text(str(all_active), size=11, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_300),
                        ],
                    ),
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Text("Завершено за всё время:", size=11, color=ft.Colors.GREY_400),
                            ft.Text(str(completed_total_count), size=11, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_300),
                        ],
                    ),
                ],
            ),
        )

        bottom_compact = ft.Container(
            alignment=ft.Alignment(0, 0),
            padding=ft.Padding(left=0, top=4, right=0, bottom=4),
            content=ft.IconButton(
                icon=ft.Icons.QUERY_STATS_ROUNDED,
                icon_color=ft.Colors.GREY_400,
                tooltip=f"На сегодня: {today_active} | Всего: {all_active} | Завершено: {completed_total_count}",
                on_click=lambda _: self.toggle_sidebar(),
            ),
        )

        self.sidebar_area.content = ft.Container(
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
            border_radius=14,
            padding=ft.Padding(left=8, top=10, right=8, bottom=10) if self.sidebar_collapsed else 14,
            expand=True,
            content=ft.Column(
                expand=True,
                controls=[
                    top_header,
                    ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                    ft.Container(height=6),
                    nav_items,
                    ft.Container(expand=True),  # Push stats to bottom
                    bottom_compact if self.sidebar_collapsed else stats_panel,
                ],
            ),
        )

    # ──────────────────────────────────────────
    # Task Cards Builder
    # ──────────────────────────────────────────
    def build_task_card(self, scored: ScoredTask, rank: int) -> ft.Card:
        """Render a single prioritized task card.

        If task is completed today, displays it as crossed out with a checkmark badge
        and an option to restore/reopen.
        Clicking anywhere on the card opens the edit dialog.
        """
        task = scored.task
        is_completed = (task.status == TaskStatus.COMPLETED)
        subject = task.subject
        tag_name = subject.name if subject else "Без предмета"
        tag_icon = subject.icon if subject else "🏷️"
        tag_color = subject.color if subject else "#607D8B"

        priority_label, priority_color, priority_icon = self._get_priority_details(
            task.priority
        )
        time_str = self._format_time(task.expected_time)
        sched_str, sched_color, sched_icon = self._format_scheduled_date(
            task.scheduled_date
        )
        deadline_str, deadline_color = self._format_deadline(
            task.deadline, scored.days_left
        )

        # AI Prediction info (if available)
        ai_pred_str = None
        if task.expected_time is not None:
            try:
                pred = TimePredictor().predict_time(task.subject_id, task.expected_time)
                if not pred.cold_start:
                    pred_min = round(pred.predicted_time * 60, 1)
                    if pred_min.is_integer():
                        pred_min = int(pred_min)
                    ai_pred_str = f"~{pred_min} мин"
            except Exception:
                ai_pred_str = None

        # Dynamic Tag container badge
        tag_badge = ft.Container(
            content=ft.Row(
                spacing=5,
                tight=True,
                controls=[
                    ft.Text(tag_icon, size=14),
                    ft.Text(
                        tag_name,
                        size=12,
                        weight=ft.FontWeight.W_600,
                        color=tag_color,
                    ),
                ],
            ),
            bgcolor=ft.Colors.with_opacity(0.14, tag_color),
            border=ft.Border.all(width=1, color=ft.Colors.with_opacity(0.4, tag_color)),
            padding=ft.Padding(left=8, top=3, right=8, bottom=3),
            border_radius=8,
        )

        # Scheduled date badge
        sched_badge = ft.Container(
            content=ft.Row(
                spacing=5,
                tight=True,
                controls=[
                    ft.Icon(sched_icon, size=14, color=sched_color),
                    ft.Text(
                        f"План: {sched_str}",
                        size=12,
                        weight=ft.FontWeight.W_600,
                        color=sched_color,
                    ),
                ],
            ),
            bgcolor=ft.Colors.with_opacity(0.12, sched_color),
            border=ft.Border.all(width=1, color=ft.Colors.with_opacity(0.35, sched_color)),
            padding=ft.Padding(left=8, top=3, right=8, bottom=3),
            border_radius=8,
        )

        # Time chip
        time_chip = ft.Container(
            content=ft.Row(
                spacing=5,
                tight=True,
                controls=[
                    ft.Icon(
                        ft.Icons.ACCESS_TIME_FILLED_ROUNDED,
                        size=14,
                        color=ft.Colors.CYAN_300,
                    ),
                    ft.Text(
                        f"Время: {time_str}",
                        size=12,
                        weight=ft.FontWeight.BOLD,
                        color=ft.Colors.CYAN_200,
                    ),
                ],
            ),
            bgcolor=ft.Colors.with_opacity(0.15, ft.Colors.CYAN_400),
            padding=ft.Padding(left=8, top=3, right=8, bottom=3),
            border_radius=8,
        )

        subtitle_rows: list[ft.Control] = [
            ft.Row(
                spacing=8,
                wrap=True,
                controls=[tag_badge, sched_badge, time_chip],
            )
        ]

        if task.description:
            subtitle_rows.append(
                ft.Text(
                    task.description,
                    size=13,
                    color=ft.Colors.GREY_500 if is_completed else ft.Colors.GREY_400,
                    max_lines=2,
                    overflow=ft.TextOverflow.ELLIPSIS,
                )
            )

        footer_controls: list[ft.Control] = [
            # Priority Badge
            ft.Row(
                [
                    ft.Icon(
                        ft.Icons.FLAG_ROUNDED,
                        size=16,
                        color=ft.Colors.GREY_500 if is_completed else priority_color,
                    ),
                    ft.Text(
                        f"Приоритет: {priority_label}",
                        size=12,
                        color=ft.Colors.GREY_500 if is_completed else priority_color,
                        weight=ft.FontWeight.W_600,
                    ),
                ],
                spacing=4,
            ),
            # Deadline
            ft.Row(
                [
                    ft.Icon(
                        ft.Icons.CALENDAR_MONTH_ROUNDED,
                        size=16,
                        color=ft.Colors.GREY_500 if is_completed else deadline_color,
                    ),
                    ft.Text(
                        f"Дедлайн: {deadline_str}",
                        size=12,
                        color=ft.Colors.GREY_500 if is_completed else deadline_color,
                    ),
                ],
                spacing=4,
            ),
        ]

        # Add AI predicted time tag if available
        if ai_pred_str and not is_completed:
            footer_controls.append(
                ft.Row(
                    [
                        ft.Icon(
                            ft.Icons.AUTO_AWESOME_ROUNDED,
                            size=16,
                            color=ft.Colors.AMBER_400,
                        ),
                        ft.Text(
                            f"Прогноз ИИ: {ai_pred_str}",
                            size=12,
                            color=ft.Colors.AMBER_300,
                            weight=ft.FontWeight.W_500,
                        ),
                    ],
                    spacing=4,
                )
            )

        # Title formatting: crossed out if completed
        if is_completed:
            title_control = ft.Text(
                f"✓ {task.name}",
                size=16,
                weight=ft.FontWeight.W_500,
                style=ft.TextStyle(
                    decoration=ft.TextDecoration.LINE_THROUGH,
                    color=ft.Colors.GREY_400,
                ),
            )
            leading_control = ft.Container(
                content=ft.Icon(
                    ft.Icons.CHECK_CIRCLE_ROUNDED,
                    color=ft.Colors.GREEN_400,
                    size=28,
                ),
                padding=4,
            )
            trailing_control = ft.Container(
                content=ft.Row(
                    spacing=4,
                    tight=True,
                    controls=[
                        ft.Icon(ft.Icons.CHECK_ROUNDED, color=ft.Colors.GREEN_300, size=14),
                        ft.Text("Завершено", size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_300),
                    ],
                ),
                bgcolor=ft.Colors.with_opacity(0.18, ft.Colors.GREEN_400),
                padding=ft.Padding(left=8, top=4, right=8, bottom=4),
                border_radius=8,
            )
            action_buttons_row = ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                controls=[
                    ft.Row(
                        spacing=6,
                        controls=[
                            ft.Icon(ft.Icons.TASK_ALT_ROUNDED, size=16, color=ft.Colors.GREEN_400),
                            ft.Text(
                                "Выполнено сегодня",
                                size=12,
                                color=ft.Colors.GREEN_400,
                                weight=ft.FontWeight.W_600,
                            ),
                        ],
                    ),
                    ft.TextButton(
                        "Вернуть в работу",
                        icon=ft.Icons.RESTORE_ROUNDED,
                        style=ft.ButtonStyle(
                            color=ft.Colors.GREY_300,
                        ) if hasattr(ft, "ButtonStyle") else None,
                        on_click=lambda _, tid=task.id, tname=task.name: self.reopen_task(tid, tname),
                    ),
                ],
            )
        else:
            title_control = ft.Text(
                f"#{rank} {task.name}",
                size=16,
                weight=ft.FontWeight.W_600,
                color=ft.Colors.ON_SURFACE,
            )
            leading_control = ft.Container(
                content=ft.Icon(
                    priority_icon,
                    color=priority_color,
                    size=28,
                ),
                padding=4,
            )
            trailing_control = ft.Container(
                content=ft.Text(
                    f"Вес: {scored.score:.1f}",
                    size=12,
                    weight=ft.FontWeight.BOLD,
                    color=ft.Colors.WHITE,
                ),
                bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                padding=ft.Padding(left=8, top=4, right=8, bottom=4),
                border_radius=8,
            )
            action_buttons_row = ft.Row(
                alignment=ft.MainAxisAlignment.END,
                controls=[
                    ft.OutlinedButton(
                        "Завершить задачу",
                        icon=ft.Icons.CHECK_CIRCLE_OUTLINE_ROUNDED,
                        style=ft.ButtonStyle(
                            color=ft.Colors.GREEN_400,
                        ) if hasattr(ft, "ButtonStyle") else None,
                        on_click=lambda _, tid=task.id, tname=task.name, et=task.expected_time: self.open_complete_dialog(tid, tname, et),
                    ),
                ],
            )

        return ft.Card(
            elevation=1 if is_completed else 2,
            content=ft.Container(
                padding=14,
                border_radius=12,
                ink=True,
                opacity=0.82 if is_completed else 1.0,
                tooltip="Нажмите на карточку, чтобы изменить задачу",
                on_click=lambda _, t=task: self.open_edit_dialog(t),
                content=ft.Column(
                    spacing=12,
                    controls=[
                        # Main ListTile with title, leading icon, and score/status
                        ft.ListTile(
                            leading=leading_control,
                            title=title_control,
                            subtitle=ft.Column(spacing=6, controls=subtitle_rows),
                            trailing=trailing_control,
                        ),
                        ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                        # Metadata footer row: Priority, Deadline, AI Prediction
                        ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            wrap=True,
                            spacing=12,
                            run_spacing=8,
                            controls=footer_controls,
                        ),
                        ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                        # Action button row
                        action_buttons_row,
                    ],
                ),
            ),
        )

    # ──────────────────────────────────────────
    # Tab 0: Today's Tasks
    # ──────────────────────────────────────────
    def _build_completed_divider(self, completed_count: int) -> ft.Control:
        """Build a straight horizontal dividing line separating uncompleted and completed tasks."""
        return ft.Container(
            padding=ft.Padding(left=0, top=14, right=0, bottom=6),
            content=ft.Column(
                spacing=8,
                controls=[
                    ft.Divider(height=2, thickness=2, color=ft.Colors.OUTLINE),
                    ft.Row(
                        spacing=6,
                        controls=[
                            ft.Icon(ft.Icons.CHECK_CIRCLE_ROUNDED, size=16, color=ft.Colors.GREEN_400),
                            ft.Text(
                                f"Завершенные сегодня задачи ({completed_count})",
                                size=12,
                                weight=ft.FontWeight.BOLD,
                                color=ft.Colors.GREY_400,
                            ),
                        ],
                    ),
                ],
            ),
        )

    def load_today_tasks(self) -> None:
        """Fetch prioritized tasks scheduled for today (including completed today) and populate column."""
        self.today_tasks_column.controls.clear()
        scored_tasks = self.scheduler.get_prioritized_tasks(only_today=True)

        active_tasks = [s for s in scored_tasks if s.task.status != TaskStatus.COMPLETED]
        completed_tasks = [s for s in scored_tasks if s.task.status == TaskStatus.COMPLETED]

        if not active_tasks and not completed_tasks:
            self.today_tasks_column.controls.append(
                ft.Card(
                    elevation=1,
                    content=ft.Container(
                        padding=40,
                        alignment=ft.Alignment(0, 0),
                        content=ft.Column(
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            spacing=12,
                            controls=[
                                ft.Icon(
                                    ft.Icons.EVENT_AVAILABLE_ROUNDED,
                                    size=48,
                                    color=ft.Colors.GREEN_400,
                                ),
                                ft.Text(
                                    "На сегодня нет запланированных задач!",
                                    size=18,
                                    weight=ft.FontWeight.BOLD,
                                ),
                                ft.Text(
                                    "Вы можете добавить новую задачу с датой выполнения на сегодня или выбрать задачу из вкладки «Все задачи».",
                                    size=14,
                                    color=ft.Colors.GREY_400,
                                    text_align=ft.TextAlign.CENTER,
                                ),
                                ft.Container(height=8),
                                FilledBtn(
                                    "Добавить задачу на сегодня",
                                    icon=ft.Icons.ADD_TASK_ROUNDED,
                                    on_click=lambda _: self.open_add_task_dialog(),
                                ),
                            ],
                        ),
                    ),
                )
            )
            return

        # 1. Add active uncompleted tasks
        if active_tasks:
            for rank, scored in enumerate(active_tasks, 1):
                self.today_tasks_column.controls.append(self.build_task_card(scored, rank))
        elif completed_tasks:
            self.today_tasks_column.controls.append(
                ft.Card(
                    elevation=1,
                    content=ft.Container(
                        padding=20,
                        alignment=ft.Alignment(0, 0),
                        content=ft.Row(
                            alignment=ft.MainAxisAlignment.CENTER,
                            spacing=10,
                            controls=[
                                ft.Icon(ft.Icons.CHECK_CIRCLE_ROUNDED, color=ft.Colors.GREEN_400, size=24),
                                ft.Text("Все активные задачи на сегодня выполнены!", size=15, weight=ft.FontWeight.BOLD),
                            ],
                        ),
                    ),
                )
            )

        # 2. Add straight divider line and completed tasks
        if completed_tasks:
            self.today_tasks_column.controls.append(self._build_completed_divider(len(completed_tasks)))
            for scored in completed_tasks:
                self.today_tasks_column.controls.append(self.build_task_card(scored, 0))

    def _render_today_tasks_view(self) -> ft.Control:
        """Build the 'Сегодняшние задачи' view."""
        self.load_today_tasks()

        today_tasks = self.scheduler.get_prioritized_tasks(only_today=True)
        today_active = len([s for s in today_tasks if s.task.status != TaskStatus.COMPLETED])
        today_done = len([s for s in today_tasks if s.task.status == TaskStatus.COMPLETED])

        header_actions = ft.Row(
            spacing=10,
            controls=[
                ft.OutlinedButton(
                    "Завершить задачи дня",
                    icon=ft.Icons.DONE_ALL_ROUNDED,
                    style=ft.ButtonStyle(
                        color=ft.Colors.GREEN_400,
                    ) if hasattr(ft, "ButtonStyle") else None,
                    on_click=lambda _: self.confirm_complete_all(only_today=True),
                ),
                FilledBtn(
                    "Новая задача",
                    icon=ft.Icons.ADD_ROUNDED,
                    on_click=lambda _: self.open_add_task_dialog(),
                ),
            ],
        )

        header = ft.Row(
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            wrap=True,
            controls=[
                ft.Column(
                    spacing=4,
                    controls=[
                        ft.Row(
                            [
                                ft.Icon(
                                    ft.Icons.TODAY_ROUNDED,
                                    color=ft.Colors.PRIMARY,
                                    size=28,
                                ),
                                ft.Text(
                                    "Сегодняшние задачи",
                                    size=22,
                                    weight=ft.FontWeight.BOLD,
                                ),
                            ],
                            spacing=10,
                        ),
                        ft.Text(
                            f"{self._format_today_header()} • К выполнению: {today_active} • Завершено сегодня: {today_done}",
                            size=13,
                            color=ft.Colors.GREY_400,
                        ),
                    ],
                ),
                header_actions,
            ],
        )

        return ft.Column(
            spacing=16,
            expand=True,
            controls=[
                header,
                ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                self.today_tasks_column,
            ],
        )

    # ──────────────────────────────────────────
    # Tab 1: All Tasks
    # ──────────────────────────────────────────
    def load_all_tasks(self) -> None:
        """Fetch all tasks (including completed today) and populate column."""
        self.all_tasks_column.controls.clear()
        scored_tasks = self.scheduler.get_prioritized_tasks(only_today=False)

        active_tasks = [s for s in scored_tasks if s.task.status != TaskStatus.COMPLETED]
        completed_tasks = [s for s in scored_tasks if s.task.status == TaskStatus.COMPLETED]

        if not active_tasks and not completed_tasks:
            self.all_tasks_column.controls.append(
                ft.Card(
                    elevation=1,
                    content=ft.Container(
                        padding=40,
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
                                    "Нет активных или просроченных задач. Отличная работа!",
                                    size=14,
                                    color=ft.Colors.GREY_400,
                                    text_align=ft.TextAlign.CENTER,
                                ),
                            ],
                        ),
                    ),
                )
            )
            return

        # 1. Add active uncompleted tasks
        if active_tasks:
            for rank, scored in enumerate(active_tasks, 1):
                self.all_tasks_column.controls.append(self.build_task_card(scored, rank))
        elif completed_tasks:
            self.all_tasks_column.controls.append(
                ft.Card(
                    elevation=1,
                    content=ft.Container(
                        padding=20,
                        alignment=ft.Alignment(0, 0),
                        content=ft.Row(
                            alignment=ft.MainAxisAlignment.CENTER,
                            spacing=10,
                            controls=[
                                ft.Icon(ft.Icons.CHECK_CIRCLE_ROUNDED, color=ft.Colors.GREEN_400, size=24),
                                ft.Text("Все активные задачи выполнены!", size=15, weight=ft.FontWeight.BOLD),
                            ],
                        ),
                    ),
                )
            )

        # 2. Add straight divider line and completed tasks
        if completed_tasks:
            self.all_tasks_column.controls.append(self._build_completed_divider(len(completed_tasks)))
            for scored in completed_tasks:
                self.all_tasks_column.controls.append(self.build_task_card(scored, 0))

    def _render_all_tasks_view(self) -> ft.Control:
        """Build the 'Все задачи' view."""
        self.load_all_tasks()

        all_tasks_scored = self.scheduler.get_prioritized_tasks(only_today=False)
        all_active = len([s for s in all_tasks_scored if s.task.status != TaskStatus.COMPLETED])
        all_done_today = len([s for s in all_tasks_scored if s.task.status == TaskStatus.COMPLETED])

        header_actions = ft.Row(
            spacing=10,
            controls=[
                ft.OutlinedButton(
                    "Завершить все задачи",
                    icon=ft.Icons.DONE_ALL_ROUNDED,
                    style=ft.ButtonStyle(
                        color=ft.Colors.GREEN_400,
                    ) if hasattr(ft, "ButtonStyle") else None,
                    on_click=lambda _: self.confirm_complete_all(only_today=False),
                ),
                FilledBtn(
                    "Новая задача",
                    icon=ft.Icons.ADD_ROUNDED,
                    on_click=lambda _: self.open_add_task_dialog(),
                ),
            ],
        )

        header = ft.Row(
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            wrap=True,
            controls=[
                ft.Column(
                    spacing=4,
                    controls=[
                        ft.Row(
                            [
                                ft.Icon(
                                    ft.Icons.CHECKLIST_ROUNDED,
                                    color=ft.Colors.PRIMARY,
                                    size=28,
                                ),
                                ft.Text(
                                    "Все задачи",
                                    size=22,
                                    weight=ft.FontWeight.BOLD,
                                ),
                            ],
                            spacing=10,
                        ),
                        ft.Text(
                            f"Активных задач: {all_active} • Завершено сегодня: {all_done_today}",
                            size=13,
                            color=ft.Colors.GREY_400,
                        ),
                    ],
                ),
                header_actions,
            ],
        )

        return ft.Column(
            spacing=16,
            expand=True,
            controls=[
                header,
                ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                self.all_tasks_column,
            ],
        )

    # ──────────────────────────────────────────
    # Tab 2: Tags / Subjects
    # ──────────────────────────────────────────
    def build_tag_card(self, tag: Subject, task_count: int) -> ft.Card:
        """Render a single tag card with icon, color indicator, count, and actions."""
        return ft.Card(
            elevation=2,
            content=ft.Container(
                padding=14,
                border_radius=12,
                content=ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    controls=[
                        ft.Row(
                            spacing=14,
                            controls=[
                                # Big icon box with custom color
                                ft.Container(
                                    content=ft.Text(tag.icon or "🏷️", size=26),
                                    bgcolor=ft.Colors.with_opacity(0.18, tag.color or "#4CAF50"),
                                    border=ft.Border.all(
                                        width=1.5,
                                        color=tag.color or "#4CAF50",
                                    ),
                                    border_radius=10,
                                    padding=10,
                                    alignment=ft.Alignment(0, 0),
                                ),
                                ft.Column(
                                    spacing=4,
                                    alignment=ft.MainAxisAlignment.CENTER,
                                    controls=[
                                        ft.Text(
                                            tag.name,
                                            size=16,
                                            weight=ft.FontWeight.BOLD,
                                            color=ft.Colors.ON_SURFACE,
                                        ),
                                        ft.Row(
                                            spacing=8,
                                            controls=[
                                                # Color badge
                                                ft.Container(
                                                    content=ft.Row(
                                                        spacing=5,
                                                        tight=True,
                                                        controls=[
                                                            ft.Container(
                                                                width=10,
                                                                height=10,
                                                                border_radius=5,
                                                                bgcolor=tag.color or "#4CAF50",
                                                            ),
                                                            ft.Text(
                                                                tag.color or "#4CAF50",
                                                                size=11,
                                                                color=ft.Colors.GREY_300,
                                                            ),
                                                        ],
                                                    ),
                                                    bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                                                    padding=ft.Padding(left=6, top=2, right=6, bottom=2),
                                                    border_radius=6,
                                                ),
                                                # Task count chip
                                                ft.Container(
                                                    content=ft.Text(
                                                        f"Задач: {task_count}",
                                                        size=11,
                                                        color=ft.Colors.GREY_300,
                                                    ),
                                                    bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                                                    padding=ft.Padding(left=6, top=2, right=6, bottom=2),
                                                    border_radius=6,
                                                ),
                                            ],
                                        ),
                                    ],
                                ),
                            ],
                        ),
                        # Action buttons
                        ft.Row(
                            spacing=6,
                            controls=[
                                ft.IconButton(
                                    icon=ft.Icons.EDIT_ROUNDED,
                                    tooltip="Редактировать тег",
                                    icon_color=ft.Colors.PRIMARY,
                                    on_click=lambda _, t=tag: self.open_edit_tag_dialog(t),
                                ),
                                ft.IconButton(
                                    icon=ft.Icons.DELETE_OUTLINE_ROUNDED,
                                    tooltip="Удалить тег",
                                    icon_color=ft.Colors.RED_400,
                                    on_click=lambda _, t=tag, cnt=task_count: self.confirm_delete_tag(t, cnt),
                                ),
                            ],
                        ),
                    ],
                ),
            ),
        )

    def load_tags(self) -> None:
        """Fetch all tags/subjects and populate the tags column."""
        self.tags_column.controls.clear()
        tags = self.task_manager.get_all_subjects()
        all_tasks = self.task_manager.get_all_tasks()

        # Count tasks per tag
        task_counts: dict[int, int] = {}
        for t in all_tasks:
            task_counts[t.subject_id] = task_counts.get(t.subject_id, 0) + 1

        if not tags:
            self.tags_column.controls.append(
                ft.Card(
                    elevation=1,
                    content=ft.Container(
                        padding=40,
                        alignment=ft.Alignment(0, 0),
                        content=ft.Column(
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            spacing=12,
                            controls=[
                                ft.Icon(
                                    ft.Icons.LOCAL_OFFER_OUTLINED,
                                    size=48,
                                    color=ft.Colors.AMBER_400,
                                ),
                                ft.Text(
                                    "Теги отсутствуют",
                                    size=18,
                                    weight=ft.FontWeight.BOLD,
                                ),
                                ft.Text(
                                    "Создайте свой первый тег, чтобы распределять задачи по предметам и темам.",
                                    size=14,
                                    color=ft.Colors.GREY_400,
                                    text_align=ft.TextAlign.CENTER,
                                ),
                                ft.Container(height=8),
                                FilledBtn(
                                    "Создать тег",
                                    icon=ft.Icons.ADD_ROUNDED,
                                    on_click=lambda _: self.open_add_tag_dialog(),
                                ),
                            ],
                        ),
                    ),
                )
            )
        else:
            for tag in tags:
                cnt = task_counts.get(tag.id, 0)
                self.tags_column.controls.append(self.build_tag_card(tag, cnt))

    def _render_tags_view(self) -> ft.Control:
        """Build the full 'Теги и предметы' screen view."""
        self.load_tags()

        header = ft.Row(
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            wrap=True,
            controls=[
                ft.Column(
                    spacing=4,
                    controls=[
                        ft.Row(
                            [
                                ft.Icon(
                                    ft.Icons.LOCAL_OFFER_ROUNDED,
                                    color=ft.Colors.PRIMARY,
                                    size=28,
                                ),
                                ft.Text(
                                    "Теги и предметы",
                                    size=22,
                                    weight=ft.FontWeight.BOLD,
                                ),
                            ],
                            spacing=10,
                        ),
                        ft.Text(
                            "Управление тегами: добавляйте, удаляйте, задавайте цвета и UTF-иконки",
                            size=13,
                            color=ft.Colors.GREY_400,
                        ),
                    ],
                ),
                FilledBtn(
                    "Создать тег",
                    icon=ft.Icons.ADD_ROUNDED,
                    on_click=lambda _: self.open_add_tag_dialog(),
                ),
            ],
        )

        return ft.Column(
            spacing=16,
            expand=True,
            controls=[
                header,
                ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                self.tags_column,
            ],
        )

    # ──────────────────────────────────────────
    # Rendering & View Updates
    # ──────────────────────────────────────────
    def _render_content(self) -> None:
        """Render the main content view based on current tab."""
        if self.current_tab == 0:
            self.content_area.content = self._render_today_tasks_view()
        elif self.current_tab == 1:
            self.content_area.content = self._render_all_tasks_view()
        else:
            self.content_area.content = self._render_tags_view()

    def render(self) -> None:
        """Assemble the complete layout (sidebar + content) on the page."""
        self.page.title = "Умное расписание"
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.padding = 16

        self._render_sidebar()
        self._render_content()
        self._update_fab()

        self.page.controls.clear()
        self.page.add(
            ft.Row(
                expand=True,
                spacing=16,
                controls=[
                    self.sidebar_area,
                    self.content_area,
                ],
            )
        )
        self.page.update()

    def refresh(self) -> None:
        """Reload data for the active view, update sidebar and page."""
        self._render_sidebar()
        self._render_content()
        self.page.update()

    # ──────────────────────────────────────────
    # Dialog Handlers
    # ──────────────────────────────────────────
    def open_add_task_dialog(self) -> None:
        """Open the task creation dialog."""
        open_task_create_dialog(self.page, on_success=self.refresh)

    def open_edit_dialog(self, task: Task) -> None:
        """Open the task editing dialog."""
        open_task_edit_dialog(self.page, task=task, on_success=self.refresh)

    def open_complete_dialog(
        self, task_id: int, task_name: str, expected_time: float | None = None
    ) -> None:
        """Open the complete task dialog."""
        open_task_complete_dialog(
            self.page,
            task_id=task_id,
            task_name=task_name,
            expected_time_hours=expected_time,
            on_success=self.refresh,
        )

    def reopen_task(self, task_id: int, task_name: str) -> None:
        """Reopen a completed task back to active status."""
        self.task_manager.reopen_task(task_id)
        _show_snack(
            self.page,
            f"Задача «{task_name}» возвращена в список активных!",
            bgcolor=ft.Colors.BLUE_800,
        )
        self.refresh()

    def open_add_tag_dialog(self) -> None:
        """Open dialog to create a new tag/subject."""
        open_tag_dialog(self.page, on_success=self.refresh)

    def open_edit_tag_dialog(self, tag: Subject) -> None:
        """Open dialog to edit an existing tag/subject."""
        open_tag_dialog(self.page, tag=tag, on_success=self.refresh)

    def confirm_delete_tag(self, tag: Subject, task_count: int) -> None:
        """Show confirmation dialog before deleting a tag."""
        warning_msg = (
            f"Внимание: к этому тегу привязано задач: {task_count} шт.\n"
            "При удалении тега эти задачи также будут удалены!"
            if task_count > 0
            else "К этому тегу нет привязанных задач."
        )

        def _execute_delete(_):
            _close_dialog(self.page, delete_dialog)
            success = self.task_manager.delete_subject(tag.id)
            if success:
                _show_snack(
                    self.page,
                    f"Тег «{tag.name}» успешно удален.",
                    bgcolor=ft.Colors.GREEN_800,
                )
            else:
                _show_snack(
                    self.page,
                    f"Не удалось удалить тег «{tag.name}».",
                    bgcolor=ft.Colors.RED_800,
                )
            self.refresh()

        delete_dialog = ft.AlertDialog(
            title=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.WARNING_ROUNDED, color=ft.Colors.RED_400, size=26),
                    ft.Text(f"Удалить тег «{tag.name}»?", weight=ft.FontWeight.BOLD, size=18),
                ],
                spacing=10,
            ),
            content=ft.Text(
                f"Вы уверены, что хотите удалить тег {tag.icon} «{tag.name}»?\n\n{warning_msg}",
                size=14,
            ),
            actions=[
                ft.TextButton(
                    "Отмена",
                    on_click=lambda _: _close_dialog(self.page, delete_dialog),
                ),
                FilledBtn(
                    "Удалить",
                    icon=ft.Icons.DELETE_ROUNDED,
                    style=ft.ButtonStyle(
                        bgcolor=ft.Colors.RED_700,
                        color=ft.Colors.WHITE,
                    ) if hasattr(ft, "ButtonStyle") else None,
                    on_click=_execute_delete,
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        _show_dialog(self.page, delete_dialog)

    def confirm_complete_all(self, only_today: bool = False) -> None:
        """Show confirmation dialog to complete active tasks."""
        tasks_list = self.scheduler.get_prioritized_tasks(only_today=only_today)
        active_tasks = [t for t in tasks_list if t.task.status != TaskStatus.COMPLETED]
        count = len(active_tasks)
        label = "сегодняшние задачи" if only_today else "все активные задачи"
        if count == 0:
            _show_snack(self.page, f"Все задачи ({label}) уже завершены!", bgcolor=ft.Colors.AMBER_800)
            return

        task_ids = [t.task.id for t in active_tasks]

        def _execute_complete_all(_):
            _close_dialog(self.page, confirm_dialog)
            completed_count = self.task_manager.complete_all_active_tasks(task_ids=task_ids)
            _show_snack(
                self.page,
                f"Задачи ({completed_count} шт.) успешно завершены и отмечены на сегодня!",
                bgcolor=ft.Colors.GREEN_800,
            )
            self.refresh()

        confirm_dialog = ft.AlertDialog(
            title=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.DONE_ALL_ROUNDED, color=ft.Colors.GREEN_400, size=26),
                    ft.Text("Завершить задачи?", weight=ft.FontWeight.BOLD, size=18),
                ],
                spacing=10,
            ),
            content=ft.Text(
                f"Вы действительно хотите завершить {label} ({count} шт.)?\n"
                "Они будут отмечены выполненными на сегодня и останутся зачеркнутыми до конца дня.",
                size=14,
            ),
            actions=[
                ft.TextButton(
                    "Отмена",
                    on_click=lambda _: _close_dialog(self.page, confirm_dialog),
                ),
                FilledBtn(
                    "Да, завершить",
                    icon=ft.Icons.CHECK_ROUNDED,
                    on_click=_execute_complete_all,
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        _show_dialog(self.page, confirm_dialog)


def main_view(page: ft.Page) -> None:
    """Convenience functional entry point for rendering the schedule screen."""
    app = ScheduleScreen(page)
    app.render()
