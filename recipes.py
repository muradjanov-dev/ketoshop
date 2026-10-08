"""
Saytdagi retseptlar — har 2 kunda bitta (egasi, 2026-10-08).

Kontent recipes_content.py da. Bu modul:
  • qaysi retsept "bugungi" ekanini hisoblaydi (saytda faqat shu bitta
    ko'rinadi — egasi: "har kuni faqat 1 ta retsept ko'rsat, hammasini emas") — START dan boshlab har
    EVERY_DAYS kunda navbatdagisi; kutubxona tugasa, boshidan aylanadi.
    Yangi retsept qo'shish = recipes_content.RECIPES oxiriga qo'shish;
  • retsept masalliqlarini katalogdagi haqiqiy mahsulotlarga bog'laydi
    (rasm, joriy narx, omborda bormi) — narx kontentda yozilmaydi, shuning
    uchun narx o'zgarsa retsept o'zi to'g'ri ko'rsatadi;
  • "🛒 Barcha masalliqlarni savatga": omborda bor har bir mahsulotdan 1 ta
    qadoq savatga tushadi; savatda allaqachon bori qayta qo'shilmaydi.

Rasmlar sun'iy intellekt yordamida yaratilgan va matnda buni ochiq aytamiz
(egasi: "rasmlar ai yordamida qilinganini bildirib qo'yishimiz kerak, matnda").
"""
import time
from datetime import date, datetime, timedelta

import database
from recipes_content import RECIPES

START = date(2026, 10, 8)
EVERY_DAYS = 2
TZ_OFFSET = timedelta(hours=5)
CATALOG_TTL = 300

AI_NOTE = {
    "uz": "📸 Rasm sun'iy intellekt yordamida yaratilgan",
    "ru": "📸 Изображение создано с помощью ИИ",
}

LABELS = {
    "badge": {"uz": "🍳 Yangi retsept", "ru": "🍳 Новый рецепт"},
    "open": {"uz": "Retseptni ochish", "ru": "Открыть рецепт"},
    "minutes": {"uz": "{n} daqiqa", "ru": "{n} мин"},
    "carbs": {"uz": "≈{n} g uglevod", "ru": "≈{n} г углеводов"},
    "kcal": {"uz": "≈{n} kkal", "ru": "≈{n} ккал"},
    "per_serving": {"uz": "1 porsiyada, taxminan", "ru": "на порцию, примерно"},
    "ingredients": {"uz": "Masalliqlar", "ru": "Ингредиенты"},
    "from_home": {"uz": "uydan", "ru": "из дома"},
    "out_of_stock": {"uz": "hozir tugagan", "ru": "нет в наличии"},
    "add_all": {"uz": "🛒 Barcha masalliqlarni savatga", "ru": "🛒 Все ингредиенты в корзину"},
    "add_all_sub": {"uz": "Ketoshop mahsulotlari — har biridan 1 qadoq",
                    "ru": "Продукты Ketoshop — по 1 упаковке"},
    "steps": {"uz": "Tayyorlash", "ru": "Приготовление"},
    "tip": {"uz": "💡 Maslahat", "ru": "💡 Совет"},
    "next": {"uz": "Keyingi retsept — {date}", "ru": "Следующий рецепт — {date}"},
    "added": {"uz": "✅ {n} ta mahsulot savatga qo'shildi", "ru": "✅ Добавлено в корзину: {n}"},
    "already": {"uz": "👍 Masalliqlar allaqachon savatingizda", "ru": "👍 Ингредиенты уже в корзине"},
    "missing": {"uz": "Hozir tugagan: {names}", "ru": "Нет в наличии: {names}"},
    "back": {"uz": "← Orqaga", "ru": "← Назад"},
}

_catalog_cache: dict = {"at": 0.0, "rows": []}


def labels(lang: str) -> dict:
    return {key: _pick(entry, lang) for key, entry in LABELS.items()}


def _pick(entry: dict, lang: str) -> str:
    if lang == "ru":
        return entry["ru"]
    if lang == "uz_cyr":
        from translit import lat_to_cyr
        return lat_to_cyr(entry["uz"])
    return entry["uz"]


def today_tk() -> date:
    return (datetime.utcnow() + TZ_OFFSET).date()


def schedule(today: date | None = None) -> tuple[dict, list[dict], date]:
    """(bugungi retsept, avvalgilari — yangisi birinchi, keyingisi qachon)."""
    today = today or today_tk()
    n = max(0, (today - START).days) // EVERY_DAYS + 1       # chiqqan retseptlar soni
    idx = (n - 1) % len(RECIPES)
    if n <= len(RECIPES):
        earlier = list(reversed(RECIPES[:idx]))
    else:
        earlier = [RECIPES[(idx - k) % len(RECIPES)] for k in range(1, len(RECIPES))]
    return RECIPES[idx], earlier, START + timedelta(days=n * EVERY_DAYS)


