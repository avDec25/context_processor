import psycopg2
import json
import logging
import os
from pathlib import Path
from psycopg2.extras import Json
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


def get_connection():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        return conn
    except Exception as e:
        logger.error("Error connecting to DB: %s", e)
        return None


def write_pr_ai_response(pr_id, ai_responses):
    conn = get_connection()
    if not conn:
        return

    try:
        with conn.cursor() as cur:
            sql = """
            INSERT INTO pull_requests (pr_id, ai_responses) 
            VALUES (%s, %s)
            ON CONFLICT (pr_id) 
            DO UPDATE SET 
                ai_responses = pull_requests.ai_responses || EXCLUDED.ai_responses;
            """

            cur.execute(sql, (pr_id, Json(ai_responses)))

        conn.commit()
        logger.info("PR #%s saved (inserted or merged).", pr_id)

    except Exception as e:
        logger.error("Error saving PR #%s: %s", pr_id, e)
        conn.rollback()
    finally:
        conn.close()


def read_pr_ai_response(pr_id):
    conn = get_connection()
    if not conn:
        return

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT ai_responses FROM pull_requests WHERE pr_id = %s", (pr_id,))
            row = cur.fetchone()
            if row:
                logger.info("Cache hit for PR #%s.", pr_id)
                return row[0]
            else:
                logger.info("No cached response for PR #%s.", pr_id)
                return None
    finally:
        conn.close()


def delete_pr_ai_response(pr_id):
    conn = get_connection()
    if not conn:
        return False

    try:
        with conn.cursor() as cur:
            sql = "DELETE FROM pull_requests WHERE pr_id = %s"
            cur.execute(sql, (pr_id,))
            rows_deleted = cur.rowcount

        conn.commit()

        if rows_deleted > 0:
            logger.info("PR #%s deleted.", pr_id)
            return True
        else:
            logger.warning("PR #%s not found, nothing deleted.", pr_id)
            return False

    except Exception as e:
        logger.error("Error deleting PR #%s: %s", pr_id, e)
        conn.rollback()
        return False
    finally:
        conn.close()
