"""
Meta Ads statistikasi -> Telegram.

meta_leads.py leadlarni olib keladi; bu modul ularni tug'dirgan reklamaning
o'zi haqida hisobot beradi — sarf, ko'rsatishlar, qamrov, kliklar, CPM va
lead narxi — to'g'ridan-to'g'ri botda, Ads Manager'ni ochmasdan.

Nega kerak bo'ldi: Ads Manager brauzerdagi Facebook profiliga bog'langan, va
profil almashib qolsa (yoki telefondan qarasangiz) statistika ko'rinmaydi.
Bot esa System User tokeni bilan ishlaydi — profil kim ekanidan qat'i nazar
har doim bir xil ma'lumotni beradi.

Uch qism:
  1. /reklama    — talab bo'yicha hisobot (Bugun / Kecha / 7 kun / 30 kun)
  2. /reklama_holat — hisob holati va yetkazish muammolari (issues_info)
  3. Kunlik avtomatik xulosa + "sarf yo'q" qorovuli

Dormant unless META_PAGE_TOKEN (yoki META_ADS_TOKEN) berilgan — meta_leads.py
bilan bir xil xulq.

Env vars
--------
META_ADS_TOKEN        ixtiyoriy; berilmasa META_PAGE_TOKEN ishlatiladi.
                      Kerakli ruxsat: ads_read (ads_management ham bo'ladi).
META_AD_ACCOUNT_ID    reklama hisobi ID (act_ prefiksisiz).
META_ADS_DAILY_HOUR   kunlik xulosa soati, Toshkent vaqti (default 10).
META_ADS_WATCHDOG     "0" desangiz "sarf yo'q" ogohlantirishi o'chadi.
META_API_VERSION      meta_leads.py dagi bilan bir xil.
"""
import asyncio
import html
import logging
import os
from datetime import datetime, timedelta, timezone

import aiohttp
from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import ADMIN_IDS

logger = logging.getLogger(__name__)
router = Router()

TOKEN = (os.getenv("META_ADS_TOKEN") or os.getenv("META_PAGE_TOKEN", "")).strip()
AD_ACCOUNT_ID = os.getenv("META_AD_ACCOUNT_ID", "840216037679254").strip().replace("act_", "")
DAILY_HOUR = int(os.getenv("META_ADS_DAILY_HOUR", "10"))
WATCHDOG_ON = os.getenv("META_ADS_WATCHDOG", "1") != "0"
API_VERSION = os.getenv("META_API_VERSION", "").strip().strip("/")

GRAPH = "https://graph.facebook.com/" + (f"{API_VERSION}/" if API_VERSION else "")
TZ = timezone(timedelta(hours=5))  # Asia/Tashkent
CHECK_EVERY = 3600  # soatiga bir marta

# Graph qaytaradigan account_status kodlari. Faqat 1 (ACTIVE) sog'lom;
# 7 (PENDING_RISK_REVIEW) — aynan "hammasi yashil, lekin yetkazish yo'q"
# holatining eng ko'p uchraydigan sababi, shuning uchun alohida yoziladi.
ACCOUNT_STATUS = {
    1: ("✅", "Faol"),
    2: ("⛔", "O'chirilgan (disabled)"),
    3: ("⚠️", "To'lov qarzi bor (unsettled)"),
    7: ("🕐", "Xavf tekshiruvida (pending risk review)"),
    8: ("⚠️", "To'lov kutilmoqda (pending settlement)"),
    9: ("⚠️", "Imtiyozli muddat (grace period)"),
    100: ("⛔", "Yopilish jarayonida"),
    101: ("⛔", "Yopilgan"),
}

PRESETS = {
    "today": ("Bugun", "today"),
    "yesterday": ("Kecha", "yesterday"),
    "last_7d": ("7 kun", "last_7d"),
    "last_30d": ("30 kun", "last_30d"),
    "maximum": ("Butun davr", "maximum"),
}

# Bitta ogohlantirish kuniga — qorovul har soatda ishlaydi, spam bo'lmasin.
_last_watchdog_date = None


