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
    _parse_date,
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

    MIN_SIDEBAR_WIDTH = 130
    MAX_SIDEBAR_WIDTH = 550
    COLLAPSED_SIDEBAR_WIDTH = 68
    DEFAULT_EXPANDED_WIDTH = 260
    COLLAPSE_THRESHOLD = 130

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
        self.saved_expanded_width = self.DEFAULT_EXPANDED_WIDTH
        self._drag_width = float(self.DEFAULT_EXPANDED_WIDTH)

        # Containers
        self.today_tasks_column = ft.Column(spacing=8, scroll=ft.ScrollMode.AUTO, expand=True)
        self.all_tasks_column = ft.Column(spacing=8, scroll=ft.ScrollMode.AUTO, expand=True)
        self.tags_column = ft.Column(spacing=8, scroll=ft.ScrollMode.AUTO, expand=True)
        self.content_area = ft.Container(expand=True)
        self.sidebar_area = ft.Container(width=self.DEFAULT_EXPANDED_WIDTH)

        # Quick-add row state
        self._last_selected_subject_id: str | None = None
        self._last_selected_priority: str = TaskPriority.MEDIUM.value
        self._last_expected_minutes: str = "60"
        self._last_selected_date: date | None = None
        self._quick_add_name_field: ft.TextField | None = None

        # Resizer handle between sidebar and content
        self.resizer_handle = self._build_resizer_handle()

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

    def _focus_control(self, control: ft.Control | None) -> None:
        """Safely focus a control supporting both synchronous and async Flet versions."""
        if not control or not hasattr(control, "focus"):
            return
        try:
            import inspect
            if hasattr(self.page, "run_task") and inspect.iscoroutinefunction(control.focus):
                self.page.run_task(control.focus)
            else:
                res = control.focus()
                if inspect.iscoroutine(res):
                    res.close()
        except Exception:
            pass

    def _focus_or_open_add_task(self) -> None:
        """Focus the inline quick-add input if present, or open creation dialog."""
        if self._quick_add_name_field and hasattr(self._quick_add_name_field, "focus"):
            self._focus_control(self._quick_add_name_field)
            return
        self.open_add_task_dialog()

    def _update_fab(self) -> None:
        """Update floating action button (disabled per user request to keep only top row)."""
        self.page.floating_action_button = None

    # ──────────────────────────────────────────
    # Sidebar Resizer & Builder (Zed-style)
    # ──────────────────────────────────────────
    def _build_resizer_handle(self) -> ft.Control:
        """Create the resizer divider bar with drag detection, hover glow, and vertically-centered toggle button."""
        def _make_line_segment() -> ft.Container:
            return ft.Container(
                width=2,
                bgcolor=ft.Colors.with_opacity(0.3, ft.Colors.OUTLINE_VARIANT),
                border_radius=1,
                expand=True,
            )

        self.resizer_top_line = _make_line_segment()
        self.resizer_bottom_line = _make_line_segment()

        self.collapse_btn_icon = ft.Icon(
            icon=ft.Icons.CHEVRON_LEFT_ROUNDED if not self.sidebar_collapsed else ft.Icons.CHEVRON_RIGHT_ROUNDED,
            size=14,
            color=ft.Colors.GREY_300,
        )

        def _on_btn_hover(e: ft.HoverEvent) -> None:
            is_hovered = str(getattr(e, "data", "")).lower() == "true" or getattr(e, "data", None) is True
            self.collapse_button_box.bgcolor = (
                ft.Colors.SURFACE_CONTAINER_HIGHEST if is_hovered else ft.Colors.SURFACE_CONTAINER_HIGH
            )
            self.collapse_button_box.border = (
                ft.Border.all(1, ft.Colors.PRIMARY)
                if is_hovered
                else ft.Border.all(1, ft.Colors.with_opacity(0.4, ft.Colors.OUTLINE_VARIANT))
            )
            self.collapse_btn_icon.color = ft.Colors.PRIMARY if is_hovered else ft.Colors.GREY_300
            self.page.update()

        self.collapse_button_box = ft.Container(
            content=self.collapse_btn_icon,
            width=18,
            height=34,
            border_radius=9,
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
            border=ft.Border.all(1, ft.Colors.with_opacity(0.4, ft.Colors.OUTLINE_VARIANT)),
            alignment=ft.Alignment(0, 0),
            tooltip="Свернуть панель" if not self.sidebar_collapsed else "Развернуть панель",
            on_hover=_on_btn_hover,
        )

        self.collapse_button = ft.GestureDetector(
            mouse_cursor=ft.MouseCursor.CLICK,
            on_tap=lambda _: self.toggle_sidebar(),
            on_pan_start=self._on_resizer_pan_start,
            on_pan_update=self._on_resizer_pan_update,
            on_pan_end=self._on_resizer_pan_end,
            content=self.collapse_button_box,
        )

        def _on_line_hover(e: ft.HoverEvent) -> None:
            is_hovered = str(getattr(e, "data", "")).lower() == "true" or getattr(e, "data", None) is True
            color = ft.Colors.PRIMARY if is_hovered else ft.Colors.with_opacity(0.3, ft.Colors.OUTLINE_VARIANT)
            w = 3 if is_hovered else 2
            self.resizer_top_line.bgcolor = color
            self.resizer_top_line.width = w
            self.resizer_bottom_line.bgcolor = color
            self.resizer_bottom_line.width = w
            self.page.update()

        top_handle = ft.GestureDetector(
            mouse_cursor=ft.MouseCursor.RESIZE_LEFT_RIGHT,
            on_pan_start=self._on_resizer_pan_start,
            on_pan_update=self._on_resizer_pan_update,
            on_pan_end=self._on_resizer_pan_end,
            on_double_tap=self._on_resizer_double_tap,
            content=ft.Container(
                width=18,
                alignment=ft.Alignment(0, 0),
                expand=True,
                on_hover=_on_line_hover,
                content=self.resizer_top_line,
            ),
            expand=True,
        )

        bottom_handle = ft.GestureDetector(
            mouse_cursor=ft.MouseCursor.RESIZE_LEFT_RIGHT,
            on_pan_start=self._on_resizer_pan_start,
            on_pan_update=self._on_resizer_pan_update,
            on_pan_end=self._on_resizer_pan_end,
            on_double_tap=self._on_resizer_double_tap,
            content=ft.Container(
                width=18,
                alignment=ft.Alignment(0, 0),
                expand=True,
                on_hover=_on_line_hover,
                content=self.resizer_bottom_line,
            ),
            expand=True,
        )

        return ft.Column(
            width=18,
            spacing=0,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                top_handle,
                self.collapse_button,
                bottom_handle,
            ],
        )

    def _update_resizer_button(self) -> None:
        """Update resizer button icon and tooltip according to sidebar state."""
        if hasattr(self, "collapse_btn_icon") and self.collapse_btn_icon:
            self.collapse_btn_icon.icon = (
                ft.Icons.CHEVRON_RIGHT_ROUNDED if self.sidebar_collapsed else ft.Icons.CHEVRON_LEFT_ROUNDED
            )
        if hasattr(self, "collapse_button_box") and self.collapse_button_box:
            self.collapse_button_box.tooltip = (
                "Развернуть панель" if self.sidebar_collapsed else "Свернуть панель"
            )

    def _on_resizer_pan_start(self, e: ft.DragStartEvent) -> None:
        """Disable animation during manual drag for immediate 1:1 response."""
        self.sidebar_area.animate_size = None
        self._drag_width = float(
            self.sidebar_area.width
            or (self.COLLAPSED_SIDEBAR_WIDTH if self.sidebar_collapsed else self.DEFAULT_EXPANDED_WIDTH)
        )

    def _on_resizer_pan_update(self, e: ft.DragUpdateEvent) -> None:
        """Adjust sidebar width smoothly as user drags horizontally."""
        dx = 0.0
        if hasattr(e, "delta_x") and e.delta_x is not None:
            dx = e.delta_x
        elif getattr(e, "local_delta", None) is not None and hasattr(e.local_delta, "x"):
            dx = e.local_delta.x
        elif getattr(e, "global_delta", None) is not None and hasattr(e.global_delta, "x"):
            dx = e.global_delta.x
        elif getattr(e, "primary_delta", None) is not None:
            dx = e.primary_delta

        if not dx:
            return

        if self.sidebar_collapsed:
            self._drag_width = max(float(self.COLLAPSED_SIDEBAR_WIDTH), self._drag_width + dx)

            # When pulling right past 130px, expand into normal mode
            if self._drag_width > self.COLLAPSE_THRESHOLD:
                self.sidebar_collapsed = False
                expanded_w = min(self.MAX_SIDEBAR_WIDTH, self._drag_width)
                self.saved_expanded_width = expanded_w
                self.sidebar_area.width = expanded_w
                self._render_sidebar()
                self._update_resizer_button()
                self.page.update()
        else:
            self._drag_width += dx

            # When dragging left down to or below 130px, collapse into compact mode
            if self._drag_width <= self.COLLAPSE_THRESHOLD:
                self.sidebar_collapsed = True
                self.sidebar_area.width = self.COLLAPSED_SIDEBAR_WIDTH
                self._drag_width = float(self.COLLAPSED_SIDEBAR_WIDTH)
                self._render_sidebar()
                self._update_resizer_button()
                self.page.update()
            else:
                clamped_w = min(self.MAX_SIDEBAR_WIDTH, max(self.MIN_SIDEBAR_WIDTH, self._drag_width))
                if clamped_w != self.sidebar_area.width:
                    self.saved_expanded_width = clamped_w
                    self.sidebar_area.width = clamped_w
                    self.page.update()

    def _on_resizer_pan_end(self, e: ft.DragEndEvent) -> None:
        """Finalize drag gesture and store chosen width."""
        if not self.sidebar_collapsed and self.sidebar_area.width:
            self.saved_expanded_width = self.sidebar_area.width
        self._update_resizer_button()
        self.page.update()

    def _on_resizer_double_tap(self, e: ft.ControlEvent) -> None:
        """Double tap resets to default expanded width or toggles collapsed state."""
        self.sidebar_area.animate_size = 200
        if self.sidebar_collapsed:
            self.sidebar_collapsed = False
            self.saved_expanded_width = self.DEFAULT_EXPANDED_WIDTH
            self.sidebar_area.width = self.DEFAULT_EXPANDED_WIDTH
            self._drag_width = float(self.DEFAULT_EXPANDED_WIDTH)
        else:
            if self.sidebar_area.width != self.DEFAULT_EXPANDED_WIDTH:
                self.saved_expanded_width = self.DEFAULT_EXPANDED_WIDTH
                self.sidebar_area.width = self.DEFAULT_EXPANDED_WIDTH
                self._drag_width = float(self.DEFAULT_EXPANDED_WIDTH)
            else:
                self.sidebar_collapsed = True
                self.sidebar_area.width = self.COLLAPSED_SIDEBAR_WIDTH
                self._drag_width = float(self.COLLAPSED_SIDEBAR_WIDTH)
        self._render_sidebar()
        self._update_resizer_button()
        self.page.update()

    def toggle_sidebar(self) -> None:
        """Toggle sidebar between collapsed (icons only) and expanded."""
        self.sidebar_collapsed = not self.sidebar_collapsed
        self.sidebar_area.animate_size = 200
        if self.sidebar_collapsed:
            self.sidebar_area.width = self.COLLAPSED_SIDEBAR_WIDTH
            self._drag_width = float(self.COLLAPSED_SIDEBAR_WIDTH)
        else:
            expanded_w = max(self.MIN_SIDEBAR_WIDTH, self.saved_expanded_width)
            self.sidebar_area.width = expanded_w
            self._drag_width = float(expanded_w)
        self._render_sidebar()
        self._update_resizer_button()
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
                    weight=ft.FontWeight.W_600 if is_active else ft.FontWeight.W_500,
                    size=14,
                    expand=True,
                    max_lines=1,
                    overflow=ft.TextOverflow.ELLIPSIS,
                ),
            ]
            if badge_text is not None:
                row_controls.append(
                    ft.Container(
                        content=ft.Text(
                            badge_text,
                            size=12,
                            weight=ft.FontWeight.BOLD,
                            color=ft.Colors.PRIMARY if is_active else ft.Colors.GREY_300,
                        ),
                        bgcolor=(
                            ft.Colors.with_opacity(0.25, ft.Colors.PRIMARY)
                            if is_active
                            else ft.Colors.SURFACE_CONTAINER_HIGHEST
                        ),
                        padding=ft.Padding(left=7, top=2, right=7, bottom=2),
                        border_radius=10,
                    )
                )

            return ft.Container(
                content=ft.Row(controls=row_controls, spacing=10),
                bgcolor=bg_color,
                border=border_style,
                border_radius=10,
                padding=ft.Padding(left=12, top=10, right=12, bottom=10),
                ink=True,
                on_click=lambda _, idx=tab_idx: self.switch_tab(idx),
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
                    ft.Text("Статистика", size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.GREY_300),
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Text("На сегодня (активно):", size=12, color=ft.Colors.GREY_400, expand=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                            ft.Text(str(today_active), size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.CYAN_300),
                        ],
                    ),
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Text("Завершено сегодня:", size=12, color=ft.Colors.GREY_400, expand=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                            ft.Text(str(today_completed), size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_400),
                        ],
                    ),
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Text("Всего активных:", size=12, color=ft.Colors.GREY_400, expand=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                            ft.Text(str(all_active), size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_300),
                        ],
                    ),
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Text("Завершено за всё время:", size=12, color=ft.Colors.GREY_400, expand=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                            ft.Text(str(completed_total_count), size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_300),
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
            padding=ft.Padding(left=8, top=12, right=8, bottom=12) if self.sidebar_collapsed else ft.Padding(left=12, top=12, right=12, bottom=12),
            expand=True,
            content=ft.Column(
                expand=True,
                controls=[
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
        """Render a single compact, responsive task card.

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

        # Compact Tag container badge
        tag_badge = ft.Container(
            content=ft.Row(
                spacing=4,
                tight=True,
                controls=[
                    ft.Text(tag_icon, size=13),
                    ft.Text(
                        tag_name,
                        size=12,
                        weight=ft.FontWeight.W_600,
                        color=tag_color,
                    ),
                ],
            ),
            bgcolor=ft.Colors.with_opacity(0.12, tag_color),
            border=ft.Border.all(width=1, color=ft.Colors.with_opacity(0.35, tag_color)),
            padding=ft.Padding(left=6, top=2, right=6, bottom=2),
            border_radius=6,
        )

        # Header controls
        if is_completed:
            status_icon = ft.Icon(
                ft.Icons.CHECK_CIRCLE_ROUNDED,
                color=ft.Colors.GREEN_400,
                size=19,
            )
            title_text = ft.Text(
                f"✓ {task.name}",
                size=14,
                weight=ft.FontWeight.W_500,
                style=ft.TextStyle(
                    decoration=ft.TextDecoration.LINE_THROUGH,
                    color=ft.Colors.GREY_400,
                ),
                expand=True,
                max_lines=1,
                overflow=ft.TextOverflow.ELLIPSIS,
            )
            action_btn = ft.IconButton(
                icon=ft.Icons.RESTORE_ROUNDED,
                icon_size=18,
                tooltip="Вернуть в работу",
                icon_color=ft.Colors.GREY_300,
                on_click=lambda _, tid=task.id, tname=task.name: self.reopen_task(tid, tname),
            )
            score_or_status = ft.Container(
                content=ft.Text("Завершено", size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_300),
                bgcolor=ft.Colors.with_opacity(0.16, ft.Colors.GREEN_400),
                padding=ft.Padding(left=6, top=2, right=6, bottom=2),
                border_radius=6,
            )
        else:
            status_icon = ft.Icon(
                priority_icon,
                color=priority_color,
                size=19,
            )
            title_text = ft.Text(
                f"#{rank} {task.name}",
                size=14,
                weight=ft.FontWeight.W_600,
                color=ft.Colors.ON_SURFACE,
                expand=True,
                max_lines=1,
                overflow=ft.TextOverflow.ELLIPSIS,
            )
            action_btn = ft.IconButton(
                icon=ft.Icons.CHECK_CIRCLE_OUTLINE_ROUNDED,
                icon_size=20,
                tooltip="Завершить задачу",
                icon_color=ft.Colors.GREEN_400,
                on_click=lambda _, tid=task.id, tname=task.name, et=task.expected_time: self.open_complete_dialog(tid, tname, et),
            )
            score_or_status = ft.Container(
                content=ft.Text(f"Вес: {scored.score:.1f}", size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                padding=ft.Padding(left=5, top=2, right=5, bottom=2),
                border_radius=6,
            )

        header_row = ft.Row(
            spacing=6,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                status_icon,
                title_text,
                tag_badge,
                score_or_status,
                action_btn,
            ],
        )

        # Compact Metadata badges in a wrap row
        metadata_chips: list[ft.Control] = [
            ft.Container(
                content=ft.Row(
                    spacing=4,
                    tight=True,
                    controls=[
                        ft.Icon(sched_icon, size=13, color=sched_color),
                        ft.Text(f"План: {sched_str}", size=12, color=sched_color, weight=ft.FontWeight.W_500),
                    ],
                ),
                bgcolor=ft.Colors.with_opacity(0.10, sched_color),
                padding=ft.Padding(left=6, top=2, right=6, bottom=2),
                border_radius=6,
            ),
            ft.Container(
                content=ft.Row(
                    spacing=4,
                    tight=True,
                    controls=[
                        ft.Icon(ft.Icons.ACCESS_TIME_ROUNDED, size=13, color=ft.Colors.CYAN_300),
                        ft.Text(time_str, size=12, color=ft.Colors.CYAN_200, weight=ft.FontWeight.W_600),
                    ],
                ),
                bgcolor=ft.Colors.with_opacity(0.10, ft.Colors.CYAN_400),
                padding=ft.Padding(left=6, top=2, right=6, bottom=2),
                border_radius=6,
            ),
            ft.Container(
                content=ft.Row(
                    spacing=4,
                    tight=True,
                    controls=[
                        ft.Icon(ft.Icons.FLAG_ROUNDED, size=13, color=ft.Colors.GREY_500 if is_completed else priority_color),
                        ft.Text(priority_label, size=12, color=ft.Colors.GREY_500 if is_completed else priority_color, weight=ft.FontWeight.W_500),
                    ],
                ),
                bgcolor=ft.Colors.with_opacity(0.08, priority_color),
                padding=ft.Padding(left=6, top=2, right=6, bottom=2),
                border_radius=6,
            ),
            ft.Container(
                content=ft.Row(
                    spacing=4,
                    tight=True,
                    controls=[
                        ft.Icon(ft.Icons.CALENDAR_MONTH_ROUNDED, size=13, color=ft.Colors.GREY_500 if is_completed else deadline_color),
                        ft.Text(f"Дедлайн: {deadline_str}", size=12, color=ft.Colors.GREY_500 if is_completed else deadline_color, weight=ft.FontWeight.W_500),
                    ],
                ),
                bgcolor=ft.Colors.with_opacity(0.08, deadline_color),
                padding=ft.Padding(left=6, top=2, right=6, bottom=2),
                border_radius=6,
            ),
        ]

        if ai_pred_str and not is_completed:
            metadata_chips.append(
                ft.Container(
                    content=ft.Row(
                        spacing=4,
                        tight=True,
                        controls=[
                            ft.Icon(ft.Icons.AUTO_AWESOME_ROUNDED, size=13, color=ft.Colors.AMBER_400),
                            ft.Text(f"ИИ: {ai_pred_str}", size=12, color=ft.Colors.AMBER_300, weight=ft.FontWeight.W_500),
                        ],
                    ),
                    bgcolor=ft.Colors.with_opacity(0.10, ft.Colors.AMBER_400),
                    padding=ft.Padding(left=6, top=2, right=6, bottom=2),
                    border_radius=6,
                )
            )

        meta_row = ft.Row(
            spacing=6,
            run_spacing=4,
            wrap=True,
            controls=metadata_chips,
        )

        card_controls: list[ft.Control] = [header_row, meta_row]

        if task.description:
            card_controls.append(
                ft.Text(
                    task.description,
                    size=12,
                    color=ft.Colors.GREY_500 if is_completed else ft.Colors.GREY_400,
                    max_lines=1,
                    overflow=ft.TextOverflow.ELLIPSIS,
                )
            )

        return ft.Card(
            elevation=1 if is_completed else 2,
            content=ft.Container(
                padding=ft.Padding(left=12, top=8, right=10, bottom=8),
                border_radius=10,
                ink=True,
                opacity=0.78 if is_completed else 1.0,
                tooltip="Нажмите на карточку, чтобы изменить задачу",
                on_click=lambda _, t=task: self.open_edit_dialog(t),
                content=ft.Column(
                    spacing=5,
                    tight=True,
                    controls=card_controls,
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
                                    "Используйте строку выше для добавления задачи на сегодня.",
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

    def _build_quick_add_bar(self, only_today: bool = False) -> ft.Control:
        """Build an inline, icon-only quick-add bar with hover tooltips for compact screens."""
        subjects = self.task_manager.get_all_subjects()
        if not subjects:
            try:
                self.task_manager.add_subject("Общее", color="#2196F3", icon="📌")
                subjects = self.task_manager.get_all_subjects()
            except Exception:
                pass

        # Priority mappings
        PRIORITY_MAP = {
            TaskPriority.LOW: ("🟢", "Низкий"),
            TaskPriority.MEDIUM: ("🟡", "Средний"),
            TaskPriority.HIGH: ("🟠", "Высокий"),
            TaskPriority.CRITICAL: ("🔴", "Критический"),
        }

        # 1. Subject / Tag
        cur_subj = None
        if self._last_selected_subject_id:
            cur_subj = next((s for s in subjects if str(s.id) == self._last_selected_subject_id), None)
        if not cur_subj and subjects:
            cur_subj = subjects[0]
            self._last_selected_subject_id = str(cur_subj.id)

        tag_icon_text = ft.Text(cur_subj.icon if cur_subj else "🏷️", size=18)

        def _set_subject(subj: Subject) -> None:
            self._last_selected_subject_id = str(subj.id)
            tag_icon_text.value = subj.icon or "🏷️"
            tag_btn.tooltip = f"Тег: {subj.name} (нажмите для выбора)"
            self.page.update()

        tag_btn = ft.PopupMenuButton(
            content=ft.Container(
                content=tag_icon_text,
                padding=ft.Padding(6, 6, 6, 6),
                border_radius=8,
                ink=True,
            ),
            tooltip=f"Тег: {cur_subj.name if cur_subj else 'Общее'} (нажмите для выбора)",
            items=[
                ft.PopupMenuItem(
                    content=ft.Row(
                        [
                            ft.Text(s.icon or "🏷️", size=16),
                            ft.Text(f" {s.name}", size=13),
                        ],
                        spacing=6,
                    ),
                    on_click=lambda _, s=s: _set_subject(s),
                )
                for s in subjects
            ],
        )

        # 2. Time selector
        cur_mins = int(self._last_expected_minutes or "60")

        def _set_time(mins: int) -> None:
            self._last_expected_minutes = str(mins)
            time_btn.tooltip = f"Время: {mins} мин (нажмите для выбора)"
            self.page.update()

        time_btn = ft.PopupMenuButton(
            content=ft.Container(
                content=ft.Icon(ft.Icons.ACCESS_TIME_ROUNDED, size=20, color=ft.Colors.PRIMARY),
                padding=ft.Padding(6, 6, 6, 6),
                border_radius=8,
                ink=True,
            ),
            tooltip=f"Время: {cur_mins} мин (нажмите для выбора)",
            items=[
                ft.PopupMenuItem(content=ft.Text("⏱️ 15 мин"), on_click=lambda _: _set_time(15)),
                ft.PopupMenuItem(content=ft.Text("⏱️ 30 мин"), on_click=lambda _: _set_time(30)),
                ft.PopupMenuItem(content=ft.Text("⏱️ 45 мин"), on_click=lambda _: _set_time(45)),
                ft.PopupMenuItem(content=ft.Text("⏱️ 60 мин (1 ч)"), on_click=lambda _: _set_time(60)),
                ft.PopupMenuItem(content=ft.Text("⏱️ 90 мин (1.5 ч)"), on_click=lambda _: _set_time(90)),
                ft.PopupMenuItem(content=ft.Text("⏱️ 120 мин (2 ч)"), on_click=lambda _: _set_time(120)),
                ft.PopupMenuItem(content=ft.Text("⏱️ 180 мин (3 ч)"), on_click=lambda _: _set_time(180)),
            ],
        )

        # 3. Priority / Difficulty rating
        try:
            cur_p = TaskPriority(self._last_selected_priority or TaskPriority.MEDIUM.value)
        except ValueError:
            cur_p = TaskPriority.MEDIUM
        p_icon, p_name = PRIORITY_MAP.get(cur_p, ("🟡", "Средний"))
        priority_icon_text = ft.Text(p_icon, size=18)

        def _set_priority(p: TaskPriority) -> None:
            self._last_selected_priority = p.value
            p_ic, p_nm = PRIORITY_MAP.get(p, ("🟡", "Средний"))
            priority_icon_text.value = p_ic
            priority_btn.tooltip = f"Рейтинг сложности: {p_nm} (нажмите для выбора)"
            self.page.update()

        priority_btn = ft.PopupMenuButton(
            content=ft.Container(
                content=priority_icon_text,
                padding=ft.Padding(6, 6, 6, 6),
                border_radius=8,
                ink=True,
            ),
            tooltip=f"Рейтинг сложности: {p_name} (нажмите для выбора)",
            items=[
                ft.PopupMenuItem(
                    content=ft.Row([ft.Text("🟢", size=16), ft.Text(" Низкий", size=13)], spacing=6),
                    on_click=lambda _: _set_priority(TaskPriority.LOW),
                ),
                ft.PopupMenuItem(
                    content=ft.Row([ft.Text("🟡", size=16), ft.Text(" Средний", size=13)], spacing=6),
                    on_click=lambda _: _set_priority(TaskPriority.MEDIUM),
                ),
                ft.PopupMenuItem(
                    content=ft.Row([ft.Text("🟠", size=16), ft.Text(" Высокий", size=13)], spacing=6),
                    on_click=lambda _: _set_priority(TaskPriority.HIGH),
                ),
                ft.PopupMenuItem(
                    content=ft.Row([ft.Text("🔴", size=16), ft.Text(" Критический", size=13)], spacing=6),
                    on_click=lambda _: _set_priority(TaskPriority.CRITICAL),
                ),
            ],
        )

        # 4. Date Picker and Calendar Button
        date_picker = ft.DatePicker(
            first_date=datetime(2020, 1, 1),
            last_date=datetime(2035, 12, 31),
            value=datetime.now(),
        )

        def _open_date_picker() -> None:
            if hasattr(self.page, "show_dialog"):
                self.page.show_dialog(date_picker)
            elif hasattr(self.page, "open"):
                self.page.open(date_picker)
            else:
                if date_picker not in self.page.overlay:
                    self.page.overlay.append(date_picker)
                date_picker.open = True
                self.page.update()

        initial_date = date.today() if only_today else (self._last_selected_date or date.today())
        d_str = "Сегодня" if initial_date == date.today() else initial_date.strftime("%d.%m.%Y")
        cal_btn = ft.IconButton(
            icon=ft.Icons.CALENDAR_MONTH_ROUNDED,
            icon_color=ft.Colors.PRIMARY,
            icon_size=20,
            tooltip=f"Дата: {d_str} (нажмите для выбора)",
            on_click=lambda _: _open_date_picker(),
        )

        def _on_date_picked(e: ft.ControlEvent) -> None:
            if date_picker.value:
                d = date_picker.value.date() if hasattr(date_picker.value, "date") else date_picker.value
                self._last_selected_date = d
                picked_str = "Сегодня" if d == date.today() else d.strftime("%d.%m.%Y")
                cal_btn.tooltip = f"Дата: {picked_str} (нажмите для выбора)"
                cal_btn.icon_color = ft.Colors.CYAN_400
                self.page.update()

        date_picker.on_change = _on_date_picked

        # 5. Task Title Field: takes all remaining width
        name_field = ft.TextField(
            hint_text="Новая задача... (Enter для сохранения)",
            prefix_icon=ft.Icons.ADD_TASK_ROUNDED,
            dense=True,
            text_size=13,
            expand=True,
            autofocus=False,
            tooltip="Название задачи (нажмите Enter для сохранения)",
            on_submit=lambda _: _submit(),
        )
        self._quick_add_name_field = name_field

        # 6. Add Task Button
        add_btn = ft.IconButton(
            icon=ft.Icons.ADD_ROUNDED,
            bgcolor=ft.Colors.PRIMARY,
            icon_color=ft.Colors.WHITE,
            icon_size=20,
            tooltip="Добавить задачу (Enter)",
            on_click=lambda _: _submit(),
        )

        def _submit(e: ft.ControlEvent | None = None) -> None:
            title = (name_field.value or "").strip()
            if not title:
                name_field.error_text = "Введите название задачи"
                self.page.update()
                return

            name_field.error_text = None

            # Subject
            subject_id = None
            if self._last_selected_subject_id:
                try:
                    subject_id = int(self._last_selected_subject_id)
                except ValueError:
                    pass
            if subject_id is None and subjects:
                subject_id = subjects[0].id

            if subject_id is None:
                _show_snack(self.page, "Сначала выберите или создайте тег!", bgcolor=ft.Colors.AMBER_800)
                return

            # Time
            time_val = 60.0
            if self._last_expected_minutes:
                try:
                    time_val = float(self._last_expected_minutes)
                except ValueError:
                    time_val = 60.0
            expected_hours = round(time_val / 60.0, 4)

            # Priority
            try:
                priority = TaskPriority(self._last_selected_priority or TaskPriority.MEDIUM.value)
            except ValueError:
                priority = TaskPriority.MEDIUM

            # Scheduled Date
            sched_date = self._last_selected_date or (date.today() if only_today else None)

            try:
                task = self.task_manager.add_task(
                    name=title,
                    subject_id=subject_id,
                    priority=priority,
                    expected_time=expected_hours,
                    scheduled_date=sched_date,
                )

                # AI time prediction info
                ai_info = ""
                try:
                    pred = TimePredictor().predict_time(subject_id, expected_hours)
                    if not pred.cold_start:
                        pred_min = round(pred.predicted_time * 60, 1)
                        ai_info = f" • ИИ прогноз: {int(pred_min) if pred_min.is_integer() else pred_min:.0f} мин"
                except Exception:
                    pass

                date_info = f" на {sched_date.strftime('%d.%m')}" if sched_date else ""
                _show_snack(self.page, f"Задача «{title}» добавлена{date_info}!{ai_info}")
                self.refresh()
                self._focus_control(self._quick_add_name_field)
            except Exception as err:
                _show_snack(self.page, f"Ошибка при добавлении задачи: {err}", bgcolor=ft.Colors.RED_800)

        row_layout = ft.Row(
            spacing=4,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                name_field,
                tag_btn,
                time_btn,
                priority_btn,
                cal_btn,
                add_btn,
            ],
        )

        return ft.Card(
            elevation=1,
            content=ft.Container(
                padding=ft.Padding(left=8, top=4, right=6, bottom=4),
                border_radius=10,
                bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
                border=ft.Border.all(1, ft.Colors.with_opacity(0.18, ft.Colors.OUTLINE)),
                content=row_layout,
            ),
        )

    def _render_today_tasks_view(self) -> ft.Control:
        """Build the 'Сегодняшние задачи' view."""
        self.load_today_tasks()

        today_tasks = self.scheduler.get_prioritized_tasks(only_today=True)
        today_active = len([s for s in today_tasks if s.task.status != TaskStatus.COMPLETED])
        today_done = len([s for s in today_tasks if s.task.status == TaskStatus.COMPLETED])

        header_actions = ft.Row(
            spacing=8,
            wrap=True,
            controls=[
                ft.OutlinedButton(
                    "Завершить задачи дня",
                    icon=ft.Icons.DONE_ALL_ROUNDED,
                    style=ft.ButtonStyle(
                        color=ft.Colors.GREEN_400,
                    ) if hasattr(ft, "ButtonStyle") else None,
                    on_click=lambda _: self.confirm_complete_all(only_today=True),
                ),
            ],
        )

        header = ft.Row(
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            wrap=True,
            run_spacing=8,
            controls=[
                ft.Column(
                    spacing=4,
                    controls=[
                        ft.Row(
                            [
                                ft.Icon(
                                    ft.Icons.TODAY_ROUNDED,
                                    color=ft.Colors.PRIMARY,
                                    size=24,
                                ),
                                ft.Text(
                                    "Сегодняшние задачи",
                                    size=20,
                                    weight=ft.FontWeight.BOLD,
                                ),
                            ],
                            spacing=8,
                        ),
                        ft.Text(
                            f"{self._format_today_header()} • К выполнению: {today_active} • Завершено: {today_done}",
                            size=12,
                            color=ft.Colors.GREY_400,
                        ),
                    ],
                ),
                header_actions,
            ],
        )

        quick_add_bar = self._build_quick_add_bar(only_today=True)

        return ft.Column(
            spacing=12,
            expand=True,
            controls=[
                header,
                ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                quick_add_bar,
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
                                    "Нет активных или просроченных задач. Для создания новой задачи используйте строку выше.",
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
            spacing=8,
            wrap=True,
            controls=[
                ft.OutlinedButton(
                    "Завершить все задачи",
                    icon=ft.Icons.DONE_ALL_ROUNDED,
                    style=ft.ButtonStyle(
                        color=ft.Colors.GREEN_400,
                    ) if hasattr(ft, "ButtonStyle") else None,
                    on_click=lambda _: self.confirm_complete_all(only_today=False),
                ),
            ],
        )

        header = ft.Row(
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            wrap=True,
            run_spacing=8,
            controls=[
                ft.Column(
                    spacing=4,
                    controls=[
                        ft.Row(
                            [
                                ft.Icon(
                                    ft.Icons.CHECKLIST_ROUNDED,
                                    color=ft.Colors.PRIMARY,
                                    size=24,
                                ),
                                ft.Text(
                                    "Все задачи",
                                    size=20,
                                    weight=ft.FontWeight.BOLD,
                                ),
                            ],
                            spacing=8,
                        ),
                        ft.Text(
                            f"Активных задач: {all_active} • Завершено сегодня: {all_done_today}",
                            size=12,
                            color=ft.Colors.GREY_400,
                        ),
                    ],
                ),
                header_actions,
            ],
        )

        quick_add_bar = self._build_quick_add_bar(only_today=False)

        return ft.Column(
            spacing=12,
            expand=True,
            controls=[
                header,
                ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                quick_add_bar,
                self.all_tasks_column,
            ],
        )

    # ──────────────────────────────────────────
    # Tab 2: Tags / Subjects
    # ──────────────────────────────────────────
    def build_tag_card(self, tag: Subject, task_count: int) -> ft.Card:
        """Render a single compact tag card matching task card design."""
        tag_color = tag.color or "#4CAF50"
        tag_icon = tag.icon or "🏷️"

        # Compact icon box
        icon_box = ft.Container(
            content=ft.Text(tag_icon, size=14),
            bgcolor=ft.Colors.with_opacity(0.14, tag_color),
            border=ft.Border.all(width=1, color=ft.Colors.with_opacity(0.4, tag_color)),
            border_radius=6,
            padding=ft.Padding(left=6, top=3, right=6, bottom=3),
            alignment=ft.Alignment(0, 0),
        )

        # Name
        name_text = ft.Text(
            tag.name,
            size=14,
            weight=ft.FontWeight.W_600,
            color=ft.Colors.ON_SURFACE,
            expand=True,
            max_lines=1,
            overflow=ft.TextOverflow.ELLIPSIS,
        )

        # Color chip
        color_chip = ft.Container(
            content=ft.Row(
                spacing=4,
                tight=True,
                controls=[
                    ft.Container(
                        width=8,
                        height=8,
                        border_radius=4,
                        bgcolor=tag_color,
                    ),
                    ft.Text(
                        tag_color,
                        size=12,
                        color=ft.Colors.GREY_300,
                        weight=ft.FontWeight.W_500,
                    ),
                ],
            ),
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            padding=ft.Padding(left=6, top=2, right=6, bottom=2),
            border_radius=6,
        )

        # Task count chip
        count_chip = ft.Container(
            content=ft.Text(
                f"Задач: {task_count}",
                size=12,
                weight=ft.FontWeight.W_500,
                color=ft.Colors.GREY_300,
            ),
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            padding=ft.Padding(left=6, top=2, right=6, bottom=2),
            border_radius=6,
        )

        # Action buttons
        edit_btn = ft.IconButton(
            icon=ft.Icons.EDIT_ROUNDED,
            icon_size=18,
            tooltip="Редактировать тег",
            icon_color=ft.Colors.PRIMARY,
            on_click=lambda _, t=tag: self.open_edit_tag_dialog(t),
        )

        delete_btn = ft.IconButton(
            icon=ft.Icons.DELETE_OUTLINE_ROUNDED,
            icon_size=18,
            tooltip="Удалить тег",
            icon_color=ft.Colors.RED_400,
            on_click=lambda _, t=tag, cnt=task_count: self.confirm_delete_tag(t, cnt),
        )

        return ft.Card(
            elevation=1,
            content=ft.Container(
                padding=ft.Padding(left=10, top=6, right=8, bottom=6),
                border_radius=10,
                ink=True,
                tooltip="Нажмите, чтобы изменить тег",
                on_click=lambda _, t=tag: self.open_edit_tag_dialog(t),
                content=ft.Row(
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        icon_box,
                        name_text,
                        color_chip,
                        count_chip,
                        edit_btn,
                        delete_btn,
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

    def _handle_page_resize(self, e: ft.ControlEvent | None = None) -> None:
        """Handle screen resizing adaptively for various screen dimensions."""
        width = getattr(self.page, "width", None) or 1000
        # Adaptive page padding based on screen width
        if width < 600:
            self.page.padding = 6
        elif width < 900:
            self.page.padding = 10
        else:
            self.page.padding = 14

        # Auto-collapse sidebar on narrow screens (< 768px)
        if width < 768 and not self.sidebar_collapsed:
            self.sidebar_collapsed = True
            self.sidebar_area.width = self.COLLAPSED_SIDEBAR_WIDTH
            self._drag_width = float(self.COLLAPSED_SIDEBAR_WIDTH)
            self._render_sidebar()
            self._update_resizer_button()

        self.page.update()

    def render(self) -> None:
        """Assemble the complete layout (sidebar + content) on the page."""
        self.page.title = "Умное расписание"
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.theme = ft.Theme(
            font_family="Roboto, Segoe UI, -apple-system, sans-serif",
            use_material3=True,
        )
        self.page.padding = 14
        self.page.on_resize = self._handle_page_resize

        self._render_sidebar()
        self._render_content()
        self._update_fab()

        self.page.controls.clear()
        self.page.add(
            ft.Row(
                expand=True,
                spacing=0,
                vertical_alignment=ft.CrossAxisAlignment.STRETCH,
                controls=[
                    self.sidebar_area,
                    self.resizer_handle,
                    ft.Container(width=10),
                    self.content_area,
                ],
            )
        )
        self._handle_page_resize()
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
