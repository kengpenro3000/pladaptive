"""Form dialog for creating a new task.

Collects task details (name, subject, expected time in minutes, priority,
deadline), calls TaskManager().add_task(), and displays the AI-predicted time
via a SnackBar.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Callable

# Ensure root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import flet as ft

from core.task_manager import TaskManager
from database.models import Task, TaskPriority


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
            ft.dropdown.Option(key=str(s.id), text=s.name)
            for s in subjects
        ]
        self.subject_dropdown = ft.Dropdown(
            label="Предмет*",
            hint_text="Выберите предмет",
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

        self.deadline_field = ft.TextField(
            label="Дедлайн (необязательно)",
            hint_text="ГГГГ-ММ-ДД (например: 2026-12-01)",
            icon=ft.Icons.CALENDAR_MONTH_ROUNDED,
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
                    spacing=14,
                    controls=[
                        self.name_field,
                        self.subject_dropdown,
                        self.time_field,
                        self.priority_dropdown,
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

        # Subject
        subject_id_raw = self.subject_dropdown.value
        if not subject_id_raw:
            self.subject_dropdown.error_text = "Выберите предмет"
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

        # Deadline
        deadline_dt: datetime | None = None
        if self.deadline_field.value:
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
            return False, name, None, None, priority, None

        subject_id = int(subject_id_raw)
        return True, name, subject_id, expected_hours, priority, deadline_dt

    def _save_task(self) -> None:
        """Validate, save task via TaskManager, display SnackBar, and close."""
        valid, name, subject_id, expected_hours, priority, deadline_dt = self._validate()
        if not valid or subject_id is None:
            return

        try:
            task: Task = self.task_manager.add_task(
                name=name,
                subject_id=subject_id,
                priority=priority,
                expected_time=expected_hours,
                deadline=deadline_dt,
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
            ft.dropdown.Option(key=str(s.id), text=s.name)
            for s in subjects
        ]
        self.subject_dropdown = ft.Dropdown(
            label="Предмет*",
            hint_text="Выберите предмет",
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

        initial_deadline = task.deadline.strftime("%Y-%m-%d") if task.deadline else ""
        self.deadline_field = ft.TextField(
            label="Дедлайн (необязательно)",
            value=initial_deadline,
            hint_text="ГГГГ-ММ-ДД (например: 2026-12-01)",
            icon=ft.Icons.CALENDAR_MONTH_ROUNDED,
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
                    spacing=14,
                    controls=[
                        self.name_field,
                        self.subject_dropdown,
                        self.time_field,
                        self.priority_dropdown,
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

        # Subject
        subject_id_raw = self.subject_dropdown.value
        if not subject_id_raw:
            self.subject_dropdown.error_text = "Выберите предмет"
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

        # Deadline
        deadline_dt: datetime | None = None
        if self.deadline_field.value:
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
            return False, name, None, None, priority, None

        subject_id = int(subject_id_raw)
        return True, name, subject_id, expected_hours, priority, deadline_dt

    def _save_task(self) -> None:
        """Validate, update task via TaskManager, display SnackBar, and close."""
        valid, name, subject_id, expected_hours, priority, deadline_dt = self._validate()
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
