"""Entry point for the Pladaptive application."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import flet as ft
from core.task_manager import TaskManager
from gui.app import main_view

# Compatibility shim: Flet 0.x provides ft.app, Flet 1.x provides ft.run
if not hasattr(ft, "app"):
    def _app(target=None, **kwargs):
        fn = target or kwargs.pop("main", None)
        return ft.run(fn, **kwargs)
    ft.app = _app


def main(page: ft.Page) -> None:
    """Entry point for Flet page initialization."""
    main_view(page)


if __name__ == "__main__":
    # Initialize database tables if not created
    TaskManager().init_db()

    # Launch GUI application
    ft.app(target=main)
