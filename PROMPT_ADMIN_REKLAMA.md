# Prompt: admin panelga "Reklama" bo'limi qo'shish

Bu faylni Claude Code (yoki boshqa IDE agenti) ochgan holda ishlating.
Pastdagi **PROMPT** blokini to'liq nusxalab tashlang.

Loyiha: `D:\projects\Ketoshop`

---

## PROMPT — shu yerdan nusxalang

```text
# CONTEXT

Project: D:\projects\Ketoshop — a Telegram marketplace bot for a keto/organic
shop in Uzbekistan.

Stack:
- Python 3.12, aiogram 3.13.1
- PostgreSQL via asyncpg (database.py, ~132 KB, one module, no ORM)
- aiohttp web server for the Telegram Mini App AND the admin panel
- Deployed on Railway via `railway up` (NOT git — there is no .git folder)
- Procfile: `web: python bot.py`
- requirements.txt: aiogram==3.13.1, asyncpg>=0.29.0, deep-translator>=1.11.0,
  openpyxl>=3.1.0  (aiohttp comes with aiogram — do not add it)

UI language is Uzbek (Latin). All user-facing strings must be Uzbek.

# WHAT ALREADY EXISTS (read these files first)

Two Meta Ads modules were added recently. READ THEM before writing anything:

1. `meta_leads.py` — Facebook/Instagram Lead Ads -> Telegram
   - `scheduler_loop(bot)` polls the Graph API every META_POLL_SECONDS
   - `poll_once(bot, session, silent)`, `fetch_forms()`, `fetch_leads()`
   - `parse_lead(lead) -> {name, phone, email, fields}`
   - `format_lead_message(lead, form_name, parsed) -> HTML string`
   - `_clean_phone(raw)` normalises UZ numbers to +998XXXXXXXXX
   - aiogram Router: callback `metalead:done:<lead_id>`, `/leads`, `/leads_test`
   - `GraphError(code, message)` exception, `is_enabled()`

2. `meta_ads.py` — Meta Ads statistics -> Telegram
   - `build_report(date_preset) -> HTML string`
   - `fetch_insights(session, date_preset, level)` — level is
     "account" | "campaign" | "adset" | "ad"
   - `fetch_account(session)` -> name, account_status, disable_reason,
     currency, balance, amount_spent, spend_cap
   - `fetch_ads_status(session)` -> name, effective_status,
     configured_status, issues_info
   - `format_report(rows_account, rows_ads, label)`,
     `format_status(account, ads)`
   - `_leads_from(row) -> (lead_count, cost_per_lead)`
   - `_num(value, digits)` — thousands separator with spaces
   - `PRESETS` dict: today / yesterday / last_7d / last_30d / maximum
   - `scheduler_loop(bot)` — daily summary at META_ADS_DAILY_HOUR + a
     zero-spend watchdog
   - aiogram Router: `/reklama`, `/reklama_holat`, callback `ads:<preset>`
   - `GraphError(code, message)`, `is_enabled()`

3. `database.py` — has a `meta_leads` table and helpers:
   `meta_lead_seen`, `save_meta_lead`, `mark_meta_lead_handled`,
   `get_meta_lead`, `get_recent_meta_leads`, `count_meta_leads`

4. `bot.py` registers both routers and both scheduler_loops.

Both modules are DORMANT unless META_PAGE_TOKEN is set. Keep that property.

# THE TASK

Add a **"📣 Reklama"** tab to the existing admin web panel so the same data is
visible in the browser, not only in Telegram.

## Files to change

- `admin_web.py` (~27 KB) — add API endpoints
- `webapp/admin.html` (~48 KB) — add the tab, the view, and the JS

Do NOT restructure these files. Follow their existing conventions exactly.

## admin_web.py conventions you MUST follow

Auth decorator (already defined around line 97):

```python
def require_auth(handler):
    async def wrapped(request: web.Request):
        if not ADMIN_WEB_PASSWORD:
            return web.json_response({"error": "admin panel disabled: ADMIN_WEB_PASSWORD not set"}, status=503)
        if not _authed(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        return await handler(request)
    return wrapped
```

Every new endpoint gets `@require_auth`.

Routes are registered at the bottom in `setup_admin_routes(app)` (line ~625):

```python
def setup_admin_routes(app: web.Application):
    app.router.add_get("/admin", admin_page)
    ...
    app.router.add_get("/admin/api/dashboard", api_dashboard)
    ...
```

Existing aggregate-endpoint style to copy (`api_dashboard`, line ~530) — one
call, `asyncio.gather`, plain `web.json_response`:

```python
@require_auth
async def api_dashboard(request: web.Request):
    period = request.query.get("period", "30d")
    if period not in ("today", "7d", "30d", "all"):
        period = "30d"
    stats, monthly, top_products, keto = await asyncio.gather(
        database.get_admin_stats(period),
        database.get_monthly_breakdown(5),
        database.get_top_products(period, limit=5),
        database.get_keto_program_stats(),
    )
    return web.json_response({"stats": stats, "monthly": monthly,
                              "top_products": top_products, "keto": keto})
```

## Endpoints to add

```
GET  /admin/api/ads?period=today|yesterday|last_7d|last_30d|maximum
     -> {
          "enabled": bool,              # meta_ads.is_enabled()
          "account": {...},             # totals row from level="account"
          "ads": [...],                 # level="ad" rows
          "campaigns": [...],           # level="campaign" rows
          "leads": {"total": int, "today": int, "unhandled": int}
        }
     Run the three insight calls with asyncio.gather.
     On GraphError return HTTP 200 with {"enabled": true, "error": "<msg>"} —
     the panel must render an error card, not a blank screen.

GET  /admin/api/ads/status
     -> {"account": {...}, "ads": [{name, effective_status, issues_info}, ...]}
     This is the diagnostic view: account_status + per-ad issues_info.

GET  /admin/api/ads/leads?limit=50
     -> {"leads": [...], "total": int}
     Use database.get_recent_meta_leads(limit) and count_meta_leads().

POST /admin/api/ads/leads/{lead_id}/handled
     -> {"ok": bool}
     Use database.mark_meta_lead_handled(lead_id, WEB_SELLER_ID).
     Return {"ok": false} when another admin already claimed it.
     NOTE: lead_id is a Meta id string, NOT an integer — the route pattern
     must be {lead_id} with no \\d+ constraint, unlike the product routes.
```

Import lazily inside the handlers (`import meta_ads`) so a missing token or a
Graph outage can never break admin panel import at startup.

## webapp/admin.html conventions you MUST follow

Helpers that already exist in the file:

```js
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];

