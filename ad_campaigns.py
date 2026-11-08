"""
Reklama kampaniyalari ↔ botning o'z hisobi (egasi, 2026-11-08, TZ: "admin
botda /reklama buyrug'i bilan va har kuni avtomatik ravishda Meta reklama
natijalarini ko'rsin, va ularni botning o'z START/do'kon hisobi bilan bir
xabarda solishtirsin"; "yangi reklama yoqsam ular ham avtomatik ko'rinishi
kerak va raqamlar ... up to date chiqishi kerak").

Each Meta campaign's spend, impressions and link clicks sit next to the
bot's own count for the campaign's start code (shop_links.py): the people who
pressed START through t.me/<bot>?start=<kod> («🤖 botga») and the people who
opened the shop through ?startapp=<kod> («🛍 do'konga») — over the same window,
the ad account's own day. The account runs on Los Angeles time, so Meta's
"today" starts at 13:00 Tashkent in winter (12:00 in summer); the report says
so, and the daily one goes out 5 minutes after that day closes.

A new campaign needs nothing: its ads' button link is read
(…?start=<kod> / ?startapp=<kod>), the code becomes a tracked link if it was
not one yet, and the campaign is linked to it. /reklama_bog sets or changes a
link by hand (an ad built on an existing post has no readable link); a hand
link always wins. Every report asks Meta and the database afresh — no cache.

  ad_campaign_links   campaign_id → name, start code, emoji
  collect(p)          the numbers for a Graph date_preset (bot, site, API)
  build_report(p)     the /reklama text
  tick(bot)           from meta_ads.scheduler_loop every few minutes: the
                      daily report and the alerts — an ad DISAPPROVED or
                      WITH_ISSUES, an active campaign that spent nothing for
                      3 hours, one START costing more than START_COST_MAX.
"""
import html
import logging
import os
import re
from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import aiohttp
from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message

import database
from config import ADMIN_IDS

logger = logging.getLogger(__name__)
router = Router()

# Owner's table, 2026-11-08.
DEFAULT_LINKS = (
    ("120261009449570456", "Kepak", "kepak", "🥖"),
    ("120261022820980456", "Glyuten 1-qism", "gluten_1_qism", "🌾"),
)
CAMPAIGN_FIELDS = ("campaign_id,campaign_name,spend,impressions,reach,"
                   "inline_link_clicks,cost_per_inline_link_click")
AD_LINK_FIELDS = ("campaign_id,campaign{name},creative{object_story_spec{video_data{call_to_action},"
                  "link_data{link,call_to_action}},asset_feed_spec{link_urls}}")
START_COST_MAX = float(os.getenv("META_START_COST_MAX", "0.10"))      # $ per START
START_ALERT_MIN_SPEND = float(os.getenv("META_START_ALERT_MIN_SPEND", "1.0"))
ZERO_SPEND_HOURS = 3
STATUS_EVERY = timedelta(minutes=15)
SYNC_EVERY = timedelta(minutes=10)
DAILY_DELAY = timedelta(minutes=5)
BAD_STATUSES = ("DISAPPROVED", "WITH_ISSUES")
LABELS = {"today": "bugun", "yesterday": "kecha", "last_7d": "oxirgi 7 kun",
          "last_30d": "oxirgi 30 kun", "maximum": "butun davr"}

_ready = False
_last_sync: datetime | None = None


# ───────────────────────────── the table ─────────────────────────────

