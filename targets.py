"""
Maqsadlar — the shop's two standing targets, pushed to the admins and kept
as a day-by-day record (owner request 2026-09-02: "kunlik 10 ta sotuv
qilishimiz kerak, va oylik $2000 sof foyda qilishimiz kerak shuni eslatib va
qancha qolganin haqida eslatib tursin va statistikaga ham yozilib borsin").

    daily   — 10 sales a day
    monthly — $2 000 net profit

Two numbers, two different clocks, so the message always answers the same two
questions: how far off are we right now, and what does that mean for the rest
of the month.

Definitions:
  * new orders and their booked value use created_at and exclude cancellations.
  * delivered revenue and COGS use delivered_at. Net profit subtracts expenses
    booked in the period from that delivered revenue and COGS.
  * The last REFRESH_DAYS days of the history are rewritten on every tick, so
    an order cancelled after its day has closed leaves that day's figures too.
  * NET PROFIT is get_admin_stats' `profit`, based on delivered orders and
    expenses booked in the period.

The dollar target is converted at TODAY's Central Bank of Uzbekistan rate
(owner, 2026-09-17: "dollar kursini hozirgi kursdan hisobla"). It is fetched
from cbu.uz a few times a day and saved into targets_state.usd_rate, so a
cbu.uz outage falls back to the last real rate instead of a stale default.

Where it sits in the day (Asia/Tashkent), alongside the buyer-facing pushes:
    13:00  mid-day  — "bugun 4 ta, yana 6 ta kerak"
    20:00  status   — where the day and month stand at 20:00, plus what the AI
                      sales assistant cost today (owner request
                      2026-09-13: "$ da, nechta token va qaysi model")
These go to ADMINS ONLY, so they are outside the two-push-a-day ceiling that
governs broadcasts to buyers (see daily_interest.py).

Public API:
  snapshot()                    -> today's + this month's figures
  build_message(snap, slot)     -> the admin push
  progress_screen()             -> the "🎯 Maqsadlar" panel screen
  scheduler_loop(bot)           -> runs forever
"""
import asyncio
import logging
import time
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.enums import ParseMode

import database
from config import ADMIN_IDS
from locales import get_month_name

logger = logging.getLogger(__name__)

TZ_OFFSET = timedelta(hours=5)   # Asia/Tashkent, fixed UTC+5, no DST
CHECK_EVERY = 1800               # 30 minutes: fine enough for a 13:00/20:00 slot
SEND_SLOTS = (13, 20)            # hours, Asia/Tashkent
SEND_DELAY = 0.05


def _now_tk() -> datetime:
    return datetime.utcnow() + TZ_OFFSET


def fmt_sum(value: float) -> str:
    return f"{int(round(value or 0)):,}".replace(",", " ")


def fmt_usd(value: float) -> str:
    return f"${int(round(value or 0)):,}".replace(",", " ")


CBU_USD_URL = "https://cbu.uz/uz/arkhiv-kursov-valyut/json/USD/"
RATE_TTL = 3 * 3600
_rate_cache: tuple[float, float | None, str | None] = (0.0, None, None)


async def current_usd_rate() -> tuple[float | None, str | None]:
    """(so'm per $1, the rate's date as dd.mm.yyyy) from the Central Bank, or
    (None, None) when cbu.uz can't be reached. Cached for RATE_TTL; every
    fresh rate is also stored as the fallback."""
    global _rate_cache
    ts, rate, day = _rate_cache
    if rate and time.monotonic() - ts < RATE_TTL:
        return rate, day
    try:
        import aiohttp
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            async with session.get(CBU_USD_URL) as resp:
                data = await resp.json(content_type=None)
        row = data[0] if isinstance(data, list) and data else {}
        rate = float(str(row.get("Rate", "")).replace(",", "."))
        if not 1_000 < rate < 100_000:             # never trust a garbled value
            raise ValueError(f"implausible USD rate {rate!r}")
        day = row.get("Date")
        _rate_cache = (time.monotonic(), rate, day)
        try:
            await database.set_targets(usd_rate=rate)
        except Exception:
            logger.warning("Could not store the fetched USD rate", exc_info=True)
        return rate, day
    except Exception:
        logger.warning("CBU USD rate unavailable — using the stored rate", exc_info=True)
        return None, None


