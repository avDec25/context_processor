"""
Database module for fetching prompts asynchronously.
Provides connection pooling and async prompt retrieval.
"""
import os
import asyncio
from typing import Optional
from pathlib import Path
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

# Load environment variables from .env.local.conf
env_path = Path(__file__).parent / '.env.local.conf'
load_dotenv(dotenv_path=env_path)

# Database configuration
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'port': os.getenv('DB_PORT', '5432'),
    'database': os.getenv('DB_NAME', 'context_processor'),
    'user': os.getenv('DB_USER', 'admin'),
    'password': os.getenv('DB_PASSWORD', 'securepassword')
}

# Connection pool (initialized on first use)
_connection_pool = None


def get_connection_pool():
    """Get or create the connection pool."""
    global _connection_pool
    if _connection_pool is None:
        _connection_pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=2,
            maxconn=10,
            **DB_CONFIG
        )
    return _connection_pool


def _fetch_prompt_sync(prompt_key: str) -> Optional[str]:
    """Synchronous function to fetch prompt from database."""
    pool = get_connection_pool()
    conn = None

    try:
        conn = pool.getconn()
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                "SELECT prompt_text FROM prompts WHERE key = %s",
                (prompt_key,)
            )
            result = cursor.fetchone()
            return result['prompt_text'] if result else None

    except psycopg2.Error as e:
        print(f"Database error fetching prompt '{prompt_key}': {e}")
        return None
    finally:
        if conn:
            pool.putconn(conn)


async def get_prompt(prompt_key: str) -> Optional[str]:
    """
    Fetch a prompt from the database asynchronously.

    Args:
        prompt_key: The key identifying the prompt (e.g., 'pr_review', 'confluence_explain')

    Returns:
        The prompt text if found, None otherwise
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch_prompt_sync, prompt_key)


async def get_prompt_with_data(prompt_key: str, **kwargs) -> Optional[str]:
    """
    Fetch a prompt and format it with provided data.

    Args:
        prompt_key: The key identifying the prompt
        **kwargs: Data to format into the prompt template

    Returns:
        The formatted prompt text if found, None otherwise
    """
    prompt_template = await get_prompt(prompt_key)
    if prompt_template:
        try:
            return prompt_template.format(**kwargs)
        except KeyError as e:
            print(f"Missing key in prompt data for '{prompt_key}': {e}")
            return None
    return None


def _list_prompts_sync() -> list:
    """Synchronous function to list all prompts from database."""
    pool = get_connection_pool()
    conn = None

    try:
        conn = pool.getconn()
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                "SELECT key, description, updated_at FROM prompts ORDER BY key"
            )
            return cursor.fetchall()

    except psycopg2.Error as e:
        print(f"Database error listing prompts: {e}")
        return []
    finally:
        if conn:
            pool.putconn(conn)


async def list_prompts() -> list:
    """
    List all prompts from the database.

    Returns:
        List of prompt dictionaries with key, description, and updated_at
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _list_prompts_sync)


def _update_prompt_sync(prompt_key: str, prompt_text: str) -> bool:
    """Synchronous function to update a prompt in the database."""
    pool = get_connection_pool()
    conn = None

    try:
        conn = pool.getconn()
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE prompts
                SET prompt_text = %s, updated_at = CURRENT_TIMESTAMP
                WHERE key = %s
                """,
                (prompt_text, prompt_key)
            )
            conn.commit()
            return cursor.rowcount > 0

    except psycopg2.Error as e:
        print(f"Database error updating prompt '{prompt_key}': {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            pool.putconn(conn)


async def update_prompt(prompt_key: str, prompt_text: str) -> bool:
    """
    Update a prompt's text in the database.

    Args:
        prompt_key: The key identifying the prompt
        prompt_text: The new prompt text

    Returns:
        True if updated successfully, False otherwise
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _update_prompt_sync, prompt_key, prompt_text)


def close_connection_pool():
    """Close all connections in the pool. Call this on application shutdown."""
    global _connection_pool
    if _connection_pool:
        _connection_pool.closeall()
        _connection_pool = None
