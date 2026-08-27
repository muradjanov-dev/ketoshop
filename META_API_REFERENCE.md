# Meta Graph API — Ketoshop uchun to'liq ma'lumotnoma

Loyihaga kerak bo'ladigan **barcha** Facebook/Meta API endpointlari.

Tekshirilgan sana: **23-Avgust, 2026**

| Parametr | Qiymat |
|---|---|
| Eng yangi versiya | **v26.0** (chiqarilgan 29-iyul 2026) |
| Oldingi versiya | v25.0 (18-fevral 2026) |
| Muhim sana | **27-oktabr 2026** — v26.0 dagi barcha o'chirishlar *hamma* qo'llab-quvvatlanadigan versiyalarga tarqaladi |
| Base URL | `https://graph.facebook.com/` |
| Bizning ID lar | Page `582508891606220` · Ad account `840216037679254` · Form `1630038098545394` |

**Versiya bo'yicha tavsiya:** URL'da versiyani **yozmang** (`https://graph.facebook.com/{id}`).
Meta uni eng eski qo'llab-quvvatlanadigan versiyaga yo'naltiradi, ya'ni versiya
sunset bo'lganda kodingiz jimgina buzilmaydi. Kodda `META_API_VERSION` env
o'zgaruvchisi bor — kerak bo'lsa `v26.0` deb qotirasiz.

v26.0 leadlar va insights'ga tegmagan. O'zgarishlar: Instagram Explore
placement olib tashlangan, Delivery Estimate'dan `daily_outcomes_curve`,
`budget_guardrail`, `estimate_dau` olib tashlangan, Special Ad Categories
uchun `advantage_audience` majburiy qilingan. Bizga ta'sir qilmaydi.

---

## 0. Autentifikatsiya

### Token turlari

| Tur | Muddat | Qachon |
|---|---|---|
| User token (Graph Explorer) | ~1 soat | faqat test uchun |
| Long-lived user token | 60 kun | vaqtinchalik |
| Page token | user token bilan bog'liq | o'rtacha |
| **System User token** | **muddatsiz** | **production — shuni oling** |

System User: `business.facebook.com/settings` → Users → System users → Add →
Add assets (Page + Ad account) → Generate new token.

### Kerakli ruxsatlar

| Ruxsat | Nima uchun |
|---|---|
| `leads_retrieval` | lead ma'lumotlarini o'qish |
| `pages_show_list` | sahifalar ro'yxati |
| `pages_read_engagement` | sahifa ma'lumotlari |
| `pages_manage_metadata` | webhook obunasi (`subscribed_apps`) |
| `pages_manage_ads` | lead formalar — Meta hujjatida App Review uchun `leads_retrieval` bilan birga talab qilinadi |
| `ads_read` | insights (statistika) |
| `ads_management` | reklamani boshqarish (pauza, budjet) |
| `business_management` | System User assetlari |

### Tokenni tekshirish

```bash
GET /debug_token?input_token={TOKEN}&access_token={TOKEN}
```
Qaytaradi: `app_id`, `type`, `expires_at` (0 = muddatsiz), `scopes`, `is_valid`.

```bash
GET /me?fields=id,name
GET /me/accounts?fields=id,name,access_token       # sahifalar
GET /me/adaccounts?fields=id,name,account_status   # reklama hisoblari
```

---

## 1. Lead Ads — leadlarni olish

### 1.1 Sahifadagi formalar ro'yxati

```
GET /{page_id}/leadgen_forms
    ?fields=id,name,status,locale,leads_count,created_time
    &limit=100
```

`status`: `ACTIVE` | `ARCHIVED` | `DELETED` | `DRAFT`

### 1.2 Bitta formaning to'liq ta'rifi

```
GET /{form_id}
    ?fields=id,name,locale,status,questions,context_card,thank_you_page,
            privacy_policy,follow_up_action_url,leads_count,block_display_for_non_targeted_viewer
```

`questions` — barcha savollar: `key`, `label`, `type`
(`FULL_NAME`, `PHONE`, `EMAIL`, `CUSTOM`, `MULTIPLE_CHOICE` …), `options`.

> **Bizga kerak:** `Eritritol 1.1` formasida email bor-yo'qligini aynan shu
> chaqiruv aytadi. Formani tahrirlab bo'lmaydi, lekin bu ta'rifni o'qib,
> yangisini aniq qayta qurish mumkin.

### 1.3 Formaning leadlari

```
GET /{form_id}/leads
    ?fields=id,created_time,field_data,campaign_id,campaign_name,
            adset_id,adset_name,ad_id,ad_name,form_id,platform,is_organic
    &limit=100
```