def find(slug: str, today: date | None = None) -> dict | None:
    """Faqat chiqqan retseptlar — kelajakdagisi havola bilan ham ochilmaydi."""
    current, earlier, _ = schedule(today)
    for recipe in [current, *earlier]:
        if recipe["slug"] == slug:
            return recipe
    return None


# ───────────────────────────── mahsulotlar ─────────────────────────────

def _norm(text: str) -> str:
    text = (text or "").lower()
    for ch in "ʻʼ‘’`´":
        text = text.replace(ch, "'")
    return text


async def _catalog() -> list[dict]:
    now = time.monotonic()
    if now - _catalog_cache["at"] < CATALOG_TTL and _catalog_cache["rows"]:
        return _catalog_cache["rows"]
    async with database.pool.acquire() as conn:
        rows = [dict(r) for r in await conn.fetch(
            """SELECT id, name, name_ru, price, unit, COALESCE(quantity, 0) AS quantity,
                      photo_id, COALESCE(discount_percent, 0) AS discount_percent, discount_until
                 FROM products
                WHERE is_active = 1 AND (b2b_only IS NOT TRUE) AND COALESCE(price, 0) > 0""")]
    _catalog_cache.update(at=now, rows=rows)
    return rows


def match_product(groups: list[list[str]], catalog: list[dict]) -> dict | None:
    """Birinchi mos guruh; bir nechta qadoq bo'lsa — omborda bor eng hamyonbopi."""
    for group in groups:
        hits = [p for p in catalog if all(tok in _norm(p["name"]) for tok in group)]
        if not hits:
            continue
        in_stock = [p for p in hits if float(p["quantity"]) > 0]
        return min(in_stock or hits, key=lambda p: float(p["price"]))
    return None


def _photo(ref) -> str | None:
    """Telegram file_id — /api/photo proksi orqali; yuklangan rasm — o'zi."""
    if not ref:
        return None
    ref = str(ref).strip()
    return ref if ref.startswith(("/", "http://", "https://")) else f"/api/photo/{ref}"


def _product_view(p: dict, lang: str) -> dict:
    from locales import get_display_unit, localize_product_text
    price = database.effective_price(p["price"], p.get("discount_percent"), p.get("discount_until"))
    return {
        "id": p["id"],
        "name": localize_product_text(p["name"], p.get("name_ru"), lang),
        "price": price,
        "unit": get_display_unit(p["unit"], lang),
        "photo_url": _photo(p.get("photo_id")),
        "out_of_stock": float(p["quantity"]) <= 0,
    }


async def view(recipe: dict, lang: str, *, full: bool = True) -> dict:
    """Mini App uchun: tarjima qilingan matn + bog'langan mahsulotlar."""
    out = {
        "slug": recipe["slug"],
        "title": _pick(recipe["title"], lang),
        "intro": _pick(recipe["intro"], lang),
        "image_url": f"/static/recipes/{recipe['slug']}.jpg",
        "minutes": recipe["minutes"],
        "rest": _pick(recipe["rest"], lang) if recipe.get("rest") else "",
        "servings": _pick(recipe["servings"], lang),
        "per_serving": recipe["per_serving"],
        "ai_note": _pick(AI_NOTE, lang),
    }
    if not full:
        return out
    catalog = await _catalog()
    ingredients = []
    for item in recipe["ingredients"]:
        row = {"amount": _pick(item["amount"], lang), "name": _pick(item["name"], lang)}
        if item.get("why"):
            row["why"] = _pick(item["why"], lang)
        if item.get("match"):
            p = match_product(item["match"], catalog)
            row["product"] = _product_view(p, lang) if p else None
        ingredients.append(row)
    out.update(
        ingredients=ingredients,
        steps=[_pick(s, lang) for s in recipe["steps"]],
        tip=_pick(recipe["tip"], lang),
    )
    return out


async def add_all_to_cart(user_id: int, recipe: dict, lang: str = "uz") -> dict:
    """Omborda bor har bir retsept mahsulotidan 1 qadoq. Savatda bori qoladi."""
    catalog = await _catalog()
    added, already, missing = [], [], []
    seen: set[int] = set()
    for item in recipe["ingredients"]:
        if not item.get("match"):
            continue
        name = _pick(item["name"], lang)
        p = match_product(item["match"], catalog)
        if not p or float(p["quantity"]) <= 0:
            missing.append(name)
            continue
        if p["id"] in seen:
            continue
        seen.add(p["id"])
        _, in_cart = await database.get_cart_line_for_product(user_id, p["id"])
        if in_cart:
            already.append(name)
            continue
        await database.add_to_cart(user_id, product_id=p["id"], quantity=1)
        added.append(name)
    return {"added": added, "already": already, "missing": missing}
