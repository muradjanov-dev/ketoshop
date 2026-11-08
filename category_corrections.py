"""
One-off category name fixes, each set applied once (keyed in
release_notes_sent) so an admin's later rename is never written over.

2026-11-08 — owner: "kategoriya nomlaridagi imloviy xatolarni ham tuzat".
Category names live in the `categories` table (seeded from locales.py once,
then edited and added to by admins), so the fix goes to the rows. A name is
only changed while it still reads exactly as the misspelt one — if an admin
already corrected it, it is left alone. The empty duplicate «Shokolad
marmalat» (made five minutes before «SHOKOLAD MARMALAD», no products in it)
is hidden, not deleted.
"""
import logging

import database

logger = logging.getLogger(__name__)

# key -> {column: (misspelt, correct)}
FIXES = {
    "category-names-2026-11-08": {
        "keto_flour": {"name_uz": ("🥣 Keto & Glutensiz unlar", "🥣 Keto & glyutensiz unlar")},
        "ziravorlar": {"name_ru": ("🫙 Ziravorlar", "🫙 Специи")},
        "keto_muzqaymoqlari": {"name_uz": ("🍦 Keto Muzqaymoqlari", "🍦 Keto muzqaymoqlari"),
                               "name_ru": ("🍦 Keto Muzqaymoqlari", "🍦 Кето-мороженое")},
        "makaronlar": {"name_uz": ("makaronlar", "🍝 Makaronlar"),
                       "name_ru": ("makaronlar", "🍝 Макароны")},
        "kofe": {"name_uz": ("Koʻfe", "☕ Kofe"), "name_ru": ("Koʻfe", "☕ Кофе")},
        "shokolad_marmalad": {"name_uz": ("SHOKOLAD MARMALAD", "🍫 Shokolad va marmelad"),
                              "name_ru": ("SHOKOLAD MARMALAD", "🍫 Шоколад и мармелад")},
        "shokolad_marmalat": {"name_uz": ("Shokolad marmalat", "🍫 Shokolad va marmelad"),
                              "name_ru": ("Shokolad marmalat", "🍫 Шоколад и мармелад")},
    },
}
# Hidden when they hold no product at all (active or not).
HIDE_IF_EMPTY = {"category-names-2026-11-08": ["shokolad_marmalat"]}


async def apply(key: str) -> list[str]:
    """The changes made, as short lines for the log."""
    done = []
    async with database.pool.acquire() as conn:
        for cat_key, columns in FIXES[key].items():
            for column, (wrong, right) in columns.items():
                changed = await conn.fetchval(
                    f"UPDATE categories SET {column} = $3 WHERE key = $1 AND {column} = $2 RETURNING key",
                    cat_key, wrong, right)
                if changed:
                    done.append(f"{cat_key}.{column}: {wrong} → {right}")
        for cat_key in HIDE_IF_EMPTY.get(key, []):
            hidden = await conn.fetchval(
                "UPDATE categories SET is_active = 0 WHERE key = $1 AND is_active = 1 "
                "AND NOT EXISTS (SELECT 1 FROM products WHERE category = $1) RETURNING key", cat_key)
            if hidden:
                done.append(f"{cat_key}: yashirildi (bo'sh takror)")
    return done


async def run_once() -> None:
    for key in FIXES:
        try:
            if not await database.claim_release_notes(key):
                continue
            done = await apply(key)
            # Every name the bot and the site show is read from locales.
            await database.sync_categories_to_locales()
        except Exception:
            logger.exception("Category correction %s failed", key)
            continue
        logger.info("Category correction %s: %s", key, done or "nothing to change")
