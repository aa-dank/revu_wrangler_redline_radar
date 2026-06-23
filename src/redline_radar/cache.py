from pathlib import Path
import sqlite3
from datetime import datetime, UTC
from redline_radar.config import TOKEN_DIR
TOKEN_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = TOKEN_DIR / "cache.db" # move this to where tokens.json are

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def initialize_db():
    with get_connection() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS session_cache (
            session_id TEXT PRIMARY KEY,
            activity_count INTEGER NOT NULL,
            latest_activity_id INTEGER NOT NULL, 
            last_synced TEXT NOT NULL
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS activities (
            session_id TEXT NOT NULL,
            activity_id INTEGER NOT NULL,
            document_id TEXT,
            user_id TEXT,
            message TEXT,
            created TEXT,
            PRIMARY KEY(session_id, activity_id)
        )
        """)
        
# ---------------------------------------------------------------------------
# Session Cache
# ---------------------------------------------------------------------------
def save_session_cache(session_id: str, activities: list[dict]):
    if not activities: return

    activity_count = len(activities)
    latest_activity_id = max(int(activity["Id"]) for activity in activities)

    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO session_cache (
                session_id,
                activity_count,
                latest_activity_id,
                last_synced
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                session_id,
                activity_count,
                latest_activity_id,
                datetime.now(UTC).isoformat(),
            )
        )

def load_session_cache(session_id: str) -> tuple[int, int, str] | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT 
                activity_count,
                latest_activity_id,
                last_synced
            FROM session_cache
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()

    if row is None: return None
    return (
        row["activity_count"],
        row["latest_activity_id"],
        row["last_synced"],
    )

# ---------------------------------------------------------------------------
# Activities
# ---------------------------------------------------------------------------
def save_activities(session_id: str, activities: list[dict]):
    with get_connection() as conn:
        conn.executemany(
            """
            INSERT OR IGNORE INTO activities (
                session_id,
                activity_id,
                document_id,
                user_id,
                message,
                created
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    session_id,
                    activity["Id"],
                    activity.get("DocumentId"),
                    activity.get("UserId"),
                    activity.get("Message"),
                    activity.get("Created"),
                )
                for activity in activities
            ],
        )

def load_activities(session_id: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT 
                activity_id,
                document_id,
                user_id,
                message,
                created
            FROM activities
            WHERE session_id = ?
            ORDER BY activity_id
            """,
            (session_id,),
        ).fetchall()

    return [
        {
            "Id": row["activity_id"],
            "DocumentId": row["document_id"],
            "UserId": row["user_id"],
            "Message": row["message"],
            "Created": row["created"],
        }
        for row in rows
    ]

def get_latest_activity_id(session_id: str) -> int | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT MAX(activity_id) AS max_id
            FROM activities
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()
    return row["max_id"] if row else None

# ---------------------------------------------------------------------------
# Validation & Check for Content
# ---------------------------------------------------------------------------
def validate_cache(session_id: str, expected_count: int) -> tuple[bool, int]:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*)
            FROM activities
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()
    cached_count = row[0]

    return (cached_count == expected_count, cached_count)

def has_session_cache(session_id: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM session_cache
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()

    return row[0] > 0

def has_cached_activities(session_id: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*)
            FROM activities
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()

    return row[0] > 0

# ---------------------------------------------------------------------------
# Clear Cache
# ---------------------------------------------------------------------------
def clear_session_cache(session_id: str):
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM session_cache WHERE session_id = ?",
            (session_id,),
        )
        conn.execute(
            "DELETE FROM activities WHERE session_id = ?",
            (session_id,),
        )