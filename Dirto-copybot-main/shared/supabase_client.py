"""Singleton Supabase client."""

from __future__ import annotations

from typing import Optional

from supabase import Client, create_client

from shared.config import SUPABASE_KEY, SUPABASE_URL

_client: Optional[Client] = None


def get_supabase() -> Client:
    """Return a singleton Supabase client instance.

    Raises ``ValueError`` if SUPABASE_URL or SUPABASE_KEY are not configured.
    """
    global _client  # noqa: PLW0603
    if _client is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise ValueError(
                "SUPABASE_URL and SUPABASE_KEY must be set in environment variables"
            )
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client