async def ensure() -> None:
    global _ready
    if _ready:
        return
    async with database.pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS ad_campaign_links (
                campaign_id TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                start_code  TEXT NOT NULL,
                emoji       TEXT,
                manual      BOOLEAN NOT NULL DEFAULT FALSE,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""")
        for cid, name, code, emoji in DEFAULT_LINKS:
            await conn.execute(
                "INSERT INTO ad_campaign_links (campaign_id, name, start_code, emoji, manual) "
                "VALUES ($1, $2, $3, $4, TRUE) ON CONFLICT (campaign_id) DO NOTHING", cid, name, code, emoji)
    _ready = True


async def links() -> list[dict]:
    await ensure()
    async with database.pool.acquire() as conn:
        rows = await conn.fetch("SELECT campaign_id, name, start_code, emoji, manual FROM ad_campaign_links "
                                "ORDER BY created_at, campaign_id")
    return [dict(r) for r in rows]


async def set_link(campaign_id: str, start_code: str, name: str, emoji: str | None = None,
                   manual: bool = True) -> None:
    """A hand link replaces anything; a found one only fills a gap."""
    await ensure()
    async with database.pool.acquire() as conn:
        if manual:
            await conn.execute(
                """INSERT INTO ad_campaign_links (campaign_id, name, start_code, emoji, manual)
                   VALUES ($1, $2, $3, $4, TRUE)
                   ON CONFLICT (campaign_id) DO UPDATE SET name = $2, start_code = $3, manual = TRUE,
                       emoji = COALESCE($4, ad_campaign_links.emoji)""",
                campaign_id, name, start_code, emoji)
        else:
            await conn.execute(
                """INSERT INTO ad_campaign_links (campaign_id, name, start_code, emoji, manual)
                   VALUES ($1, $2, $3, $4, FALSE) ON CONFLICT (campaign_id) DO NOTHING""",
                campaign_id, name, start_code, emoji)


async def remove_link(campaign_id: str) -> bool:
    await ensure()
    async with database.pool.acquire() as conn:
        return await conn.fetchval("DELETE FROM ad_campaign_links WHERE campaign_id = $1 RETURNING campaign_id",
                                   campaign_id) is not None


# ───────────────────────────── new campaigns, by themselves ─────────────────────────────

def clean_name(meta_name: str | None) -> str:
    """'[08/11/2026] Glyuten 1-qism - Trafik (bot do'kon)' -> 'Glyuten 1-qism'."""
    name = re.sub(r"^\s*\[[^\]]*\]\s*", "", meta_name or "")
    name = re.split(r"\s+[-–—|]\s+", name, maxsplit=1)[0].strip()
    return name[:60] or (meta_name or "")[:60]


def code_from_link(url: str | None) -> str | None:
    """t.me/<bot>?start=kepak or …/shop?startapp=kepak -> 'kepak'."""
    if not url or "t.me/" not in url:
        return None
    q = parse_qs(urlparse(url).query)
    for key in ("start", "startapp"):
        if q.get(key):
            return q[key][0].strip().lower().replace("-", "_") or None
    return None


def ad_link(ad: dict) -> str | None:
    """The button link of an ad, wherever its creative keeps it."""
    cr = ad.get("creative") or {}
    oss = cr.get("object_story_spec") or {}
    for part in ("video_data", "link_data"):
        data = oss.get(part) or {}
        link = ((data.get("call_to_action") or {}).get("value") or {}).get("link") or data.get("link")
        if link:
            return link
    for u in (cr.get("asset_feed_spec") or {}).get("link_urls") or []:
        if u.get("website_url"):
            return u["website_url"]
    return None


async def sync_from_ads(session, force: bool = False) -> int:
    """Link every campaign whose ads point at a t.me start code. Returns how
    many links were added. At most every SYNC_EVERY unless forced; never raises."""
    global _last_sync
    now = datetime.now(timezone.utc)
    if not force and _last_sync and now - _last_sync < SYNC_EVERY:
        return 0
    _last_sync = now
    import meta_ads
    import shop_links
    added = 0
    try:
        known = {t["campaign_id"] for t in await links()}
        for acc in await meta_ads.account_ids(session):
            try:
                data = await meta_ads._get(session, f"act_{acc}/ads", fields=AD_LINK_FIELDS, limit=100)
            except meta_ads.GraphError:
                logger.warning("Ad links of act_%s unreadable", acc, exc_info=True)
                continue
            for ad in data.get("data", []):
                cid = str(ad.get("campaign_id") or "")
                code = code_from_link(ad_link(ad))
                if not cid or cid in known or not code or not shop_links.CODE_RE.match(code) \
                        or shop_links._reserved(code):
                    continue
                name = clean_name((ad.get("campaign") or {}).get("name")) or code
                await shop_links.ensure_code(code, name)
                await set_link(cid, code, name, manual=False)
                known.add(cid)
                added += 1
                logger.info("Campaign %s linked to ?start=%s by its ad link", cid, code)
    except Exception:
        logger.exception("Ad link sync failed")
    return added


