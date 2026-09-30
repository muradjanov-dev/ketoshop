"""
OLX.uz ga mahsulotlarni brauzer orqali joylash — API'siz (2026-09-29).

Egasining kompyuterida ishlaydi, serverda emas: OLX'ga kirish telefon + SMS
bilan bo'ladi, buni faqat odam qila oladi. Shuning uchun alohida Chrome
profili ochiladi, egasi unda bir marta OLX'ga va /admin saytga kiradi, qolganini
shu skript qiladi — o'sha ochiq brauzerga CDP orqali ulanib.

Ishga tushirish:
    1) Chrome (bir marta):
       chrome.exe --remote-debugging-port=9333 --user-data-dir=%LOCALAPPDATA%\\ketoshop-olx-profile
       → olx.uz ga kiring, yangi tabda https://<sayt>/admin ga kiring.
    2) python scripts/olx_post.py --site https://<sayt> --dry --limit 1   # to'ldiradi, joylamaydi
       python scripts/olx_post.py --site https://<sayt> --limit 1         # bitta sinov
       python scripts/olx_post.py --site https://<sayt>                   # qolgani

Mahsulot, narx, rasm — /admin/api/products dan, kirilgan sessiya cookie'si
bilan (parol skriptga berilmaydi). Matn olx_export.py dagi bilan bir xil.
Joylanganlar posted.json da (profil papkasida) — takror ishga tushirish
faqat qolganlarini joylaydi.
"""
import argparse
import asyncio
import html
import json
import os
import random
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://unused/olx-local")  # config.py talabi; bazaga ulanmaydi

from playwright.async_api import async_playwright  # noqa: E402

import olx_export  # noqa: E402
from config import ADMIN_IDS  # noqa: E402

PROFILE = Path(os.getenv("LOCALAPPDATA", ".")) / "ketoshop-olx-profile"
POSTED = PROFILE / "posted.json"
CDP = "http://127.0.0.1:9333"
FOOD = "Продукты питания"              # OLX: Дом и сад / Продукты питания / Напитки
# Do'kon kategoriyasi → OLX bo'limlari (afzal tartibda). Bepul limit bo'lim
# bo'yicha: 29.09 "Кондитерские изделия" 5 tadan keyin pul so'radi, shuning
# uchun har mahsulot o'z joyiga tushadi va limit tugasa keyingisiga o'tadi.
CATEGORY_MAP = {
    "ready_made": ["Кондитерские изделия", "Другое"],
    "honey": ["Мёд", "Бакалея", "Другое"],
}
DEFAULT_CATEGORIES = ["Бакалея", "Другое"]
EXHAUSTED = PROFILE / "exhausted.json"   # limiti tugagan OLX bo'limlari
CITY = "Ташкент"
CONTACT_NAME = "Ketoshop"
PHONE = olx_export._phones().split(",")[0].strip()   # Ketoshop raqami (SUPPORT_PHONES)


def load_posted() -> dict:
    try:
        return json.loads(POSTED.read_text("utf-8"))
    except Exception:
        return {}


def save_posted(data: dict) -> None:
    POSTED.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")


def _normalize(p: dict) -> dict:
    if isinstance(p.get("discount_until"), str):
        try:
            p["discount_until"] = datetime.fromisoformat(p["discount_until"]).replace(tzinfo=None)
        except ValueError:
            p["discount_until"] = None
    return p


async def fetch_products(ctx, site: str) -> list[dict]:
    resp = await ctx.request.get(f"{site}/admin/api/products")
    if resp.status != 200:
        raise SystemExit(f"/admin/api/products → {resp.status}. Shu brauzerda {site}/admin ga kirilganmi?")
    items = (await resp.json())["products"]
    return [_normalize(p) for p in items
            if p.get("is_active") == 1 and not p.get("b2b_only") and float(p.get("quantity") or 0) > 0]


