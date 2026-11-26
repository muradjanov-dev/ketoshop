"""🧭 Talab — dashboard'ning eng tepasidagi bo'lim (egasi, 2026-11-26: "filterlar
asosida odamlar malum vaqt oralig'ida qaysi mahsulotlarni ko'proq so'rashdi,
qanday mavzularda savollar berishdi, umuman talabdan kelib chiqib qanday taklif
berishimiz va sotuvlarni oshirishimiz mumkinligini takliflarini beradigan bo'lim
qo'sh, asosiy dashboardga teparoqqa").

Manbalar (tanlangan davr, Toshkent kunlari — dashboard bilan bir oyna):
* AI suhbatlari (ai_dialog): bot, sayt yordamchisi, kanal guruhi — mijoz savoli;
* Instagram/Facebook izohlari (meta_comments, spam emas);
* Instagram Direct (ig_dm_messages);
* saytdagi qidiruvlar (site_events kind='search').

Hisob kodda, model chaqirilmaydi (bepul): mavzu — ai_stats.classify; mahsulot —
katalog nomining asosi (o'lcham va qadoqsiz: "Bodom uni 500gr" → "bodom uni")
savol matnida uchrasa. Har mahsulot guruhi uchun: necha marta / necha odam
so'radi, saytda necha marta ochildi va savatga tushdi, shu davrda qancha
sotildi, qoldig'i — va qisqa signal ("so'raladi, sotilmayapti", "tugagan").

AI takliflari — alohida tugma (POST /admin/api/demand/advice): yig'ilgan
raqamlar va savollardan namunalar GPT ga beriladi, 5–7 ta aniq taklif qaytadi.
Bir davr uchun 6 soat keshlanadi (bosgan sari pul ketmasin).
"""
from __future__ import annotations

import json
import logging
import re
import time
from collections import Counter, defaultdict
from datetime import timedelta

import ai_stats
import database

logger = logging.getLogger(__name__)

CHANNELS = {"bot": "🤖 Bot", "site": "🌐 Sayt yordamchisi", "group": "👥 Guruh",
            "instagram": "📸 Instagram izohi", "direct": "📩 Direct", "search": "🔎 Sayt qidiruvi"}
SAMPLES_PER_TOPIC = 6
TOP_PRODUCTS = 25
ADVICE_TTL = 6 * 3600
_advice_cache: dict[str, tuple[float, list[str]]] = {}

_SIZE = re.compile(r"\b\d+[.,]?\d*\s*(gr|g|gram|kg|kilo|ml|l|litr|dona|ta|г|гр|кг|мл|л)\b\.?", re.I)
_JUNK = re.compile(r"[«»\"()\[\]+,.!:;/\\|—–\-🍫🍯🫒✏️🥄]")
_APOS = re.compile(r"[ʻʼ‘’`´]")


def _latin(text: str) -> str:
    text = _APOS.sub("'", (text or "").lower())
    if re.search(r"[а-яёўқғҳ]", text):
        try:
            from translit import cyr_to_lat
            text = text + " " + cyr_to_lat(text).lower()
        except Exception:
            pass
    return text


def base_name(name: str) -> str:
    """'Bodom uni 500gr' → 'bodom uni'; 'Qora guruch 1kg Tayland' → 'qora guruch'."""
    text = _SIZE.sub(" ", _APOS.sub("'", (name or "").lower()))
    text = _JUNK.sub(" ", text)
    words = [w for w in text.split() if not w.isdigit()]
    return " ".join(words[:2]).strip()


def _stem(word: str) -> str:
    """O'zbekcha qo'shimchasiz o'zak: 'unidan' → 'uni', 'steviyani' → 'steviya'."""
    for suf in ("laridan", "lardan", "larini", "lari", "dan", "ni", "ga", "da", "ning", "ning"):
        if len(word) > len(suf) + 2 and word.endswith(suf):
            return word[: -len(suf)]
    return word


