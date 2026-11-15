"""SQLAlchemy 2.0 engine and session configuration for SQLite."""

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# ---------- paths ----------
# planner.db lives next to the project root (i.e. beside the `database/` package).
_BASE_DIR = Path(__file__).resolve().parent.parent
DATABASE_URL = f"sqlite:///{_BASE_DIR / 'planner.db'}"

# ---------- engine ----------
engine = create_engine(
    DATABASE_URL,
    echo=False,
    # SQLite requires this so that foreign-key constraints are enforced.
    connect_args={"check_same_thread": False},
)

# ---------- session factory ----------
SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


# ---------- helpers ----------
def get_session():
    """Context-manager / generator that yields a session and closes it afterward.

    Usage::

        with get_session() as session:
            ...
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def init_db() -> None:
    """Create all tables that don't yet exist in the database and ensure columns exist."""
    from database.models import Base  # local import to avoid circular deps

    Base.metadata.create_all(bind=engine)

    # SQLite migration: ensure color and icon columns exist on subjects table
    with engine.connect() as conn:
        res = conn.exec_driver_sql("PRAGMA table_info(subjects)").fetchall()
        cols = [r[1] for r in res]
        if "color" not in cols:
            conn.exec_driver_sql("ALTER TABLE subjects ADD COLUMN color VARCHAR(32) NOT NULL DEFAULT '#4CAF50'")
        if "icon" not in cols:
            conn.exec_driver_sql("ALTER TABLE subjects ADD COLUMN icon VARCHAR(16) NOT NULL DEFAULT '🏷️'")

        # Ensure scheduled_date column exists on tasks table
        res_tasks = conn.exec_driver_sql("PRAGMA table_info(tasks)").fetchall()
        cols_tasks = [r[1] for r in res_tasks]
        if "scheduled_date" not in cols_tasks:
            conn.exec_driver_sql("ALTER TABLE tasks ADD COLUMN scheduled_date DATE")

        # Ensure completed_at column exists on tasks table
        if "completed_at" not in cols_tasks:
            conn.exec_driver_sql("ALTER TABLE tasks ADD COLUMN completed_at DATE")
            conn.exec_driver_sql("""
                UPDATE tasks
                SET completed_at = (
                    SELECT completed_at FROM history
                    WHERE history.task_id = tasks.id
                    ORDER BY history.id DESC
                    LIMIT 1
                )
                WHERE tasks.status = 'completed' AND tasks.completed_at IS NULL
            """)

        conn.commit()