Vaqt bo'yicha filtr (polling uchun):

```
&filtering=[{"field":"time_created","operator":"GREATER_THAN","value":<unix_ts>}]
```

`field_data` shakli:
```json
[{"name": "full_name",    "values": ["Aziz Karimov"]},
 {"name": "phone_number", "values": ["+998901234567"]}]
```

### 1.4 Bitta lead (webhook'dan keyin)

```
GET /{leadgen_id}
    ?fields=id,created_time,field_data,ad_id,ad_name,campaign_name,form_id
```

### 1.5 Reklama hisobi darajasidagi barcha leadlar

```
GET /act_{ad_account_id}/leads          # hisobdagi hamma forma bo'yicha
GET /{ad_id}/leads                      # bitta reklama bo'yicha
```

> ⚠️ Meta leadlarni **90 kun** saqlaydi. Shu sababli `meta_leads` jadvali bor.

---

## 2. Lead Ads — Webhook (real vaqt)

Polling o'rniga (yoki yonida). Kechikish 1–2 soniya.

### 2.1 Obuna

App → Webhooks → Page → `leadgen` maydoni. Yoki API orqali:

```
POST /{page_id}/subscribed_apps
     ?subscribed_fields=leadgen
     &access_token={PAGE_TOKEN}
```

Tekshirish: `GET /{page_id}/subscribed_apps`

### 2.2 Verification handshake (GET)

Meta sizning endpointingizga bir marta GET yuboradi:

```
GET /your/webhook?hub.mode=subscribe
                 &hub.challenge=<random>
                 &hub.verify_token=<siz kiritgan token>
```

`hub.verify_token` to'g'ri bo'lsa — `hub.challenge` ni **plain text** qaytaring.

### 2.3 Lead keldi (POST)

```json
{
  "object": "page",
  "entry": [{
    "id": "582508891606220",
    "time": 1787465280,
    "changes": [{
      "field": "leadgen",
      "value": {
        "leadgen_id": "1234567890",
        "page_id": "582508891606220",
        "form_id": "1630038098545394",
        "adgroup_id": "120259534482350456",
        "created_time": 1787465279
      }
    }]
  }]
}
```

Payload'da **ma'lumot yo'q** — faqat `leadgen_id`. Keyin 1.4 dagi chaqiruvni
qilasiz. `X-Hub-Signature-256` sarlavhasini app secret bilan tekshiring.

### 2.4 Test

`developers.facebook.com/tools/lead-ads-testing` — soxta lead yuboradi.

---

## 3. Ads Insights — statistika

### 3.1 Asosiy chaqiruv

```
GET /act_{ad_account_id}/insights
    ?fields=spend,impressions,reach,frequency,clicks,inline_link_clicks,
            ctr,cpc,cpm,cpp,actions,cost_per_action_type,
            objective,account_currency,date_start,date_stop
    &level=account
    &date_preset=today
    &limit=100
```

`level`: `account` | `campaign` | `adset` | `ad`
(`ad` bo'lsa `ad_name`, `campaign_name` maydonlarini ham qo'shing)

`date_preset`: `today`, `yesterday`, `this_week_mon_today`, `last_7d`,
`last_14d`, `last_28d`, `last_30d`, `last_90d`, `this_month`, `last_month`,
`maximum`

Aniq oraliq:
```
&time_range={"since":"2026-08-01","until":"2026-08-23"}
&time_increment=1        # kunlik qatorlar
```

### 3.2 Breakdown — kim, qayerda, qachon

```
&breakdowns=age,gender
&breakdowns=publisher_platform,platform_position,impression_device
&breakdowns=country,region
&breakdowns=hourly_stats_aggregated_by_advertiser_time_zone
&action_breakdowns=action_type
```

> **Dayparting qarori uchun:** `hourly_stats_aggregated_by_advertiser_time_zone`
> — qaysi soatlarda lead arzon tushayotganini aynan shu ko'rsatadi.

### 3.3 Konversiya (lead) ko'rsatkichlari

`actions` massividan quyidagi `action_type` larni qidiring:
- `lead`
- `onsite_conversion.lead_grouped`
- `leadgen_grouped`

Narxi: `cost_per_action_type` massivida shu action_type bo'yicha.

Atribusiya oynasi:
```
&action_attribution_windows=["7d_click","1d_view"]
```

### 3.4 Katta hisobot — asinxron

```
POST /act_{id}/insights          -> {"report_run_id": "..."}
GET  /{report_run_id}            -> async_status, async_percent_completion
GET  /{report_run_id}/insights   -> tayyor natija
```