# ───────────────────────────── numbers ─────────────────────────────

def _f(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _n(v) -> str:
    return f"{int(round(_f(v))):,}".replace(",", " ")


def _usd(v, digits: int = 2) -> str:
    return f"${_f(v):.{digits}f}"


def meta_day_start_tashkent(tz_hours: float) -> int:
    """The hour (Tashkent, UTC+5) at which the ad account's day begins."""
    return int(round(5 - tz_hours)) % 24


def window(preset: str, rows: list[dict], tz_hours: float, now_utc: datetime):
    """(first_day, last_day, start_utc, end_utc) of the report — the account's
    own days, as naive UTC for the bot's tables. «Butun davr» has no start."""
    import ads_impact
    today = (now_utc + timedelta(hours=tz_hours)).date()
    row = next((r for r in rows if r.get("date_start") and r.get("date_stop")), None)
    first, last = ads_impact.preset_dates(preset, row, today)
    start, end = ads_impact.utc_window(first, last, now_utc, tz_hours)
    if preset == "maximum":
        start = None
    return first, last, start, end


def arrival_cost(spend: float, bot: int, app: int) -> tuple[str, float | None]:
    """What one arrival cost: per START when the ad sends people to the bot,
    per shop opening when it sends them to the shop instead."""
    if bot:
        return "1 START narxi", spend / bot
    if app:
        return "1 do'kon ochilishi narxi", spend / app
    return "1 START narxi", None


def summarize(rows: list[dict], table: list[dict], counts: dict) -> tuple[list[dict], dict]:
    """One line per campaign that ran or brought someone, linked ones first."""
    by_id = {str(r.get("campaign_id")): r for r in rows}
    linked = {t["campaign_id"]: t for t in table}
    items = []
    totals = {"spend": 0.0, "impressions": 0.0, "clicks": 0.0, "bot": 0, "app": 0}
    for cid in [t["campaign_id"] for t in table] + [c for c in by_id if c not in linked]:
        r, t = by_id.get(cid, {}), linked.get(cid)
        spend = _f(r.get("spend"))
        c = counts.get(t["start_code"], {"bot": 0, "app": 0}) if t else None
        if not r and not (c and (c["bot"] or c["app"])):
            continue                                  # nothing ran and nobody came
        if not t and spend <= 0:
            continue                                  # an old campaign's empty row
        clicks = _f(r.get("inline_link_clicks"))
        cpc = _f(r.get("cost_per_inline_link_click")) or (spend / clicks if clicks else None)
        cost_label, cost = arrival_cost(spend, c["bot"], c["app"]) if c else (None, None)
        items.append({
            "campaign_id": cid, "name": t["name"] if t else clean_name(r.get("campaign_name")) or cid,
            "emoji": (t.get("emoji") if t else None) or "📣", "start_code": t["start_code"] if t else None,
            "spend": spend, "impressions": _f(r.get("impressions")), "clicks": clicks, "cpc": cpc,
            "bot": c["bot"] if c else None, "app": c["app"] if c else None,
            "cost_label": cost_label, "cost": cost,
        })
        totals["spend"] += spend
        totals["impressions"] += _f(r.get("impressions"))
        totals["clicks"] += clicks
        if c:
            totals["bot"] += c["bot"]
            totals["app"] += c["app"]
    t_label, t_cost = arrival_cost(totals["spend"], totals["bot"], totals["app"])
    totals.update(cost_label=t_label, cost=t_cost)
    return items, totals


async def collect(preset: str) -> dict:
    """Fresh from Meta and the database, every call."""
    import ads_impact
    import shop_links
    async with aiohttp.ClientSession() as session:
        tz = await ads_impact.account_tz_hours(session)
        await sync_from_ads(session)
        rows = await fetch_rows(session, preset)
    table = await links()
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    first, last, start, end = window(preset, rows, tz, now_utc)
    counts = await shop_links.people_between([t["start_code"] for t in table], start, end)
    items, totals = summarize(rows, table, counts)
    return {"preset": preset, "label": LABELS.get(preset, preset), "first": first, "last": last,
            "tz_hours": tz, "day_starts": meta_day_start_tashkent(tz), "items": items, "totals": totals}


def format_report(data: dict) -> str:
    first, last = data["first"], data["last"]
    days = f"{first:%d.%m}" if first == last else f"{first:%d.%m}–{last:%d.%m}"
    lines = [f"📊 <b>Reklama — {data['label']} ({days})</b>",
             f"<i>Meta kuni Toshkent vaqti bilan {data['day_starts']:02d}:00 da boshlanadi "
             f"(hisob Los-Anjeles vaqtida).</i>", ""]
    for it in data["items"]:
        lines.append(f"{it['emoji']} <b>{html.escape(it['name'])}</b>")
        lines.append(f"💰 {_usd(it['spend'])} · 👁 {_n(it['impressions'])} · 👆 {_n(it['clicks'])} bosish"
                     + (f" ({_usd(it['cpc'], 3)})" if it["cpc"] else ""))
        if it["start_code"]:
            lines.append(f"🤖 botga {_n(it['bot'])} · 🛍 do'konga {_n(it['app'])}")
            cost = _usd(it["cost"], 3) if it["cost"] is not None else "—"
            lines.append(f"➡️ {it['cost_label']}: {cost}")
        else:
            lines.append("🔗 Bot havolasi topilmadi: "
                         f"<code>/reklama_bog {html.escape(it['campaign_id'])} kod</code>")
        lines.append("")
    if not data["items"]:
        lines.append("<i>Bu davrda reklama yurmagan.</i>")
        return "\n".join(lines)
    t = data["totals"]
    lines.append(f"<b>Jami:</b> {_usd(t['spend'])} · botga {_n(t['bot'])} · do'konga {_n(t['app'])}")
    lines.append("<i>«botga» — havola orqali START bosganlar, «do'konga» — do'konni havola orqali "
                 "ochganlar (/sayt_havolalar bilan bir xil hisob, adminlarsiz). Meta raqamlari "
                 "~15 daqiqa kechikadi.</i>")
    return "\n".join(lines)


async def fetch_rows(session, preset: str) -> list[dict]:
    import meta_ads
    ids = await meta_ads.account_ids(session)
    rows = []
    for acc in ids:
        try:
            data = await meta_ads._get(session, f"act_{acc}/insights", level="campaign",
                                       date_preset=preset, fields=CAMPAIGN_FIELDS, limit=100)
        except meta_ads.GraphError:
            if acc == ids[0]:
                raise
            logger.warning("Campaign insights for act_%s failed", acc, exc_info=True)
            continue
        rows += data.get("data", [])
    return rows


async def build_report(preset: str) -> str:
    return format_report(await collect(preset))


# ───────────────────────────── schedule + alerts ─────────────────────────────

def daily_due(now_utc: datetime, tz_hours: float) -> date | None:
    """The account day whose «kecha» report is due now, or None before the
    account's midnight + DAILY_DELAY. The caller sends it once per day."""
    local = now_utc + timedelta(hours=tz_hours)
    midnight_utc = datetime.combine(local.date(), datetime.min.time()) - timedelta(hours=tz_hours)
    return local.date() if now_utc >= midnight_utc + DAILY_DELAY else None


def zero_spend_since(history: list[tuple[datetime, float]], now_utc: datetime) -> bool:
    """True when the spend has not moved for ZERO_SPEND_HOURS — `history` is
    (when, today's spend) for one campaign within one account day."""
    cutoff = now_utc - timedelta(hours=ZERO_SPEND_HOURS)
    old = [s for t, s in history if t <= cutoff]
    if not old:
        return False                               # not watched for 3 hours yet
    return abs(history[-1][1] - old[-1]) < 0.005


_spend_hist: dict[str, list[tuple[datetime, float]]] = {}
_hist_day: date | None = None
_active: set[str] = set()
_last_status_check: datetime | None = None


async def _notify(bot: Bot, text: str) -> None:
    for admin_id in dict.fromkeys(ADMIN_IDS):
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML", disable_web_page_preview=True)
        except Exception:
            logger.warning("Ad alert to %s failed", admin_id, exc_info=True)


async def _check_statuses(bot: Bot, session) -> None:
    import meta_ads
    global _active
    ads = await meta_ads.fetch_ads_status(session)
    _active = {str(a.get("campaign_id")) for a in ads if a.get("effective_status") == "ACTIVE"}
    for a in ads:
        status = a.get("effective_status")
        if status not in BAD_STATUSES:
            continue
        if not await database.claim_release_notes(f"adalert:{a.get('id')}:{status}"):
            continue
        why = "; ".join(i.get("error_message") or i.get("error_summary") or ""
                        for i in (a.get("issues_info") or []) if isinstance(i, dict)).strip("; ")
        await _notify(bot, "🚨 <b>Reklamada muammo</b>\n\n"
                           f"«{html.escape(a.get('name') or '?')}» — <b>{status}</b>"
                           + (f"\n{html.escape(why)}" if why else "")
                           + "\n\nAds Manager'da tekshiring: /reklama_holat")


async def tick(bot: Bot) -> None:
    """Every few minutes from meta_ads.scheduler_loop. Never raises."""
    import ads_impact
    import shop_links
    global _hist_day, _last_status_check
    try:
        async with aiohttp.ClientSession() as session:
            tz = await ads_impact.account_tz_hours(session)
            now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
            await sync_from_ads(session)

            # The daily report — yesterday's whole account day, once.
            day = daily_due(now_utc, tz)
            if day and await database.claim_release_notes(f"ads-daily:{day.isoformat()}"):
                await _notify(bot, await build_report("yesterday"))
                logger.info("Daily campaign report for %s sent", day - timedelta(days=1))

            if _last_status_check is None or now_utc - _last_status_check >= STATUS_EVERY:
                _last_status_check = now_utc
                await _check_statuses(bot, session)

            rows = await fetch_rows(session, "today")
        local_day = (now_utc + timedelta(hours=tz)).date()
        if _hist_day != local_day:                    # Meta's day rolled over: spend restarts at 0
            _spend_hist.clear()
            _hist_day = local_day
        spend = {str(r.get("campaign_id")): _f(r.get("spend")) for r in rows}
        table = await links()
        names = {t["campaign_id"]: t["name"] for t in table}
        import meta_ads
        for cid in (_active if meta_ads.WATCHDOG_ON else ()):
            hist = _spend_hist.setdefault(cid, [])
            hist.append((now_utc, spend.get(cid, 0.0)))
            del hist[:-100]
            if zero_spend_since(hist, now_utc) and \
                    await database.claim_release_notes(f"adzero:{cid}:{local_day.isoformat()}"):
                await _notify(bot, "⚠️ <b>Reklama to'xtab qolgan bo'lishi mumkin</b>\n\n"
                                   f"«{html.escape(names.get(cid, cid))}» faol, lekin oxirgi "
                                   f"{ZERO_SPEND_HOURS} soatda sarf o'zgarmadi ({_usd(spend.get(cid, 0.0))}).\n"
                                   "Sabab: /reklama_holat")

        # One START costing too much (today, once a day per campaign).
        first, last, start, end = window("today", rows, tz, now_utc)
        counts = await shop_links.people_between([t["start_code"] for t in table], start, end)
        for t in table:
            s = spend.get(t["campaign_id"], 0.0)
            if s < START_ALERT_MIN_SPEND:
                continue
            c = counts.get(t["start_code"], {"bot": 0, "app": 0})
            what, cost = arrival_cost(s, c["bot"], c["app"])
            if cost is not None and cost <= START_COST_MAX:
                continue
            if not await database.claim_release_notes(f"adcost:{t['campaign_id']}:{local_day.isoformat()}"):
                continue
            await _notify(bot, "💸 <b>Kelgan odam qimmatga tushyapti</b>\n\n"
                               f"«{html.escape(t['name'])}»: bugun {_usd(s)}, "
                               f"🤖 botga {c['bot']} · 🛍 do'konga {c['app']}\n"
                               f"{what}: <b>{_usd(cost, 3) if cost is not None else 'hech kim kelmadi'}</b> "
                               f"(chegara {_usd(START_COST_MAX, 2)}).")
    except Exception:
        logger.exception("Ad campaign tick failed")


# ───────────────────────────── /reklama_bog ─────────────────────────────

@router.message(Command("reklama_bog"))
async def cmd_link(message: Message):
    """/reklama_bog — the table; /reklama_bog <campaign_id> <kod> [nomi] — link
    a campaign to a start code; /reklama_bog <campaign_id> off — unlink."""
    if message.from_user.id not in ADMIN_IDS or message.chat.type != "private":
        return
    parts = (message.text or "").split(maxsplit=3)
    if len(parts) == 1:
        rows = await links()
        lines = ["🔗 <b>Kampaniya ↔ bot havolasi</b>",
                 "<i>Yangi reklama tugmasida t.me/ketoshopbot?start=kod bo'lsa — o'zi bog'lanadi.</i>", ""]
        lines += [f"{r['emoji'] or '📣'} {html.escape(r['name'])} — <code>{r['campaign_id']}</code> → "
                  f"<code>?start={html.escape(r['start_code'])}</code>"
                  + ("" if r["manual"] else " <i>(avtomatik)</i>") for r in rows] or ["<i>Bo'sh</i>"]
        lines += ["", "Qo'lda: <code>/reklama_bog 1202… kod Nomi</code>",
                  "O'chirish: <code>/reklama_bog 1202… off</code>"]
        await message.answer("\n".join(lines), parse_mode="HTML")
        return
    cid = parts[1].strip()
    if not cid.isdigit():
        await message.answer("❌ Kampaniya ID raqamlardan iborat bo'lsin (Ads Manager'dagi Campaign ID).")
        return
    if len(parts) >= 3 and parts[2].lower() in ("off", "o'chir", "ochir"):
        await message.answer("🗑 O'chirildi." if await remove_link(cid) else "Bunday kampaniya jadvalda yo'q.")
        return
    if len(parts) < 3:
        await message.answer("Kodni ham yozing: <code>/reklama_bog 1202… kepak Kepak</code>", parse_mode="HTML")
        return
    import shop_links
    code = parts[2].strip().lower().replace("-", "_")
    if not shop_links.CODE_RE.match(code) or shop_links._reserved(code):
        await message.answer("❌ Bu kod bo'lmaydi — lotin harflari, raqam va _ bilan yozing.")
        return
    name = (parts[3].strip() if len(parts) > 3 else "") or code
    await shop_links.ensure_code(code, name)
    await set_link(cid, code, name[:60])
    await message.answer(f"✅ <code>{cid}</code> → <code>?start={html.escape(code)}</code> ({html.escape(name)})\n"
                         "Natija: /reklama", parse_mode="HTML")