def _days_in_month(day) -> int:
    nxt = (day.replace(day=28) + timedelta(days=4)).replace(day=1)
    return (nxt - timedelta(days=1)).day


async def snapshot() -> dict:
    """Everything both the push and the panel screen need, in one place so the
    two can never disagree about where we stand."""
    state = await database.get_targets_state()
    today = _now_tk().date()
    first = today.replace(day=1)

    day_stats = await database.get_admin_stats("today")
    month_stats = await database.get_admin_stats(
        {"start": first.isoformat(), "end": today.isoformat()}
    )

    # New orders and delivered sales are separate clocks: a newly booked
    # order counts toward the daily goal before delivery, while profit only
    # includes orders delivered during the period.
    sales = int(day_stats.get("orders_sold") or 0)

    daily_target = int(state.get("daily_orders") or 10)
    live_rate, rate_date = await current_usd_rate()
    usd_rate = live_rate or float(state.get("usd_rate") or 12800)
    monthly_usd = float(state.get("monthly_profit_usd") or 2000)
    monthly_uzs = monthly_usd * usd_rate

    month_profit = float(month_stats.get("profit") or 0)
    days_total = _days_in_month(today)
    days_left = days_total - today.day + 1          # today counts as still winnable

    remaining_uzs = max(0.0, monthly_uzs - month_profit)

    # AI sarfi — hisobot uchun qo'shimcha, shuning uchun o'qilmay qolsa ham
    # asosiy maqsad xabari baribir ketadi.
    ai_today, ai_month, ai_questions = [], {}, 0
    try:
        ai_today = await database.get_ai_usage_today()
        ai_month = await database.get_ai_usage_month()
        ai_questions = await database.count_ai_questions_today()
    except Exception:
        logger.warning("AI usage for the daily report could not be loaded", exc_info=True)

    return {
        "date": today,
        "month_first": first,
        "sales": sales,
        "daily_target": daily_target,
        "sales_left": max(0, daily_target - sales),
        "day_revenue": float(day_stats.get("revenue") or 0),
        "day_booked_value": float(day_stats.get("booked_value") or 0),
        "day_delivered_revenue": float(day_stats.get("delivered_revenue", day_stats.get("revenue")) or 0),
        "day_delivered_count": int(day_stats.get("orders_delivered") or 0),
        "day_profit": float(day_stats.get("profit") or 0),
        "day_keto_discount": float(day_stats.get("keto_discount") or 0),
        "month_keto_discount": float(month_stats.get("keto_discount") or 0),
        "month_profit": month_profit,
        "month_profit_usd": month_profit / usd_rate if usd_rate else 0.0,
        "month_revenue": float(month_stats.get("revenue") or 0),
        "month_booked_value": float(month_stats.get("booked_value") or 0),
        "month_delivered_revenue": float(month_stats.get("delivered_revenue", month_stats.get("revenue")) or 0),
        "month_delivered_count": int(month_stats.get("orders_delivered") or 0),
        "month_orders": int(month_stats.get("orders_sold") or 0),
        "monthly_target_usd": monthly_usd,
        "monthly_target_uzs": monthly_uzs,
        "remaining_uzs": remaining_uzs,
        "remaining_usd": remaining_uzs / usd_rate if usd_rate else 0.0,
        "needed_per_day_usd": (remaining_uzs / usd_rate / days_left)
                              if usd_rate and days_left else 0.0,
        "days_left": days_left,
        "days_total": days_total,
        "usd_rate": usd_rate,
        "usd_rate_date": rate_date,
        "missing_cost_products": month_stats.get("missing_cost_products") or [],
        "enabled": bool(state.get("enabled", True)),
        "ai_today": ai_today,
        "ai_month": ai_month,
        "ai_questions": ai_questions,
    }


def _bar(done: float, target: float, width: int = 10) -> str:
    """A ten-block progress bar — the share of the target reached reads faster
    than the two numbers it is built from."""
    if target <= 0:
        return "▫️" * width
    filled = max(0, min(width, int(round(width * done / target))))
    return "🟩" * filled + "⬜" * (width - filled)


def _percent(done: float, target: float) -> int:
    return int(round(100 * done / target)) if target > 0 else 0