def is_enabled() -> bool:
    return bool(TOKEN)


def _now_tk() -> datetime:
    return datetime.now(TZ)


# ---------------------------------------------------------------- Graph API

class GraphError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(f"[{code}] {message}")


async def _get(session: aiohttp.ClientSession, path: str, **params) -> dict:
    params["access_token"] = TOKEN
    async with session.get(GRAPH + path, params=params,
                           timeout=aiohttp.ClientTimeout(total=45)) as resp:
        data = await resp.json(content_type=None)
    if isinstance(data, dict) and "error" in data:
        err = data["error"]
        raise GraphError(err.get("code"), err.get("message", "unknown"))
    return data


INSIGHT_FIELDS = ("spend,impressions,reach,frequency,clicks,inline_link_clicks,"
                  "ctr,cpm,cpc,actions,cost_per_action_type")


async def fetch_insights(session, date_preset: str, level: str = "account") -> list[dict]:
    fields = INSIGHT_FIELDS
    if level in ("ad", "adset", "campaign"):
        fields += f",{level}_name"
    data = await _get(session, f"act_{AD_ACCOUNT_ID}/insights",
                      fields=fields, date_preset=date_preset, level=level, limit=25)
    return data.get("data", [])


async def fetch_account(session) -> dict:
    return await _get(
        session, f"act_{AD_ACCOUNT_ID}",
        fields="name,account_status,disable_reason,currency,balance,amount_spent,spend_cap",
    )


async def fetch_ads_status(session) -> list[dict]:
    """effective_status + issues_info — Ads Manager jadvalida ko'rinmaydigan,
    lekin yetkazish nega to'xtaganini aniq aytadigan yagona joy."""
    data = await _get(session, f"act_{AD_ACCOUNT_ID}/ads",
                      fields="name,effective_status,configured_status,issues_info", limit=50)
    return data.get("data", [])


# ---------------------------------------------------------------- formatting

def _num(v, digits=0) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "—"
    if digits:
        return f"{f:,.{digits}f}".replace(",", " ")
    return f"{f:,.0f}".replace(",", " ")


def _leads_from(row: dict) -> tuple[int, float | None]:
    """Meta lead konversiyasini bir nechta action_type nomi bilan qaytaradi —
    Instant Form uchun odatda 'lead', ba'zan 'onsite_conversion.lead_grouped'."""
    wanted = {"lead", "onsite_conversion.lead_grouped", "leadgen_grouped"}
    count = 0
    for a in row.get("actions") or []:
        if a.get("action_type") in wanted:
            try:
                count += int(float(a.get("value", 0)))
            except (TypeError, ValueError):
                pass
    cost = None
    for c in row.get("cost_per_action_type") or []:
        if c.get("action_type") in wanted:
            try:
                cost = float(c.get("value"))
            except (TypeError, ValueError):
                pass
            break
    return count, cost


