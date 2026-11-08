"""Kategoriya nomlaridagi imlo xatolari (egasi, 2026-11-08). The SQL runs
against an in-memory SQLite copy of the prod rows as they were that day."""
import asyncio
import contextlib
import os
import re
import sqlite3
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://unused/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import category_corrections as cc
import database
import locales

ROWS = [  # key, name_uz, name_ru — as on prod, 2026-11-08
    ("keto_flour", "🥣 Keto & Glutensiz unlar", "🥣 Кето и безглютеновые муки"),
    ("ziravorlar", "🫙 Ziravorlar", "🫙 Ziravorlar"),
    ("keto_muzqaymoqlari", "🍦 Keto Muzqaymoqlari", "🍦 Keto Muzqaymoqlari"),
    ("makaronlar", "makaronlar", "makaronlar"),
    ("kofe", "Koʻfe", "Koʻfe"),
    ("shokolad_marmalat", "Shokolad marmalat", "Shokolad marmalat"),
    ("shokolad_marmalad", "SHOKOLAD MARMALAD", "SHOKOLAD MARMALAD"),
    ("salt", "🧂 Tuz", "🧂 Соль"),
]


class Conn:
    def __init__(self):
        self.db = sqlite3.connect(":memory:")
        self.db.execute("CREATE TABLE categories (key TEXT PRIMARY KEY, name_uz TEXT, name_ru TEXT, is_active INTEGER DEFAULT 1)")
        self.db.execute("CREATE TABLE products (id INTEGER PRIMARY KEY, category TEXT)")
        self.db.executemany("INSERT INTO categories (key, name_uz, name_ru) VALUES (?,?,?)", ROWS)
        self.db.executemany("INSERT INTO products (category) VALUES (?)", [("shokolad_marmalad",), ("kofe",)])

    async def fetchval(self, sql, *args):
        positions = [int(n) - 1 for n in re.findall(r"\$(\d+)", sql)]
        row = self.db.execute(re.sub(r"\$\d+", "?", sql), tuple(args[i] for i in positions)).fetchone()
        return row[0] if row else None

    def get(self, key):
        return self.db.execute("SELECT name_uz, name_ru, is_active FROM categories WHERE key = ?", (key,)).fetchone()


class Pool:
    def __init__(self, conn):
        self.conn = conn

    @contextlib.asynccontextmanager
    async def acquire(self):
        yield self.conn


class CorrectionTest(unittest.TestCase):
    def run_it(self, conn, claimed=True):
        sync = AsyncMock()
        with patch.object(database, "pool", Pool(conn)), \
             patch.object(database, "claim_release_notes", AsyncMock(return_value=claimed)), \
             patch.object(database, "sync_categories_to_locales", sync):
            asyncio.run(cc.run_once())
        return sync

    def test_names_fixed(self):
        conn = Conn()
        sync = self.run_it(conn)
        self.assertEqual(conn.get("keto_flour")[0], "🥣 Keto & glyutensiz unlar")
        self.assertEqual(conn.get("keto_flour")[1], "🥣 Кето и безглютеновые муки")   # ru was right
        self.assertEqual(conn.get("kofe")[:2], ("☕ Kofe", "☕ Кофе"))
        self.assertEqual(conn.get("makaronlar")[:2], ("🍝 Makaronlar", "🍝 Макароны"))
        self.assertEqual(conn.get("keto_muzqaymoqlari")[:2], ("🍦 Keto muzqaymoqlari", "🍦 Кето-мороженое"))
        self.assertEqual(conn.get("ziravorlar")[:2], ("🫙 Ziravorlar", "🫙 Специи"))
        self.assertEqual(conn.get("shokolad_marmalad"), ("🍫 Shokolad va marmelad", "🍫 Шоколад и мармелад", 1))
        self.assertEqual(conn.get("salt"), ("🧂 Tuz", "🧂 Соль", 1))                    # untouched
        sync.assert_awaited_once()                                                    # bot and site read it now

    def test_empty_duplicate_hidden_full_one_kept(self):
        conn = Conn()
        self.run_it(conn)
        self.assertEqual(conn.get("shokolad_marmalat")[2], 0)
        self.assertEqual(conn.get("shokolad_marmalad")[2], 1)

    def test_admin_rename_is_never_overwritten(self):
        conn = Conn()
        conn.db.execute("UPDATE categories SET name_uz = '☕ Qahva' WHERE key = 'kofe'")
        self.run_it(conn)
        self.assertEqual(conn.get("kofe")[0], "☕ Qahva")

    def test_runs_once(self):
        conn = Conn()
        sync = self.run_it(conn, claimed=False)
        self.assertEqual(conn.get("kofe")[0], "Koʻfe")
        sync.assert_not_awaited()

    def test_seed_spelling(self):
        self.assertEqual(locales.TEXTS["cat_keto_flour"]["uz"], "🥣 Keto & glyutensiz unlar")
        from translit import lat_to_cyr
        self.assertIn("глютенсиз", lat_to_cyr("glyutensiz"))


if __name__ == "__main__":
    unittest.main()
