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
META_AD_ACCOUNT_ID    ixtiyoriy; reklama hisobi ID(lari), vergul bilan (act_ siz).
                      Berilmasa — token ko'radigan HAMMA hisob (me/adaccounts):
                      Instagram ilovasidan "Boost" qilinganlar ko'pincha alohida
                      hisobda turadi, ular shu yo'l bilan o'zi qo'shiladi.
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
DEFAULT_AD_ACCOUNT = "840216037679254"
ENV_AD_ACCOUNTS = [a.strip().replace("act_", "")
                   for a in os.getenv("META_AD_ACCOUNT_ID", "").split(",") if a.strip()]
AD_ACCOUNT_ID = (ENV_AD_ACCOUNTS or [DEFAULT_AD_ACCOUNT])[0]
ACCOUNTS_TTL = 3600
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
_accounts_cache: tuple[float, list[str]] = (0.0, [])
# Oxirgi fetch_insights'da o'qib bo'lmagan hisoblar — hisobotda ogohlantirish uchun.
last_failed: list[str] = []

# Instagram ilovasidagi "Boost" reklamaga o'zi qo'yadigan nom boshlanishlari.
IG_BOOST_PREFIXES = ("instagram post", "публикация в instagram", "instagram-публикация",
                     "instagram posti", "instagram publication")


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


def is_ig_boost(name: str | None) -> bool:
    return (name or "").strip().lower().startswith(IG_BOOST_PREFIXES)


def source_tag(name: str | None) -> str:
    return "📱 Instagram boost" if is_ig_boost(name) else "📣 Ads Manager"


async def account_ids(session) -> list[str]:
    """Qaysi reklama hisoblari o'qiladi. META_AD_ACCOUNT_ID berilgan bo'lsa —
    o'shalar; aks holda token ko'radigan hammasi (soatiga bir yangilanadi),
    shunda egasi yangi hisobni ketoshop-bot'ga ulasa, bot uni o'zi topadi."""
    global _accounts_cache
    if ENV_AD_ACCOUNTS:
        return ENV_AD_ACCOUNTS
    ts, ids = _accounts_cache
    if ids and _now_tk().timestamp() - ts < ACCOUNTS_TTL:
        return ids
    try:
        data = await _get(session, "me/adaccounts", fields="account_id,currency", limit=50)
        rows = data.get("data", [])
        for r in rows:
            if r.get("currency") not in (None, "USD"):
                logger.warning("Ad account %s is in %s — spend is summed as if USD",
                               r.get("account_id"), r.get("currency"))
        found = [str(r["account_id"]) for r in rows if r.get("account_id")]
    except Exception:
        logger.warning("Ad account discovery failed — using the default account", exc_info=True)
        found = []
    # Asosiy hisob birinchi: vaqt zonasi va holat shundan olinadi.
    found = sorted(set(found) | {DEFAULT_AD_ACCOUNT},
                   key=lambda a: (a != DEFAULT_AD_ACCOUNT, a))
    _accounts_cache = (_now_tk().timestamp(), found)
    return found


