"""
One-off stock corrections, each applied once (keyed in release_notes_sent)
and reported to the admins.

2026-11-06 — B2B order #889 (05.11) was keyed with price and quantity in
each other's box: 6 000 kg × 50 so'm instead of 50 kg × 6 000 so'm. The
admin deleted it and keyed it again correctly as #897. A B2B order never
takes stock out, but deleting one used to put its quantities back in
(database.delete_order_permanently), so the delete ADDED 38 000 kg that
never existed: Kepak +6 000, Qora fermentlangan Solod 1kg +12 000,
Makkajo'xori uni +8 000, No'xat uni +12 000 — inflating the stock value on
the dashboard. These amounts are taken back out here.
"""
import logging

from aiogram import Bot

import database
from config import ADMIN_IDS

logger = logging.getLogger(__name__)

CORRECTIONS = {
    "stock-fix-b2b-889-2026-11-06": {
        "why": "B2B #889 o'chirilganda (miqdor va narx almashib qolgan edi) omborga qo'shilib qolgan miqdor",
        "lines": [(38, 6000), (35, 12000), (36, 8000), (51, 12000)],
    },
}


def _fmt(n: float) -> str:
    return f"{float(n):,.0f}".replace(",", " ") if float(n).is_integer() else f"{float(n):g}"


async def run_once(bot: Bot | None) -> None:
    for key, fix in CORRECTIONS.items():
        try:
            if not await database.claim_release_notes(key):
                continue
            done = await database.subtract_stock(fix["lines"])
        except Exception:
            logger.exception("Stock correction %s failed", key)
            continue
        logger.info("Stock correction %s: %s", key, done)
        if bot is None:
            continue
        lines = []
        for row in done:
            if row["applied"]:
                lines.append(f"• {row['name']}: {_fmt(row['before'])} → <b>{_fmt(row['after'])}</b> {row['unit'] or ''}".rstrip())
            else:
                lines.append(f"• {row['name']}: {_fmt(row['before'])} — o'zgartirilmadi (qoldiq ayiriladigandan kam)")
        text = ("🧮 <b>Ombor tuzatildi</b>\n"
                f"{fix['why']} ayirildi:\n" + "\n".join(lines) +
                "\n\nEndi qo'lda kiritilgan va B2B buyurtma o'chirilsa yoki bekor qilinsa, omborga hech narsa "
                "qaytarilmaydi — ular ombordan olinmagan ham.")
        for admin_id in list(dict.fromkeys(ADMIN_IDS)):
            try:
                await bot.send_message(admin_id, text, parse_mode="HTML")
            except Exception:
                logger.warning("Stock correction note to %s failed", admin_id, exc_info=True)
