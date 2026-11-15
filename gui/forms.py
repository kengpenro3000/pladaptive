"""Form dialog for creating a new task.

Collects task details (name, subject, expected time in minutes, priority,
deadline), calls TaskManager().add_task(), and displays the AI-predicted time
via a SnackBar.
"""

from __future__ import annotations

import sys
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Callable

# Ensure root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import flet as ft

from core.task_manager import TaskManager
from database.models import Subject, Task, TaskPriority


def _show_dialog(page: ft.Page, dialog: ft.AlertDialog) -> None:
    """Open a dialog compatible with both Flet 0.x and 1.x."""
    if hasattr(page, "show_dialog"):
        page.show_dialog(dialog)
    elif hasattr(page, "open"):
        page.open(dialog)
    else:
        page.dialog = dialog
        dialog.open = True
        page.update()


def _close_dialog(page: ft.Page, dialog: ft.AlertDialog) -> None:
    """Close an active dialog compatible with both Flet 0.x and 1.x."""
    if hasattr(page, "pop_dialog"):
        page.pop_dialog()
    elif hasattr(page, "close"):
        page.close(dialog)
    else:
        dialog.open = False
        page.update()


def _show_snack(page: ft.Page, text: str, bgcolor: str = ft.Colors.GREEN_800) -> None:
    """Display a SnackBar compatible with both Flet 0.x and 1.x."""
    snack = ft.SnackBar(
        content=ft.Row(
            controls=[
                ft.Icon(ft.Icons.CHECK_CIRCLE_ROUNDED, color=ft.Colors.WHITE, size=22),
                ft.Text(text, color=ft.Colors.WHITE, weight=ft.FontWeight.W_500, size=14),
            ],
            spacing=10,
        ),
        bgcolor=bgcolor,
        duration=5000,
    )
    if hasattr(page, "show_dialog"):
        page.show_dialog(snack)
    elif hasattr(page, "open"):
        page.open(snack)
    else:
        page.snack_bar = snack
        snack.open = True
        page.update()


def _parse_date(date_str: str) -> date | None:
    """Parse date string into a date object."""
    clean = date_str.strip()
    if not clean:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(clean, fmt).date()
        except ValueError:
            pass
    raise ValueError("Используйте формат ГГГГ-ММ-ДД (например: 2026-11-15)")


def _parse_deadline(date_str: str) -> datetime | None:
    """Parse deadline string from multiple common formats."""
    clean = date_str.strip()
    if not clean:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M", "%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(clean, fmt)
        except ValueError:
            pass
    raise ValueError("Используйте формат ГГГГ-ММ-ДД (например: 2026-12-01)")