def _f(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _sum_actions(rows: list[dict], key: str) -> list[dict]:
    totals: dict[str, float] = {}
    for r in rows:
        for a in r.get(key) or []:
            totals[a.get("action_type")] = totals.get(a.get("action_type"), 0.0) + _f(a.get("value"))
    return [{"action_type": t, "value": str(v)} for t, v in totals.items()]


def merge_account_rows(rows: list[dict]) -> dict | None:
    """Bir nechta hisobning account-darajadagi qatorlari → bitta qator.
    Qamrov (reach) qo'shiladi — bir odam ikkala hisob reklamasini ko'rgan
    bo'lsa ikki marta sanaladi; nisbatlar yig'indidan qayta hisoblanadi."""
    if not rows:
        return None
    if len(rows) == 1:
        return rows[0]
    out = {"date_start": min(r.get("date_start") or "9999" for r in rows),
           "date_stop": max(r.get("date_stop") or "" for r in rows)}
    for k in ("spend", "impressions", "reach", "clicks", "inline_link_clicks"):
        out[k] = str(sum(_f(r.get(k)) for r in rows))
    for k in ("actions", "video_thruplay_watched_actions"):
        out[k] = _sum_actions(rows, k)
    spend, imp = _f(out["spend"]), _f(out["impressions"])
    clicks, reach = _f(out["clicks"]), _f(out["reach"])
    out["ctr"] = str(clicks / imp * 100) if imp else "0"
    out["cpm"] = str(spend / imp * 1000) if imp else "0"
    out["cpc"] = str(spend / clicks) if clicks else "0"
    out["frequency"] = str(imp / reach) if reach else "0"
    out["cost_per_action_type"] = [{"action_type": a["action_type"],
                                    "value": str(spend / _f(a["value"]))}
                                   for a in out["actions"] if _f(a["value"])]
    return out


async def fetch_insights(session, date_preset: str, level: str = "account") -> list[dict]:
    """Hamma reklama hisoblari bo'yicha. Bitta hisob o'qilmasa — qolganlari
    bilan davom etadi (last_failed'ga yoziladi); hammasi yiqilsa — xato."""
    fields = INSIGHT_FIELDS
    if level in ("ad", "adset", "campaign"):
        fields += f",{level}_name"
    ids = await account_ids(session)
    results = await asyncio.gather(
        *[_get(session, f"act_{a}/insights", fields=fields, date_preset=date_preset,
               level=level, limit=100) for a in ids],
        return_exceptions=True)
    rows, failed, first_error = [], [], None
    for acc, res in zip(ids, results):
        if isinstance(res, BaseException):
            failed.append(acc)
            first_error = first_error or res
            logger.warning("Insights for act_%s failed: %s", acc, res)
            continue
        for r in res.get("data", []):
            r["account_id"] = acc
            rows.append(r)
    last_failed[:] = failed
    if failed and len(failed) == len(ids):
        raise first_error if isinstance(first_error, GraphError) else GraphError(None, str(first_error))
    if level == "account" and len(rows) > 1:
        rows = [merge_account_rows(rows)]
    return rows


async def fetch_account(session, account_id: str | None = None) -> dict:
    return await _get(
        session, f"act_{account_id or (await account_ids(session))[0]}",
        fields="name,account_status,disable_reason,currency,balance,amount_spent,spend_cap",
    )


async def fetch_ads_status(session, account_id: str | None = None) -> list[dict]:
    """effective_status + issues_info — Ads Manager jadvalida ko'rinmaydigan,
    lekin yetkazish nega to'xtaganini aniq aytadigan yagona joy.
    account_id berilmasa — hamma hisoblar."""
    ids = [account_id] if account_id else await account_ids(session)
    out = []
    for acc in ids:
        try:
            data = await _get(session, f"act_{acc}/ads",
                              fields="name,effective_status,configured_status,issues_info", limit=50)
        except GraphError:
            if account_id:
                raise
            logger.warning("Ads status for act_%s failed", acc, exc_info=True)
            continue
        out += data.get("data", [])
    return out


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
            mark = "📱 " if is_ig_boost(a.get("ad_name")) else ""
            lines.append(
                f"• {mark}{html.escape(a.get('ad_name') or '—')} — "
                f"${_num(a.get('spend'), 2)} · {_num(a.get('impressions'))} ko'rs. · {a_leads} lead"
            )
    if last_failed:
        lines.append("")
        lines.append("⚠️ <i>O'qib bo'lmagan reklama hisobi: "
                     + ", ".join(f"act_{a}" for a in last_failed)
                     + " — ketoshop-bot'ga ruxsat berilganini tekshiring.</i>")
    return "\n".join(lines)


def format_status(account: dict, ads: list[dict]) -> str:
    code = account.get("account_status")
    emoji, label = ACCOUNT_STATUS.get(code, ("❔", f"Noma'lum ({code})"))
    cur = account.get("currency", "USD")

    title = html.escape(str(account.get("name") or account.get("id") or ""))
    lines = [f"🔍 <b>Hisob holati</b>{f' · {title}' if title else ''}", ""]
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
        ig = "📱 " if is_ig_boost(a.get("name")) else ""
        lines.append(f"{mark} {ig}{html.escape(a.get('name') or '—')} — <code>{st}</code>")
        for issue in (a.get("issues_info") or []):
            msg = issue.get("error_summary") or issue.get("error_message") or ""
            if msg:
                lines.append(f"    ⚠️ {html.escape(msg)}")
    if not ads:
        lines.append("<i>Reklama topilmadi.</i>")
    return "\n".join(lines)


def _period_keyboard(preset: str = "today") -> InlineKeyboardMarkup:
    row1 = [InlineKeyboardButton(text=PRESETS[k][0], callback_data=f"ads:{k}")
            for k in ("today", "yesterday")]
    row2 = [InlineKeyboardButton(text=PRESETS[k][0], callback_data=f"ads:{k}")
            for k in ("last_7d", "last_30d", "maximum")]
    # 🎬 Videolar / 📦 Mahsulotlar / 📈 Bog'liqlik — ads_impact.py
    import ads_impact
    return InlineKeyboardMarkup(inline_keyboard=[row1, row2] + ads_impact.view_rows(preset))


# ---------------------------------------------------------------- core

async def build_report(date_preset: str) -> str:
    label = PRESETS.get(date_preset, (date_preset, date_preset))[0]
    async with aiohttp.ClientSession() as session:
        account_rows = await fetch_insights(session, date_preset, "account")
        try:
            ad_rows = await fetch_insights(session, date_preset, "ad")
        except GraphError:
            ad_rows = []
    text = format_report(account_rows, ad_rows, label)
    # Shu davrda do'kon nima sotdi — bazadan; u yiqilsa Meta hisoboti baribir chiqadi.
    try:
        import ads_impact
        text += "\n" + await ads_impact.sales_block(
            date_preset, account_rows[0] if account_rows else None)
    except Exception:
        logger.exception("Ads sales block failed")
    return text


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
                await _notify_admins(bot, await build_report("yesterday"),
                                     _period_keyboard("yesterday"))
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
        await message.answer("⚠️ META_ADS_TOKEN o'rnatilmagan — statistika o'chiq.")
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
                                         reply_markup=_period_keyboard(preset))
    except Exception:
        await callback.message.answer(text, parse_mode="HTML",
                                      reply_markup=_period_keyboard(preset))


@router.message(Command("reklama_holat"))
async def cmd_status(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    if not is_enabled():
        await message.answer("⚠️ META_ADS_TOKEN o'rnatilmagan — statistika o'chiq.")
        return
    await message.answer("⏳ Hisob holati tekshirilmoqda…")
    # Har bir reklama hisobi alohida xabar: Instagram boost'lari turgan hisobda
    # "To'lov qarzi bor" bo'lsa, aynan shu yerda ko'rinadi.
    async with aiohttp.ClientSession() as session:
        ids = await account_ids(session)
        for acc in ids:
            try:
                account = await fetch_account(session, acc)
                ads = await fetch_ads_status(session, acc)
                text = format_status(account, ads)
            except GraphError as e:
                text = f"❌ act_{acc}: <code>{html.escape(str(e))}</code>"
            await message.answer(text, parse_mode="HTML")
