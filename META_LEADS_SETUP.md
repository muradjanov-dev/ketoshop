# Meta Lead Ads → Telegram — sozlash va davom ettirish

Ketoshop bot uchun Meta (Facebook/Instagram) Instant Form leadlarini
real vaqtda Telegram adminlariga yetkazish integratsiyasi.

Holat: **kod yozilgan va repoga qo'yilgan**, token va Railway env
o'zgaruvchilari qolgan.

---

## 1. VS Code uchun tayyor prompt

Quyidagini VS Code'dagi AI yordamchisiga (Copilot Chat / Cursor / Claude)
to'liq nusxalab tashlang:

```text
CONTEXT
I maintain a Telegram marketplace bot at D:\projects\Ketoshop.
Stack: Python 3.12, aiogram 3.13.1, asyncpg + PostgreSQL, aiohttp,
deployed on Railway (Procfile: `web: python bot.py`).
The bot already runs several asyncio background loops started in bot.py:
broadcast.py, personal_recommend.py, db_backup.py, gamification.py,
referral_contest.py — all expose `async def scheduler_loop(bot)`.

WHAT ALREADY EXISTS
A Meta Lead Ads integration was added in three places:

1. meta_leads.py (NEW, ~330 lines)
   - Polls the Facebook Graph API for new Instant Form leads
   - `scheduler_loop(bot)` — polls every META_POLL_SECONDS (default 60)
   - `poll_once(bot, session, silent)` — one sweep over all forms
   - `fetch_forms()` / `fetch_leads()` — Graph API calls
   - `parse_lead()` — flattens Meta's field_data into name/phone/email
   - `format_lead_message()` — builds the HTML Telegram message
   - `_clean_phone()` — normalises UZ numbers to +998XXXXXXXXX
   - aiogram Router with:
       * callback `metalead:done:<lead_id>` → "Bog'landim" claim button
       * `/leads` → last 10 leads (admins only)
       * `/leads_test` → connection smoke test (admins only)
   - Disabled entirely (logs one line, returns) when META_PAGE_TOKEN is unset

2. database.py (MODIFIED)
   - New table `meta_leads` created inside init_db(), right after the
     db_backup_state block
   - New helpers at end of file: meta_lead_seen, save_meta_lead,
     mark_meta_lead_handled, get_meta_lead, get_recent_meta_leads,
     count_meta_leads

3. bot.py (MODIFIED)
   - `from meta_leads import router as meta_leads_router` after the
     support_relay import
   - `dp.include_router(meta_leads_router)` right after broadcast_admin_router
   - `meta_leads_task = asyncio.create_task(meta_leads_scheduler_loop(bot))`
     before the referral_contest task
   - `meta_leads_task.cancel()` in the finally block

MY ENVIRONMENT
- Facebook Page ID: 582508891606220 (Keto market.uz)
- Ad account ID: 840216037679254
- Instant Form: "Eritritol 1.1"
- Campaign: "Keto video 1 (Eritritol 1)"

WHAT I WANT YOU TO DO
1. Read meta_leads.py, and the meta_leads parts of bot.py and database.py.
2. Verify the integration is correct and consistent with the rest of the
   codebase — especially: router ordering vs the catch-all support_relay
   router, the asyncio task lifecycle, and asyncpg parameter usage.
3. Point out any bug, race condition, or unhandled Graph API error case.
4. Do NOT rewrite working code. Suggest minimal diffs only.

Then help me with whichever of these I ask for next:
- writing a pytest test for parse_lead() / _clean_phone() / format_lead_message()
- migrating from polling to a Graph API webhook (leadgen field subscription)
- adding lead stats to the existing admin panel (admin_web.py / webapp/admin.html)
- writing leads into the existing `users` table so leads and buyers link up
```

---

## 2. Texnik spetsifikatsiya

### O'zgargan fayllar

| Fayl | Holat | Nima |
|---|---|---|
| `meta_leads.py` | **yangi** | Butun integratsiya |
| `database.py` | tahrirlangan | `meta_leads` jadvali + 6 funksiya |
| `bot.py` | tahrirlangan | Router + background task |
| `requirements.txt` | **tegilmagan** | `aiohttp` aiogram bilan keladi |

### Ma'lumotlar bazasi

```sql
CREATE TABLE IF NOT EXISTS meta_leads (
    lead_id      TEXT PRIMARY KEY,   -- Meta lead id, idempotentlik kaliti
    form_id      TEXT,
    form_name    TEXT,
    full_name    TEXT,
    phone        TEXT,               -- +998XXXXXXXXX ko'rinishida
    email        TEXT,
    campaign_name TEXT,
    ad_name      TEXT,
    raw          JSONB,              -- Meta qaytargan to'liq javob
    created_time TIMESTAMPTZ,        -- buyer to'ldirgan vaqt
    received_at  TIMESTAMPTZ DEFAULT NOW(),
    handled_by   BIGINT,             -- "Bog'landim" bosgan admin id
    handled_at   TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS meta_leads_created_idx ON meta_leads (created_time DESC);
```

Jadval `init_db()` ichida yaratiladi — alohida migratsiya kerak emas,
birinchi deploy'da o'zi paydo bo'ladi.

### Graph API chaqiruvlari

```
GET https://graph.facebook.com/{PAGE_ID}/leadgen_forms
    ?fields=id,name,status&limit=100

GET https://graph.facebook.com/{FORM_ID}/leads
    ?fields=id,created_time,field_data,campaign_name,adset_name,
            ad_name,platform,is_organic
    &limit=50
```

Versiya ataylab ko'rsatilmagan — Meta uni eng eski qo'llab-quvvatlanadigan
versiyaga yo'naltiradi, shunda versiya sunset bo'lganda integratsiya
jimgina buzilmaydi. Kerak bo'lsa `META_API_VERSION=v23.0` bilan qotiring.