async def download_photos(ctx, site: str, p: dict, folder: Path) -> list[str]:
    refs = [r for r in (p.get("image_url"), p.get("photo_id")) if r]
    refs = list(dict.fromkeys(refs))[:olx_export.MAX_PHOTOS]
    files = []
    for i, ref in enumerate(refs, 1):
        url = ref if ref.startswith("http") else (site + ref if ref.startswith("/") else f"{site}/api/photo/{ref}")
        resp = await ctx.request.get(url)
        if resp.status == 200:
            path = folder / f"{p['id']}_{i}.jpg"
            path.write_bytes(await resp.body())
            files.append(str(path))
    return files


def load_exhausted() -> set:
    try:
        return set(json.loads(EXHAUSTED.read_text("utf-8")))
    except Exception:
        return set()


def categories_for(p: dict, exhausted: set) -> list[str]:
    return [c for c in CATEGORY_MAP.get(p.get("category"), DEFAULT_CATEGORIES) if c not in exhausted]


async def pick_category(page, category: str) -> None:
    box = page.locator("[data-testid=category-field-container]")
    text = await box.inner_text()
    if category in text and "Наше предложение" not in text:
        return
    button = box.get_by_text("Изменить").or_(box.get_by_text("Выберите категорию")).first
    await button.click()
    search = page.get_by_placeholder("Поиск").last
    await search.fill(FOOD)
    await page.wait_for_timeout(2000)
    # "Другое" OLX'da o'nlab bo'limda bor — faqat Продукты питания ichidagisini olamiz.
    await page.evaluate("""([name, food]) => {
        const el = [...document.querySelectorAll('*')].find(e =>
            e.children.length === 0 && e.textContent.trim() === name &&
            e.parentElement && e.parentElement.parentElement &&
            e.parentElement.parentElement.innerText.includes(food));
        if (!el) throw new Error('OLX bo\'limi topilmadi: ' + name);
        el.click();
    }""", [category, FOOD])
    await page.wait_for_timeout(1500)
    text = await box.inner_text()
    if category not in text or FOOD not in text:
        raise RuntimeError(f"bo'lim tanlanmadi: {category}")


async def fill_ad(page, p: dict, photos: list[str], category: str) -> None:
    await page.goto("https://www.olx.uz/d/adding/", wait_until="domcontentloaded")
    # Tugallanmagan qoralama bo'lsa OLX "davom ettirasizmi?" deb so'raydi — har doim toza boshlaymiz.
    fresh = page.get_by_text("Нет, начать заново")
    title = page.locator("#title")
    await fresh.or_(title).first.wait_for()
    if await fresh.is_visible():
        await fresh.click()
    await title.wait_for()
    await page.fill("#title", olx_export.olx_title(p))
    await page.keyboard.press("Tab")
    await page.wait_for_timeout(2500)          # OLX o'z kategoriya taklifini chiqarguncha
    await pick_category(page, category)

    if photos:
        await page.locator("input[data-testid=attach-photos-input]").first.set_input_files(photos)
        await page.wait_for_timeout(2000 + 1500 * len(photos))

    await page.fill("#description", olx_export.olx_description(p))
    await page.fill("[data-testid=price-input]", str(olx_export.price_of(p)))

    # Valyuta o'zi "сум" turadi; boshqasi bo'lsa to'xtaymiz, adashib $ bilan chiqmasin.
    currency = page.locator("[data-testid=parameters-field-widget] input[placeholder='Выбрать']")
    if await currency.count() and (await currency.first.input_value()).strip() != "сум":
        raise RuntimeError("valyuta 'сум' emas — qo'lda tekshiring")

    for testid in ("private_business_business_unactive", "parameters.state_new_unactive"):
        btn = page.locator(f"[data-testid='{testid}']")
        if await btn.count():
            await btn.first.click()

    loc = page.locator("[data-testid=autosuggest-location-search-input]")
    if not (await loc.input_value()).strip():
        await loc.fill(CITY)
        await page.wait_for_timeout(1500)
        await page.locator("[data-testid=location-list-item]").first.click()

    await page.locator("input[name=person]").fill(CONTACT_NAME)
    phone = page.locator("input[name=phone]")
    if await phone.is_editable():
        await phone.fill(PHONE)