async function api(path,opts={}){
  const r=await fetch(path,{headers:{'Content-Type':'application/json'},credentials:'same-origin',...opts});
  if(r.status===401){showLogin();throw new Error('unauthorized');}
  const data=await r.json().catch(()=>({}));
  if(!r.ok)throw new Error(data.error||('HTTP '+r.status));
  return data;
}

function toast(msg){ /* shows #toast for 2.4s */ }
function esc(s){ /* HTML-escapes — use it on EVERY interpolated value */ }
function fmtSom(n){ /* UZS formatting */ }
```

Tab markup (line ~205):

```html
<div class="tabs">
  <button class="tab active" data-view="dashboard">📊 Dashboard</button>
  <button class="tab" data-view="products">📦 Mahsulotlar</button>
  <button class="tab" data-view="sets">🎁 To'plamlar (Set)</button>
  <button class="tab" data-view="contest">🏆 Musobaqa</button>
  <button class="tab" data-view="keto">🥑 Keto</button>
</div>
```

Tab switching JS (line ~610) — it is generic, so a new tab needs no JS change
to switch, only to load its data:

```js
$$('.tab').forEach(t=>t.addEventListener('click',()=>{
  $$('.tab').forEach(x=>x.classList.toggle('active',x===t));
  $$('.view').forEach(v=>v.classList.toggle('active',v.id==='view-'+t.dataset.view));
}));
```

Each view is `<section class="view" id="view-NAME">`. Reuse the existing CSS
classes — DO NOT invent a new design system:

- `.kpi-grid` / `.kpi-card` with `.lab`, `.val.tnum`, `.sub`  (see renderKpis)
- `.dash-grid` / `.dash-card` with `<h3>`
- `.hbar-list` for horizontal bar charts
- `.tbl-wrap` + `<table>` + `.empty` for tables
- `.period-switch` with `<button data-period="...">` (copy #dashPeriod)
- `.toolbar`, `.count-pill`, `.btn .btn-p .btn-o .btn-sm .btn-danger`, `.hint`

## What the Reklama view must contain

1. **Period switch** — Bugun / Kecha / 7 kun / 30 kun / Hammasi
   (maps to today / yesterday / last_7d / last_30d / maximum)

2. **KPI cards** (reuse `.kpi-grid`), Uzbek labels:
   - Sarflandi ($, 2 decimals)
   - Ko'rsatishlar
   - Qamrov
   - Kliklar
   - CTR (%)
   - CPM ($)
   - Leadlar
   - Lead narxi ($)

3. **Per-ad table**: Reklama nomi | Sarf | Ko'rsatishlar | Kliklar | CTR |
   Leadlar | Lead narxi — sorted by spend desc.

4. **Leadlar table**: Vaqt | Ism | Telefon | Kampaniya | Holat.
   Phone in a `<code>` element, click-to-copy via
   `navigator.clipboard.writeText` + `toast('📋 Nusxalandi')`.
   "Holat" column: a "✅ Bog'landim" button when unhandled, a green check plus
   the admin id when handled. Clicking POSTs to the handled endpoint and
   re-renders.

5. **Holat card** — from `/admin/api/ads/status`:
   account_status with an emoji, balance, amount_spent, spend_cap, then each
   ad's `effective_status` and any `issues_info` messages as warnings.
   Use the ACCOUNT_STATUS mapping already in meta_ads.py — import it, don't
   duplicate it.

6. **When `enabled` is false**: show one card explaining META_PAGE_TOKEN is not
   set and that the section is inactive. No errors, no blank screen.

7. **When `error` is present**: show the Graph API message in a red card.

## Constraints

- No new Python dependencies.
- No new npm/CDN/JS libraries — the panel is one self-contained HTML file.
- Everything in Uzbek (Latin).
- `esc()` every interpolated string. There is no framework escaping here.
- Keep dark/light theme support — use the existing CSS variables
  (`var(--panel)`, `var(--ink)`, `var(--ink-2)`, `var(--chip-bg)`,
  `var(--shadow)`), never hardcoded colors.
- Money is USD (Meta ad account currency), NOT so'm — do not use `fmtSom` for
  ad spend. Shop revenue stays in so'm.

# HOW TO WORK

1. Read `meta_ads.py`, `meta_leads.py`, `admin_web.py`, and
   `webapp/admin.html` (at least the tabs block, `api()`, `loadDashboard`,
   `renderKpis`, `loadKeto`/`renderKeto`, and `setup_admin_routes`).
2. Show me the plan before editing.
3. Implement `admin_web.py` first, then `webapp/admin.html`.
4. Verify: `python -m py_compile admin_web.py meta_ads.py bot.py`
5. Tell me exactly what to test in the browser.

Do not deploy — I run `railway up` myself.
```