### Takrorlanishning oldini olish

Ikki qatlam:

1. Yuborishdan **oldin** `meta_lead_seen(lead_id)` tekshiriladi
2. `INSERT ... ON CONFLICT (lead_id) DO NOTHING` — ikkita poll bir vaqtda
   ishlab qolsa ham baza darajasida bitta yozuv

"Bog'landim" tugmasi ham shunday: `UPDATE ... WHERE handled_by IS NULL`
qaytargan qatorga qarab qaror qilinadi, ya'ni ikki admin bir vaqtda bossa
faqat bittasi yutadi.

### Sovuq start

Birinchi ishga tushishda `count_meta_leads() == 0` bo'lsa, birinchi sweep
**jim** o'tadi: mavjud leadlar bazaga yoziladi, lekin Telegramga
yuborilmaydi. Bu 90 kunlik eski leadlar birdan yuzlab xabar bo'lib
kelishining oldini oladi.

---

## 3. Token olish

**Kerak:** System User token (muddatsiz). Page tokendan foydalanmang —
u 60 kunda tugaydi.

1. `developers.facebook.com` → **My Apps → Create App → Business**
   (agar App'ingiz bo'lmasa)
2. `business.facebook.com/settings` → **Users → System users** → **Add**
   - Nom: `Leads Bot`
   - Rol: **Admin**
3. **Add assets:**
   - **Pages** → `Keto market.uz` → to'liq huquq
   - **Ad accounts** → `840216037679254` → to'liq huquq
4. **Generate new token** → App'ni tanlang → ruxsatlar:

```
leads_retrieval          ← leadlarni o'qish (majburiy)
pages_show_list          ← sahifalar ro'yxati
pages_read_engagement    ← sahifa ma'lumotlari
pages_manage_metadata    ← formalar ro'yxati
ads_management           ← campaign_name / ad_name maydonlari
```

5. Tokenni nusxalang — **u faqat bir marta ko'rsatiladi**

> App Review kerak emas: System User o'z biznesingizdagi assetlarga
> ishlaganda `leads_retrieval` review'siz ishlaydi.

---

## 4. Railway sozlash

Railway → bot servisi → **Variables**:

```env
META_PAGE_TOKEN=EAAG...            # majburiy — busiz integratsiya o'chiq
META_PAGE_ID=582508891606220       # ixtiyoriy, default shu
META_POLL_SECONDS=60               # ixtiyoriy, minimum 20
META_LEAD_FORM_IDS=                # ixtiyoriy, bo'sh = barcha formalar
META_API_VERSION=                  # ixtiyoriy, bo'sh = versiyasiz
```

Keyin **Deploy**.

---

## 5. Tekshirish ro'yxati

| # | Amal | Kutilgan natija |
|---|---|---|
| 1 | Railway log | `Meta lead polling started (every 60s, page 582508891606220)` |
| 2 | Botga `/leads_test` | ✅ Ulanish ishlayapti + formalar ro'yxati |
| 3 | Botga `/leads` | "Hozircha lead yo'q" (yoki ro'yxat) |
| 4 | Reklamadan test lead to'ldirish | 1 daqiqa ichida barcha adminlarga xabar |
| 5 | "✅ Bog'landim" bosish | Xabar tahrirlanadi, tugma yo'qoladi |
| 6 | Ikkinchi admin bossa | "boshqa admin oldi" ogohlantirishi |

Test lead uchun: Ads Manager → forma → **Preview** → to'ldirish. Yoki
Meta'ning Lead Ads Testing Tool: `developers.facebook.com/tools/lead-ads-testing`

---

## 6. Muammolarni bartaraf qilish

| Belgi | Sabab | Yechim |
|---|---|---|
| Log: `polling disabled` | `META_PAGE_TOKEN` yo'q | Railway Variables'ga qo'shing |
| `/leads_test` → `[190/...]` | Token muddati tugagan / bekor qilingan | Yangi System User token |
| `/leads_test` → `[200/...]` | Ruxsat yetishmaydi | `leads_retrieval` ni qo'shing |
| Formalar 0 ta | Sahifa asset biriktirilmagan | System User → Add assets → Pages |
| Leadlar kelmayapti, xato yo'q | Reklama hali lead bermagan | Test lead bilan tekshiring |
| `campaign_name` bo'sh | `ads_management` yo'q | Tokenni qayta generate qiling |
| Xabar ikki marta keldi | Ikki instans ishlayapti | Railway'da 1 ta replika qoldiring |

---

## 7. Keyingi qadamlar (ixtiyoriy)

**Webhook'ga o'tish** — 1 daqiqa o'rniga 1-2 soniya kechikish.
`webapp_server.py` da allaqachon aiohttp server bor (`create_webapp`),
shunga `/meta/webhook` route qo'shsa bo'ladi:
- `GET` — `hub.challenge` verification
- `POST` — `{ leadgen_id, form_id, page_id }` keladi, keyin
  `GET /{leadgen_id}` bilan to'liq ma'lumot olinadi
- Facebook App → Webhooks → Page → `leadgen` maydoniga obuna

Polling'ni zaxira sifatida qoldiring — webhook bir marta yetkazadi,
o'tkazib yuborsa polling tutib qoladi.

**Admin panelga qo'shish** — `admin_web.py` + `webapp/admin.html` da
leadlar jadvali, CSV eksport, konversiya statistikasi.

**`users` bilan bog'lash** — lead telefon raqami bo'yicha mavjud
xaridorni topib, `meta_leads` ga `user_id` ustuni qo'shish. Shunda
"reklama qancha haqiqiy xaridor keltirdi" degan savolga javob bo'ladi.
