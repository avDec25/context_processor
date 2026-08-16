import logging
import os
import re
from pathlib import Path

import psycopg2
from psycopg2.extras import Json, RealDictCursor
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load environment variables from .env.local.conf
env_path = Path(__file__).parent / '.env.local.conf'
load_dotenv(dotenv_path=env_path)

DB_CONFIG = {
    "dbname": os.getenv("DB_NAME", "context_processor"),
    "user": os.getenv("DB_USER", "admin"),
    "password": os.getenv("DB_PASSWORD", "securepassword"),
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5432")
}


_TODO_ITEM_RE = re.compile(r"^\s*[-*+]\s+\[([ xX])\]\s+(.+?)\s*$", re.MULTILINE)


def extract_todos(ai_summary: str) -> list[dict]:
    """Extract Markdown task-list items from an AI-generated email summary."""
    return [
        {
            "id": f"todo-{index}",
            "text": match.group(2),
            "completed": match.group(1).lower() == "x",
        }
        for index, match in enumerate(_TODO_ITEM_RE.finditer(ai_summary or ""), start=1)
    ]


def get_connection():
    try:
        return psycopg2.connect(**DB_CONFIG)
    except Exception as e:
        logger.error("Error connecting to DB: %s", e)
        return None


def write_email_summary(record: dict) -> None:
    conn = get_connection()
    if not conn:
        return

    try:
        with conn.cursor() as cur:
            sql = """
            INSERT INTO email_summaries
                (interval_key, folder, start_date, end_date, email_count, emails, ai_summary, todos)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (interval_key)
            DO UPDATE SET
                folder = EXCLUDED.folder,
                start_date = EXCLUDED.start_date,
                end_date = EXCLUDED.end_date,
                email_count = EXCLUDED.email_count,
                emails = EXCLUDED.emails,
                ai_summary = EXCLUDED.ai_summary,
                todos = EXCLUDED.todos,
                updated_on = NOW() AT TIME ZONE 'Asia/Tokyo';
            """
            cur.execute(sql, (
                record['interval_key'], record['folder'], record['start_date'], record['end_date'],
                record['email_count'], Json(record['emails']), record['ai_summary'], Json(record.get('todos', [])),
            ))

        conn.commit()
        logger.info("Email summary %s saved (inserted or updated).", record['interval_key'])

    except Exception as e:
        logger.error("Error saving email summary %s: %s", record.get('interval_key'), e)
        conn.rollback()
    finally:
        conn.close()


def read_email_summary(interval_key: str):
    conn = get_connection()
    if not conn:
        return None

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT interval_key, folder, start_date, end_date, email_count, emails, ai_summary, todos,
                       created_on, updated_on
                FROM email_summaries
                WHERE interval_key = %s
                """,
                (interval_key,)
            )
            row = cur.fetchone()
            if row:
                logger.info("Cache hit for email summary %s.", interval_key)
                return dict(row)
            logger.info("No cached email summary for %s.", interval_key)
            return None
    finally:
        conn.close()


def delete_email_summary(interval_key: str) -> bool:
    conn = get_connection()
    if not conn:
        return False

    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM email_summaries WHERE interval_key = %s", (interval_key,))
            rows_deleted = cur.rowcount

        conn.commit()

        if rows_deleted > 0:
            logger.info("Email summary %s deleted.", interval_key)
            return True
        logger.warning("Email summary %s not found, nothing deleted.", interval_key)
        return False

    except Exception as e:
        logger.error("Error deleting email summary %s: %s", interval_key, e)
        conn.rollback()
        return False
    finally:
        conn.close()


def save_email_todo(interval_key: str, todo_id: str, completed: bool) -> list[dict] | None:
    """Persist one todo checkbox and return the updated list, or ``None`` if absent.

    The row lock makes simultaneous checkbox updates safe: each update starts from
    the most recently stored todo list.
    """
    conn = get_connection()
    if not conn:
        return None

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT todos FROM email_summaries WHERE interval_key = %s FOR UPDATE",
                (interval_key,),
            )
            row = cur.fetchone()
            if not row:
                conn.rollback()
                return None

            todos = row["todos"] or []
            todo = next((item for item in todos if item.get("id") == todo_id), None)
            if not todo:
                conn.rollback()
                return None

            todo["completed"] = completed
            cur.execute(
                """
                UPDATE email_summaries
                SET todos = %s, updated_on = NOW() AT TIME ZONE 'Asia/Tokyo'
                WHERE interval_key = %s
                """,
                (Json(todos), interval_key),
            )
        conn.commit()
        return todos
    except Exception as e:
        logger.error("Error saving todo %s for email summary %s: %s", todo_id, interval_key, e)
        conn.rollback()
        return None
    finally:
        conn.close()