def _pattern(base: str) -> re.Pattern | None:
    words = [w for w in base.split() if len(w) >= 3]
    if not words:
        return None
    parts = [re.escape(_stem(w)[:max(4, len(_stem(w)) - 1)]) for w in words]
    return re.compile(r"\b" + r"\w*\W+".join(parts), re.I)


async def _rows(since, until) -> list[dict]:
    """[{channel, user, text, at}] — mijozlar yozgan matnlar shu oynada."""
    out: list[dict] = []
    cond = "created_at >= $1" + (" AND created_at <= $2" if until else "")
    args = [since] + ([until] if until else [])
    async with database.pool.acquire() as conn:
        queries = [
            ("ai", f"SELECT channel, user_id::text AS u, question AS t, created_at AS at FROM ai_dialog "
                   f"WHERE {cond}"),
            ("instagram", f"SELECT 'instagram' AS channel, COALESCE(username, from_id) AS u, text AS t, "
                          f"COALESCE(created_at, received_at) AS at FROM meta_comments "
                          f"WHERE COALESCE(category, '') <> 'spam' AND "
                          + cond.replace("created_at", "COALESCE(created_at, received_at)")),
            ("direct", f"SELECT 'direct' AS channel, from_id AS u, text AS t, created_at AS at FROM ig_dm_messages "
                       f"WHERE COALESCE(status, '') NOT IN ('spam') AND {cond}"),
            ("search", f"SELECT 'search' AS channel, user_id::text AS u, ref AS t, created_at AS at FROM site_events "
                       f"WHERE kind = 'search' AND ref IS NOT NULL AND {cond}"),
        ]
        for name, sql in queries:
            try:
                for r in await conn.fetch(sql, *args):
                    if (r["t"] or "").strip():
                        out.append({"channel": r["channel"], "user": r["u"] or "", "text": r["t"], "at": r["at"]})
            except Exception:
                logger.warning("demand: %s unreadable", name, exc_info=True)
    return [r for r in out if r["channel"] in CHANNELS]


async def _site_products(since, until) -> dict[int, dict]:
    cond = "created_at >= $1" + (" AND created_at <= $2" if until else "")
    args = [since] + ([until] if until else [])
    try:
        async with database.pool.acquire() as conn:
            rows = await conn.fetch(
                f"""SELECT ref, COUNT(*) FILTER (WHERE kind = 'view' AND COALESCE(src, '') <> 'back') AS opens,
                           COUNT(*) FILTER (WHERE kind = 'cart_add') AS cart_adds
                      FROM site_events WHERE screen = 'product' AND {cond} GROUP BY ref""", *args)
    except Exception:
        logger.warning("demand: site events unreadable", exc_info=True)
        return {}
    out = {}
    for r in rows:
        try:
            out[int(r["ref"])] = {"opens": int(r["opens"] or 0), "cart_adds": int(r["cart_adds"] or 0)}
        except (TypeError, ValueError):
            continue
    return out


def _signal(g: dict) -> str:
    if g["asked_users"] >= 2 and g["stock"] <= 0:
        return "🔴 So'raladi, lekin tugagan — keltirish kerak"
    if g["asked_users"] >= 3 and g["sold"] == 0:
        return "🟠 So'raladi, sotilmayapti — narx/aksiya/ko'rinishni tekshiring"
    if g["opens"] >= 10 and g["cart_adds"] == 0:
        return "🟡 Saytda ko'riladi, savatga tushmaydi — rasm/tavsif/narx"
    if g["sold"] and g["asked_users"] >= 3:
        return "🟢 Talab va sotuv bor — ko'proq ko'rsating, setga qo'shing"
    return ""


