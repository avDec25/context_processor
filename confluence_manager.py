import requests
import psycopg2
import json
from psycopg2.extras import Json

# --- Configuration ---
DB_CONFIG = {
    "dbname": "context_processor",
    "user": "admin",
    "password": "securepassword",
    "host": "localhost",
    "port": "5432"
}

# https://confluence.rakuten-it.com/confluence/spaces/IBH/pages/6420926933/2.+Investigation+-+Genre+History+Upgrade+and+SyncBatch+Abolishment
confluence_url = "https://confluence.rakuten-it.com/confluence"
page_id = "6420926933"
personal_access_token = "REDACTED"
api_url = f"{confluence_url}/rest/api/content/{page_id}?expand=body.storage"
headers = {
    "Authorization": f"Bearer {personal_access_token}",
    "Accept": "application/json"
}


def get_connection():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        return conn
    except Exception as e:
        print(f"Error connecting to DB: {e}")
        return None


def write_confluence_ai_response(confluence_id, ai_responses):
    conn = get_connection()
    if not conn:
        return

    try:
        with conn.cursor() as cur:
            sql = """
            INSERT INTO confluence (confluence_id, ai_responses) 
            VALUES (%s, %s)
            ON CONFLICT (confluence_id) 
            DO UPDATE SET 
                ai_responses = confluence.ai_responses || EXCLUDED.ai_responses;
            """

            cur.execute(sql, (confluence_id, Json(ai_responses)))

        conn.commit()
        print(f"Confluence #{confluence_id} processed successfully (Inserted or Merged).")

    except Exception as e:
        print(f"Error processing Confluence #{confluence_id}: {e}")
        conn.rollback()
    finally:
        conn.close()


def read_confluence_ai_response(confluence_id):
    conn = get_connection()
    if not conn:
        return

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT ai_responses FROM confluence WHERE confluence_id = %s", (confluence_id,))
            row = cur.fetchone()
            if row:
                print(f"\nFound Confluence #{confluence_id}:")
                print(f"  AI Responses: {json.dumps(row[0], indent=2)}")
                return row[0]
            else:
                print(f"Confluence #{confluence_id} not found.")
                return None
    finally:
        conn.close()


def delete_confluence_ai_response(confluence_id):
    conn = get_connection()
    if not conn:
        return False

    try:
        with conn.cursor() as cur:
            sql = "DELETE FROM confluence WHERE confluence_id = %s"
            cur.execute(sql, (confluence_id,))
            rows_deleted = cur.rowcount

        conn.commit()

        if rows_deleted > 0:
            print(f"Confluence #{confluence_id} deleted successfully.")
            return True
        else:
            print(f"Confluence #{confluence_id} not found. Nothing deleted.")
            return False

    except Exception as e:
        print(f"Error deleting Confluence #{confluence_id}: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()