---

## 4. Diagnostika — nega ishlamayapti

Bu bo'lim aynan bizning bugungi muammomiz uchun.

### 4.1 Hisob holati

```
GET /act_{ad_account_id}
    ?fields=name,account_status,disable_reason,currency,timezone_name,
            balance,amount_spent,spend_cap,funding_source_details,
            is_prepay_account,business,age
```

**`account_status` kodlari:**

| Kod | Ma'nosi |
|---|---|
| 1 | ACTIVE ✅ |
| 2 | DISABLED ⛔ |
| 3 | UNSETTLED (to'lanmagan qarz) |
| 7 | **PENDING_RISK_REVIEW** 🕐 |
| 8 | PENDING_SETTLEMENT |
| 9 | IN_GRACE_PERIOD |
| 100 | PENDING_CLOSURE |
| 101 | CLOSED |

> **7 = PENDING_RISK_REVIEW** — "hammasi yashil, lekin yetkazish yo'q"
> holatining eng ko'p uchraydigan sababi. Ads Manager interfeysi buni
> **ko'rsatmaydi**, faqat API aytadi.

`balance` va `amount_spent` — eng kichik birlikda (sentlarda), 100 ga bo'ling.

### 4.2 Reklama darajasidagi muammolar

```
GET /act_{ad_account_id}/ads
    ?fields=name,status,configured_status,effective_status,issues_info,
            created_time,updated_time,adset_id,campaign_id
    &limit=100
```

**`effective_status`:** `ACTIVE`, `PAUSED`, `DELETED`, `PENDING_REVIEW`,
`DISAPPROVED`, `PREAPPROVED`, `PENDING_BILLING_INFO`, `CAMPAIGN_PAUSED`,
`ARCHIVED`, `ADSET_PAUSED`, `IN_PROCESS`, `WITH_ISSUES`

**`issues_info`** — eng qimmatli maydon:
```json
[{"level": "AD", "error_code": 1815869,
  "error_summary": "Ad account is under review",
  "error_message": "...", "error_type": "..."}]
```

### 4.3 Yetkazish tashxisi

```
GET /{adset_id}/delivery_estimate?fields=estimate_ready,estimate_mau_lower_bound,estimate_mau_upper_bound
GET /{adset_id}/targetingsentencelines
GET /{ad_id}/previews?ad_format=DESKTOP_FEED_STANDARD
```

> ⚠️ v26.0 da `daily_outcomes_curve`, `budget_guardrail`, `estimate_dau`
> olib tashlangan.

### 4.4 Learning phase

```
GET /{adset_id}/insights?fields=spend,actions
GET /{adset_id}?fields=learning_stage_info
```
`learning_stage_info` → `status`: `LEARNING` | `SUCCESS` | `LEARNING_LIMITED`,
`conversions`, `last_sig_edit_ts`.

---

## 5. Boshqaruv (yozish)

> ⚠️ Barcha budjetlar **eng kichik birlikda** — USD uchun sentlarda.
> `$15/kun` = `daily_budget=1500`.

### 5.1 Pauza / ishga tushirish

```
POST /{ad_id}         status=PAUSED | ACTIVE
POST /{adset_id}      status=PAUSED | ACTIVE
POST /{campaign_id}   status=PAUSED | ACTIVE
```

### 5.2 Budjet

```
POST /{adset_id}
     daily_budget=1500                 # $15.00/kun
     # yoki
     lifetime_budget=10500             # $105.00 umrbod
     end_time=2026-08-30T23:59:59+0500 # lifetime uchun MAJBURIY
```

### 5.3 Vaqt jadvali (dayparting)

```
POST /{adset_id}
     lifetime_budget=10500
     end_time=...
     pacing_type=["day_parting"]
     adset_schedule=[
       {"start_minute":1080,"end_minute":1439,"days":[0,1,2,3,4,5,6],
        "timezone_type":"USER"}
     ]
```

- `start_minute` / `end_minute` — yarim tundan boshlab daqiqalarda
  (18:00 = 1080, 23:59 = 1439)
- `days` — 0 = yakshanba … 6 = shanba
- `timezone_type` — `"USER"` (ko'ruvchining vaqti) yoki `"ADVERTISER"`

> **Muhim cheklov:** `adset_schedule` faqat **lifetime_budget** bilan ishlaydi.
> Kunlik budjetda dayparting umuman mumkin emas — bu Meta'ning qattiq qoidasi.

### 5.4 Reklama va forma yaratish

```
POST /act_{id}/campaigns      name, objective=OUTCOME_LEADS, status, special_ad_categories=[]
POST /act_{id}/adsets         name, campaign_id, daily_budget, billing_event,
                              optimization_goal=LEAD_GENERATION, targeting, promoted_object
POST /act_{id}/adcreatives    name, object_story_spec
POST /act_{id}/ads            name, adset_id, creative={"creative_id": ...}
POST /{page_id}/leadgen_forms name, questions, privacy_policy, locale, follow_up_action_url
```

> Instant Form **yaratilgandan keyin tahrirlab bo'lmaydi**. Yagona yo'l —
> yangisini yaratib, reklamaga ulash.

---

## 6. Sahifa va biznes

```
GET /{page_id}?fields=id,name,username,fan_count,followers_count,link,verification_status
GET /{page_id}/subscribed_apps
GET /{business_id}/owned_ad_accounts?fields=id,name,account_status
GET /{business_id}/system_users
GET /{business_id}/client_pages
```

---

## 7. Xato kodlari

| Kod | Ma'nosi | Yechim |
|---|---|---|
| 190 | Token yaroqsiz / muddati tugagan | Yangi token |
| 102 | Sessiya yaroqsiz | Qayta login |
| 10 | Ruxsat yo'q | Scope qo'shing |
| 200–299 | Ruxsat yetishmaydi | Asset biriktiring / scope |
| 100 | Parametr xato | Maydon nomini tekshiring |
| 4 | App rate limit | Kuting / kamroq so'rov |
| 17 | User rate limit | Kuting |
| 80004 | Ads API rate limit | Backoff |
| 613 | Chaqiruvlar limiti | Backoff |
| 2635 | Eski versiya | Versiyani yangilang |
| 368 | Vaqtinchalik blok | Kuting |

### Rate limit sarlavhalari

Har javobda:
```
X-Business-Use-Case-Usage: {"<act_id>":[{"type":"ads_insights",
  "call_count":12,"total_cputime":8,"total_time":9,
  "estimated_time_to_regain_access":0}]}
```

Har uch qiymat 100 ga yaqinlashsa — tezlikni pasaytiring.
`estimated_time_to_regain_access` daqiqalarda (bloklangan bo'lsa).

**Bizning yuk:** leadlar 60 sekundda 1 marta, statistika soatiga 1 marta —
limitdan ancha pastda.

---

## 8. Loyihada qaysi endpoint qayerda ishlatiladi

| Endpoint | Fayl | Vazifa |
|---|---|---|
| `/{page_id}/leadgen_forms` | `meta_leads.py` | formalarni topish |
| `/{form_id}/leads` | `meta_leads.py` | yangi leadlar |
| `/act_{id}/insights` | `meta_ads.py` | statistika |
| `/act_{id}` | `meta_ads.py` | hisob holati |
| `/act_{id}/ads` | `meta_ads.py` | effective_status + issues_info |
| `/{form_id}?fields=questions` | ⬜ | forma ta'rifini o'qish (email masalasi) |
| `/{adset_id}` POST | ⬜ | budjet / dayparting |
| `/{page_id}/subscribed_apps` | ⬜ | webhook'ga o'tganda |

---

## 9. Tezkor test (token olgach)

```bash
TOKEN="EAAG..."
ACT="840216037679254"
PAGE="582508891606220"
FORM="1630038098545394"

# Token sog'ligi
curl -s "https://graph.facebook.com/debug_token?input_token=$TOKEN&access_token=$TOKEN"

# Hisob holati — nega ishlamayotganini shu aytadi
curl -s "https://graph.facebook.com/act_$ACT?fields=name,account_status,disable_reason,balance,amount_spent,spend_cap&access_token=$TOKEN"

# Reklamalar va muammolari
curl -s "https://graph.facebook.com/act_$ACT/ads?fields=name,effective_status,issues_info&access_token=$TOKEN"

# Bugungi statistika
curl -s "https://graph.facebook.com/act_$ACT/insights?fields=spend,impressions,reach,clicks,ctr,cpm,actions&date_preset=today&level=account&access_token=$TOKEN"

# Formaning to'liq ta'rifi — email bormi?
curl -s "https://graph.facebook.com/$FORM?fields=name,locale,status,questions&access_token=$TOKEN"

# Leadlar
curl -s "https://graph.facebook.com/$FORM/leads?fields=id,created_time,field_data&limit=10&access_token=$TOKEN"
```

Ikkinchi va uchinchi buyruq — bugungi "reklama nega ishlamayapti" savolining
javobini beradi.