def build_message(snap: dict, slot: int) -> str:
    """The admin push: a live status at either the midday or 20:00 slot."""
    midday = slot < 20
    lines = ["🎯 <b>MAQSADLAR</b>" if midday else "🎯 <b>20:00 HOLATIGA</b>", ""]

    # ----- daily sales -----
    sales, target = snap["sales"], snap["daily_target"]
    lines.append(f"📦 <b>Bugungi yangi buyurtmalar: {sales} / {target}</b>")
    lines.append(f"{_bar(sales, target)}  {_percent(sales, target)}%")
    if sales >= target:
        lines.append(f"✅ Kunlik maqsad bajarildi! (+{sales - target} ta ortiqcha)"
                     if sales > target else "✅ Kunlik maqsad bajarildi!")
    elif midday:
        lines.append(f"⏳ Hozircha maqsadgacha <b>{snap['sales_left']} ta</b> yangi buyurtma qoldi.")
    else:
        lines.append(f"⏳ 20:00 holatiga kunlik maqsadgacha <b>{snap['sales_left']} ta</b> buyurtma qoldi.")
    lines.append(f"🧾 Yangi buyurtmalar summasi: {fmt_sum(snap.get('day_booked_value', 0))} so'm")
    lines.append(f"🚚 Yetkazilgan savdo: {fmt_sum(snap.get('day_delivered_revenue', snap['day_revenue']))} so'm")
    lines.append(f"💵 Yetkazilgan savdodan sof foyda: {fmt_sum(snap['day_profit'])} so'm")
    # Keto chegirmasi tushumdan allaqachon ayrilgan — Chiqimlarga IKKINCHI
    # marta yozilmaydi, aks holda bir xil pul ikki marta ayrilgan bo'lardi.
    if snap.get("day_keto_discount"):
        lines.append(f"🎁 Keto chegirmasi: {fmt_sum(snap['day_keto_discount'])} so'm "
                     f"(tushumdan ayrilgan)")
    lines.append("")

    # ----- monthly profit -----
    lines.append(f"💰 <b>Oylik sof foyda: {fmt_usd(snap['month_profit_usd'])} / "
                 f"{fmt_usd(snap['monthly_target_usd'])}</b>")
    lines.append(f"{_bar(snap['month_profit'], snap['monthly_target_uzs'])}  "
                 f"{_percent(snap['month_profit'], snap['monthly_target_uzs'])}%")
    rate_src = (f"Markaziy bank, {snap['usd_rate_date']}" if snap.get("usd_rate_date")
                else "oxirgi saqlangan kurs")
    lines.append(f"   ({fmt_sum(snap['month_profit'])} so'm · "
                 f"1$ = {fmt_sum(snap['usd_rate'])} so'm, {rate_src})")
    missing = snap.get("missing_cost_products") or []
    if missing:
        names = ", ".join(missing[:5]) + (f" va yana {len(missing) - 5} ta" if len(missing) > 5 else "")
        lines.append(f"⚠️ Tannarxi kiritilmagan: {names} — foyda shular tannarxicha "
                     f"yuqori ko'rsatilgan. Admin panelda «Asl narx»ni to'ldiring.")
    if snap["remaining_uzs"] <= 0:
        lines.append("🏆 <b>Oylik maqsad bajarildi!</b>")
    else:
        lines.append(f"⏳ Yana <b>{fmt_usd(snap['remaining_usd'])}</b> "
                     f"({fmt_sum(snap['remaining_uzs'])} so'm) kerak")
        lines.append(f"📅 Oyning oxirigacha <b>{snap['days_left']} kun</b> — "
                     f"kuniga {fmt_usd(snap['needed_per_day_usd'])} qilish kerak")
    lines.append("")
    lines.append(f"📊 Oy boshidan: {snap['month_orders']} ta yangi buyurtma · "
                 f"{fmt_sum(snap.get('month_booked_value', 0))} so'm buyurtma summasi")
    lines.append(f"🚚 Shu davrda yetkazilgan savdo: "
                 f"{fmt_sum(snap.get('month_delivered_revenue', snap['month_revenue']))} so'm")
    if snap.get("month_keto_discount"):
        lines.append(f"🎁 Shu oyda Keto bilan to'langan: "
                     f"{fmt_sum(snap['month_keto_discount'])} so'm")

    # Kun yakunida AI xarajati. AI umuman ishlatilmagan va yoqilmagan bo'lsa
    # blok chiqmaydi — bo'sh "$0.00" har kuni ko'z o'ngida turmasin.
    if not midday:
        ai_block = _ai_block(snap)
        if ai_block:
            lines += [""] + ai_block
    return "\n".join(lines)


