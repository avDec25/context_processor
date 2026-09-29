"""
Database module for fetching prompts asynchronously.
Provides connection pooling and async prompt retrieval.
"""
import logging
import os
import asyncio
import re
from typing import Optional
from pathlib import Path
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

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

CONFLUENCE_PROMPT_FIELDS = {
    "confluence_explain": {"confluence_content"},
    "confluence_rewrite": {"confluence_content"},
    "confluence_page_update": {"confluence_content", "instruction"},
}


def validate_prompt_template(prompt_key: str, prompt_text: str):
    required = CONFLUENCE_PROMPT_FIELDS.get(prompt_key, set())
    missing = [field for field in sorted(required) if "{" + field + "}" not in prompt_text]
    if missing:
        raise ValueError(f"Prompt '{prompt_key}' is missing placeholders: {', '.join(missing)}")


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
        logger.error("Database error fetching prompt '%s': %s", prompt_key, e)
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
        validate_prompt_template(prompt_key, prompt_template)
        missing = CONFLUENCE_PROMPT_FIELDS.get(prompt_key, set()) - kwargs.keys()
        if missing:
            raise ValueError(f"Missing prompt inputs: {', '.join(sorted(missing))}")
        # Replace only original placeholders, never tokens inside inserted data.
        pattern = "|".join(re.escape("{" + key + "}") for key in kwargs)
        if not pattern:
            return prompt_template
        return re.sub(pattern, lambda match: str(kwargs[match.group(0)[1:-1]]), prompt_template)
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
        logger.error("Database error listing prompts: %s", e)
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
        logger.error("Database error updating prompt '%s': %s", prompt_key, e)
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
    validate_prompt_template(prompt_key, prompt_text)
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _update_prompt_sync, prompt_key, prompt_text)


def close_connection_pool():
    """Close all connections in the pool. Call this on application shutdown."""
    global _connection_pool
    if _connection_pool:
        _connection_pool.closeall()
        _connection_pool = None