class PaidLimit(Exception):
    """OLX bepul limit tugadi va pul so'rayapti — to'xtaymiz, egasi hal qiladi."""


async def submit(page) -> int:
    """E'lonni yuboradi, OLX bergan ad-id ni qaytaradi.
    Muvaffaqiyat belgisi — /purchase/...?ad-id=N&activation-code=activated_from_free_limit.
    Forma o'zgarmasa, xatolar matni bilan istisno."""
    # Rasm hali yuklanayotgan bo'lsa tugma o'chiq turadi — yoqilguncha kutamiz.
    btn = page.locator("[data-testid=submit-btn]")
    for _ in range(90):
        if await btn.is_enabled():
            break
        await page.wait_for_timeout(1000)
    await btn.click()
    try:
        await page.wait_for_url(re.compile(r"ad-id=\d+"), timeout=30000)
    except Exception:
        errs = await page.eval_on_selector_all(
            "[data-has-error=true]", "els => els.map(e => e.innerText.slice(0, 120))")
        raise RuntimeError("OLX qabul qilmadi: " + ("; ".join(e.replace("\n", " ") for e in errs) or page.url))
    ad_id = int(re.search(r"ad-id=(\d+)", page.url).group(1))
    # Bepul limitdan ham, sotib olingan paketdan ham faollashgani "activated_from_…"
    # bilan qaytadi; to'lov usulini tanlash sahifasi (/activate/method/) — pul so'ralyapti.
    if "/activate/method" in page.url or "activated_from" not in page.url:
        raise PaidLimit(f"ad-id={ad_id}: {page.url}")
    return ad_id


def ad_link(ad_id: int) -> str:
    return f"https://www.olx.uz/d/{ad_id}/"


def bot_token() -> str:
    token = os.getenv("KETOSHOP_BOT_TOKEN", "").strip()
    if not token and (PROFILE / "bot_token.txt").exists():
        token = (PROFILE / "bot_token.txt").read_text("utf-8").strip()
    return token