def format_report(rows_account: list[dict], rows_ads: list[dict], label: str) -> str:
    if not rows_account:
        return (f"📊 <b>Reklama — {html.escape(label)}</b>\n\n"
                "Bu davr uchun ma'lumot yo'q (sarf ham, ko'rsatish ham bo'lmagan).")

    r = rows_account[0]
    spend = float(r.get("spend") or 0)
    impressions = int(float(r.get("impressions") or 0))
    leads, cpl = _leads_from(r)

    lines = [f"📊 <b>Reklama — {html.escape(label)}</b>", ""]
    lines.append(f"💵 <b>Sarflandi:</b> ${_num(spend, 2)}")
    lines.append(f"👁 <b>Ko'rsatishlar:</b> {_num(impressions)}")
    lines.append(f"👥 <b>Qamrov:</b> {_num(r.get('reach'))}")
    if r.get("frequency"):
        lines.append(f"🔁 <b>Chastota:</b> {_num(r.get('frequency'), 2)}")
    lines.append(f"🖱 <b>Kliklar:</b> {_num(r.get('inline_link_clicks') or r.get('clicks'))}")
    if r.get("ctr"):
        lines.append(f"📈 <b>CTR:</b> {_num(r.get('ctr'), 2)}%")
    if r.get("cpm"):
        lines.append(f"💰 <b>CPM:</b> ${_num(r.get('cpm'), 2)}")
    lines.append("")
    lines.append(f"🎯 <b>Leadlar:</b> {leads}")
    lines.append(f"🏷 <b>Lead narxi:</b> " + (f"${_num(cpl, 2)}" if cpl else "—"))

    if impressions == 0 and spend == 0:
        lines.append("")
        lines.append("⚠️ <i>Yetkazish yo'q — /reklama_holat bilan sababini tekshiring.</i>")

    if rows_ads:
        lines.append("")
        lines.append("<b>Reklamalar bo'yicha:</b>")
        for a in sorted(rows_ads, key=lambda x: float(x.get("spend") or 0), reverse=True)[:8]:
            a_leads, _ = _leads_from(a)
            lines.append(
                f"• {html.escape(a.get('ad_name') or '—')} — "
                f"${_num(a.get('spend'), 2)} · {_num(a.get('impressions'))} ko'rs. · {a_leads} lead"
            )
    return "\n".join(lines)


def format_status(account: dict, ads: list[dict]) -> str:
    code = account.get("account_status")
    emoji, label = ACCOUNT_STATUS.get(code, ("❔", f"Noma'lum ({code})"))
    cur = account.get("currency", "USD")

    lines = [f"🔍 <b>Hisob holati</b>", ""]
    lines.append(f"{emoji} <b>Status:</b> {label}")
    if account.get("disable_reason"):
        lines.append(f"⛔ <b>Sabab kodi:</b> {account['disable_reason']}")
    # Graph bu ikkalasini eng kichik birlikda (sentlarda) qaytaradi.
    for key, title in (("balance", "Qarz"), ("amount_spent", "Jami sarflangan")):
        if account.get(key) is not None:
            lines.append(f"• <b>{title}:</b> {_num(float(account[key]) / 100, 2)} {cur}")
    if account.get("spend_cap") and float(account["spend_cap"]) > 0:
        lines.append(f"• <b>Sarf limiti:</b> {_num(float(account['spend_cap']) / 100, 2)} {cur}")

    lines.append("")
    lines.append("<b>Reklamalar:</b>")
    for a in ads[:15]:
        st = a.get("effective_status", "?")
        mark = "🟢" if st == "ACTIVE" else ("⚪" if st in ("PAUSED", "ADSET_PAUSED", "CAMPAIGN_PAUSED") else "🔴")
        lines.append(f"{mark} {html.escape(a.get('name') or '—')} — <code>{st}</code>")
        for issue in (a.get("issues_info") or []):
            msg = issue.get("error_summary") or issue.get("error_message") or ""
            if msg:
                lines.append(f"    ⚠️ {html.escape(msg)}")
    if not ads:
        lines.append("<i>Reklama topilmadi.</i>")
    return "\n".join(lines)


def _period_keyboard() -> InlineKeyboardMarkup:
    row1 = [InlineKeyboardButton(text=PRESETS[k][0], callback_data=f"ads:{k}")
            for k in ("today", "yesterday")]
    row2 = [InlineKeyboardButton(text=PRESETS[k][0], callback_data=f"ads:{k}")
            for k in ("last_7d", "last_30d", "maximum")]
    return InlineKeyboardMarkup(inline_keyboard=[row1, row2])


# ---------------------------------------------------------------- core

async def build_report(date_preset: str) -> str:
    label = PRESETS.get(date_preset, (date_preset, date_preset))[0]
    async with aiohttp.ClientSession() as session:
        account_rows = await fetch_insights(session, date_preset, "account")
        try:
            ad_rows = await fetch_insights(session, date_preset, "ad")
        except GraphError:
            ad_rows = []
    return format_report(account_rows, ad_rows, label)