def _ai_block(snap: dict) -> list[str]:
    today, month = snap.get("ai_today") or [], snap.get("ai_month") or {}
    questions = int(snap.get("ai_questions") or 0)
    try:
        import ai_sales
        enabled = ai_sales.is_enabled()
        lines = ai_sales.usage_lines(today, month)
    except Exception:
        return []
    if not (today or int((month or {}).get("requests") or 0) or enabled):
        return []
    if questions:
        lines.append(f"   ❓ AI javob bera olmagan savollar: <b>{questions} ta</b> — /ai_bilim")
    return lines


async def progress_screen() -> str:
    """The "🎯 Maqsadlar" panel screen: where we are now, plus the last two
    weeks day by day so a bad run is visible as a run, not as one bad day."""
    snap = await snapshot()
    summary = await database.get_target_month_summary(snap["month_first"])
    history = await database.get_target_days(limit=14)

    lines = [build_message(snap, slot=13), ""]
    lines.append(f"🗓 <b>Shu oyda:</b> {int(summary.get('days_hit') or 0)}/"
                 f"{int(summary.get('days') or 0)} kun maqsadga yetgan · "
                 f"eng yaxshi kun {int(summary.get('best_day') or 0)} ta")
    if not snap["enabled"]:
        lines.append("⚠️ Eslatmalar o'chirilgan.")
    if history:
        lines += ["", "📅 <b>Oxirgi kunlar:</b>"]
        for row in history:
            hit = "✅" if int(row["orders"]) >= int(row["daily_target"]) else "❌"
            lines.append(
                f"{hit} {row['day']:%d.%m} — {int(row['orders'])}/{int(row['daily_target'])} ta · "
                f"{fmt_sum(row['profit'])} so'm foyda"
            )
    else:
        lines += ["", "📅 Tarix hali yig'ilmagan — birinchi kun bugundan boshlanadi."]
    return "\n".join(lines)


# Kunlik tarixni nechta kun orqaga qayta yozish. Bugungi kun yetarli emas:
# kecha tushgan buyurtma bugun bekor qilinsa, o'sha kunning qatori eski
# raqam bilan qotib qolar edi va «Oxirgi kunlar» ro'yxati hech qachon
# tuzalmasdi (egasi, 2026-09-25: "agar buyurtma bekor bo'lsa unda u savdodan
# olib tashlansin"). Bir hafta — buyurtma bekor bo'ladigan real oraliq.
REFRESH_DAYS = 7


async def _refresh_history(snap: dict) -> None:
    """Rewrite the last REFRESH_DAYS days of target_days from the live data.

    Every figure is recomputed, so a cancellation, a corrected tannarx or a
    late-entered sale all reach the history by themselves. record_target_day
    upserts on the day, so this only ever overwrites the shop's own rows.
    """
    for back in range(1, REFRESH_DAYS + 1):
        day = snap["date"] - timedelta(days=back)
        try:
            stats = await database.get_admin_stats(
                {"start": day.isoformat(), "end": day.isoformat()}
            )
            month_first = day.replace(day=1)
            month = await database.get_admin_stats(
                {"start": month_first.isoformat(), "end": day.isoformat()}
            )
            await database.record_target_day(
                day, int(stats.get("orders_sold") or 0), snap["daily_target"],
                float(stats.get("revenue") or 0), float(stats.get("profit") or 0),
                float(month.get("profit") or 0),
                snap["monthly_target_usd"], snap["usd_rate"],
                booked_value=float(stats.get("booked_value") or 0),
            )
        except Exception:
            logger.exception("Could not refresh target day %s", day)