---

## Prompt tashqarisidagi ma'lumot (siz uchun)

### Railway env o'zgaruvchilari

```env
META_PAGE_TOKEN     = <System User token>
META_PAGE_ID        = 582508891606220
META_AD_ACCOUNT_ID  = 840216037679254
META_ADS_DAILY_HOUR = 10          # ixtiyoriy
META_POLL_SECONDS   = 60          # ixtiyoriy
```

Token ruxsatlari: `leads_retrieval`, `ads_read`, `pages_show_list`,
`pages_read_engagement`, `pages_manage_metadata`.

### Deploy

```powershell
cd D:\projects\Ketoshop
railway up
```

### Tekshirish ro'yxati

| # | Amal | Kutilgan |
|---|---|---|
| 1 | `/admin` ochish | "📣 Reklama" tab paydo bo'lgan |
| 2 | Tabni bosish | KPI kartalar to'ladi |
| 3 | Davrni almashtirish | Raqamlar yangilanadi |
| 4 | Holat kartasi | account_status + issues_info ko'rinadi |
| 5 | Telefonga bosish | "📋 Nusxalandi" toast |
| 6 | "Bog'landim" | Belgilanadi, sahifa yangilanmasdan |
| 7 | Token o'chirilgan holda | "o'chiq" kartasi, xato yo'q |

### Mavjud fayllar holati

| Fayl | Holat |
|---|---|
| `meta_leads.py` | ✅ yozilgan |
| `meta_ads.py` | ✅ yozilgan |
| `database.py` | ✅ `meta_leads` jadvali + 6 funksiya |
| `bot.py` | ✅ 2 router + 2 scheduler |
| `META_LEADS_SETUP.md` | ✅ token va sozlash qo'llanmasi |
| `admin_web.py` | ⬜ shu prompt bilan qilinadi |
| `webapp/admin.html` | ⬜ shu prompt bilan qilinadi |
