"""
Postgres-backed FSM storage for aiogram-3 — survives bot restarts so users
mid-checkout (e.g., waiting for a payment cheque) aren't wedged when the
process recycles.

Uses the existing global asyncpg pool from `database`; requires init_db()
to have run before any storage call.
"""
import json

from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, StorageKey

import database


class PostgresStorage(BaseStorage):
    _table_ready = False

    async def _ensure_table(self) -> None:
        if PostgresStorage._table_ready:
            return
        async with database.pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS fsm_state (
                    key TEXT PRIMARY KEY,
                    state TEXT,
                    data JSONB NOT NULL DEFAULT '{}'::jsonb,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        PostgresStorage._table_ready = True

    @staticmethod
    def _key(key: StorageKey) -> str:
        return f"{key.bot_id}:{key.chat_id}:{key.user_id}"

    async def set_state(self, key: StorageKey, state: State | str | None = None) -> None:
        await self._ensure_table()
        state_str = state.state if isinstance(state, State) else state
        async with database.pool.acquire() as conn:
            if state_str is None:
                # Clear both state and data so we don't keep stale rows around
                await conn.execute("DELETE FROM fsm_state WHERE key = $1", self._key(key))
            else:
                await conn.execute(
                    """
                    INSERT INTO fsm_state (key, state, updated_at)
                    VALUES ($1, $2, CURRENT_TIMESTAMP)
                    ON CONFLICT (key) DO UPDATE
                        SET state = EXCLUDED.state, updated_at = CURRENT_TIMESTAMP
                    """,
                    self._key(key), state_str,
                )

    async def get_state(self, key: StorageKey) -> str | None:
        await self._ensure_table()
        async with database.pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT state FROM fsm_state WHERE key = $1", self._key(key)
            )

    async def set_data(self, key: StorageKey, data: dict) -> None:
        await self._ensure_table()
        async with database.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO fsm_state (key, data, updated_at)
                VALUES ($1, $2::jsonb, CURRENT_TIMESTAMP)
                ON CONFLICT (key) DO UPDATE
                    SET data = EXCLUDED.data, updated_at = CURRENT_TIMESTAMP
                """,
                self._key(key), json.dumps(data, default=str, ensure_ascii=False),
            )

    async def get_data(self, key: StorageKey) -> dict:
        await self._ensure_table()
        async with database.pool.acquire() as conn:
            row = await conn.fetchval(
                "SELECT data FROM fsm_state WHERE key = $1", self._key(key)
            )
        if row is None:
            return {}
        if isinstance(row, str):
            return json.loads(row)
        return row

    async def close(self) -> None:
        # Pool lifecycle is owned by database.close_db() — nothing to do here.
        return