async def collect(period) -> dict:
    """Dashboard bo'limi uchun hamma raqamlar."""
    start, end = database._period_range(period)
    since = start or (database._period_start("all") if hasattr(database, "_period_start") else None)
    if since is None:
        from datetime import datetime
        since = datetime(2020, 1, 1)
    rows = await _rows(since, end)
    products = [p for p in await database.admin_list_products(include_inactive=False) if not p.get("b2b_only")]
    sales = await database.get_product_sales(period)
    sold = {r["id"]: float(r.get("qty") or 0) for r in sales.get("rows", []) if r.get("kind") == "product"}
    site = await _site_products(since, end)

    groups: dict[str, dict] = {}
    for p in products:
        base = base_name(p.get("name") or "")
        if not base or len(base) < 4:
            continue
        g = groups.setdefault(base, {"name": base, "products": [], "ids": [], "stock": 0.0, "sold": 0.0,
                                     "opens": 0, "cart_adds": 0, "asked": 0, "asked_users": 0,
                                     "by_channel": Counter(), "examples": []})
        g["products"].append(p.get("name"))
        g["ids"].append(p["id"])
        g["stock"] += float(p.get("quantity") or 0)
        g["sold"] += sold.get(p["id"], 0.0)
        s = site.get(p["id"]) or {}
        g["opens"] += s.get("opens", 0)
        g["cart_adds"] += s.get("cart_adds", 0)
    patterns = [(base, _pattern(base)) for base in groups]
    patterns = [(b, rx) for b, rx in patterns if rx]

    topics = Counter()
    topic_samples: dict[str, list[str]] = defaultdict(list)
    channels = Counter()
    users_by_group: dict[str, set] = defaultdict(set)
    empty_searches = Counter()
    for r in rows:
        channels[r["channel"]] += 1
        text = r["text"]
        latin = _latin(text)
        if r["channel"] != "search":
            for t in ai_stats.classify(text):
                topics[t] += 1
                if len(topic_samples[t]) < SAMPLES_PER_TOPIC:
                    topic_samples[t].append(text.strip()[:180])
        hit = False
        for base, rx in patterns:
            if rx.search(latin):
                g = groups[base]
                g["asked"] += 1
                g["by_channel"][r["channel"]] += 1
                users_by_group[base].add(f"{r['channel']}:{r['user']}")
                if len(g["examples"]) < 3:
                    g["examples"].append(text.strip()[:140])
                hit = True
        if r["channel"] == "search" and not hit:
            empty_searches[text.strip().lower()[:60]] += 1
    for base, users in users_by_group.items():
        groups[base]["asked_users"] = len(users)

    top = sorted((g for g in groups.values() if g["asked"] or g["opens"]),
                 key=lambda g: (-g["asked_users"], -g["asked"], -g["opens"]))[:TOP_PRODUCTS]
    for g in top:
        g["by_channel"] = dict(g["by_channel"])
        g["signal"] = _signal(g)
        g["sold"] = round(g["sold"], 2)
        g["stock"] = round(g["stock"], 2)
    return {
        "messages": len(rows),
        "people": len({f"{r['channel']}:{r['user']}" for r in rows}),
        "channels": [{"key": k, "title": CHANNELS[k], "n": channels[k]} for k in CHANNELS if channels[k]],
        "topics": [{"key": k, "title": ai_stats.TOPIC_TITLES.get(k, k), "n": n,
                    "samples": topic_samples.get(k, [])} for k, n in topics.most_common()],
        "products": top,
        "unmet": [{"q": q, "n": n} for q, n in empty_searches.most_common(15)],
    }


# ─────────────────────────────── AI takliflari ──────────────────────────────

ADVICE_RULES = """Sen Keto shop (keto, PP, glyutensiz va qandsiz mahsulotlar do'koni, Toshkent, Telegram bot +
sayt + Instagram) egasiga sotuv bo'yicha maslahatchisan. Senga tanlangan davrdagi mijozlar TALABI berilgan:
qaysi mahsulotlarni qancha so'rashgan (va qancha sotilgan, qoldig'i, saytda ko'rilishi), qanday mavzularda
savol berishgan, saytda nimani qidirib topishmagan, va savollardan namunalar.

5–7 ta ANIQ, amaliy taklif yoz — har biri bitta qator, o'zbek tilida (lotin), boshida mos emoji:
- qaysi mahsulotni keltirish / ko'paytirish (so'raladi, tugagan), qaysi biriga aksiya yoki set,
- qaysi mahsulotni ko'proq ko'rsatish (kanal posti, retsept, Instagram), qaysi savollarga tayyor javob,
- topilmagan qidiruvlardan — katalogga nima qo'shish,
- har taklifda raqamga tayan ("12 kishi so'radi, 0 sotildi").
Faqat berilgan raqamlar; taxmin va umumiy gap ("sifatni oshiring") yo'q. Sotuvni oshirishga qaratilgan bo'lsin.
JSON: {"advice": ["...", "..."]}"""
ADVICE_SCHEMA = {"type": "object", "properties": {"advice": {"type": "array", "items": {"type": "string"}}},
                 "required": ["advice"], "additionalProperties": False}