async def _tick(bot: Bot) -> None:
    snap = await snapshot()

    # Bekor qilingan buyurtmalarning sovg'a / bonus / kuryer chiqimlari
    # Chiqimlardan olib tashlansin — jo'natilmagan buyurtma pul yemasin.
    try:
        dropped = await database.drop_cancelled_order_expenses()
        if dropped:
            logger.info("Unbooked %d expense row(s) from cancelled orders", dropped)
    except Exception:
        logger.exception("Could not unbook cancelled orders' expenses")

    # Record first, always — the history has to keep filling even when the
    # reminders are switched off, or the statistics grow holes.
    try:
        await database.record_target_day(
            snap["date"], snap["sales"], snap["daily_target"],
            snap["day_revenue"], snap["day_profit"], snap["month_profit"],
            snap["monthly_target_usd"], snap["usd_rate"],
            booked_value=snap.get("day_booked_value", 0),
        )
    except Exception:
        logger.exception("Could not record target day")

    await _refresh_history(snap)

    if not snap["enabled"]:
        return

    now_tk = _now_tk()
    slot = max((h for h in SEND_SLOTS if now_tk.hour >= h), default=None)
    if slot is None:
        return

    state = await database.get_targets_state()
    if (state.get("last_sent_date") == snap["date"]
            and int(state.get("last_sent_slot") or 0) >= slot):
        return

    # Keep an immutable copy of the figures and exact text for this slot.
    text = build_message(snap, slot)
    try:
        created = await database.record_target_report_snapshot(snap["date"], slot, snap, text)
    except Exception:
        logger.exception("Could not save target report snapshot")
        return
    if not created:
        # A previous attempt already froze this slot. Don't send a newer
        # live report under an older immutable snapshot.
        await database.mark_targets_sent(snap["date"], slot)
        return

    # Claim the slot before sending, so a crash mid-fan-out cannot re-push to
    # admins who already got it.
    await database.mark_targets_sent(snap["date"], slot)
    delivered = 0
    attempted = 0
    for admin_id in ADMIN_IDS:
        attempted += 1
        try:
            await bot.send_message(admin_id, text, parse_mode=ParseMode.HTML)
            delivered += 1
        except Exception:
            logger.debug("Target reminder to %s failed", admin_id)
        await asyncio.sleep(SEND_DELAY)
    try:
        await database.finish_target_report_snapshot(
            snap["date"], slot, attempted, delivered
        )
    except Exception:
        logger.exception("Could not save target report delivery outcome")
    logger.info("Target reminder sent for slot %02d:00 (%d sales, %.0f so'm month profit)",
                slot, snap["sales"], snap["month_profit"])


# A one-off "where we stand" push to every admin, outside the 13:00/20:00
# slots. The owner asks for one when something has changed and the whole team
# needs the same picture at the same moment (2026-09-25: "barcha adminlarga
# maqsadlarimiz raqamlarini va hozirgi statusini eslatib va kunlik qancha
# savdo qilishimiz kerakligini eslatib yana bir status yubor").
#
# Keyed like the release notes, and claimed in the database before sending, so
# a restart or a redeploy cannot push it twice. To send another one later,
# change the date in the key.
STATUS_PUSH_KEY = "targets-status-2026-09-25"


