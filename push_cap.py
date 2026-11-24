"""Bitta userga kuniga nechta rejali xabar — umumiy chegara (egasi, 2026-11-15:
"kuniga 3–3,5 ta bu juda ko'p, maximum 2 ta, 3 kun ichida botda umuman tugma
bosmasa unda 1 ta kuniga" va "Hali xarid qilmagan user … maximum 1 ta").

2026-11-24, egasi: "xabarlarni qisqartirish kerak, ular sog'inishlari kerak" —
haftasiga 3 / 2, kuniga 1, orasida kamida 1 kun bo'sh, shaxsiylari oldin.

Chegara (Toshkent kuni, hafta — bugun bilan oxirgi 7 kun):
  * xaridor (bekor qilinmagan buyurtmasi bor) va oxirgi QUIET_AFTER_DAYS kunda
    botda tugma bosgan, yozgan yoki saytni ishlatgan — kuniga ACTIVE_BUYER_MAX (1),
    haftasiga ACTIVE_BUYER_WEEK (3);
  * qolgan hamma — xarid qilmaganlar va 3 kundan beri jimlar — kuniga QUIET_MAX (1),
    haftasiga QUIET_WEEK (2);
  * kecha xabar ketgan bo'lsa — bugun yo'q (GAP_DAYS);
  * ustunlik (reserve_for): past turlar haftalik o'rinni muhimlariga qoldiradi.

Rejali, hammaga boradigan xabarlar shu darvozadan o'tadi (claim): maslahat,
shaxsiy tavsiya, aksiya ko'rgazmasi/e'loni, kun mahsuloti, qiziqish eslatmasi,
Keto savol, qayta sotuv, tashlab ketilgan savat, sovg'a kampaniyasi e'loni.
Kun ichida birinchi kelgan yuboradi: 07:30 o'yin seriyasi eslatmasi → 08:00 maslahat → 09:30 qayta sotuv →
10:00 tavsiya → 12:00 aksiya → 13:00 kun mahsuloti → 18:00 qiziqish →
20:00 Keto savol.

Darvozadan o'tmaydi (hisobga ham kirmaydi): buyurtma va to'lov xabarlari, odam
o'zi so'ragani («Kelganda xabar bering», AI suhbat), yangi a'zoning birinchi
kungi tanishuvi (til, video, 100 Keto, YANGI5), admin qo'lda yuborgan xabar.
"""
from __future__ import annotations

import logging

import database

logger = logging.getLogger(__name__)

# Egasi, 2026-11-24: "ularga boradigan xabarlarni qisqartirish kerak, ular sog'inishlari kerak" —
# tanlovi: haftasiga 3 / 2, kuniga 1, orasida kamida 1 kun bo'sh; shaxsiylari oldin.
ACTIVE_BUYER_MAX = 1           # kuniga
QUIET_MAX = 1
ACTIVE_BUYER_WEEK = 3          # oxirgi 7 kunda
QUIET_WEEK = 2
GAP_DAYS = 1                   # kecha xabar ketgan bo'lsa — bugun yo'q
QUIET_AFTER_DAYS = 3

# Ustunlik: haftalik o'rinlarning bir qismi muhimroq xabarlarga qoldiriladi.
# Yuqori — shaxsiy va kerakli (AI tavsiya, fikr so'rash, aksiya, savat, qayta sotuv,
# sovg'a): haftalik chegaragacha. O'rta (kun mahsuloti, o'yin seriyasi) — 1 o'rin
# yuqorilarga qolsa. Past (umumiy maslahat, qiziqish, Keto savol) — 2 o'rin qolsa.
HIGH = {"reco", "fikr", "aksiya", "savat", "qayta_sotuv", "sovga"}
LOW = {"tips", "qiziqish", "keto_savol"}


def reserve_for(kind: str) -> int:
    return 0 if kind in HIGH else 2 if kind in LOW else 1


async def claim(user_id: int, kind: str, unless: tuple[str, ...] = ()) -> bool:
    """True — shu xabar bugun yuborilishi mumkin (va hisobga yozildi);
    False — kunlik yoki haftalik chegara to'lgan, kecha xabar ketgan yoki bu
    turga o'rin qolmagan. Baza xatosida False: chegara hech qachon oshib ketmasin."""
    try:
        ok = await database.claim_user_push(
            user_id, kind, ACTIVE_BUYER_MAX, QUIET_MAX, QUIET_AFTER_DAYS, list(unless) if unless else None,
            ACTIVE_BUYER_WEEK, QUIET_WEEK, reserve_for(kind), GAP_DAYS)
        if ok:
            # The post that follows ends with «savolingiz bo'lsa — yozing» (post_ask.py).
            import post_ask
            post_ask.mark(user_id)
        return ok
    except Exception:
        logger.exception("push cap: claim failed for %s (%s) — not sent", user_id, kind)
        return False


# ─────────────────────────────── /xabar_soni ────────────────────────────────
from aiogram import Router  # noqa: E402
from aiogram.filters import Command  # noqa: E402
from aiogram.types import Message  # noqa: E402

router = Router(name="push_cap")

KIND_NAMES = {"tips": "Keto maslahat", "reco": "Shaxsiy tavsiya", "aksiya": "Aksiya", "kun_mahsuloti": "Kun mahsuloti",
              "qiziqish": "Qiziqish eslatmasi", "keto_savol": "Keto savol", "qayta_sotuv": "Qayta sotuv",
              "savat": "Savat eslatmasi", "sovga": "Sovg'a kampaniyasi", "fikr": "Fikr so'rash (AI)",
              "oyin": "O'yin seriyasi eslatmasi"}


def stats_text(st: dict, days: int) -> str:
    per_user_day = st["total"] / st["user_days"] if st["user_days"] else 0
    lines = [f"📨 <b>Rejali xabarlar — oxirgi {days} kun</b>", "",
             f"Jami: <b>{st['total']}</b> ta, {st['users']} ta userga",
             f"Xabar olgan userga kuniga o'rtacha: <b>{per_user_day:.1f}</b> ta",
             f"Chegara: faol xaridorga haftasiga {ACTIVE_BUYER_WEEK} ta, xarid qilmagan va "
             f"{QUIET_AFTER_DAYS} kundan beri jimlarga {QUIET_WEEK} ta; kuniga ko'pi bilan "
             f"{ACTIVE_BUYER_MAX} ta, ikki xabar orasida kamida {GAP_DAYS} kun bo'sh; "
             "shaxsiy xabarlar umumiylardan oldin", ""]
    for kind, n in st["kinds"].items():
        lines.append(f"• {KIND_NAMES.get(kind, kind)}: {n}")
    lines.append("")
    lines.append("Buyurtma xabarlari, «Kelganda xabar bering», AI suhbat va yangi a'zoning birinchi kuni "
                 "hisobga kirmaydi.")
    return "\n".join(lines)


@router.message(Command("xabar_soni"))
async def cmd_push_stats(message: Message):
    from config import ADMIN_IDS
    if message.from_user.id not in ADMIN_IDS:
        return
    st = await database.user_push_stats(7)
    await message.answer(stats_text(st, 7), parse_mode="HTML")