async def _notify_admins(bot: Bot, text: str, kb=None):
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML",
                                   reply_markup=kb, disable_web_page_preview=True)
        except Exception:
            logger.warning("Ads report to admin %s failed", admin_id, exc_info=True)


async def scheduler_loop(bot: Bot):
    if not is_enabled():
        logger.info("Meta ads reporting disabled (no token)")
        return

    logger.info("Meta ads reporting started (daily at %02d:00 Asia/Tashkent)", DAILY_HOUR)
    global _last_watchdog_date
    last_daily_date = None

    while True:
        try:
            now = _now_tk()
            today = now.date()

            # Kunlik xulosa — kechagi kun bo'yicha, chunki u to'liq yopilgan.
            if last_daily_date != today and now.hour >= DAILY_HOUR:
                await _notify_admins(bot, await build_report("yesterday"), _period_keyboard())
                last_daily_date = today
                logger.info("Daily ads summary sent")

            # Qorovul: reklama faol, lekin tushdan keyin ham sarf 0 bo'lsa —
            # bu "sekin start" emas, biror narsa to'sib turibdi.
            if WATCHDOG_ON and _last_watchdog_date != today and now.hour >= 12:
                async with aiohttp.ClientSession() as session:
                    rows = await fetch_insights(session, "today", "account")
                    spend = float(rows[0].get("spend") or 0) if rows else 0.0
                    if spend == 0:
                        ads = await fetch_ads_status(session)
                        if any(a.get("effective_status") == "ACTIVE" for a in ads):
                            account = await fetch_account(session)
                            await _notify_admins(
                                bot,
                                "🚨 <b>Reklama pul sarflamayapti</b>\n\n"
                                f"Bugun soat {now.hour}:00 ga qadar sarf <b>$0.00</b>, "
                                "lekin reklama holati ACTIVE.\n\n"
                                + format_status(account, ads),
                            )
                            _last_watchdog_date = today
                            logger.warning("Zero-spend watchdog fired")
                    else:
                        _last_watchdog_date = today  # sarf bor — bugun tekshirish shart emas
        except GraphError as e:
            logger.error("Ads insights error: %s", e)
        except Exception:
            logger.exception("Ads scheduler tick failed")

        await asyncio.sleep(CHECK_EVERY)


# ---------------------------------------------------------------- handlers

@router.message(Command("reklama"))
async def cmd_report(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    if not is_enabled():
        await message.answer("⚠️ META_PAGE_TOKEN o'rnatilmagan — statistika o'chiq.")
        return
    await message.answer("⏳ Meta'dan olinmoqda…")
    try:
        await message.answer(await build_report("today"), parse_mode="HTML",
                             reply_markup=_period_keyboard())
    except GraphError as e:
        await message.answer(f"❌ <code>{html.escape(str(e))}</code>", parse_mode="HTML")


@router.callback_query(F.data.startswith("ads:"))
async def cb_period(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Faqat adminlar uchun", show_alert=True)
        return
    preset = callback.data.split(":", 1)[1]
    if preset not in PRESETS:
        await callback.answer()
        return
    await callback.answer("Yuklanmoqda…")
    try:
        text = await build_report(preset)
    except GraphError as e:
        text = f"❌ <code>{html.escape(str(e))}</code>"
    try:
        await callback.message.edit_text(text, parse_mode="HTML",
                                         reply_markup=_period_keyboard())
    except Exception:
        await callback.message.answer(text, parse_mode="HTML",
                                      reply_markup=_period_keyboard())


@router.message(Command("reklama_holat"))
async def cmd_status(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    if not is_enabled():
        await message.answer("⚠️ META_PAGE_TOKEN o'rnatilmagan — statistika o'chiq.")
        return
    await message.answer("⏳ Hisob holati tekshirilmoqda…")
    try:
        async with aiohttp.ClientSession() as session:
            account = await fetch_account(session)
            ads = await fetch_ads_status(session)
        await message.answer(format_status(account, ads), parse_mode="HTML")
    except GraphError as e:
        await message.answer(f"❌ <code>{html.escape(str(e))}</code>", parse_mode="HTML")