def build_status_reminder(snap: dict) -> str:
    """The standing targets, where we are against them right now, and what the
    rest of the month asks for per day — the three things an owner's reminder
    has to answer, in that order."""
    sales, target = snap["sales"], snap["daily_target"]
    # Every figure gets the date it belongs to. The same message is read at
    # 13:00 and forwarded on at midnight, and "136 ta sotuv" means nothing
    # without the window it was counted over.
    day = snap.get("date")
    first = snap.get("month_first") or (day.replace(day=1) if day else None)
    today_str = f"{day:%d.%m.%Y}" if day else "—"
    month_str = (f"{get_month_name(day.month, 'uz')} {day.year}" if day else "—")
    window_str = f"{first:%d.%m} – {day:%d.%m}" if day and first else "—"

    lines = [
        "📣 <b>ESLATMA — MAQSADLARIMIZ</b>",
        f"🗓 <b>{today_str}</b> (bugun) · {month_str}",
        "",
        "🎯 <b>Ikkita maqsad turibdi:</b>",
        f"   1️⃣ Har kuni <b>{target} ta yangi buyurtma</b>",
        f"   2️⃣ Oyiga <b>{fmt_usd(snap['monthly_target_usd'])} sof foyda</b>"
        f" ({fmt_sum(snap['monthly_target_uzs'])} so'm)",
        "",
        f"📦 <b>Bugun ({today_str}) yangi buyurtmalar: {sales} / {target}</b>",
        f"{_bar(sales, target)}  {_percent(sales, target)}%",
    ]
    if sales >= target:
        lines.append("✅ Bugungi maqsad bajarildi!")
    else:
        lines.append(f"⏳ Bugun yana <b>{snap['sales_left']} ta</b> yangi buyurtma kerak.")

    lines += [
        "",
        f"💰 <b>{month_str} foydasi: {fmt_usd(snap['month_profit_usd'])} / "
        f"{fmt_usd(snap['monthly_target_usd'])}</b>",
        f"{_bar(snap['month_profit'], snap['monthly_target_uzs'])}  "
        f"{_percent(snap['month_profit'], snap['monthly_target_uzs'])}%",
        f"   ({fmt_sum(snap['month_profit'])} so'm · 1$ = {fmt_sum(snap['usd_rate'])} so'm"
        + (f", Markaziy bank {snap['usd_rate_date']}" if snap.get("usd_rate_date") else "")
        + ")",
    ]
    if snap["remaining_uzs"] <= 0:
        lines.append("🏆 <b>Oylik maqsad bajarildi!</b>")
    else:
        lines += [
            f"⏳ Yana <b>{fmt_usd(snap['remaining_usd'])}</b> "
            f"({fmt_sum(snap['remaining_uzs'])} so'm) kerak",
            "",
            f"📅 <b>Oyning oxirigacha {snap['days_left']} kun qoldi</b>"
            + (f" ({day:%d.%m} – {snap['days_total']:02d}.{day.month:02d})" if day else "")
            + ".",
            f"   Har kuni <b>{fmt_usd(snap['needed_per_day_usd'])}</b> sof foyda "
            f"({fmt_sum(snap['needed_per_day_usd'] * snap['usd_rate'])} so'm) "
            f"qilsak, maqsadga yetamiz.",
            f"   Ya'ni kuniga <b>{snap['daily_target']} ta yangi buyurtma</b> — bu ikkalasi "
            f"bitta ish.",
        ]

    lines += [
        "",
        f"📊 Oy boshidan ({window_str}): <b>{snap['month_orders']} ta yangi buyurtma</b> · "
        f"{fmt_sum(snap.get('month_booked_value', 0))} so'm buyurtma summasi",
        f"🚚 Shu davrda yetkazilgan savdo: "
        f"{fmt_sum(snap.get('month_delivered_revenue', snap['month_revenue']))} so'm",
    ]
    missing = snap.get("missing_cost_products") or []
    if missing:
        names = ", ".join(missing[:5]) + (f" va yana {len(missing) - 5} ta"
                                          if len(missing) > 5 else "")
        lines.append(f"⚠️ Tannarxi kiritilmagan: {names} — foyda haqiqiydan "
                     f"yuqori ko'rinadi.")
    # The closing line has to mean something on a day the target is already
    # met, too — "bugungi 0 tani yopamiz" would read as a mistake.
    lines.append("")
    if snap["sales_left"]:
        lines.append(f"💪 Qani, bugungi {snap['sales_left']} tani yopamiz!")
    else:
        lines.append("💪 Zo'r ketyapmiz — shu suratni ushlab turaylik!")
    return "\n".join(lines)


async def send_status_reminder(bot: Bot, key: str = STATUS_PUSH_KEY) -> bool:
    """Push build_status_reminder to every admin, at most once per key."""
    if not await database.claim_release_notes(key):
        return False
    try:
        snap = await snapshot()
        text = build_status_reminder(snap)
    except Exception:
        # Give the key back, or a transient database hiccup would burn the
        # send and the admins would never get it.
        logger.exception("Could not build the targets status reminder")
        await database.release_release_notes(key)
        return False

    sent = failed = 0
    for admin_id in list(dict.fromkeys(ADMIN_IDS)):
        try:
            await bot.send_message(admin_id, text, parse_mode=ParseMode.HTML)
            sent += 1
        except Exception as exc:
            failed += 1
            logger.warning("Targets status to admin %s failed: %s", admin_id, exc)
        await asyncio.sleep(SEND_DELAY)
    logger.info("Targets status %s: %d sent, %d failed", key, sent, failed)
    return True


async def scheduler_loop(bot: Bot) -> None:
    logger.info("Targets scheduler started (%s Asia/Tashkent)",
                ", ".join(f"{h:02d}:00" for h in SEND_SLOTS))
    await asyncio.sleep(45)   # let startup settle
    try:
        await send_status_reminder(bot)
    except Exception:
        logger.exception("Targets status reminder failed")
    while True:
        try:
            await _tick(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Targets tick failed")
        await asyncio.sleep(CHECK_EVERY)
