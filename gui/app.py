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

import gc
import sys
from datetime import date, datetime
from pathlib import Path
import re

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

    TAG_PRESET_ICONS = ["🏷️", "📚", "💻", "🔬", "📐", "🎨", "📝", "💡", "⚡", "🎯", "🌐", "🧪", "📈", "☕", "🚀", "💼"]
    TAG_PRESET_COLORS = [
        ("#4CAF50", "Зеленый"),
        ("#2196F3", "Синий"),
        ("#9C27B0", "Фиолетовый"),
        ("#FF9800", "Оранжевый"),
        ("#E91E63", "Розовый"),
        ("#F44336", "Красный"),
        ("#00BCD4", "Бирюзовый"),
        ("#FFC107", "Янтарный"),
        ("#607D8B", "Серо-голубой"),
        ("#3F51B5", "Индиго"),
    ]

    def __init__(self, page: ft.Page) -> None:
        self.page = page
        self.scheduler = TaskScheduler()
        self.task_manager = TaskManager()
        self.predictor = TimePredictor()

        # Batch pagination limits to avoid bloated control trees in memory
        self.all_tasks_limit = 40
        self.archive_tasks_limit = 40

        # Active tab: 0 = Today's tasks, 1 = All tasks, 2 = Tags, 3 = Archive
        self.current_tab = 0
        self.sidebar_collapsed = False
        self.saved_expanded_width = self.DEFAULT_EXPANDED_WIDTH
        self._drag_width = float(self.DEFAULT_EXPANDED_WIDTH)

        # Containers (ListView provides Flutter viewport virtualization for fast scrolling with many tasks)
        self.today_tasks_column = ft.ListView(spacing=8, expand=True)
        self.all_tasks_column = ft.ListView(spacing=8, expand=True)
        self.tags_column = ft.ListView(spacing=8, expand=True)
        self.archive_column = ft.ListView(spacing=8, expand=True)

        # Main content area with smooth animated transition switcher (300ms symmetric fade) to hide page loads without jitter
        self.content_area = ft.AnimatedSwitcher(
            content=ft.Container(expand=True),
            transition=ft.AnimatedSwitcherTransition.FADE,
            duration=300,
            reverse_duration=300,
            switch_in_curve=ft.AnimationCurve.EASE_OUT,
            switch_out_curve=ft.AnimationCurve.EASE_OUT,
            expand=True,
        )
        self.sidebar_area = ft.Container(
            width=self.DEFAULT_EXPANDED_WIDTH,
            on_click=lambda _: self.close_right_panel() if self.right_panel_open else None,
        )

        # Tab view caching for zero-lag 0ms tab switching
        self._tab_views: dict[int, ft.Control] = {}
        self._dirty_tabs: set[int] = {0, 1, 2, 3}
        self._tab_versions: dict[int, int] = {0: 0, 1: 0, 2: 0, 3: 0}
        self._nav_btn_containers: dict[int, ft.Container] = {}
        self._task_card_containers: dict[int, ft.Container] = {}
        self._tag_card_containers: dict[int, ft.Container] = {}

        # Quick-add task row state
        self._last_selected_subject_id: str | None = None
        self._last_selected_priority: str = TaskPriority.MEDIUM.value
        self._last_expected_minutes: str = "60"
        self._last_selected_date: date | None = None
        self._quick_add_name_field: ft.TextField | None = None

        # Quick-add tag row state
        self._last_tag_icon: str = "🏷️"
        self._last_tag_color: str = "#4CAF50"
        self._quick_add_tag_name_field: ft.TextField | None = None

        # Resizer handle between sidebar and content
        self.resizer_handle = self._build_resizer_handle()

        # Right overlay panel state (opens on top without shifting main list)
        self.right_panel_open: bool = False
        self.right_panel_mode: str = "task"  # "task" or "tag"
        self.selected_task_id: int | None = None
        self.selected_tag_id: int | None = None
        self._last_selected_task_id: int | None = None
        self._last_selected_tag_id: int | None = None
        self.right_panel_width: int = 400
        self.right_panel_container: ft.Container = self._build_right_panel_container()
        self.right_panel_barrier: ft.Container = self._build_right_panel_barrier()

        # Stack wrapping content_area, backdrop barrier, and overlay right panel (fit=EXPAND prevents layout resize jitter)
        self.main_content_stack: ft.Stack = ft.Stack(
            expand=True,
            fit=ft.StackFit.EXPAND,
            controls=[
                self.content_area,
                self.right_panel_barrier,
                self.right_panel_container,
            ],
        )

        # Setup keyboard shortcuts (e.g. Esc to close right panel)
        self._setup_keyboard_shortcuts()

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
        """Switch active tab: 0 (Today), 1 (All Tasks), 2 (Tags), 3 (Archive)."""
        if self.right_panel_open:
            self.close_right_panel()
        if self.current_tab != tab_index:
            self.current_tab = tab_index
            self._update_sidebar_tab_selection()
            self._render_content()
            self._update_fab()
            self.page.update()

    def _update_sidebar_tab_selection(self) -> None:
        """Fast update of sidebar navigation button highlights without re-querying stats."""
        if not hasattr(self, "_nav_btn_containers") or not self._nav_btn_containers:
            self._render_sidebar()
            return
        for idx, btn in self._nav_btn_containers.items():
            is_active = (idx == self.current_tab)
            btn.bgcolor = (
                ft.Colors.with_opacity(0.18, ft.Colors.PRIMARY)
                if is_active
                else ft.Colors.TRANSPARENT
            )
            btn.border = (
                ft.Border.all(1, ft.Colors.with_opacity(0.4, ft.Colors.PRIMARY))
                if is_active
                else ft.Border.all(1, ft.Colors.TRANSPARENT)
            )

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
        stats = self.task_manager.get_sidebar_stats()
        today_active = stats["today_active"]
        today_completed = stats["today_completed"]
        all_active = stats["all_active"]
        tags_count = stats["tags_count"]
        completed_total_count = stats["completed_total"]
        archived_count = stats["archived_count"]

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
                ft.Border.all(width=1, color=ft.Colors.with_opacity(0.4, ft.Colors.PRIMARY))
                if is_active
                else ft.Border.all(width=1, color=ft.Colors.TRANSPARENT)
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
                    animate=250,
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
                animate=250,
                on_click=lambda _, idx=tab_idx: self.switch_tab(idx),
            )

        # Navigation items
        self._nav_btn_containers.clear()
        btn_0 = _nav_button("Сегодняшние задачи", ft.Icons.TODAY_ROUNDED, 0, str(today_active))
        btn_1 = _nav_button("Все задачи", ft.Icons.CHECKLIST_ROUNDED, 1, str(all_active))
        btn_2 = _nav_button("Теги и предметы", ft.Icons.LOCAL_OFFER_ROUNDED, 2, str(tags_count))
        btn_3 = _nav_button("Архив", ft.Icons.INVENTORY_2_ROUNDED, 3, str(archived_count) if archived_count > 0 else None)
        self._nav_btn_containers[0] = btn_0
        self._nav_btn_containers[1] = btn_1
        self._nav_btn_containers[2] = btn_2
        self._nav_btn_containers[3] = btn_3

        nav_items = ft.Column(
            spacing=8,
            controls=[btn_0, btn_1, btn_2, btn_3],
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
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Text("В архиве:", size=12, color=ft.Colors.GREY_400, expand=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                            ft.Text(str(archived_count), size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.CYAN_300),
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
                tooltip=f"На сегодня: {today_active} | Всего: {all_active} | Архив: {archived_count}",
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
                pred = self.predictor.predict_time(task.subject_id, task.expected_time)
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
            archive_btn = ft.IconButton(
                icon=ft.Icons.ARCHIVE_ROUNDED,
                icon_size=18,
                tooltip="Отправить в архив",
                icon_color=ft.Colors.CYAN_300,
                on_click=lambda _, tid=task.id, tname=task.name: self.archive_task(tid, tname),
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
            archive_btn = None
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

        header_controls: list[ft.Control] = [
            status_icon,
            title_text,
            tag_badge,
            score_or_status,
        ]
        if archive_btn is not None:
            header_controls.append(archive_btn)
        header_controls.append(action_btn)

        header_row = ft.Row(
            spacing=4,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=header_controls,
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
                ft.Container(
                    padding=ft.Padding(left=2, top=2, right=2, bottom=2),
                    content=ft.Row(
                        spacing=6,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                        controls=[
                            ft.Icon(ft.Icons.NOTES_ROUNDED, size=14, color=ft.Colors.CYAN_300 if not is_completed else ft.Colors.GREY_500),
                            ft.Text(
                                task.description,
                                size=12,
                                color=ft.Colors.GREY_300 if not is_completed else ft.Colors.GREY_500,
                                max_lines=2,
                                overflow=ft.TextOverflow.ELLIPSIS,
                                expand=True,
                            ),
                        ],
                    ),
                )
            )
        else:
            card_controls.append(
                ft.Container(
                    padding=ft.Padding(left=2, top=1, right=2, bottom=1),
                    content=ft.Row(
                        spacing=4,
                        controls=[
                            ft.Icon(ft.Icons.ADD_COMMENT_OUTLINED, size=12, color=ft.Colors.GREY_500),
                            ft.Text("Добавить описание...", size=11, color=ft.Colors.GREY_500),
                        ],
                    ),
                )
            )

        is_selected = (self.selected_task_id == task.id and self.right_panel_open)
        card_border = (
            ft.Border.all(1.5, ft.Colors.CYAN_400)
            if is_selected
            else None
        )

        card_container = ft.Container(
            key=f"task_card_container_{task.id}",
            padding=ft.Padding(left=12, top=8, right=10, bottom=8),
            border_radius=10,
            border=card_border,
            ink=True,
            opacity=0.78 if is_completed else 1.0,
            tooltip="Нажмите, чтобы открыть описание и параметры задачи",
            on_click=lambda _, t=task: self.open_right_panel(t),
            content=ft.Column(
                spacing=5,
                tight=True,
                controls=card_controls,
            ),
        )
        self._task_card_containers[task.id] = card_container

        return ft.Card(
            key=f"task_card_{task.id}",
            elevation=1 if is_completed else (3 if is_selected else 2),
            content=card_container,
        )

    # ──────────────────────────────────────────
    # Tab 0: Today's Tasks
    # ──────────────────────────────────────────
    def _build_completed_divider(self, completed_count: int, only_today: bool = True) -> ft.Control:
        """Build a horizontal divider separating uncompleted and completed tasks with an archive-all action."""
        title = f"Завершенные сегодня задачи ({completed_count})" if only_today else f"Завершенные задачи ({completed_count})"
        return ft.Container(
            padding=ft.Padding(left=0, top=14, right=0, bottom=6),
            content=ft.Column(
                spacing=8,
                controls=[
                    ft.Divider(height=2, thickness=2, color=ft.Colors.OUTLINE),
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Row(
                                spacing=6,
                                controls=[
                                    ft.Icon(ft.Icons.CHECK_CIRCLE_ROUNDED, size=16, color=ft.Colors.GREEN_400),
                                    ft.Text(
                                        title,
                                        size=12,
                                        weight=ft.FontWeight.BOLD,
                                        color=ft.Colors.GREY_400,
                                    ),
                                ],
                            ),
                            ft.TextButton(
                                "Все в архив",
                                icon=ft.Icons.ARCHIVE_ROUNDED,
                                tooltip="Отправить все завершенные задачи в архив",
                                on_click=lambda _: self.archive_all_completed(only_today=only_today),
                            ),
                        ],
                    ),
                ],
            ),
        )

    def load_today_tasks(self) -> tuple[int, int]:
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
            return 0, 0

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

        return len(active_tasks), len(completed_tasks)

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

        # 2. Time selector with presets and custom time input dialog
        TIME_PRESETS = [
            (15, "15 мин"),
            (25, "25 мин (Помодоро)"),
            (30, "30 мин"),
            (45, "45 мин"),
            (60, "60 мин (1 ч)"),
            (90, "90 мин (1.5 ч)"),
            (120, "120 мин (2 ч)"),
            (180, "180 мин (3 ч)"),
        ]

        def _open_custom_time_dialog() -> None:
            time_input = ft.TextField(
                label="Время (минуты)",
                value=str(self._last_expected_minutes or "60"),
                suffix=ft.Text("мин"),
                keyboard_type=ft.KeyboardType.NUMBER,
                input_filter=ft.NumbersOnlyInputFilter(),
                autofocus=True,
                dense=True,
                width=240,
                on_submit=lambda _: _save_custom_time(),
            )

            def _apply_chip(m: int) -> None:
                time_input.value = str(m)
                time_input.error_text = None
                self.page.update()

            chips = [
                ft.Chip(
                    label=ft.Text(f"{m} мин"),
                    on_click=lambda _, m=m: _apply_chip(m),
                )
                for m in [15, 20, 25, 35, 40, 50, 75, 100, 150]
            ]

            def _save_custom_time(e: ft.ControlEvent | None = None) -> None:
                raw = (time_input.value or "").strip()
                if not raw or not raw.isdigit() or int(raw) <= 0:
                    time_input.error_text = "Введите число минут (> 0)"
                    self.page.update()
                    return
                mins = int(raw)
                _close_dialog(self.page, custom_dialog)
                _set_time(mins)
                self._focus_control(self._quick_add_name_field)

            custom_dialog = ft.AlertDialog(
                modal=True,
                title=ft.Row(
                    [
                        ft.Icon(ft.Icons.ACCESS_TIME_ROUNDED, color=ft.Colors.PRIMARY, size=22),
                        ft.Text("Своё время на задачу", weight=ft.FontWeight.BOLD, size=16),
                    ],
                    spacing=8,
                ),
                content=ft.Column(
                    tight=True,
                    spacing=12,
                    controls=[
                        ft.Text("Укажите число минут или выберите быстрый вариант:", size=13, color=ft.Colors.OUTLINE),
                        time_input,
                        ft.Row(wrap=True, spacing=6, controls=chips),
                    ],
                ),
                actions=[
                    ft.TextButton("Отмена", on_click=lambda _: _close_dialog(self.page, custom_dialog)),
                    FilledBtn("Применить", icon=ft.Icons.CHECK_ROUNDED, on_click=_save_custom_time),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
            _show_dialog(self.page, custom_dialog)
            self._focus_control(time_input)

        def _build_time_items() -> list[ft.PopupMenuItem]:
            mins_val = int(self._last_expected_minutes or "60")
            preset_mins = [p[0] for p in TIME_PRESETS]

            items: list[ft.PopupMenuItem] = [
                ft.PopupMenuItem(
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.EDIT_ROUNDED, size=16, color=ft.Colors.PRIMARY),
                            ft.Text("Своё время...", size=13, weight=ft.FontWeight.W_500),
                        ],
                        spacing=8,
                    ),
                    on_click=lambda _: _open_custom_time_dialog(),
                ),
            ]

            if mins_val not in preset_mins:
                items.append(
                    ft.PopupMenuItem(
                        content=ft.Row(
                            [
                                ft.Icon(ft.Icons.CHECK_ROUNDED, size=15, color=ft.Colors.GREEN_400),
                                ft.Text(f"{mins_val} мин (выбрано)", size=13, weight=ft.FontWeight.BOLD),
                            ],
                            spacing=8,
                        ),
                        on_click=lambda _, m=mins_val: _set_time(m),
                    )
                )

            for m, label in TIME_PRESETS:
                is_selected = (m == mins_val)
                items.append(
                    ft.PopupMenuItem(
                        content=ft.Row(
                            [
                                ft.Icon(
                                    ft.Icons.CHECK_ROUNDED if is_selected else ft.Icons.ACCESS_TIME_ROUNDED,
                                    size=15,
                                    color=ft.Colors.GREEN_400 if is_selected else ft.Colors.OUTLINE,
                                ),
                                ft.Text(
                                    label,
                                    size=13,
                                    weight=ft.FontWeight.BOLD if is_selected else ft.FontWeight.NORMAL,
                                ),
                            ],
                            spacing=8,
                        ),
                        on_click=lambda _, m=m: _set_time(m),
                    )
                )
            return items

        def _set_time(mins: int) -> None:
            self._last_expected_minutes = str(mins)
            time_btn.tooltip = f"Время: {mins} мин (нажмите для выбора)"
            time_btn.items = _build_time_items()
            self.page.update()

        cur_mins = int(self._last_expected_minutes or "60")
        time_btn = ft.PopupMenuButton(
            content=ft.Container(
                content=ft.Icon(ft.Icons.ACCESS_TIME_ROUNDED, size=20, color=ft.Colors.PRIMARY),
                padding=ft.Padding(6, 6, 6, 6),
                border_radius=8,
                ink=True,
            ),
            tooltip=f"Время: {cur_mins} мин (нажмите для выбора)",
            items=_build_time_items(),
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

            # Time: check inline time in title (e.g. "Задача 45м", "Доклад 1.5ч", "~25m") or quick-add time selector
            inline_time_match = re.search(
                r"\s+(?:~|@)?(\d+(?:\.\d+)?)\s*(мин|минут|минуты|м|m|min|mins|minutes|ч|час|часа|часов|h|hr|hrs)\s*$",
                title,
                re.IGNORECASE,
            )
            time_val = 60.0
            if inline_time_match:
                parsed_num = float(inline_time_match.group(1))
                parsed_unit = inline_time_match.group(2).lower()
                clean_title = title[:inline_time_match.start()].strip()
                if clean_title:
                    title = clean_title
                    time_val = (parsed_num * 60.0) if any(u in parsed_unit for u in ["ч", "h"]) else parsed_num
                    mins_int = int(time_val) if time_val.is_integer() else round(time_val, 1)
                    self._last_expected_minutes = str(mins_int)
                    time_btn.tooltip = f"Время: {mins_int} мин (нажмите для выбора)"
                    time_btn.items = _build_time_items()
            elif self._last_expected_minutes:
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
                    pred = self.predictor.predict_time(subject_id, expected_hours)
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
        today_active, today_done = self.load_today_tasks()

        header_actions = ft.Row(
            spacing=6,
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
                ft.IconButton(
                    icon=ft.Icons.VIEW_SIDEBAR_ROUNDED,
                    tooltip="Панель описания задачи",
                    icon_color=ft.Colors.CYAN_300 if self.right_panel_open else ft.Colors.GREY_400,
                    on_click=lambda _: self.toggle_right_panel(),
                ),
                ft.IconButton(
                    icon=ft.Icons.SETTINGS_ROUNDED,
                    tooltip="Настройки",
                    icon_color=ft.Colors.GREY_400,
                    on_click=lambda _: self.open_settings_dialog(),
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
    def load_all_tasks(self) -> tuple[int, int]:
        """Fetch all tasks (including completed today) and populate column with batched rendering."""
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
            return 0, 0

        # 1. Add active uncompleted tasks (batched to reduce Flet control tree RAM)
        if active_tasks:
            display_active = active_tasks[:self.all_tasks_limit]
            for rank, scored in enumerate(display_active, 1):
                self.all_tasks_column.controls.append(self.build_task_card(scored, rank))

            if len(active_tasks) > self.all_tasks_limit:
                rem = len(active_tasks) - self.all_tasks_limit
                def _show_more_all(_):
                    self.all_tasks_limit += 40
                    self.load_all_tasks()
                    self.page.update()

                self.all_tasks_column.controls.append(
                    ft.Container(
                        alignment=ft.Alignment(0, 0),
                        padding=ft.Padding(0, 8, 0, 8),
                        content=ft.OutlinedButton(
                            f"Показать еще ({rem} активных задач)...",
                            icon=ft.Icons.EXPAND_MORE_ROUNDED,
                            on_click=_show_more_all,
                        ),
                    )
                )
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
            self.all_tasks_column.controls.append(self._build_completed_divider(len(completed_tasks), only_today=False))
            for scored in completed_tasks:
                self.all_tasks_column.controls.append(self.build_task_card(scored, 0))

        return len(active_tasks), len(completed_tasks)

    def _render_all_tasks_view(self) -> ft.Control:
        """Build the 'Все задачи' view."""
        all_active, all_done_today = self.load_all_tasks()

        header_actions = ft.Row(
            spacing=6,
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
                ft.IconButton(
                    icon=ft.Icons.VIEW_SIDEBAR_ROUNDED,
                    tooltip="Панель описания задачи",
                    icon_color=ft.Colors.CYAN_300 if self.right_panel_open else ft.Colors.GREY_400,
                    on_click=lambda _: self.toggle_right_panel(),
                ),
                ft.IconButton(
                    icon=ft.Icons.SETTINGS_ROUNDED,
                    tooltip="Настройки",
                    icon_color=ft.Colors.GREY_400,
                    on_click=lambda _: self.open_settings_dialog(),
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
            on_click=lambda _, t=tag: self.open_right_tag_panel(t),
        )

        delete_btn = ft.IconButton(
            icon=ft.Icons.DELETE_OUTLINE_ROUNDED,
            icon_size=18,
            tooltip="Удалить тег",
            icon_color=ft.Colors.RED_400,
            on_click=lambda _, t=tag, cnt=task_count: self.confirm_delete_tag(t, cnt),
        )

        is_selected = (self.selected_tag_id == tag.id and self.right_panel_open and self.right_panel_mode == "tag")
        card_border = (
            ft.Border.all(1.5, ft.Colors.CYAN_400)
            if is_selected
            else None
        )

        tag_card_container = ft.Container(
            key=f"tag_card_container_{tag.id}",
            padding=ft.Padding(left=10, top=6, right=8, bottom=6),
            border_radius=10,
            border=card_border,
            ink=True,
            tooltip="Нажмите, чтобы открыть и редактировать параметры тега",
            on_click=lambda _, t=tag: self.open_right_tag_panel(t),
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
        )
        self._tag_card_containers[tag.id] = tag_card_container

        return ft.Card(
            key=f"tag_card_{tag.id}",
            elevation=1 if not is_selected else 2,
            content=tag_card_container,
        )

    def load_tags(self) -> None:
        """Fetch all tags/subjects and populate the tags column."""
        self.tags_column.controls.clear()
        tags = self.task_manager.get_all_subjects()
        task_counts = self.task_manager.get_task_counts_by_subject()

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

    def _build_quick_add_tag_bar(self) -> ft.Control:
        """Build an inline quick-add bar for tags in the same compact icon-based design."""
        selected_icon = [self._last_tag_icon or "🏷️"]
        selected_color = [self._last_tag_color or "#4CAF50"]

        # 1. Icon selector
        icon_display = ft.Text(selected_icon[0], size=18)

        def _set_icon(ico: str) -> None:
            selected_icon[0] = ico
            self._last_tag_icon = ico
            icon_display.value = ico
            icon_btn.tooltip = f"Иконка: {ico} (нажмите для выбора)"
            self.page.update()

        icon_btn = ft.PopupMenuButton(
            content=ft.Container(
                content=icon_display,
                padding=ft.Padding(6, 6, 6, 6),
                border_radius=8,
                ink=True,
            ),
            tooltip=f"Иконка: {selected_icon[0]} (нажмите для выбора)",
            items=[
                ft.PopupMenuItem(
                    content=ft.Row([ft.Text(ico, size=18), ft.Text(f" {ico}", size=13)], spacing=6),
                    on_click=lambda _, ico=ico: _set_icon(ico),
                )
                for ico in self.TAG_PRESET_ICONS
            ],
        )

        # 2. Color selector
        color_circle = ft.Container(
            width=20,
            height=20,
            border_radius=10,
            bgcolor=selected_color[0],
            border=ft.Border.all(1.5, ft.Colors.WHITE),
        )

        def _set_color(hex_col: str, name_col: str) -> None:
            selected_color[0] = hex_col
            self._last_tag_color = hex_col
            color_circle.bgcolor = hex_col
            color_btn.tooltip = f"Цвет: {name_col} (нажмите для выбора)"
            self.page.update()

        init_col_name = next((name for h, name in self.TAG_PRESET_COLORS if h == selected_color[0]), "Зеленый")
        color_btn = ft.PopupMenuButton(
            content=ft.Container(
                content=color_circle,
                padding=ft.Padding(6, 6, 6, 6),
                border_radius=8,
                ink=True,
            ),
            tooltip=f"Цвет: {init_col_name} (нажмите для выбора)",
            items=[
                ft.PopupMenuItem(
                    content=ft.Row(
                        [
                            ft.Container(width=16, height=16, border_radius=8, bgcolor=h),
                            ft.Text(f" {name}", size=13),
                        ],
                        spacing=8,
                    ),
                    on_click=lambda _, h=h, name=name: _set_color(h, name),
                )
                for h, name in self.TAG_PRESET_COLORS
            ],
        )

        # 3. Name field
        name_field = ft.TextField(
            hint_text="Новый тег / предмет... (Enter для сохранения)",
            prefix_icon=ft.Icons.LOCAL_OFFER_ROUNDED,
            dense=True,
            text_size=13,
            expand=True,
            autofocus=False,
            tooltip="Название нового тега (нажмите Enter для сохранения)",
            on_submit=lambda _: _submit(),
        )
        self._quick_add_tag_name_field = name_field

        # 4. Add button
        add_btn = ft.IconButton(
            icon=ft.Icons.ADD_ROUNDED,
            bgcolor=ft.Colors.PRIMARY,
            icon_color=ft.Colors.WHITE,
            icon_size=20,
            tooltip="Создать тег (Enter)",
            on_click=lambda _: _submit(),
        )

        def _submit(e: ft.ControlEvent | None = None) -> None:
            title = (name_field.value or "").strip()
            if not title:
                name_field.error_text = "Введите название тега"
                self.page.update()
                return

            name_field.error_text = None
            try:
                self.task_manager.add_subject(
                    name=title,
                    color=selected_color[0],
                    icon=selected_icon[0],
                )
                _show_snack(self.page, f"Тег «{title}» успешно создан!")
                name_field.value = ""
                self.refresh()
                self._focus_control(self._quick_add_tag_name_field)
            except Exception as err:
                _show_snack(self.page, f"Ошибка при создании тега: {err}", bgcolor=ft.Colors.RED_800)

        row_layout = ft.Row(
            spacing=4,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                name_field,
                icon_btn,
                color_btn,
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

    def _render_tags_view(self) -> ft.Control:
        """Build the full 'Теги и предметы' screen view."""
        self.load_tags()

        header_actions = ft.Row(
            spacing=6,
            controls=[
                ft.IconButton(
                    icon=ft.Icons.VIEW_SIDEBAR_ROUNDED,
                    tooltip="Панель параметров тега",
                    icon_color=ft.Colors.CYAN_300 if (self.right_panel_open and self.right_panel_mode == "tag") else ft.Colors.GREY_400,
                    on_click=lambda _: self.toggle_right_panel(),
                ),
                ft.IconButton(
                    icon=ft.Icons.SETTINGS_ROUNDED,
                    tooltip="Настройки",
                    icon_color=ft.Colors.GREY_400,
                    on_click=lambda _: self.open_settings_dialog(),
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
                            "Управление тегами: добавляйте в строку, редактируйте параметры и цвета",
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
                self._build_quick_add_tag_bar(),
                ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                self.tags_column,
            ],
        )

    # ──────────────────────────────────────────
    # Tab 3: Archive View
    # ──────────────────────────────────────────
    def build_archived_task_card(self, task: Task) -> ft.Card:
        """Render a single archived task card with unarchive, restore, and delete actions."""
        subject = task.subject
        tag_name = subject.name if subject else "Без предмета"
        tag_icon = subject.icon if subject else "🏷️"
        tag_color = subject.color if subject else "#607D8B"

        priority_label, priority_color, _ = self._get_priority_details(task.priority)
        time_str = self._format_time(task.expected_time)

        # Completed date string
        completed_str = task.completed_at.strftime("%d.%m.%Y") if task.completed_at else "Ранее"

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

        status_icon = ft.Icon(
            ft.Icons.INVENTORY_2_ROUNDED,
            color=ft.Colors.CYAN_300,
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

        status_badge = ft.Container(
            content=ft.Text("В архиве", size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.CYAN_300),
            bgcolor=ft.Colors.with_opacity(0.16, ft.Colors.CYAN_400),
            padding=ft.Padding(left=6, top=2, right=6, bottom=2),
            border_radius=6,
        )

        # Unarchive (return from archive back to completed list)
        unarchive_btn = ft.IconButton(
            icon=ft.Icons.UNARCHIVE_ROUNDED,
            icon_size=18,
            tooltip="Вернуть из архива",
            icon_color=ft.Colors.CYAN_300,
            on_click=lambda _, tid=task.id, tname=task.name: self.unarchive_task(tid, tname),
        )

        # Reopen (return to active work)
        restore_btn = ft.IconButton(
            icon=ft.Icons.RESTORE_ROUNDED,
            icon_size=18,
            tooltip="Вернуть в работу (активные задачи)",
            icon_color=ft.Colors.GREEN_400,
            on_click=lambda _, tid=task.id, tname=task.name: self.reopen_archived_task(tid, tname),
        )

        # Delete permanently
        delete_btn = ft.IconButton(
            icon=ft.Icons.DELETE_OUTLINE_ROUNDED,
            icon_size=18,
            tooltip="Удалить навсегда",
            icon_color=ft.Colors.RED_400,
            on_click=lambda _, tid=task.id, tname=task.name: self.confirm_delete_archived_task(tid, tname),
        )

        header_row = ft.Row(
            spacing=4,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                status_icon,
                title_text,
                tag_badge,
                status_badge,
                unarchive_btn,
                restore_btn,
                delete_btn,
            ],
        )

        metadata_chips = [
            ft.Container(
                content=ft.Row(
                    spacing=4,
                    tight=True,
                    controls=[
                        ft.Icon(ft.Icons.EVENT_AVAILABLE_ROUNDED, size=13, color=ft.Colors.GREEN_400),
                        ft.Text(f"Завершено: {completed_str}", size=12, color=ft.Colors.GREEN_300, weight=ft.FontWeight.W_500),
                    ],
                ),
                bgcolor=ft.Colors.with_opacity(0.10, ft.Colors.GREEN_400),
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
                        ft.Icon(ft.Icons.FLAG_ROUNDED, size=13, color=ft.Colors.GREY_500),
                        ft.Text(priority_label, size=12, color=ft.Colors.GREY_500, weight=ft.FontWeight.W_500),
                    ],
                ),
                bgcolor=ft.Colors.with_opacity(0.08, priority_color),
                padding=ft.Padding(left=6, top=2, right=6, bottom=2),
                border_radius=6,
            ),
        ]

        meta_row = ft.Row(
            spacing=6,
            run_spacing=4,
            wrap=True,
            controls=metadata_chips,
        )

        card_controls: list[ft.Control] = [header_row, meta_row]
        if task.description:
            card_controls.append(
                ft.Container(
                    padding=ft.Padding(left=2, top=2, right=2, bottom=2),
                    content=ft.Row(
                        spacing=6,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                        controls=[
                            ft.Icon(ft.Icons.NOTES_ROUNDED, size=14, color=ft.Colors.GREY_500),
                            ft.Text(
                                task.description,
                                size=12,
                                color=ft.Colors.GREY_500,
                                max_lines=2,
                                overflow=ft.TextOverflow.ELLIPSIS,
                                expand=True,
                            ),
                        ],
                    ),
                )
            )

        is_selected = (self.selected_task_id == task.id and self.right_panel_open)
        card_border = (
            ft.Border.all(1.5, ft.Colors.CYAN_400)
            if is_selected
            else None
        )

        card_container = ft.Container(
            key=f"archive_card_container_{task.id}",
            padding=ft.Padding(left=12, top=8, right=10, bottom=8),
            border_radius=10,
            border=card_border,
            ink=True,
            opacity=0.88,
            tooltip="Нажмите, чтобы открыть описание и параметры задачи",
            on_click=lambda _, t=task: self.open_right_panel(t),
            content=ft.Column(
                spacing=5,
                tight=True,
                controls=card_controls,
            ),
        )
        self._task_card_containers[task.id] = card_container

        return ft.Card(
            key=f"archive_card_{task.id}",
            elevation=1 if not is_selected else 2,
            content=card_container,
        )

    def load_archived_tasks(self) -> int:
        """Fetch all archived tasks and populate the archive column with batched rendering."""
        self.archive_column.controls.clear()
        archived = self.task_manager.get_archived_tasks()

        if not archived:
            self.archive_column.controls.append(
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
                                    ft.Icons.INVENTORY_2_OUTLINED,
                                    size=48,
                                    color=ft.Colors.CYAN_300,
                                ),
                                ft.Text(
                                    "Архив пуст",
                                    size=18,
                                    weight=ft.FontWeight.BOLD,
                                ),
                                ft.Text(
                                    "Выполненные задачи можно отправлять в архив кнопкой 📦 на карточке задачи или «Все в архив».",
                                    size=14,
                                    color=ft.Colors.GREY_400,
                                    text_align=ft.TextAlign.CENTER,
                                ),
                            ],
                        ),
                    ),
                )
            )
            return 0

        total_archived = len(archived)
        display_archived = archived[:self.archive_tasks_limit]
        for task in display_archived:
            self.archive_column.controls.append(self.build_archived_task_card(task))

        if total_archived > self.archive_tasks_limit:
            rem = total_archived - self.archive_tasks_limit
            def _show_more_archived(_):
                self.archive_tasks_limit += 40
                self.load_archived_tasks()
                self.page.update()

            self.archive_column.controls.append(
                ft.Container(
                    alignment=ft.Alignment(0, 0),
                    padding=ft.Padding(0, 8, 0, 8),
                    content=ft.OutlinedButton(
                        f"Показать еще ({rem} задач в архиве)...",
                        icon=ft.Icons.EXPAND_MORE_ROUNDED,
                        on_click=_show_more_archived,
                    ),
                )
            )

        return total_archived

    def _render_archive_view(self) -> ft.Control:
        """Build the 'Архив задач' view."""
        archived_count = self.load_archived_tasks()

        header_actions = []
        if archived_count > 0:
            header_actions.append(
                ft.OutlinedButton(
                    "Очистить архив",
                    icon=ft.Icons.DELETE_SWEEP_ROUNDED,
                    style=ft.ButtonStyle(
                        color=ft.Colors.RED_400,
                    ) if hasattr(ft, "ButtonStyle") else None,
                    on_click=lambda _: self.confirm_clear_archive(),
                )
            )
        header_actions.append(
            ft.IconButton(
                icon=ft.Icons.VIEW_SIDEBAR_ROUNDED,
                tooltip="Панель описания задачи",
                icon_color=ft.Colors.CYAN_300 if self.right_panel_open else ft.Colors.GREY_400,
                on_click=lambda _: self.toggle_right_panel(),
            )
        )
        header_actions.append(
            ft.IconButton(
                icon=ft.Icons.SETTINGS_ROUNDED,
                tooltip="Настройки",
                icon_color=ft.Colors.GREY_400,
                on_click=lambda _: self.open_settings_dialog(),
            )
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
                                    ft.Icons.INVENTORY_2_ROUNDED,
                                    color=ft.Colors.CYAN_300,
                                    size=26,
                                ),
                                ft.Text(
                                    "Архив задач",
                                    size=22,
                                    weight=ft.FontWeight.BOLD,
                                ),
                            ],
                            spacing=10,
                        ),
                        ft.Text(
                            f"Завершенные задачи, отправленные на долгосрочное хранение ({archived_count})",
                            size=13,
                            color=ft.Colors.GREY_400,
                        ),
                    ],
                ),
                ft.Row(spacing=8, wrap=True, controls=header_actions),
            ],
        )

        return ft.Column(
            spacing=16,
            expand=True,
            controls=[
                header,
                ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                self.archive_column,
            ],
        )

    # ──────────────────────────────────────────
    # Right Overlay Panel (Task Description & Details)
    # ──────────────────────────────────────────
    def _build_right_panel_container(self) -> ft.Container:
        """Create the semi-transparent overlay right panel container with blur effect."""
        return ft.Container(
            right=0,
            top=0,
            bottom=0,
            width=self.right_panel_width,
            visible=False,
            opacity=0.0,
            animate_opacity=250,
            bgcolor=ft.Colors.with_opacity(0.70, "#161822"),
            blur=ft.Blur(20, 20, ft.BlurTileMode.CLAMP),
            border=ft.Border(
                left=ft.BorderSide(1.5, ft.Colors.with_opacity(0.35, ft.Colors.OUTLINE)),
            ),
            shadow=ft.BoxShadow(
                spread_radius=2,
                blur_radius=28,
                color=ft.Colors.with_opacity(0.6, ft.Colors.BLACK),
                offset=ft.Offset(-6, 0),
            ),
            border_radius=ft.BorderRadius(top_left=16, bottom_left=16, top_right=0, bottom_right=0),
            padding=ft.Padding(left=18, top=16, right=18, bottom=16),
            content=ft.Column(scroll=ft.ScrollMode.AUTO, expand=True, spacing=14),
            on_click=lambda _: None,  # Absorb clicks inside panel so they do not hit the barrier
        )

    def _build_right_panel_barrier(self) -> ft.Container:
        """Create the clickable semi-transparent backdrop barrier that closes the panel on click."""
        return ft.Container(
            left=0,
            top=0,
            right=0,
            bottom=0,
            visible=False,
            opacity=0.0,
            animate_opacity=250,
            bgcolor=ft.Colors.with_opacity(0.35, ft.Colors.BLACK),
            blur=ft.Blur(4, 4, ft.BlurTileMode.CLAMP),
            on_click=lambda _: self.close_right_panel(),
        )

    def _setup_keyboard_shortcuts(self) -> None:
        """Register global keyboard shortcuts, e.g. Esc to dismiss overlay drawer."""
        prev_handler = getattr(self.page, "on_keyboard_event", None)

        def _on_keyboard(e: ft.KeyboardEvent) -> None:
            if prev_handler and callable(prev_handler):
                try:
                    prev_handler(e)
                except Exception:
                    pass
            # Dismiss right overlay panel on Escape key
            if getattr(e, "key", "") in ("Escape", "Esc"):
                dialog = getattr(self.page, "dialog", None)
                if dialog and getattr(dialog, "open", False):
                    return
                if self.right_panel_open:
                    self.close_right_panel()

        self.page.on_keyboard_event = _on_keyboard

    def _render_right_panel_content(self, task: Task | None = None) -> None:
        """Populate the right overlay panel with editable description and properties."""
        col = self.right_panel_container.content
        if not isinstance(col, ft.Column):
            col = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True, spacing=14)
            self.right_panel_container.content = col
        col.controls.clear()

        if task is None and self.selected_task_id:
            task = self.task_manager.get_task_by_id(self.selected_task_id)

        if task is None:
            col.controls.extend([
                ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    controls=[
                        ft.Text("Описание задачи", size=16, weight=ft.FontWeight.BOLD),
                        ft.IconButton(
                            icon=ft.Icons.CLOSE_ROUNDED,
                            tooltip="Закрыть панель",
                            icon_size=20,
                            on_click=lambda _: self.close_right_panel(),
                        ),
                    ],
                ),
                ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                ft.Container(
                    padding=40,
                    alignment=ft.Alignment(0, 0),
                    content=ft.Column(
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=12,
                        controls=[
                            ft.Icon(ft.Icons.TOUCH_APP_ROUNDED, size=40, color=ft.Colors.GREY_500),
                            ft.Text("Задача не выбрана", size=15, weight=ft.FontWeight.BOLD),
                            ft.Text(
                                "Нажмите на любую задачу в списке, чтобы открыть и редактировать её описание.",
                                size=13,
                                color=ft.Colors.GREY_400,
                                text_align=ft.TextAlign.CENTER,
                            ),
                        ],
                    ),
                ),
            ])
            return

        # ── Header ──────────────────────────────────────
        header = ft.Row(
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            controls=[
                ft.Row(
                    spacing=8,
                    controls=[
                        ft.Icon(ft.Icons.DESCRIPTION_ROUNDED, color=ft.Colors.PRIMARY, size=22),
                        ft.Text("Карточка задачи", size=16, weight=ft.FontWeight.BOLD),
                    ],
                ),
                ft.Row(
                    spacing=0,
                    controls=[
                        ft.IconButton(
                            icon=ft.Icons.OPEN_IN_NEW_ROUNDED,
                            tooltip="Открыть в модальном окне",
                            icon_size=18,
                            icon_color=ft.Colors.GREY_400,
                            on_click=lambda _, t=task: self.open_edit_dialog(t),
                        ),
                        ft.IconButton(
                            icon=ft.Icons.CLOSE_ROUNDED,
                            tooltip="Закрыть панель (Esc)",
                            icon_size=20,
                            icon_color=ft.Colors.GREY_300,
                            on_click=lambda _: self.close_right_panel(),
                        ),
                    ],
                ),
            ],
        )

        # ── Title field ─────────────────────────────────
        title_field = ft.TextField(
            label="Название задачи",
            value=task.name,
            dense=True,
            text_size=13,
        )

        # ── Description field (editable multiline) ───────
        desc_field = ft.TextField(
            label="Описание и заметки",
            value=task.description or "",
            multiline=True,
            min_lines=6,
            max_lines=14,
            hint_text="Добавьте подробное описание задачи, ссылки, подпункты или заметки...",
            text_size=13,
            dense=True,
        )

        # ── Tag selector ─────────────────────────────────
        subjects = self.task_manager.get_all_subjects()
        subject_options = [
            ft.dropdown.Option(key=str(s.id), text=f"{s.icon or '🏷️'} {s.name}")
            for s in subjects
        ]
        subj_dropdown = ft.Dropdown(
            label="Тег / Предмет",
            options=subject_options,
            value=str(task.subject_id),
            dense=True,
            text_size=13,
        )

        # ── Priority selector ────────────────────────────
        priority_dropdown = ft.Dropdown(
            label="Сложность / Приоритет",
            options=[
                ft.dropdown.Option(key=TaskPriority.LOW.value, text="🟢 Низкий"),
                ft.dropdown.Option(key=TaskPriority.MEDIUM.value, text="🟡 Средний"),
                ft.dropdown.Option(key=TaskPriority.HIGH.value, text="🟠 Высокий"),
                ft.dropdown.Option(key=TaskPriority.CRITICAL.value, text="🔴 Критический"),
            ],
            value=task.priority.value,
            dense=True,
            text_size=13,
        )

        # ── Expected Time ────────────────────────────────
        cur_mins = round(task.expected_time * 60) if task.expected_time else 60
        time_field = ft.TextField(
            label="Ожидаемое время",
            value=str(cur_mins),
            suffix=ft.Text("мин"),
            keyboard_type=ft.KeyboardType.NUMBER,
            input_filter=ft.NumbersOnlyInputFilter(),
            dense=True,
            text_size=13,
        )

        # ── Scheduled Date Button ────────────────────────
        sched_state = {"date": task.scheduled_date}
        sched_dp = ft.DatePicker(
            first_date=datetime(2020, 1, 1),
            last_date=datetime(2035, 12, 31),
            value=datetime.combine(task.scheduled_date, datetime.min.time()) if task.scheduled_date else datetime.now(),
        )

        def _on_sched_picked(e: ft.ControlEvent) -> None:
            if sched_dp.value:
                d = sched_dp.value.date() if hasattr(sched_dp.value, "date") else sched_dp.value
                sched_state["date"] = d
                sched_str = "Сегодня" if d == date.today() else d.strftime("%d.%m.%Y")
                sched_btn.content = f"План: {sched_str}"
                self.page.update()

        sched_dp.on_change = _on_sched_picked

        def _open_sched_dp(_) -> None:
            if hasattr(self.page, "show_dialog"):
                self.page.show_dialog(sched_dp)
            elif hasattr(self.page, "open"):
                self.page.open(sched_dp)
            else:
                if sched_dp not in self.page.overlay:
                    self.page.overlay.append(sched_dp)
                sched_dp.open = True
                self.page.update()

        cur_sched_text = (
            "Сегодня" if task.scheduled_date == date.today()
            else (task.scheduled_date.strftime("%d.%m.%Y") if task.scheduled_date else "Не запланировано")
        )
        sched_btn = ft.OutlinedButton(
            f"План: {cur_sched_text}",
            icon=ft.Icons.CALENDAR_MONTH_ROUNDED,
            on_click=_open_sched_dp,
        )

        # ── AI info ──────────────────────────────────────
        ai_chip = None
        if task.expected_time is not None:
            try:
                pred = self.predictor.predict_time(task.subject_id, task.expected_time)
                if not pred.cold_start:
                    ai_mins = round(pred.predicted_time * 60, 1)
                    ai_chip = ft.Container(
                        padding=ft.Padding(8, 6, 8, 6),
                        border_radius=8,
                        bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.AMBER_400),
                        content=ft.Row(
                            spacing=6,
                            controls=[
                                ft.Icon(ft.Icons.AUTO_AWESOME_ROUNDED, size=15, color=ft.Colors.AMBER_400),
                                ft.Text(f"ИИ прогноз: ~{int(ai_mins) if ai_mins.is_integer() else ai_mins} мин", size=12, color=ft.Colors.AMBER_300),
                            ],
                        ),
                    )
            except Exception:
                pass

        # ── Save callback ─────────────────────────────────
        def _save_changes(e: ft.ControlEvent | None = None) -> None:
            name_val = (title_field.value or "").strip()
            if not name_val:
                title_field.error_text = "Название не может быть пустым"
                self.page.update()
                return
            title_field.error_text = None

            try:
                s_id = int(subj_dropdown.value) if (subj_dropdown.value and subj_dropdown.value != "None") else task.subject_id
            except (ValueError, TypeError):
                s_id = task.subject_id

            try:
                p_val = TaskPriority(priority_dropdown.value) if priority_dropdown.value else task.priority
            except (ValueError, TypeError):
                p_val = task.priority
            try:
                t_mins = float(time_field.value or "60")
                exp_h = round(t_mins / 60.0, 4)
            except ValueError:
                exp_h = task.expected_time

            updated_task = self.task_manager.update_task(
                task_id=task.id,
                name=name_val,
                subject_id=s_id,
                description=desc_field.value,
                priority=p_val,
                expected_time=exp_h,
                scheduled_date=sched_state["date"],
            )
            _show_snack(self.page, f"Описание и данные задачи «{name_val}» сохранены!", bgcolor=ft.Colors.GREEN_800)
            self.refresh()
            self._render_right_panel_content(updated_task)
            self._scroll_to_task(task.id)
            self.page.update()

        # ── Action buttons row ────────────────────────────
        save_btn = FilledBtn(
            "Сохранить описание",
            icon=ft.Icons.SAVE_ROUNDED,
            on_click=_save_changes,
        )

        status_btn = None
        if task.status != TaskStatus.COMPLETED:
            status_btn = ft.OutlinedButton(
                "Завершить",
                icon=ft.Icons.CHECK_CIRCLE_OUTLINE_ROUNDED,
                style=ft.ButtonStyle(color=ft.Colors.GREEN_400) if hasattr(ft, "ButtonStyle") else None,
                on_click=lambda _, tid=task.id, tname=task.name, et=task.expected_time: self.open_complete_dialog(tid, tname, et),
            )
        else:
            status_btn = ft.OutlinedButton(
                "В архив",
                icon=ft.Icons.ARCHIVE_ROUNDED,
                style=ft.ButtonStyle(color=ft.Colors.CYAN_300) if hasattr(ft, "ButtonStyle") else None,
                on_click=lambda _, tid=task.id, tname=task.name: self.archive_task(tid, tname),
            )

        delete_btn = ft.IconButton(
            icon=ft.Icons.DELETE_OUTLINE_ROUNDED,
            icon_color=ft.Colors.RED_400,
            tooltip="Удалить задачу",
            on_click=lambda _, tid=task.id, tname=task.name: self.confirm_delete_archived_task(tid, tname),
        )

        actions_row = ft.Row(
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            controls=[
                save_btn,
                ft.Row(spacing=4, controls=[status_btn, delete_btn] if status_btn else [delete_btn]),
            ],
        )

        col_controls: list[ft.Control] = [
            header,
            ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
            title_field,
            desc_field,
            ft.Text("Свойства задачи", size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.GREY_400),
            subj_dropdown,
            priority_dropdown,
            time_field,
            sched_btn,
        ]
        if ai_chip:
            col_controls.append(ai_chip)
        col_controls.extend([
            ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
            actions_row,
        ])

        col.controls = col_controls

    def _render_right_tag_panel_content(self, tag: Subject | None = None) -> None:
        """Populate the right overlay panel with editable tag properties and live preview."""
        col = self.right_panel_container.content
        if not isinstance(col, ft.Column):
            col = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True, spacing=14)
            self.right_panel_container.content = col
        col.controls.clear()

        if tag is None and self.selected_tag_id:
            tag = self.task_manager.get_subject_by_id(self.selected_tag_id)

        if tag is None:
            col.controls.extend([
                ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    controls=[
                        ft.Text("Параметры тега", size=16, weight=ft.FontWeight.BOLD),
                        ft.IconButton(
                            icon=ft.Icons.CLOSE_ROUNDED,
                            tooltip="Закрыть панель",
                            icon_size=20,
                            on_click=lambda _: self.close_right_panel(),
                        ),
                    ],
                ),
                ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                ft.Container(
                    padding=40,
                    alignment=ft.Alignment(0, 0),
                    content=ft.Column(
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=12,
                        controls=[
                            ft.Icon(ft.Icons.LOCAL_OFFER_OUTLINED, size=40, color=ft.Colors.GREY_500),
                            ft.Text("Тег не выбран", size=15, weight=ft.FontWeight.BOLD),
                            ft.Text(
                                "Нажмите на любой тег в списке, чтобы открыть и редактировать его параметры.",
                                size=13,
                                color=ft.Colors.GREY_400,
                                text_align=ft.TextAlign.CENTER,
                            ),
                        ],
                    ),
                ),
            ])
            return

        cur_color = [tag.color or "#4CAF50"]
        cur_icon = [tag.icon or "🏷️"]

        # ── Header ──────────────────────────────────────
        header = ft.Row(
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            controls=[
                ft.Row(
                    spacing=8,
                    controls=[
                        ft.Icon(ft.Icons.LOCAL_OFFER_ROUNDED, color=ft.Colors.PRIMARY, size=22),
                        ft.Text("Карточка тега", size=16, weight=ft.FontWeight.BOLD),
                    ],
                ),
                ft.Row(
                    spacing=0,
                    controls=[
                        ft.IconButton(
                            icon=ft.Icons.OPEN_IN_NEW_ROUNDED,
                            tooltip="Открыть в модальном окне",
                            icon_size=18,
                            icon_color=ft.Colors.GREY_400,
                            on_click=lambda _, t=tag: self.open_edit_tag_dialog(t),
                        ),
                        ft.IconButton(
                            icon=ft.Icons.CLOSE_ROUNDED,
                            tooltip="Закрыть панель (Esc)",
                            icon_size=20,
                            icon_color=ft.Colors.GREY_300,
                            on_click=lambda _: self.close_right_panel(),
                        ),
                    ],
                ),
            ],
        )

        # ── Live Preview Badge ───────────────────────────
        preview_icon = ft.Text(cur_icon[0], size=16)
        preview_name = ft.Text(tag.name, size=13, weight=ft.FontWeight.W_600, color=cur_color[0])
        preview_box = ft.Container(
            padding=ft.Padding(left=10, top=5, right=10, bottom=5),
            border_radius=8,
            border=ft.Border.all(1, cur_color[0]),
            bgcolor=ft.Colors.with_opacity(0.15, cur_color[0]),
            content=ft.Row([preview_icon, preview_name], spacing=6, tight=True),
        )

        preview_card = ft.Container(
            padding=10,
            border_radius=10,
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            content=ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                controls=[
                    ft.Text("Предпросмотр тега:", size=12, color=ft.Colors.GREY_400),
                    preview_box,
                ],
            ),
        )

        # ── Name Field ──────────────────────────────────
        name_field = ft.TextField(
            label="Название тега / предмета",
            value=tag.name,
            dense=True,
            text_size=13,
        )

        def _update_preview() -> None:
            preview_name.value = name_field.value or "Без названия"
            preview_name.color = cur_color[0]
            preview_icon.value = cur_icon[0]
            preview_box.border = ft.Border.all(1, cur_color[0])
            preview_box.bgcolor = ft.Colors.with_opacity(0.15, cur_color[0])
            self.page.update()

        name_field.on_change = lambda _: _update_preview()

        # ── Color Palette ────────────────────────────────
        color_containers: list[ft.Container] = []

        def _select_color(col_hex: str) -> None:
            cur_color[0] = col_hex
            for cc, (h, _) in zip(color_containers, self.TAG_PRESET_COLORS):
                is_sel = (h == col_hex)
                cc.border = ft.Border.all(2.5, ft.Colors.WHITE if is_sel else ft.Colors.TRANSPARENT)
            _update_preview()

        for h, name in self.TAG_PRESET_COLORS:
            is_sel = (h == cur_color[0])
            c_box = ft.Container(
                width=28,
                height=28,
                border_radius=14,
                bgcolor=h,
                border=ft.Border.all(2.5, ft.Colors.WHITE if is_sel else ft.Colors.TRANSPARENT),
                ink=True,
                tooltip=name,
                on_click=lambda _, h=h: _select_color(h),
            )
            color_containers.append(c_box)

        colors_wrap = ft.Row(
            wrap=True,
            spacing=8,
            run_spacing=8,
            controls=color_containers,
        )

        # ── Emoji / Icon Palette ─────────────────────────
        icon_containers: list[ft.Container] = []

        def _select_icon(ico: str) -> None:
            cur_icon[0] = ico
            for ic_box, ic in zip(icon_containers, self.TAG_PRESET_ICONS):
                is_sel = (ic == ico)
                ic_box.bgcolor = ft.Colors.with_opacity(0.25, ft.Colors.PRIMARY) if is_sel else ft.Colors.TRANSPARENT
                ic_box.border = ft.Border.all(1.5, ft.Colors.PRIMARY if is_sel else ft.Colors.with_opacity(0.2, ft.Colors.OUTLINE))
            _update_preview()

        for ico in self.TAG_PRESET_ICONS:
            is_sel = (ico == cur_icon[0])
            i_box = ft.Container(
                width=34,
                height=34,
                border_radius=8,
                alignment=ft.Alignment(0, 0),
                bgcolor=ft.Colors.with_opacity(0.25, ft.Colors.PRIMARY) if is_sel else ft.Colors.TRANSPARENT,
                border=ft.Border.all(1.5, ft.Colors.PRIMARY if is_sel else ft.Colors.with_opacity(0.2, ft.Colors.OUTLINE)),
                ink=True,
                tooltip=ico,
                on_click=lambda _, ico=ico: _select_icon(ico),
                content=ft.Text(ico, size=18),
            )
            icon_containers.append(i_box)

        icons_wrap = ft.Row(
            wrap=True,
            spacing=6,
            run_spacing=6,
            controls=icon_containers,
        )

        # ── Tasks with this tag ──────────────────────────
        task_count = self.task_manager.get_task_count_by_subject(tag.id)
        all_tasks = self.task_manager.get_tasks_by_subject(tag.id, limit=5)

        tasks_summary = ft.Container(
            padding=10,
            border_radius=10,
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            content=ft.Column(
                spacing=6,
                controls=[
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Text("Привязанные задачи:", size=12, color=ft.Colors.GREY_400),
                            ft.Text(f"{task_count} шт.", size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.CYAN_300),
                        ],
                    ),
                ] + ([
                    ft.Text(f"• {t.name}", size=11, color=ft.Colors.GREY_300, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
                    for t in all_tasks
                ] if all_tasks else [ft.Text("Нет привязанных задач", size=11, color=ft.Colors.GREY_500)]),
            ),
        )

        # ── Save callback ─────────────────────────────────
        def _save_tag(e: ft.ControlEvent | None = None) -> None:
            name_val = (name_field.value or "").strip()
            if not name_val:
                name_field.error_text = "Введите название тега"
                self.page.update()
                return

            name_field.error_text = None
            try:
                updated_tag = self.task_manager.update_subject(
                    subject_id=tag.id,
                    name=name_val,
                    color=cur_color[0],
                    icon=cur_icon[0],
                )
                _show_snack(self.page, f"Тег «{name_val}» успешно обновлен!", bgcolor=ft.Colors.GREEN_800)
                self.refresh()
                self._render_right_tag_panel_content(updated_tag)
                self._scroll_to_tag(tag.id)
                self.page.update()
            except Exception as err:
                _show_snack(self.page, f"Ошибка при обновлении тега: {err}", bgcolor=ft.Colors.RED_800)

        save_btn = FilledBtn(
            "Сохранить изменения",
            icon=ft.Icons.SAVE_ROUNDED,
            on_click=_save_tag,
        )

        delete_btn = ft.IconButton(
            icon=ft.Icons.DELETE_OUTLINE_ROUNDED,
            icon_color=ft.Colors.RED_400,
            tooltip="Удалить тег",
            on_click=lambda _, t=tag, cnt=task_count: self.confirm_delete_tag(t, cnt),
        )

        actions_row = ft.Row(
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            controls=[
                save_btn,
                delete_btn,
            ],
        )

        col.controls = [
            header,
            ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
            preview_card,
            name_field,
            ft.Text("Цвет тега", size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.GREY_400),
            colors_wrap,
            ft.Text("Иконка / Эмодзи", size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.GREY_400),
            icons_wrap,
            tasks_summary,
            ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
            actions_row,
        ]

    def _scroll_to_task(self, task_id: int) -> None:
        """Ensure the active list view stays scrolled to the edited/selected task."""
        if not getattr(self, "page", None):
            return

        if self.current_tab == 0:
            target_list = self.today_tasks_column
            scroll_key = f"task_card_{task_id}"
        elif self.current_tab == 1:
            target_list = self.all_tasks_column
            scroll_key = f"task_card_{task_id}"
        elif self.current_tab == 3:
            target_list = self.archive_column
            scroll_key = f"archive_card_{task_id}"
        else:
            return

        # Estimate approximate offset in case scroll_key is out-of-viewport in virtualized list
        approx_offset = None
        for idx, c in enumerate(target_list.controls):
            if getattr(c, "key", None) == scroll_key:
                approx_offset = max(0.0, float(idx * 110 - 20))
                break

        async def _do_scroll():
            import asyncio
            await asyncio.sleep(0.04)
            try:
                await target_list.scroll_to(scroll_key=scroll_key, duration=150)
            except Exception:
                if approx_offset is not None:
                    try:
                        await target_list.scroll_to(offset=approx_offset, duration=150)
                    except Exception:
                        pass

        try:
            if hasattr(self.page, "run_task"):
                self.page.run_task(_do_scroll)
        except Exception:
            pass

    def _scroll_to_tag(self, tag_id: int) -> None:
        """Ensure the tags list view stays scrolled to the edited/selected tag."""
        if not getattr(self, "page", None) or self.current_tab != 2:
            return

        target_list = self.tags_column
        scroll_key = f"tag_card_{tag_id}"

        approx_offset = None
        for idx, c in enumerate(target_list.controls):
            if getattr(c, "key", None) == scroll_key:
                approx_offset = max(0.0, float(idx * 65 - 20))
                break

        async def _do_scroll():
            import asyncio
            await asyncio.sleep(0.04)
            try:
                await target_list.scroll_to(scroll_key=scroll_key, duration=150)
            except Exception:
                if approx_offset is not None:
                    try:
                        await target_list.scroll_to(offset=approx_offset, duration=150)
                    except Exception:
                        pass

        try:
            if hasattr(self.page, "run_task"):
                self.page.run_task(_do_scroll)
        except Exception:
            pass

    def open_right_tag_panel(self, tag: Subject) -> None:
        """Open the translucent right panel for editing a tag."""
        prev_id = self.selected_tag_id
        self.right_panel_mode = "tag"
        self.selected_tag_id = tag.id
        self._last_selected_tag_id = tag.id
        self.selected_task_id = None
        self.right_panel_open = True
        w = getattr(self.page, "width", 1000) or 1000
        self.right_panel_container.width = min(420, max(300, w - 60))
        self._render_right_tag_panel_content(tag)
        self.right_panel_barrier.visible = True
        self.right_panel_barrier.opacity = 1.0
        self.right_panel_container.visible = True
        self.right_panel_container.opacity = 1.0

        if prev_id and prev_id in self._tag_card_containers:
            self._tag_card_containers[prev_id].border = None
            try:
                self._tag_card_containers[prev_id].update()
            except Exception:
                pass
        if tag.id in self._tag_card_containers:
            self._tag_card_containers[tag.id].border = ft.Border.all(1.5, ft.Colors.CYAN_400)
            try:
                self._tag_card_containers[tag.id].update()
            except Exception:
                pass

        try:
            self.right_panel_barrier.update()
            self.right_panel_container.update()
        except Exception:
            self.page.update()

        self._scroll_to_tag(tag.id)

    def open_right_panel(self, task: Task) -> None:
        """Open the translucent right panel with editable task description and properties."""
        prev_id = self.selected_task_id
        self.right_panel_mode = "task"
        self.selected_task_id = task.id
        self._last_selected_task_id = task.id
        self.selected_tag_id = None
        self.right_panel_open = True
        w = getattr(self.page, "width", 1000) or 1000
        self.right_panel_container.width = min(420, max(300, w - 60))
        self._render_right_panel_content(task)
        self.right_panel_barrier.visible = True
        self.right_panel_barrier.opacity = 1.0
        self.right_panel_container.visible = True
        self.right_panel_container.opacity = 1.0

        if prev_id and prev_id in self._task_card_containers:
            self._task_card_containers[prev_id].border = None
            try:
                self._task_card_containers[prev_id].update()
            except Exception:
                pass
        if task.id in self._task_card_containers:
            self._task_card_containers[task.id].border = ft.Border.all(1.5, ft.Colors.CYAN_400)
            try:
                self._task_card_containers[task.id].update()
            except Exception:
                pass

        try:
            self.right_panel_barrier.update()
            self.right_panel_container.update()
        except Exception:
            self.page.update()

        self._scroll_to_task(task.id)

    def close_right_panel(self) -> None:
        """Close the right overlay panel."""
        self.right_panel_open = False
        prev_task_id = self.selected_task_id
        prev_tag_id = self.selected_tag_id
        if prev_task_id and prev_task_id in self._task_card_containers:
            self._task_card_containers[prev_task_id].border = None
            try:
                self._task_card_containers[prev_task_id].update()
            except Exception:
                pass
        if prev_tag_id and prev_tag_id in self._tag_card_containers:
            self._tag_card_containers[prev_tag_id].border = None
            try:
                self._tag_card_containers[prev_tag_id].update()
            except Exception:
                pass
        if prev_task_id:
            self._last_selected_task_id = prev_task_id
        if prev_tag_id:
            self._last_selected_tag_id = prev_tag_id
        self.selected_task_id = None
        self.selected_tag_id = None
        self.right_panel_barrier.visible = False
        self.right_panel_barrier.opacity = 0.0
        self.right_panel_container.visible = False
        self.right_panel_container.opacity = 0.0
        try:
            self.right_panel_barrier.update()
            self.right_panel_container.update()
        except Exception:
            self.page.update()

    def toggle_right_panel(self, task: Task | None = None, tag: Subject | None = None) -> None:
        """Toggle right panel visibility for tasks or tags."""
        if self.right_panel_open:
            self.close_right_panel()
        else:
            if tag:
                self.open_right_tag_panel(tag)
            elif task:
                self.open_right_panel(task)
            elif self.current_tab == 2:
                # In tags tab: if a tag is selected, open it; otherwise open empty panel without selecting top tag
                if self.selected_tag_id:
                    target_tag = self.task_manager.get_subject_by_id(self.selected_tag_id)
                    if target_tag:
                        self.open_right_tag_panel(target_tag)
                        return
                self.right_panel_mode = "tag"
                self.selected_tag_id = None
                self.right_panel_open = True
                w = getattr(self.page, "width", 1000) or 1000
                self.right_panel_container.width = min(420, max(300, w - 60))
                self._render_right_tag_panel_content(None)
                self.right_panel_barrier.visible = True
                self.right_panel_barrier.opacity = 1.0
                self.right_panel_container.visible = True
                self.right_panel_container.opacity = 1.0
                try:
                    self.right_panel_barrier.update()
                    self.right_panel_container.update()
                except Exception:
                    self.page.update()
            else:
                # In tasks tabs (0, 1, 3): if a task is selected, open it; otherwise open empty panel without selecting top task
                if self.selected_task_id:
                    target_task = self.task_manager.get_task_by_id(self.selected_task_id)
                    if target_task:
                        self.open_right_panel(target_task)
                        return
                self.right_panel_mode = "task"
                self.selected_task_id = None
                self.right_panel_open = True
                w = getattr(self.page, "width", 1000) or 1000
                self.right_panel_container.width = min(420, max(300, w - 60))
                self._render_right_panel_content(None)
                self.right_panel_barrier.visible = True
                self.right_panel_barrier.opacity = 1.0
                self.right_panel_container.visible = True
                self.right_panel_container.opacity = 1.0
                try:
                    self.right_panel_barrier.update()
                    self.right_panel_container.update()
                except Exception:
                    self.page.update()

    # ──────────────────────────────────────────
    # Rendering & View Updates
    # ──────────────────────────────────────────
    def _get_or_build_tab_view(self, tab_idx: int) -> ft.Control:
        """Return the pre-rendered tab view or build it if dirty/missing."""
        if tab_idx in self._dirty_tabs or tab_idx not in self._tab_views:
            if not hasattr(self, "_tab_versions"):
                self._tab_versions = {0: 0, 1: 0, 2: 0, 3: 0}
            self._tab_versions[tab_idx] = self._tab_versions.get(tab_idx, 0) + 1

            if tab_idx == 0:
                inner = self._render_today_tasks_view()
            elif tab_idx == 1:
                inner = self._render_all_tasks_view()
            elif tab_idx == 2:
                inner = self._render_tags_view()
            else:
                inner = self._render_archive_view()

            # Keep stable container key for the tab so AnimatedSwitcher smoothly transitions
            # between different tabs without destroying and resetting the scroll position on same-tab data reload.
            view = ft.Container(
                content=inner,
                expand=True,
                alignment=ft.Alignment(-1, -1),
                key=f"tab_view_{tab_idx}",
            )
            self._tab_views[tab_idx] = view
            self._dirty_tabs.discard(tab_idx)

        return self._tab_views[tab_idx]

    def _render_content(self) -> None:
        """Render the main content view using cached tab views when clean, or build when dirty."""
        self.content_area.content = self._get_or_build_tab_view(self.current_tab)

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

        # Adaptive width for overlay right panel
        if hasattr(self, "right_panel_container") and self.right_panel_container:
            self.right_panel_container.width = min(420, max(280, width - 40))

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
        if not hasattr(self.page, "theme_mode") or self.page.theme_mode is None:
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
                    self.main_content_stack,
                ],
            )
        )
        self._handle_page_resize()
        self.page.update()

    def refresh(self) -> None:
        """Reload data for the active view, update sidebar and page."""
        target_task_id = self.selected_task_id or getattr(self, "_last_selected_task_id", None)
        target_tag_id = self.selected_tag_id or getattr(self, "_last_selected_tag_id", None)

        self._dirty_tabs = {0, 1, 2, 3}
        self._task_card_containers.clear()
        self._tag_card_containers.clear()
        TimePredictor.clear_cache()
        self._render_sidebar()
        self._render_content()
        self.page.update()
        gc.collect(1)

        # Restore scroll position to the task/tag being edited
        if target_task_id and self.current_tab in (0, 1, 3):
            self._scroll_to_task(target_task_id)
        elif target_tag_id and self.current_tab == 2:
            self._scroll_to_tag(target_tag_id)

    # ──────────────────────────────────────────
    # Dialog Handlers
    # ──────────────────────────────────────────
    def open_add_task_dialog(self) -> None:
        """Open the task creation dialog."""
        open_task_create_dialog(self.page, on_success=self.refresh)

    def open_edit_dialog(self, task: Task) -> None:
        """Open the task editing dialog."""
        self.selected_task_id = task.id
        self._last_selected_task_id = task.id
        self._scroll_to_task(task.id)
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

    def archive_task(self, task_id: int, task_name: str) -> None:
        """Move a completed task to the archive."""
        if self.selected_task_id == task_id and self.right_panel_open:
            self.close_right_panel()
        self.task_manager.archive_task(task_id)
        _show_snack(
            self.page,
            f"Задача «{task_name}» отправлена в архив!",
            bgcolor=ft.Colors.CYAN_800,
        )
        self.refresh()

    def archive_all_completed(self, only_today: bool = False) -> None:
        """Move all completed tasks to the archive."""
        count = self.task_manager.archive_all_completed_tasks(only_today=only_today)
        if count > 0:
            _show_snack(
                self.page,
                f"Отправлено в архив задач: {count} шт.",
                bgcolor=ft.Colors.CYAN_800,
            )
        else:
            _show_snack(
                self.page,
                "Нет завершенных задач для отправки в архив.",
                bgcolor=ft.Colors.GREY_800,
            )
        self.refresh()

    def unarchive_task(self, task_id: int, task_name: str) -> None:
        """Return a task from the archive back to completed list."""
        self.task_manager.unarchive_task(task_id, reopen=False)
        _show_snack(
            self.page,
            f"Задача «{task_name}» возвращена из архива!",
            bgcolor=ft.Colors.CYAN_800,
        )
        self.refresh()

    def reopen_archived_task(self, task_id: int, task_name: str) -> None:
        """Return an archived task directly to active work."""
        self.task_manager.reopen_task(task_id)
        _show_snack(
            self.page,
            f"Задача «{task_name}» возвращена в активные задачи!",
            bgcolor=ft.Colors.GREEN_800,
        )
        self.refresh()

    def confirm_delete_archived_task(self, task_id: int, task_name: str) -> None:
        """Show confirmation dialog before permanently deleting an archived task."""
        def _execute_delete(_):
            _close_dialog(self.page, delete_dialog)
            if self.selected_task_id == task_id and self.right_panel_open:
                self.close_right_panel()
            success = self.task_manager.delete_task(task_id)
            if success:
                _show_snack(
                    self.page,
                    f"Задача «{task_name}» навсегда удалена.",
                    bgcolor=ft.Colors.RED_800,
                )
            self.refresh()

        delete_dialog = ft.AlertDialog(
            modal=True,
            title=ft.Row(
                [
                    ft.Icon(ft.Icons.WARNING_ROUNDED, color=ft.Colors.RED_400),
                    ft.Text("Удалить задачу?", weight=ft.FontWeight.BOLD),
                ],
                spacing=8,
            ),
            content=ft.Text(f"Вы уверены, что хотите навсегда удалить задачу «{task_name}» из архива? Это действие необратимо."),
            actions=[
                ft.TextButton("Отмена", on_click=lambda _: _close_dialog(self.page, delete_dialog)),
                FilledBtn(
                    "Удалить навсегда",
                    style=ft.ButtonStyle(bgcolor=ft.Colors.RED_700, color=ft.Colors.WHITE) if hasattr(ft, "ButtonStyle") else None,
                    on_click=_execute_delete,
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        _show_dialog(self.page, delete_dialog)

    def confirm_clear_archive(self) -> None:
        """Show confirmation dialog before clearing the entire archive."""
        def _execute_clear(_):
            _close_dialog(self.page, clear_dialog)
            count = self.task_manager.clear_archive()
            _show_snack(
                self.page,
                f"Архив очищен. Удалено задач: {count} шт.",
                bgcolor=ft.Colors.RED_800,
            )
            self.refresh()

        clear_dialog = ft.AlertDialog(
            modal=True,
            title=ft.Row(
                [
                    ft.Icon(ft.Icons.DELETE_SWEEP_ROUNDED, color=ft.Colors.RED_400),
                    ft.Text("Очистить весь архив?", weight=ft.FontWeight.BOLD),
                ],
                spacing=8,
            ),
            content=ft.Text("Все задачи в архиве будут удалены безвозвратно. Продолжить?"),
            actions=[
                ft.TextButton("Отмена", on_click=lambda _: _close_dialog(self.page, clear_dialog)),
                FilledBtn(
                    "Очистить",
                    style=ft.ButtonStyle(bgcolor=ft.Colors.RED_700, color=ft.Colors.WHITE) if hasattr(ft, "ButtonStyle") else None,
                    on_click=_execute_clear,
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        _show_dialog(self.page, clear_dialog)

    def open_add_tag_dialog(self) -> None:
        """Open dialog to create a new tag/subject."""
        open_tag_dialog(self.page, on_success=self.refresh)

    def open_edit_tag_dialog(self, tag: Subject) -> None:
        """Open dialog to edit an existing tag/subject."""
        self.selected_tag_id = tag.id
        self._last_selected_tag_id = tag.id
        self._scroll_to_tag(tag.id)
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
            if self.selected_tag_id == tag.id and self.right_panel_open:
                self.close_right_panel()
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

    def set_theme_mode(self, mode: ft.ThemeMode = ft.ThemeMode.DARK) -> None:
        """Enforce Dark theme mode."""
        self.page.theme_mode = ft.ThemeMode.DARK
        self.right_panel_container.bgcolor = ft.Colors.with_opacity(0.70, "#161822")
        self.right_panel_barrier.bgcolor = ft.Colors.with_opacity(0.35, ft.Colors.BLACK)
        self.refresh()

    def open_settings_dialog(self) -> None:
        """Open the Settings modal dialog with Interface, App Options, and Shortcuts tabs."""
        active_tab_idx = [0]  # 0: Интерфейс, 1: Опции приложения, 2: Шорткаты
        content_holder = ft.Container(expand=True)
        tab_buttons_holder = ft.Row(spacing=6)

        def _get_tab_content() -> ft.Control:
            idx = active_tab_idx[0]
            if idx == 0:
                # Вкладка 1: «Интерфейс» (только тёмная тема)
                return ft.Column(
                    spacing=14,
                    controls=[
                        ft.Text("Оформление темы", size=15, weight=ft.FontWeight.BOLD),
                        ft.Container(
                            padding=16,
                            border_radius=12,
                            border=ft.Border.all(1.5, ft.Colors.PRIMARY),
                            bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.PRIMARY),
                            content=ft.Row(
                                spacing=12,
                                controls=[
                                    ft.Icon(ft.Icons.DARK_MODE_ROUNDED, size=28, color=ft.Colors.PRIMARY),
                                    ft.Column(
                                        spacing=2,
                                        controls=[
                                            ft.Text("Тёмная тема (по умолчанию)", size=14, weight=ft.FontWeight.BOLD),
                                            ft.Text("Интерфейс приложения работает в тёмном режиме.", size=12, color=ft.Colors.GREY_400),
                                        ],
                                    ),
                                ],
                            ),
                        ),
                    ],
                )

            elif idx == 1:
                # Вкладка 2: «Опции приложения»
                return ft.Container(
                    alignment=ft.Alignment(0, 0),
                    padding=20,
                    content=ft.Column(
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=10,
                        controls=[
                            ft.Icon(ft.Icons.TUNE_ROUNDED, size=44, color=ft.Colors.GREY_500),
                            ft.Text("Опции приложения", size=16, weight=ft.FontWeight.BOLD),
                            ft.Text(
                                "В этом разделе появятся дополнительные параметры и настройки приложения.",
                                size=13,
                                color=ft.Colors.GREY_400,
                                text_align=ft.TextAlign.CENTER,
                            ),
                        ],
                    ),
                )

            else:
                # Вкладка 3: «Шорткаты»
                return ft.Column(
                    spacing=12,
                    controls=[
                        ft.Text("Горячие клавиши", size=15, weight=ft.FontWeight.BOLD),
                        ft.Container(
                            padding=12,
                            border_radius=8,
                            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                            content=ft.Row(
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                controls=[
                                    ft.Text("Закрыть правую панель или окно настроек", size=13),
                                    ft.Container(
                                        padding=ft.Padding(8, 3, 8, 3),
                                        border_radius=6,
                                        border=ft.Border.all(1, ft.Colors.OUTLINE),
                                        content=ft.Text("Esc", size=12, weight=ft.FontWeight.BOLD),
                                    ),
                                ],
                            ),
                        ),
                        ft.Container(
                            padding=12,
                            border_radius=8,
                            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                            content=ft.Row(
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                controls=[
                                    ft.Text("Быстрое сохранение задачи или тега", size=13),
                                    ft.Container(
                                        padding=ft.Padding(8, 3, 8, 3),
                                        border_radius=6,
                                        border=ft.Border.all(1, ft.Colors.OUTLINE),
                                        content=ft.Text("Enter", size=12, weight=ft.FontWeight.BOLD),
                                    ),
                                ],
                            ),
                        ),
                        ft.Text(
                            "Пользовательская настройка сочетаний клавиш появится в будущих обновлениях.",
                            size=12,
                            color=ft.Colors.GREY_400,
                            italic=True,
                        ),
                    ],
                )

        def _select_tab(idx: int):
            active_tab_idx[0] = idx
            _update_dialog_view()

        def _update_dialog_view():
            tab_defs = [
                (0, "Интерфейс", ft.Icons.PALETTE_ROUNDED),
                (1, "Опции приложения", ft.Icons.TUNE_ROUNDED),
                (2, "Шорткаты", ft.Icons.KEYBOARD_ROUNDED),
            ]
            tab_buttons = []
            for t_idx, t_label, t_icon in tab_defs:
                is_sel = (active_tab_idx[0] == t_idx)
                tab_buttons.append(
                    ft.Container(
                        content=ft.Row(
                            spacing=6,
                            tight=True,
                            controls=[
                                ft.Icon(t_icon, size=16, color=ft.Colors.WHITE if is_sel else ft.Colors.GREY_400),
                                ft.Text(
                                    t_label,
                                    size=13,
                                    weight=ft.FontWeight.BOLD if is_sel else ft.FontWeight.W_500,
                                    color=ft.Colors.WHITE if is_sel else ft.Colors.GREY_300,
                                ),
                            ],
                        ),
                        bgcolor=ft.Colors.PRIMARY if is_sel else ft.Colors.TRANSPARENT,
                        padding=ft.Padding(12, 8, 12, 8),
                        border_radius=8,
                        ink=True,
                        on_click=lambda _, idx=t_idx: _select_tab(idx),
                    )
                )

            tab_buttons_holder.controls = tab_buttons
            content_holder.content = _get_tab_content()
            self.page.update()

        _update_dialog_view()

        settings_dialog = ft.AlertDialog(
            modal=True,
            title=ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                controls=[
                    ft.Row(
                        spacing=10,
                        controls=[
                            ft.Icon(ft.Icons.SETTINGS_ROUNDED, color=ft.Colors.PRIMARY, size=24),
                            ft.Text("Настройки", size=20, weight=ft.FontWeight.BOLD),
                        ],
                    ),
                    ft.IconButton(
                        icon=ft.Icons.CLOSE_ROUNDED,
                        icon_size=20,
                        tooltip="Закрыть",
                        on_click=lambda _: _close_dialog(self.page, settings_dialog),
                    ),
                ],
            ),
            content=ft.Container(
                width=520,
                height=320,
                content=ft.Column(
                    spacing=14,
                    controls=[
                        ft.Container(
                            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                            padding=4,
                            border_radius=10,
                            content=tab_buttons_holder,
                        ),
                        ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                        content_holder,
                    ],
                ),
            ),
            actions=[
                ft.TextButton(
                    "Закрыть",
                    on_click=lambda _: _close_dialog(self.page, settings_dialog),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

        _show_dialog(self.page, settings_dialog)


def main_view(page: ft.Page) -> None:
    """Convenience functional entry point for rendering the schedule screen."""
    app = ScheduleScreen(page)
    app.render()
