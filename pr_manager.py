import psycopg2
import json
from psycopg2.extras import Json

DB_CONFIG = {
    "dbname": "context_processor",
    "user": "admin",
    "password": "securepassword",
    "host": "localhost",
    "port": "5432"
}


def get_connection():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        return conn
    except Exception as e:
        print(f"Error connecting to DB: {e}")
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
        print(f"PR #{pr_id} processed successfully (Inserted or Merged).")

    except Exception as e:
        print(f"Error processing PR #{pr_id}: {e}")
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
                print(f"\nFound PR #{pr_id}:")
                print(f"  AI Responses: {json.dumps(row[0], indent=2)}")
                return row[0]
            else:
                print(f"PR #{pr_id} not found.")
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
            print(f"PR #{pr_id} deleted successfully.")
            return True
        else:
            print(f"PR #{pr_id} not found. Nothing deleted.")
            return False

    except Exception as e:
        print(f"Error deleting PR #{pr_id}: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()
