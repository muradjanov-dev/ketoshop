"""
Meta (Facebook/Instagram) Lead Ads -> Telegram.

Buyers who fill the Instant Form attached to a Lead Ads campaign never touch
the bot, so their contact details used to sit unread in Meta's Forms Library —
where Meta also deletes them after 90 days. This polls the Graph API and pushes
every new lead to all admins the moment it lands, with the phone number as
tap-to-copy text and a "Bog'landim" button so the team can see at a glance
which ones somebody already called.

Polling rather than webhooks on purpose: a webhook needs a public callback URL
on a Facebook App plus `leads_retrieval` App Review, while a System User token
from Business Settings works today with no review. The Railway service already
runs several background loops (broadcast.py, db_backup.py, gamification.py) —
this is one more of the same shape.

Dormant unless META_PAGE_TOKEN is set: without it the loop logs one line and
sleeps forever, so a deploy that hasn't got the env var yet behaves exactly as
before rather than crash-looping.

Env vars
--------
META_PAGE_TOKEN     required to enable. System User or Page token with
                    leads_retrieval + pages_show_list + pages_read_engagement.
META_PAGE_ID        the Facebook Page id (default: Keto market.uz).
META_LEAD_FORM_IDS  optional comma-separated form ids. Left unset, every
                    active form on the Page is polled, so a new form created
                    in Ads Manager is picked up without a redeploy.
META_POLL_SECONDS   how often to poll (default 60, floor 20).
META_API_VERSION    optional, e.g. "v23.0". Unset = unversioned Graph call,
                    which Meta resolves to the oldest supported version —
                    deliberately the default so a version sunset can't
                    silently break this months from now.
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

import database
from config import ADMIN_IDS

logger = logging.getLogger(__name__)
router = Router()

PAGE_TOKEN = os.getenv("META_PAGE_TOKEN", "").strip()
PAGE_ID = os.getenv("META_PAGE_ID", "582508891606220").strip()
FORM_IDS = [f.strip() for f in os.getenv("META_LEAD_FORM_IDS", "").split(",") if f.strip()]
POLL_SECONDS = max(20, int(os.getenv("META_POLL_SECONDS", "60")))
API_VERSION = os.getenv("META_API_VERSION", "").strip().strip("/")

GRAPH = "https://graph.facebook.com/" + (f"{API_VERSION}/" if API_VERSION else "")
TZ = timezone(timedelta(hours=5))  # Asia/Tashkent, fixed UTC+5, no DST

# Meta's standard field keys -> (emoji, Uzbek label). Anything not listed is
# a custom question the form author wrote, and is rendered with its own name.
KNOWN_FIELDS = {
    "full_name": ("👤", "Ism"),
    "first_name": ("👤", "Ism"),
    "last_name": ("👤", "Familiya"),
    "phone_number": ("📞", "Telefon"),
    "email": ("✉️", "Email"),
    "city": ("🏙", "Shahar"),
    "street_address": ("📍", "Manzil"),
    "province": ("🗺", "Viloyat"),
    "company_name": ("🏢", "Kompaniya"),
    "job_title": ("💼", "Lavozim"),
}

# One alert per token/permission failure streak, not one per poll — a dead
# token would otherwise spam every admin 1440 times a day.
_last_error_alert: datetime | None = None
ERROR_ALERT_COOLDOWN = timedelta(hours=6)


def is_enabled() -> bool:
    return bool(PAGE_TOKEN)


# ---------------------------------------------------------------- Graph API

class GraphError(Exception):
    def __init__(self, code, subcode, message):
        self.code, self.subcode, self.message = code, subcode, message
        super().__init__(f"[{code}/{subcode}] {message}")

    @property
    def is_auth_problem(self) -> bool:
        """190 = token expired/revoked, 10 & 200-299 = missing permission.
        These need a human to re-issue the token; everything else (rate
        limits, transient 500s) just needs the next poll to come around."""
        return self.code in (10, 190) or (self.code is not None and 200 <= self.code <= 299)


async def _graph_get(session: aiohttp.ClientSession, path: str, **params) -> dict:
    params["access_token"] = PAGE_TOKEN
    async with session.get(GRAPH + path, params=params, timeout=aiohttp.ClientTimeout(total=30)) as resp:
        data = await resp.json(content_type=None)
    if isinstance(data, dict) and "error" in data:
        err = data["error"]
        raise GraphError(err.get("code"), err.get("error_subcode"), err.get("message", "unknown"))
    return data


async def fetch_forms(session: aiohttp.ClientSession) -> list[dict]:
    """Active lead forms on the Page. Re-read every poll so a form created in
    Ads Manager starts flowing without touching the deployment."""
    if FORM_IDS:
        out = []
        for fid in FORM_IDS:
            try:
                out.append(await _graph_get(session, fid, fields="id,name,status"))
            except GraphError:
                logger.warning("Lead form %s unreadable", fid, exc_info=True)
        return out
    data = await _graph_get(session, f"{PAGE_ID}/leadgen_forms", fields="id,name,status", limit=100)
    return data.get("data", [])


async def fetch_leads(session: aiohttp.ClientSession, form_id: str, limit: int = 50) -> list[dict]:
    """Newest-first page of leads for one form. Meta returns them in reverse
    chronological order, so `limit` acts as "how far back to look" — 50 is far
    more than one poll interval could ever produce."""
    data = await _graph_get(
        session,
        f"{form_id}/leads",
        fields="id,created_time,field_data,campaign_name,adset_name,ad_name,platform,is_organic",
        limit=limit,
    )
    return data.get("data", [])


# ---------------------------------------------------------------- formatting

def _clean_phone(raw: str) -> str:
    """Meta hands phone numbers back in whatever shape the buyer typed. Strip
    the noise so the tap-to-copy value can be pasted straight into a dialer."""
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return raw.strip()
    if len(digits) == 9:              # 901234567 -> local, add country code
        digits = "998" + digits
    elif len(digits) == 12 and digits.startswith("998"):
        pass
    return "+" + digits


def parse_lead(lead: dict) -> dict:
    """Flatten Meta's field_data list into something renderable, keeping the
    original order so the message reads like the form the buyer filled in."""
    name = phone = email = ""
    ordered = []
    for field in lead.get("field_data") or []:
        key = (field.get("name") or "").lower()
        value = ", ".join(v for v in (field.get("values") or []) if v).strip()
        if not value:
            continue
        if key == "phone_number":
            value = _clean_phone(value)
            phone = value
        elif key in ("full_name", "first_name"):
            name = name or value
        elif key == "email":
            email = value
        emoji, label = KNOWN_FIELDS.get(key, ("❓", (field.get("name") or key).replace("_", " ").capitalize()))
        ordered.append((emoji, label, value, key == "phone_number"))
    return {"name": name, "phone": phone, "email": email, "fields": ordered}


def _fmt_time(created_time: str) -> str:
    try:
        dt = datetime.fromisoformat(created_time.replace("Z", "+00:00"))
        return dt.astimezone(TZ).strftime("%d.%m.%Y %H:%M")
    except Exception:
        return created_time or "—"


def format_lead_message(lead: dict, form_name: str, parsed: dict) -> str:
    lines = [f"🔥 <b>Yangi lead</b> — {html.escape(form_name)}", ""]
    for emoji, label, value, is_phone in parsed["fields"]:
        safe = html.escape(value)
        # <code> makes it tap-to-copy in every Telegram client; a tel: link
        # can't be used here (Telegram rejects it on inline buttons).
        rendered = f"<code>{safe}</code>" if is_phone else safe
        lines.append(f"{emoji} <b>{html.escape(label)}:</b> {rendered}")
    if not parsed["fields"]:
        lines.append("<i>(forma bo'sh qaytdi)</i>")

    lines.append("")
    lines.append(f"🕐 {_fmt_time(lead.get('created_time', ''))}")
    trail = " › ".join(x for x in (lead.get("campaign_name"), lead.get("adset_name"), lead.get("ad_name")) if x)
    if trail:
        lines.append(f"📢 {html.escape(trail)}")
    if lead.get("platform"):
        lines.append(f"📱 {html.escape(str(lead['platform']))}")
    return "\n".join(lines)


def _lead_keyboard(lead_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Bog'landim", callback_data=f"metalead:done:{lead_id}"),
    ]])


# ---------------------------------------------------------------- delivery

async def _notify_admins(bot: Bot, text: str, lead_id: str | None = None) -> int:
    sent = 0
    kb = _lead_keyboard(lead_id) if lead_id else None
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML", reply_markup=kb,
                                   disable_web_page_preview=True)
            sent += 1
        except Exception:
            logger.warning("Lead notify to admin %s failed", admin_id, exc_info=True)
    return sent


async def _alert_admins_once(bot: Bot, text: str):
    global _last_error_alert
    now = datetime.now(TZ)
    if _last_error_alert and now - _last_error_alert < ERROR_ALERT_COOLDOWN:
        return
    _last_error_alert = now
    await _notify_admins(bot, text)


async def poll_once(bot: Bot, session: aiohttp.ClientSession, silent: bool = False) -> dict:
    """One sweep over every form. `silent` records leads without notifying —
    used on the very first run so an existing backlog doesn't arrive as a
    burst of hundreds of messages the moment this ships."""
    new_count, forms_seen = 0, 0
    for form in await fetch_forms(session):
        form_id, form_name = form.get("id"), form.get("name") or "Lead forma"
        if not form_id:
            continue
        forms_seen += 1
        try:
            leads = await fetch_leads(session, form_id)
        except GraphError:
            logger.warning("Leads unreadable for form %s", form_id, exc_info=True)
            continue

        # Oldest first, so a burst arrives in the order buyers submitted it.
        for lead in reversed(leads):
            lead_id = lead.get("id")
            if not lead_id or await database.meta_lead_seen(lead_id):
                continue
            parsed = parse_lead(lead)
            await database.save_meta_lead(
                lead_id=lead_id,
                form_id=form_id,
                form_name=form_name,
                full_name=parsed["name"],
                phone=parsed["phone"],
                email=parsed["email"],
                campaign_name=lead.get("campaign_name"),
                ad_name=lead.get("ad_name"),
                created_time=lead.get("created_time"),
                raw=lead,
            )
            new_count += 1
            if not silent:
                await _notify_admins(bot, format_lead_message(lead, form_name, parsed), lead_id)
    return {"forms": forms_seen, "new": new_count}


async def scheduler_loop(bot: Bot):
    if not is_enabled():
        logger.info("Meta lead polling disabled (META_PAGE_TOKEN not set)")
        return

    logger.info("Meta lead polling started (every %ds, page %s)", POLL_SECONDS, PAGE_ID)
    # Cold start: if we've never stored a lead, treat whatever Meta already
    # holds as history rather than news.
    first_run = await database.count_meta_leads() == 0
    if first_run:
        logger.info("No leads recorded yet — first sweep will be silent (backfill)")

    async with aiohttp.ClientSession() as session:
        while True:
            try:
                result = await poll_once(bot, session, silent=first_run)
                if first_run:
                    logger.info("Backfilled %d existing lead(s) silently", result["new"])
                    first_run = False
                elif result["new"]:
                    logger.info("Pushed %d new lead(s) to %d admin(s)", result["new"], len(ADMIN_IDS))
            except GraphError as e:
                logger.error("Graph API error while polling leads: %s", e)
                if e.is_auth_problem:
                    await _alert_admins_once(
                        bot,
                        "⚠️ <b>Meta lead ulanishi uzildi</b>\n\n"
                        f"Graph API xatosi: <code>{html.escape(str(e))}</code>\n\n"
                        "META_PAGE_TOKEN muddati tugagan yoki ruxsat olib tashlangan. "
                        "Business Settings → System Users dan yangi token oling va "
                        "Railway'dagi <code>META_PAGE_TOKEN</code> ni yangilang.\n\n"
                        "Shu vaqt ichida leadlar Meta'da saqlanib turadi — token "
                        "tiklanganda hammasi yetkaziladi.",
                    )
            except Exception:
                logger.exception("Meta lead poll failed")

            await asyncio.sleep(POLL_SECONDS)


# ---------------------------------------------------------------- handlers

@router.callback_query(F.data.startswith("metalead:done:"))
async def mark_handled(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Faqat adminlar uchun", show_alert=True)
        return

    lead_id = callback.data.split(":", 2)[2]
    claimed = await database.mark_meta_lead_handled(lead_id, callback.from_user.id)
    who = html.escape(callback.from_user.full_name or str(callback.from_user.id))

    if not claimed:
        # Someone else tapped it first — say who, don't overwrite their name.
        row = await database.get_meta_lead(lead_id)
        other = row.get("handled_by") if row else None
        await callback.answer(
            f"Bu leadni allaqachon boshqa admin oldi (ID {other})." if other else "Allaqachon belgilangan.",
            show_alert=True,
        )
        return

    stamp = datetime.now(TZ).strftime("%d.%m.%Y %H:%M")
    try:
        await callback.message.edit_text(
            (callback.message.html_text or callback.message.text or "")
            + f"\n\n✅ <b>{who}</b> bog'landi — {stamp}",
            parse_mode="HTML",
            reply_markup=None,
        )
    except Exception:
        logger.debug("Could not edit lead message", exc_info=True)
    await callback.answer("Belgilandi ✅")


@router.message(Command("leads"))
async def recent_leads(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    rows = await database.get_recent_meta_leads(10)
    if not rows:
        await message.answer("Hozircha lead yo'q.")
        return

    total = await database.count_meta_leads()
    lines = [f"📋 <b>Oxirgi {len(rows)} ta lead</b> (jami {total})", ""]
    for r in rows:
        mark = "✅" if r.get("handled_by") else "🔴"
        when = r["created_time"].astimezone(TZ).strftime("%d.%m %H:%M") if r.get("created_time") else "—"
        name = html.escape(r.get("full_name") or "—")
        phone = html.escape(r.get("phone") or "—")
        lines.append(f"{mark} {when} · {name} · <code>{phone}</code>")
    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("leads_test"))
async def test_connection(message: Message):
    """Setup smoke test: proves the token works and shows what it can see,
    so a misconfigured env var surfaces here instead of as silence."""
    if message.from_user.id not in ADMIN_IDS:
        return
    if not is_enabled():
        await message.answer(
            "⚠️ META_PAGE_TOKEN o'rnatilmagan — lead integratsiyasi o'chiq.\n"
            "Railway → Variables ga qo'shing va qayta deploy qiling."
        )
        return

    await message.answer("⏳ Meta bilan bog'lanmoqda…")
    try:
        async with aiohttp.ClientSession() as session:
            forms = await fetch_forms(session)
            lines = [f"✅ <b>Ulanish ishlayapti</b>\n\nSahifa: <code>{html.escape(PAGE_ID)}</code>",
                     f"Formalar: {len(forms)}", ""]
            for f in forms[:10]:
                leads = await fetch_leads(session, f["id"], limit=1)
                lines.append(
                    f"• <b>{html.escape(f.get('name') or f['id'])}</b> — {f.get('status', '?')}"
                    f"{' · oxirgi lead: ' + _fmt_time(leads[0].get('created_time', '')) if leads else ' · lead yo`q'}"
                )
            lines.append("")
            lines.append(f"Bazada saqlangan: {await database.count_meta_leads()} ta")
            lines.append(f"Tekshirish oralig'i: {POLL_SECONDS} soniya")
        await message.answer("\n".join(lines), parse_mode="HTML")
    except GraphError as e:
        await message.answer(
            f"❌ <b>Graph API xatosi</b>\n<code>{html.escape(str(e))}</code>\n\n"
            + ("Token muddati tugagan yoki ruxsat yetarli emas — yangi token oling."
               if e.is_auth_problem else "Vaqtinchalik xato bo'lishi mumkin, keyinroq urinib ko'ring."),
            parse_mode="HTML",
        )
    except Exception as e:
        await message.answer(f"❌ Xato: <code>{html.escape(str(e))}</code>", parse_mode="HTML")