class TaskCreateDialog:
    """Modal dialog for creating a new task."""

    def __init__(
        self,
        page: ft.Page,
        task_manager: TaskManager | None = None,
        on_success: Callable[[], None] | None = None,
    ) -> None:
        self.page = page
        self.task_manager = task_manager or TaskManager()
        self.on_success = on_success

        # ── Form Inputs ─────────────────────────────
        self.name_field = ft.TextField(
            label="Название задачи*",
            hint_text="Например: Решить домашку по матанализу",
            autofocus=True,
        )

        subjects = self.task_manager.get_all_subjects()
        subject_options = [
            ft.dropdown.Option(key=str(s.id), text=f"{getattr(s, 'icon', '🏷️')} {s.name}")
            for s in subjects
        ]
        self.subject_dropdown = ft.Dropdown(
            label="Тег / Предмет*",
            hint_text="Выберите тег",
            options=subject_options,
            value=subject_options[0].key if subject_options else None,
        )

        self.time_field = ft.TextField(
            label="Ожидаемое время (в минутах)*",
            hint_text="Например: 90",
            input_filter=ft.NumbersOnlyInputFilter(),
            keyboard_type=ft.KeyboardType.NUMBER,
        )

        self.priority_dropdown = ft.Dropdown(
            label="Приоритет*",
            value=TaskPriority.MEDIUM.value,
            options=[
                ft.dropdown.Option(key=TaskPriority.LOW.value, text="Низкий (Low)"),
                ft.dropdown.Option(key=TaskPriority.MEDIUM.value, text="Средний (Medium)"),
                ft.dropdown.Option(key=TaskPriority.HIGH.value, text="Высокий (High)"),
                ft.dropdown.Option(key=TaskPriority.CRITICAL.value, text="Критический (Critical)"),
            ],
        )

        today_str = date.today().strftime("%Y-%m-%d")
        self.scheduled_date_field = ft.TextField(
            label="Запланировано на день",
            value=today_str,
            hint_text="ГГГГ-ММ-ДД (например: 2026-11-15)",
            icon=ft.Icons.EVENT_ROUNDED,
        )

        self.sched_date_picker = ft.DatePicker(
            first_date=datetime(2020, 1, 1),
            last_date=datetime(2035, 12, 31),
            value=datetime.now(),
            on_change=self._on_sched_date_picked,
        )

        self.scheduled_date_field.suffix = ft.IconButton(
            icon=ft.Icons.CALENDAR_MONTH_ROUNDED,
            tooltip="Выбрать день в календаре",
            on_click=lambda _: self._open_sched_calendar(),
        )

        quick_sched_chips = ft.Row(
            spacing=6,
            controls=[
                ft.TextButton("Сегодня", on_click=lambda _: self._set_sched_date(date.today())),
                ft.TextButton("Завтра", on_click=lambda _: self._set_sched_date(date.today() + timedelta(days=1))),
                ft.TextButton("Через 3 дня", on_click=lambda _: self._set_sched_date(date.today() + timedelta(days=3))),
                ft.TextButton("Без даты", on_click=lambda _: self._set_sched_date(None)),
            ],
        )

        self.deadline_field = ft.TextField(
            label="Дедлайн (необязательно)",
            hint_text="ГГГГ-ММ-ДД (например: 2026-12-01)",
            icon=ft.Icons.SCHEDULE_ROUNDED,
        )

        self.date_picker = ft.DatePicker(
            first_date=datetime(2020, 1, 1),
            last_date=datetime(2035, 12, 31),
            on_change=self._on_date_picked,
        )

        self.deadline_field.suffix = ft.IconButton(
            icon=ft.Icons.CALENDAR_TODAY_ROUNDED,
            tooltip="Выбрать дату в календаре",
            on_click=lambda _: self._open_calendar(),
        )

        # ── Dialog Assembly ──────────────────────────
        FilledBtn = getattr(ft, "FilledButton", getattr(ft, "ElevatedButton", ft.TextButton))

        self.dialog = ft.AlertDialog(
            title=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.ADD_TASK_ROUNDED, color=ft.Colors.PRIMARY, size=26),
                    ft.Text("Новая задача", weight=ft.FontWeight.BOLD, size=20),
                ],
                spacing=10,
            ),
            content=ft.Container(
                width=480,
                content=ft.Column(
                    tight=True,
                    spacing=12,
                    controls=[
                        self.name_field,
                        self.subject_dropdown,
                        self.time_field,
                        self.priority_dropdown,
                        self.scheduled_date_field,
                        quick_sched_chips,
                        self.deadline_field,
                    ],
                ),
            ),
            actions=[
                ft.TextButton(
                    "Отмена",
                    on_click=lambda _: _close_dialog(self.page, self.dialog),
                ),
                FilledBtn(
                    "Сохранить",
                    icon=ft.Icons.CHECK_ROUNDED,
                    on_click=lambda _: self._save_task(),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

    def _set_sched_date(self, d: date | None) -> None:
        """Set scheduled date from quick action buttons."""
        self.scheduled_date_field.value = d.strftime("%Y-%m-%d") if d else ""
        self.scheduled_date_field.error_text = None
        self.page.update()

    def _open_sched_calendar(self) -> None:
        """Open native DatePicker for scheduled date field."""
        if hasattr(self.page, "show_dialog"):
            self.page.show_dialog(self.sched_date_picker)
        elif hasattr(self.page, "open"):
            self.page.open(self.sched_date_picker)
        else:
            self.page.overlay.append(self.sched_date_picker)
            self.sched_date_picker.open = True
            self.page.update()

    def _on_sched_date_picked(self, e: ft.ControlEvent) -> None:
        """Handle scheduled date selection from DatePicker."""
        if self.sched_date_picker.value:
            self.scheduled_date_field.value = self.sched_date_picker.value.strftime("%Y-%m-%d")
            self.scheduled_date_field.error_text = None
            self.page.update()

    def _open_calendar(self) -> None:
        """Open native DatePicker for deadline field."""
        if hasattr(self.page, "show_dialog"):
            self.page.show_dialog(self.date_picker)
        elif hasattr(self.page, "open"):
            self.page.open(self.date_picker)
        else:
            self.page.overlay.append(self.date_picker)
            self.date_picker.open = True
            self.page.update()

    def _on_date_picked(self, e: ft.ControlEvent) -> None:
        """Handle date selection from DatePicker."""
        if self.date_picker.value:
            self.deadline_field.value = self.date_picker.value.strftime("%Y-%m-%d")
            self.deadline_field.error_text = None
            self.page.update()

    def _validate(self) -> tuple[bool, str, int | None, float | None, TaskPriority, datetime | None, date | None]:
        """Validate input fields and return parsed values or error."""
        has_error = False

        # Name
        name = (self.name_field.value or "").strip()
        if not name:
            self.name_field.error_text = "Введите название задачи"
            has_error = True
        else:
            self.name_field.error_text = None

        # Subject / Tag
        subject_id_raw = self.subject_dropdown.value
        if not subject_id_raw:
            self.subject_dropdown.error_text = "Выберите тег"
            has_error = True
        else:
            self.subject_dropdown.error_text = None

        # Expected Time
        time_raw = (self.time_field.value or "").strip()
        expected_hours: float | None = None
        if not time_raw:
            self.time_field.error_text = "Укажите ожидаемое время"
            has_error = True
        else:
            try:
                minutes = float(time_raw)
                if minutes <= 0:
                    self.time_field.error_text = "Время должно быть больше 0"
                    has_error = True
                else:
                    self.time_field.error_text = None
                    expected_hours = round(minutes / 60.0, 4)
            except ValueError:
                self.time_field.error_text = "Введите корректное число"
                has_error = True

        # Priority
        try:
            priority = TaskPriority(self.priority_dropdown.value or TaskPriority.MEDIUM.value)
        except ValueError:
            priority = TaskPriority.MEDIUM

        # Scheduled Date
        sched_date: date | None = None
        if self.scheduled_date_field.value and self.scheduled_date_field.value.strip():
            try:
                sched_date = _parse_date(self.scheduled_date_field.value)
                self.scheduled_date_field.error_text = None
            except ValueError as err:
                self.scheduled_date_field.error_text = str(err)
                has_error = True
        else:
            self.scheduled_date_field.error_text = None

        # Deadline
        deadline_dt: datetime | None = None
        if self.deadline_field.value and self.deadline_field.value.strip():
            try:
                deadline_dt = _parse_deadline(self.deadline_field.value)
                self.deadline_field.error_text = None
            except ValueError as err:
                self.deadline_field.error_text = str(err)
                has_error = True
        else:
            self.deadline_field.error_text = None

        if has_error:
            self.page.update()
            return False, name, None, None, priority, None, None

        subject_id = int(subject_id_raw)
        return True, name, subject_id, expected_hours, priority, deadline_dt, sched_date

    def _save_task(self) -> None:
        """Validate, save task via TaskManager, display SnackBar, and close."""
        valid, name, subject_id, expected_hours, priority, deadline_dt, sched_date = self._validate()
        if not valid or subject_id is None:
            return

        try:
            task: Task = self.task_manager.add_task(
                name=name,
                subject_id=subject_id,
                priority=priority,
                expected_time=expected_hours,
                deadline=deadline_dt,
                scheduled_date=sched_date,
            )

            # Close dialog first
            _close_dialog(self.page, self.dialog)

            # Intercept prediction message from add_task
            if hasattr(task, "prediction_message") and task.prediction_message:
                snack_message = task.prediction_message
            elif hasattr(task, "prediction") and task.prediction:
                pred_min = round(task.prediction.predicted_time * 60, 1)
                snack_message = (
                    f"Задача добавлена. Ожидаемое время: {round(task.prediction.expected_time * 60, 1)} мин. "
                    f"Предсказанное время: {pred_min} мин."
                )
            else:
                snack_message = f"Задача '{task.name}' успешно добавлена!"

            # Show prediction result via SnackBar
            _show_snack(self.page, snack_message)

            # Refresh list if callback provided
            if self.on_success:
                self.on_success()

        except Exception as err:
            self.name_field.error_text = f"Ошибка сохранения: {err}"
            self.page.update()

    def show(self) -> None:
        """Display the task creation dialog."""
        _show_dialog(self.page, self.dialog)


def open_task_create_dialog(
    page: ft.Page,
    task_manager: TaskManager | None = None,
    on_success: Callable[[], None] | None = None,
) -> TaskCreateDialog:
    """Helper function to instantiate and show the task creation dialog."""
    form = TaskCreateDialog(page, task_manager=task_manager, on_success=on_success)
    form.show()
    return form


class TaskEditDialog:
    """Modal dialog for editing an existing task, styled identically to TaskCreateDialog."""

    def __init__(
        self,
        page: ft.Page,
        task: Task,
        task_manager: TaskManager | None = None,
        on_success: Callable[[], None] | None = None,
    ) -> None:
        self.page = page
        self.task = task
        self.task_manager = task_manager or TaskManager()
        self.on_success = on_success

        # ── Form Inputs (Pre-filled with task data) ──
        self.name_field = ft.TextField(
            label="Название задачи*",
            value=task.name,
            hint_text="Например: Решить домашку по матанализу",
            autofocus=True,
        )

        subjects = self.task_manager.get_all_subjects()
        subject_options = [
            ft.dropdown.Option(key=str(s.id), text=f"{getattr(s, 'icon', '🏷️')} {s.name}")
            for s in subjects
        ]
        self.subject_dropdown = ft.Dropdown(
            label="Тег / Предмет*",
            hint_text="Выберите тег",
            options=subject_options,
            value=str(task.subject_id),
        )

        initial_minutes = ""
        if task.expected_time is not None:
            r = round(task.expected_time * 60, 1)
            initial_minutes = str(int(r)) if r.is_integer() else f"{r:.1f}"

        self.time_field = ft.TextField(
            label="Ожидаемое время (в минутах)*",
            value=initial_minutes,
            hint_text="Например: 90",
            input_filter=ft.NumbersOnlyInputFilter(),
            keyboard_type=ft.KeyboardType.NUMBER,
        )

        self.priority_dropdown = ft.Dropdown(
            label="Приоритет*",
            value=task.priority.value,
            options=[
                ft.dropdown.Option(key=TaskPriority.LOW.value, text="Низкий (Low)"),
                ft.dropdown.Option(key=TaskPriority.MEDIUM.value, text="Средний (Medium)"),
                ft.dropdown.Option(key=TaskPriority.HIGH.value, text="Высокий (High)"),
                ft.dropdown.Option(key=TaskPriority.CRITICAL.value, text="Критический (Critical)"),
            ],
        )

        initial_sched = task.scheduled_date.strftime("%Y-%m-%d") if getattr(task, "scheduled_date", None) else ""
        self.scheduled_date_field = ft.TextField(
            label="Запланировано на день",
            value=initial_sched,
            hint_text="ГГГГ-ММ-ДД (например: 2026-11-15)",
            icon=ft.Icons.EVENT_ROUNDED,
        )

        self.sched_date_picker = ft.DatePicker(
            first_date=datetime(2020, 1, 1),
            last_date=datetime(2035, 12, 31),
            value=datetime.combine(task.scheduled_date, datetime.min.time()) if getattr(task, "scheduled_date", None) else datetime.now(),
            on_change=self._on_sched_date_picked,
        )

        self.scheduled_date_field.suffix = ft.IconButton(
            icon=ft.Icons.CALENDAR_MONTH_ROUNDED,
            tooltip="Выбрать день в календаре",
            on_click=lambda _: self._open_sched_calendar(),
        )

        quick_sched_chips = ft.Row(
            spacing=6,
            controls=[
                ft.TextButton("Сегодня", on_click=lambda _: self._set_sched_date(date.today())),
                ft.TextButton("Завтра", on_click=lambda _: self._set_sched_date(date.today() + timedelta(days=1))),
                ft.TextButton("Через 3 дня", on_click=lambda _: self._set_sched_date(date.today() + timedelta(days=3))),
                ft.TextButton("Без даты", on_click=lambda _: self._set_sched_date(None)),
            ],
        )

        initial_deadline = task.deadline.strftime("%Y-%m-%d") if task.deadline else ""
        self.deadline_field = ft.TextField(
            label="Дедлайн (необязательно)",
            value=initial_deadline,
            hint_text="ГГГГ-ММ-ДД (например: 2026-12-01)",
            icon=ft.Icons.SCHEDULE_ROUNDED,
        )

        self.date_picker = ft.DatePicker(
            first_date=datetime(2020, 1, 1),
            last_date=datetime(2035, 12, 31),
            value=task.deadline if task.deadline else None,
            on_change=self._on_date_picked,
        )

        self.deadline_field.suffix = ft.IconButton(
            icon=ft.Icons.CALENDAR_TODAY_ROUNDED,
            tooltip="Выбрать дату в календаре",
            on_click=lambda _: self._open_calendar(),
        )

        # ── Dialog Assembly ──────────────────────────
        FilledBtn = getattr(ft, "FilledButton", getattr(ft, "ElevatedButton", ft.TextButton))

        self.dialog = ft.AlertDialog(
            title=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.EDIT_NOTE_ROUNDED, color=ft.Colors.PRIMARY, size=26),
                    ft.Text("Редактирование задачи", weight=ft.FontWeight.BOLD, size=20),
                ],
                spacing=10,
            ),
            content=ft.Container(
                width=480,
                content=ft.Column(
                    tight=True,
                    spacing=12,
                    controls=[
                        self.name_field,
                        self.subject_dropdown,
                        self.time_field,
                        self.priority_dropdown,
                        self.scheduled_date_field,
                        quick_sched_chips,
                        self.deadline_field,
                    ],
                ),
            ),
            actions=[
                ft.TextButton(
                    "Отмена",
                    on_click=lambda _: _close_dialog(self.page, self.dialog),
                ),
                FilledBtn(
                    "Сохранить изменения",
                    icon=ft.Icons.SAVE_ROUNDED,
                    on_click=lambda _: self._save_task(),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

    def _set_sched_date(self, d: date | None) -> None:
        """Set scheduled date from quick action buttons."""
        self.scheduled_date_field.value = d.strftime("%Y-%m-%d") if d else ""
        self.scheduled_date_field.error_text = None
        self.page.update()

    def _open_sched_calendar(self) -> None:
        """Open native DatePicker for scheduled date field."""
        if hasattr(self.page, "show_dialog"):
            self.page.show_dialog(self.sched_date_picker)
        elif hasattr(self.page, "open"):
            self.page.open(self.sched_date_picker)
        else:
            self.page.overlay.append(self.sched_date_picker)
            self.sched_date_picker.open = True
            self.page.update()

    def _on_sched_date_picked(self, e: ft.ControlEvent) -> None:
        """Handle scheduled date selection from DatePicker."""
        if self.sched_date_picker.value:
            self.scheduled_date_field.value = self.sched_date_picker.value.strftime("%Y-%m-%d")
            self.scheduled_date_field.error_text = None
            self.page.update()

    def _open_calendar(self) -> None:
        """Open native DatePicker for deadline field."""
        if hasattr(self.page, "show_dialog"):
            self.page.show_dialog(self.date_picker)
        elif hasattr(self.page, "open"):
            self.page.open(self.date_picker)
        else:
            self.page.overlay.append(self.date_picker)
            self.date_picker.open = True
            self.page.update()

    def _on_date_picked(self, e: ft.ControlEvent) -> None:
        """Handle date selection from DatePicker."""
        if self.date_picker.value:
            self.deadline_field.value = self.date_picker.value.strftime("%Y-%m-%d")
            self.deadline_field.error_text = None
            self.page.update()

    def _validate(self) -> tuple[bool, str, int | None, float | None, TaskPriority, datetime | None]:
        """Validate input fields and return parsed values or error."""
        has_error = False

        # Name
        name = (self.name_field.value or "").strip()
        if not name:
            self.name_field.error_text = "Введите название задачи"
            has_error = True
        else:
            self.name_field.error_text = None

        # Subject / Tag
        subject_id_raw = self.subject_dropdown.value
        if not subject_id_raw:
            self.subject_dropdown.error_text = "Выберите тег"
            has_error = True
        else:
            self.subject_dropdown.error_text = None

        # Expected Time
        time_raw = (self.time_field.value or "").strip()
        expected_hours: float | None = None
        if not time_raw:
            self.time_field.error_text = "Укажите ожидаемое время"
            has_error = True
        else:
            try:
                minutes = float(time_raw)
                if minutes <= 0:
                    self.time_field.error_text = "Время должно быть больше 0"
                    has_error = True
                else:
                    self.time_field.error_text = None
                    expected_hours = round(minutes / 60.0, 4)
            except ValueError:
                self.time_field.error_text = "Введите корректное число"
                has_error = True

        # Priority
        try:
            priority = TaskPriority(self.priority_dropdown.value or TaskPriority.MEDIUM.value)
        except ValueError:
            priority = TaskPriority.MEDIUM

        # Scheduled Date
        sched_date: date | None = None
        if self.scheduled_date_field.value and self.scheduled_date_field.value.strip():
            try:
                sched_date = _parse_date(self.scheduled_date_field.value)
                self.scheduled_date_field.error_text = None
            except ValueError as err:
                self.scheduled_date_field.error_text = str(err)
                has_error = True
        else:
            self.scheduled_date_field.error_text = None

        # Deadline
        deadline_dt: datetime | None = None
        if self.deadline_field.value and self.deadline_field.value.strip():
            try:
                deadline_dt = _parse_deadline(self.deadline_field.value)
                self.deadline_field.error_text = None
            except ValueError as err:
                self.deadline_field.error_text = str(err)
                has_error = True
        else:
            self.deadline_field.error_text = None

        if has_error:
            self.page.update()
            return False, name, None, None, priority, None, None

        subject_id = int(subject_id_raw)
        return True, name, subject_id, expected_hours, priority, deadline_dt, sched_date

    def _save_task(self) -> None:
        """Validate, update task via TaskManager, display SnackBar, and close."""
        valid, name, subject_id, expected_hours, priority, deadline_dt, sched_date = self._validate()
        if not valid or subject_id is None:
            return

        try:
            updated_task: Task = self.task_manager.update_task(
                self.task.id,
                name=name,
                subject_id=subject_id,
                priority=priority,
                expected_time=expected_hours,
                deadline=deadline_dt,
                scheduled_date=sched_date,
            )

            # Close dialog first
            _close_dialog(self.page, self.dialog)

            # Intercept prediction message from update_task
            if hasattr(updated_task, "prediction_message") and updated_task.prediction_message:
                snack_message = updated_task.prediction_message
            else:
                snack_message = f"Задача '{updated_task.name}' успешно обновлена!"

            # Show prediction result via SnackBar
            _show_snack(self.page, snack_message)

            # Refresh list if callback provided
            if self.on_success:
                self.on_success()

        except Exception as err:
            self.name_field.error_text = f"Ошибка сохранения: {err}"
            self.page.update()

    def show(self) -> None:
        """Display the task editing dialog."""
        _show_dialog(self.page, self.dialog)


def open_task_edit_dialog(
    page: ft.Page,
    task: Task,
    task_manager: TaskManager | None = None,
    on_success: Callable[[], None] | None = None,
) -> TaskEditDialog:
    """Helper function to instantiate and show the task editing dialog."""
    form = TaskEditDialog(page, task=task, task_manager=task_manager, on_success=on_success)
    form.show()
    return form


class TaskCompleteDialog:
    """Dialog asking for actual time spent before completing a task."""

    def __init__(
        self,
        page: ft.Page,
        task_id: int,
        task_name: str,
        expected_time_hours: float | None = None,
        task_manager: TaskManager | None = None,
        on_success: Callable[[], None] | None = None,
    ) -> None:
        self.page = page
        self.task_id = task_id
        self.task_name = task_name
        self.task_manager = task_manager or TaskManager()
        self.on_success = on_success

        default_min = ""
        if expected_time_hours is not None:
            r = round(expected_time_hours * 60)
            default_min = str(r)

        self.time_field = ft.TextField(
            label="Фактическое время (в минутах)*",
            value=default_min,
            hint_text="Например: 45",
            autofocus=True,
            input_filter=ft.NumbersOnlyInputFilter(),
            keyboard_type=ft.KeyboardType.NUMBER,
        )

        FilledBtn = getattr(ft, "FilledButton", getattr(ft, "ElevatedButton", ft.TextButton))

        self.dialog = ft.AlertDialog(
            title=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.CHECK_CIRCLE_OUTLINE_ROUNDED, color=ft.Colors.GREEN_400, size=26),
                    ft.Text("Завершение задачи", weight=ft.FontWeight.BOLD, size=18),
                ],
                spacing=10,
            ),
            content=ft.Container(
                width=420,
                content=ft.Column(
                    tight=True,
                    spacing=12,
                    controls=[
                        ft.Text(
                            f"Задача: {self.task_name}",
                            weight=ft.FontWeight.W_600,
                            size=14,
                            color=ft.Colors.PRIMARY,
                        ),
                        ft.Text(
                            "Сколько минут вы фактически потратили на задачу?",
                            size=14,
                            color=ft.Colors.GREY_300,
                        ),
                        self.time_field,
                    ],
                ),
            ),
            actions=[
                ft.TextButton(
                    "Отмена",
                    on_click=lambda _: _close_dialog(self.page, self.dialog),
                ),
                FilledBtn(
                    "Подтвердить",
                    icon=ft.Icons.CHECK_ROUNDED,
                    on_click=lambda _: self._complete_task(),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

    def _complete_task(self) -> None:
        raw_val = (self.time_field.value or "").strip()
        if not raw_val:
            self.time_field.error_text = "Введите потраченное время"
            self.page.update()
            return

        try:
            minutes = float(raw_val)
            if minutes <= 0:
                self.time_field.error_text = "Время должно быть больше 0"
                self.page.update()
                return
        except ValueError:
            self.time_field.error_text = "Введите число"
            self.page.update()
            return

        actual_hours = round(minutes / 60.0, 4)

        try:
            self.task_manager.complete_task(self.task_id, actual_time=actual_hours)
            _close_dialog(self.page, self.dialog)

            min_display = int(minutes) if minutes.is_integer() else minutes
            _show_snack(
                self.page,
                f"Задача «{self.task_name}» завершена! Фактическое время ({min_display} мин) записано в историю.",
                bgcolor=ft.Colors.GREEN_800,
            )

            if self.on_success:
                self.on_success()
        except Exception as err:
            self.time_field.error_text = f"Ошибка: {err}"
            self.page.update()

    def show(self) -> None:
        """Display the complete task dialog."""
        _show_dialog(self.page, self.dialog)


def open_task_complete_dialog(
    page: ft.Page,
    task_id: int,
    task_name: str,
    expected_time_hours: float | None = None,
    task_manager: TaskManager | None = None,
    on_success: Callable[[], None] | None = None,
) -> TaskCompleteDialog:
    """Helper function to instantiate and show the task completion dialog."""
    form = TaskCompleteDialog(
        page,
        task_id=task_id,
        task_name=task_name,
        expected_time_hours=expected_time_hours,
        task_manager=task_manager,
        on_success=on_success,
    )
    form.show()
    return form


class TagDialog:
    """Modal dialog for creating or editing a Tag / Subject."""

    PRESET_ICONS = ["📚", "💻", "🔬", "📐", "🎨", "📝", "💡", "⚡", "🎯", "🌐", "🧪", "📈", "☕", "🚀", "🏷️", "💼"]
    PRESET_COLORS = ["#4CAF50", "#2196F3", "#9C27B0", "#FF9800", "#E91E63", "#F44336", "#00BCD4", "#FFC107", "#607D8B", "#3F51B5"]

    def __init__(
        self,
        page: ft.Page,
        tag: Subject | None = None,
        task_manager: TaskManager | None = None,
        on_success: Callable[[], None] | None = None,
    ) -> None:
        self.page = page
        self.tag = tag
        self.task_manager = task_manager or TaskManager()
        self.on_success = on_success

        is_edit = tag is not None
        title_text = "Редактирование тега" if is_edit else "Новый тег"
        title_icon = ft.Icons.EDIT_ROUNDED if is_edit else ft.Icons.LOCAL_OFFER_ROUNDED

        self.name_field = ft.TextField(
            label="Название тега / предмета*",
            value=tag.name if is_edit else "",
            hint_text="Например: Программирование",
            autofocus=True,
            on_change=lambda _: self._update_preview(),
        )

        self.icon_field = ft.TextField(
            label="UTF-иконка / Эмодзи*",
            value=tag.icon if is_edit else "🏷️",
            hint_text="Например: 💻",
            max_length=4,
            width=140,
            on_change=lambda _: self._update_preview(),
        )

        self.color_field = ft.TextField(
            label="Цвет (HEX-код)*",
            value=tag.color if is_edit else "#4CAF50",
            hint_text="#4CAF50",
            max_length=9,
            width=180,
            on_change=lambda _: self._update_preview(),
        )

        # Quick icon chips
        icon_chips = [
            ft.Container(
                content=ft.Text(ico, size=18),
                padding=6,
                border_radius=8,
                bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                ink=True,
                tooltip=f"Выбрать {ico}",
                on_click=lambda _, i=ico: self._select_icon(i),
            )
            for ico in self.PRESET_ICONS
        ]

        # Quick color circles
        color_chips = [
            ft.Container(
                width=26,
                height=26,
                border_radius=13,
                bgcolor=col,
                ink=True,
                tooltip=col,
                on_click=lambda _, c=col: self._select_color(c),
            )
            for col in self.PRESET_COLORS
        ]

        # Live preview container
        self.preview_text_icon = ft.Text("🏷️", size=16)
        self.preview_text_name = ft.Text("Предпросмотр тега", weight=ft.FontWeight.W_600, size=13)
        self.preview_container = ft.Container(
            padding=ft.Padding(left=12, top=6, right=12, bottom=6),
            border_radius=8,
            border=ft.Border.all(width=1, color="#4CAF50"),
            content=ft.Row(
                spacing=8,
                tight=True,
                controls=[
                    self.preview_text_icon,
                    self.preview_text_name,
                ],
            ),
        )

        FilledBtn = getattr(ft, "FilledButton", getattr(ft, "ElevatedButton", ft.TextButton))

        self.dialog = ft.AlertDialog(
            title=ft.Row(
                controls=[
                    ft.Icon(title_icon, color=ft.Colors.PRIMARY, size=26),
                    ft.Text(title_text, weight=ft.FontWeight.BOLD, size=20),
                ],
                spacing=10,
            ),
            content=ft.Container(
                width=480,
                content=ft.Column(
                    tight=True,
                    spacing=14,
                    controls=[
                        self.name_field,
                        ft.Row(
                            spacing=12,
                            controls=[
                                self.icon_field,
                                self.color_field,
                            ],
                        ),
                        ft.Text("Быстрый выбор иконки:", size=12, color=ft.Colors.GREY_400),
                        ft.Row(wrap=True, spacing=6, run_spacing=6, controls=icon_chips),
                        ft.Text("Быстрый выбор цвета:", size=12, color=ft.Colors.GREY_400),
                        ft.Row(wrap=True, spacing=8, run_spacing=8, controls=color_chips),
                        ft.Divider(height=1),
                        ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            controls=[
                                ft.Text("Внешний вид тега:", size=12, color=ft.Colors.GREY_400),
                                self.preview_container,
                            ],
                        ),
                    ],
                ),
            ),
            actions=[
                ft.TextButton(
                    "Отмена",
                    on_click=lambda _: _close_dialog(self.page, self.dialog),
                ),
                FilledBtn(
                    "Сохранить тег",
                    icon=ft.Icons.CHECK_ROUNDED,
                    on_click=lambda _: self._save_tag(),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self._update_preview()

    def _select_icon(self, icon: str) -> None:
        self.icon_field.value = icon
        self._update_preview()
        self.page.update()

    def _select_color(self, color: str) -> None:
        self.color_field.value = color
        self._update_preview()
        self.page.update()

    def _update_preview(self) -> None:
        icon = (self.icon_field.value or "🏷️").strip() or "🏷️"
        name = (self.name_field.value or "Название тега").strip() or "Название тега"
        color = (self.color_field.value or "#4CAF50").strip() or "#4CAF50"

        self.preview_container.border = ft.Border.all(width=1, color=color)
        self.preview_text_icon.value = icon
        self.preview_text_name.value = name

    def _save_tag(self) -> None:
        name = (self.name_field.value or "").strip()
        icon = (self.icon_field.value or "🏷️").strip() or "🏷️"
        color = (self.color_field.value or "#4CAF50").strip() or "#4CAF50"

        if not name:
            self.name_field.error_text = "Введите название тега"
            self.page.update()
            return

        try:
            if self.tag is None:
                self.task_manager.add_subject(name=name, color=color, icon=icon)
                msg = f"Тег «{name}» успешно создан!"
            else:
                self.task_manager.update_subject(self.tag.id, name=name, color=color, icon=icon)
                msg = f"Тег «{name}» успешно обновлен!"

            _close_dialog(self.page, self.dialog)
            _show_snack(self.page, msg, bgcolor=ft.Colors.GREEN_800)

            if self.on_success:
                self.on_success()
        except Exception as err:
            self.name_field.error_text = f"Ошибка: {err}"
            self.page.update()

    def show(self) -> None:
        _show_dialog(self.page, self.dialog)


def open_tag_dialog(
    page: ft.Page,
    tag: Subject | None = None,
    task_manager: TaskManager | None = None,
    on_success: Callable[[], None] | None = None,
) -> TagDialog:
    dlg = TagDialog(page, tag=tag, task_manager=task_manager, on_success=on_success)
    dlg.show()
    return dlg