def advice_input(stats: dict) -> str:
    lines = [f"Xabarlar: {stats['messages']}, odamlar: {stats['people']}",
             "Kanallar: " + ", ".join(f"{c['title']} {c['n']}" for c in stats["channels"]), "",
             "MAHSULOTLAR (so'radi: marta/odam · saytda ochildi/savatga · sotildi · qoldiq):"]
    for g in stats["products"][:20]:
        lines.append(f"- {g['name']}: {g['asked']}/{g['asked_users']} · {g['opens']}/{g['cart_adds']} · "
                     f"{g['sold']:g} · {g['stock']:g}" + (f" · namuna: «{g['examples'][0]}»" if g["examples"] else ""))
    lines += ["", "MAVZULAR:"] + [f"- {t['title']}: {t['n']}" + (f" · «{t['samples'][0]}»" if t["samples"] else "")
                                  for t in stats["topics"]]
    if stats["unmet"]:
        lines += ["", "SAYTDA QIDIRIB TOPILMAGAN:"] + [f"- {u['q']} ({u['n']})" for u in stats["unmet"]]
    return "\n".join(lines)[:12000]


USAGE_TAG = " · talab"


async def _ask(key: str, model: str, user: str) -> dict | None:
    import ai_provider
    import openai
    try:
        client = openai.AsyncOpenAI(api_key=key, timeout=90.0, max_retries=1)
        resp = await client.responses.create(
            model=model, instructions=ADVICE_RULES,
            input=[{"role": "user", "content": [{"type": "input_text", "text": user}]}],
            reasoning={"effort": "low"}, max_output_tokens=3000,
            text={"format": {"type": "json_schema", "name": "talab_taklif", "schema": ADVICE_SCHEMA,
                             "strict": True}})
    except Exception as exc:
        import ai_balance
        ai_balance.note_error(exc)
        logger.warning("demand advice: AI failed: %s", exc)
        return None
    try:
        usage = ai_provider._openai_usage(getattr(resp, "usage", None))
        await database.record_ai_usage(model + USAGE_TAG, "openai", usage.input, usage.cached, usage.output,
                                       ai_provider.estimate_cost(model, usage.input, usage.cached, usage.output))
    except Exception:
        logger.debug("demand advice usage not recorded", exc_info=True)
    try:
        data = json.loads(getattr(resp, "output_text", "") or "{}")
    except (TypeError, ValueError):
        logger.warning("demand advice: non-JSON answer (status %s)", getattr(resp, "status", "?"))
        return None
    return data if isinstance(data, dict) else None


async def advice(period_key: str, stats: dict) -> list[str]:
    cached = _advice_cache.get(period_key)
    if cached and time.time() - cached[0] < ADVICE_TTL:
        return cached[1]
    import comment_ai
    key = await comment_ai._openai_key()
    if not key:
        return ["AI kaliti yo'q — /ai_kalit"]
    # comment_ai._ask_openai faqat "reply" maydonli javobni qabul qiladi — takliflar uchun
    # o'z chaqiruvimiz (egasi, 2026-11-26: "ai taklifi ishlamayapti").
    data = await _ask(key, comment_ai.openai_model(), advice_input(stats))
    items = [a.strip() for a in ((data or {}).get("advice") or []) if (a or "").strip()][:8]
    if items:
        _advice_cache[period_key] = (time.time(), items)
    return items or ["AI hozir javob bermadi — birozdan keyin qayta bosing."]


def period_key(period) -> str:
    return json.dumps(period, sort_keys=True, default=str)