async def notify_admins(ctx, posted: dict, total: int, force: bool = False, extra: str = "") -> None:
    """Har 10 ta yangi e'londa adminlarga bot orqali havolalar ro'yxati.
    Token hali qo'yilmagan bo'lsa ro'yxat navbatda qoladi va keyingi safar ketadi."""
    pending = [(pid, a) for pid, a in posted.items() if a.get("ad_id") and not a.get("notified")]
    if not pending or (len(pending) < 10 and not force):
        return
    token = bot_token()
    if not token:
        print(f"(bot token yo'q — {len(pending)} ta e'lon xabari navbatda)")
        return
    done = sum(1 for a in posted.values() if a.get("ad_id"))
    lines = [f"🟢 <b>OLX: yana {len(pending)} ta mahsulot joylandi</b> ({done}/{total})", ""]
    for i, (_, a) in enumerate(pending, 1):
        lines.append(f'{i}. <a href="{ad_link(a["ad_id"])}">{html.escape(a["title"])}</a> — {a["price"]:,} so\'m'.replace(",", " "))
    lines.append("\nE'lonlar OLX moderatsiyasidan o'tgach havola ochiladi (odatda bir necha daqiqa).")
    if extra:
        lines.append("\n" + extra)
    text = "\n".join(lines)
    ok = 0
    for admin_id in ADMIN_IDS:
        resp = await ctx.request.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": admin_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True})
        ok += resp.status == 200
    if ok:
        for pid, _ in pending:
            posted[pid]["notified"] = True
        save_posted(posted)
    print(f"📨 adminlarga yuborildi: {ok}/{len(ADMIN_IDS)}")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", required=True, help="bot sayti, masalan https://example.uz")
    ap.add_argument("--dry", action="store_true", help="to'ldiradi, lekin joylamaydi")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", type=int, help="faqat shu mahsulot id")
    args = ap.parse_args()
    site = args.site.rstrip("/")

    posted = load_posted()
    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(CDP)
        ctx = browser.contexts[0]
        products = await fetch_products(ctx, site)
        todo = [p for p in products if str(p["id"]) not in posted]
        if args.only:
            todo = [p for p in products if p["id"] == args.only]
        if args.limit:
            todo = todo[:args.limit]
        print(f"Faol mahsulot: {len(products)}, joylangan: {len(posted)}, bu safar: {len(todo)}", flush=True)

        page = await ctx.new_page()
        tmp = Path(tempfile.mkdtemp(prefix="olx_"))
        fails_in_row = 0
        stop_note = ""
        exhausted = load_exhausted()
        for n, p in enumerate(todo, 1):
            title = olx_export.olx_title(p)
            cats = categories_for(p, exhausted)
            if not cats:
                print(f"[{n}/{len(todo)}] ⏭ #{p['id']} {title}: bepul bo'lim qolmadi", flush=True)
                continue
            category = cats[0]
            try:
                photos = await download_photos(ctx, site, p, tmp)
                await fill_ad(page, p, photos, category)
                if args.dry:
                    shot = tmp / f"{p['id']}.png"
                    await page.screenshot(path=str(shot), full_page=True)
                    print(f"[{n}] DRY #{p['id']} {title} — {len(photos)} rasm, skrinshot: {shot}", flush=True)
                    continue
                ad_id = await submit(page)
                posted[str(p["id"])] = {"title": title, "price": olx_export.price_of(p), "ad_id": ad_id,
                                        "category": category, "photos": len(photos),
                                        "at": datetime.now().isoformat(timespec="seconds")}
                save_posted(posted)
                fails_in_row = 0
                print(f"[{n}/{len(todo)}] ✅ #{p['id']} {title} [{category}] → {ad_link(ad_id)}", flush=True)
                await notify_admins(ctx, posted, len(products))
            except PaidLimit as e:
                # E'lon OLX'da "Неоплаченные"da qoladi (ko'rinmaydi, pul yechilmaydi).
                # Mahsulotni belgilab qo'yamiz — keyingi ishga tushirishda qayta
                # yaratilmasin; bo'limni tugagan deb, qolganlar boshqasiga o'tadi.
                exhausted.add(category)
                EXHAUSTED.write_text(json.dumps(sorted(exhausted), ensure_ascii=False), "utf-8")
                posted[str(p["id"])] = {"title": title, "price": olx_export.price_of(p), "unpaid": str(e),
                                        "category": category, "at": datetime.now().isoformat(timespec="seconds")}
                save_posted(posted)
                print(f"[{n}/{len(todo)}] 💰 #{p['id']} {title}: '{category}' limiti tugadi — "
                      f"bu bo'lim o'tkazib yuboriladi", flush=True)
            except Exception as e:
                fails_in_row += 1
                await page.screenshot(path=str(tmp / f"{p['id']}_error.png"), full_page=True)
                print(f"[{n}/{len(todo)}] ❌ #{p['id']} {title}: {e}", flush=True)
                if fails_in_row >= 3:
                    stop_note = "⏸ Ketma-ket 3 ta xato — to'xtatildi, tekshirish kerak."
                    print(stop_note, flush=True)
                    break
            # Odamdek oraliq — OLX ketma-ket e'lonlarni spam deb bloklamasin.
            await asyncio.sleep(random.uniform(40, 90) if not args.dry else 1)
        if not args.dry:
            await notify_admins(ctx, posted, len(products), force=True, extra=stop_note)
        print("Skrinshotlar:", tmp, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
