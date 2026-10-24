"""
Saytning qulayligi haqida mijoz fikri (owner, 2026-10-13).

Mini App saytda bir daqiqadan ko'p bo'lgan mijozdan 5 yulduzcha va izoh
bilan "sayt qulaymi?" deb so'raydi; javob shu yerdan barcha adminlarga
botdan keladi. Hech narsa bazaga yozilmaydi — fikr adminlar chatida qoladi.

Public API:
  parse(data)                              -> (rating, comment) | None
  allow(user_id, now=None)                 -> False within COOLDOWN of the last one
  admin_text(user, user_id, rating, comment, lang) -> HTML message for admins
  notify_admins(bot, text)                 -> number of admins reached
  ask_due(asks, last_asked, answered, internal, now) -> whether to show the sheet

Who is asked (owner, 2026-10-24: "nega hadeb so'rayveryapti?"): the server
keeps one row per buyer (site_feedback_asks). A buyer who answered is never
asked again; one who didn't is asked at most MAX_ASKS times, ASK_AGAIN_DAYS
apart. Showing the sheet counts as asking, however the buyer leaves it.
Admin and shop accounts are not asked at all.
"""
import html
import logging
import time
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.enums import ParseMode

from config import ADMIN_IDS

logger = logging.getLogger(__name__)

MAX_COMMENT = 1000
COOLDOWN = 600          # one feedback per buyer per 10 minutes — a double tap
                        # or a scripted loop must not flood the admins' chat
ASK_AGAIN_DAYS = 30
MAX_ASKS = 2
_LANG_NAMES = {"uz": "o'zbek (lotin)", "uz_cyr": "o'zbek (kirill)", "ru": "rus"}
_last_sent: dict[int, float] = {}


def parse(data) -> tuple[int, str] | None:
    """Validated (rating, comment), or None when there is nothing to send.
    rating 0 means "no stars, comment only"; a comment may be empty when
    stars were given. Anything else is rejected."""
    if not isinstance(data, dict):
        return None
    rating = data.get("rating", 0)
    if isinstance(rating, bool) or not isinstance(rating, int) or not 0 <= rating <= 5:
        return None
    comment = data.get("comment") or ""
    if not isinstance(comment, str):
        return None
    comment = comment.strip()[:MAX_COMMENT]
    if rating == 0 and not comment:
        return None
    return rating, comment


def ask_due(asks: int, last_asked: datetime | None, answered: bool, internal: bool,
            now: datetime) -> bool:
    if internal or answered or asks >= MAX_ASKS:
        return False
    return last_asked is None or now - last_asked >= timedelta(days=ASK_AGAIN_DAYS)


def allow(user_id: int, now: float | None = None) -> bool:
    now = time.monotonic() if now is None else now
    last = _last_sent.get(user_id)
    if last is not None and now - last < COOLDOWN:
        return False
    _last_sent[user_id] = now
    return True


def _who(user: dict | None, user_id: int) -> str:
    user = user or {}
    name = " ".join(p for p in (user.get("first_name"), user.get("last_name")) if p).strip()
    parts = []
    if name:
        parts.append(html.escape(name))
    if user.get("username"):
        parts.append("@" + html.escape(user["username"]))
    return " · ".join(parts) or f"ID {user_id}"


def admin_text(user: dict | None, user_id: int, rating: int, comment: str, lang: str) -> str:
    stars = ("⭐" * rating + f"  <b>{rating}/5</b>") if rating else "— (yulduzcha qo'yilmadi)"
    body = html.escape(comment) if comment else "— (izoh yozilmadi)"
    return (
        "🌐 <b>Sayt haqida yangi fikr</b>\n"
        f"👤 {_who(user, user_id)} (ID: <code>{user_id}</code>)\n"
        f"Baho: {stars}\n"
        f"💬 Izoh: {body}\n"
        f"🗣 Til: {_LANG_NAMES.get(lang, lang)}"
    )


async def notify_admins(bot: Bot, text: str) -> int:
    sent = 0
    for admin_id in list(dict.fromkeys(ADMIN_IDS)):
        try:
            await bot.send_message(admin_id, text, parse_mode=ParseMode.HTML)
            sent += 1
        except Exception as exc:
            logger.warning("Site feedback to admin %s failed: %s", admin_id, exc)
    return sent
