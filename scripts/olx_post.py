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
import json
import os
import random
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://unused/olx-local")  # config.py talabi; bazaga ulanmaydi

from playwright.async_api import async_playwright  # noqa: E402

import olx_export  # noqa: E402

PROFILE = Path(os.getenv("LOCALAPPDATA", ".")) / "ketoshop-olx-profile"
POSTED = PROFILE / "posted.json"
CDP = "http://127.0.0.1:9333"
CATEGORY = "Кондитерские изделия"      # egasi tanlagan (Продукты питания / Напитки)
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


async def pick_category(page) -> None:
    box = page.locator("[data-testid=category-field-container]")
    text = await box.inner_text()
    if CATEGORY in text and "Наше предложение" not in text:
        return
    button = box.get_by_text("Изменить").or_(box.get_by_text("Выберите категорию")).first
    await button.click()
    search = page.get_by_placeholder("Поиск").last
    await search.fill(CATEGORY)
    await page.get_by_text(CATEGORY, exact=True).first.click()
    await page.wait_for_timeout(1500)


async def fill_ad(page, p: dict, photos: list[str]) -> None:
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
    await pick_category(page)

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


async def submit(page) -> str:
    await page.locator("[data-testid=submit-btn]").click()
    await page.wait_for_timeout(6000)
    return page.url


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
        print(f"Faol mahsulot: {len(products)}, joylangan: {len(posted)}, bu safar: {len(todo)}")

        page = await ctx.new_page()
        tmp = Path(tempfile.mkdtemp(prefix="olx_"))
        for n, p in enumerate(todo, 1):
            title = olx_export.olx_title(p)
            try:
                photos = await download_photos(ctx, site, p, tmp)
                await fill_ad(page, p, photos)
                shot = tmp / f"{p['id']}.png"
                await page.screenshot(path=str(shot), full_page=True)
                if args.dry:
                    print(f"[{n}] DRY #{p['id']} {title} — {len(photos)} rasm, skrinshot: {shot}")
                    continue
                url = await submit(page)
                posted[str(p["id"])] = {"title": title, "price": olx_export.price_of(p),
                                        "after_submit_url": url, "at": datetime.now().isoformat(timespec="seconds")}
                save_posted(posted)
                print(f"[{n}] ✅ #{p['id']} {title} → {url}")
            except Exception as e:
                await page.screenshot(path=str(tmp / f"{p['id']}_error.png"), full_page=True)
                print(f"[{n}] ❌ #{p['id']} {title}: {e}")
            # Odamdek oraliq — OLX ketma-ket e'lonlarni spam deb bloklamasin.
            await asyncio.sleep(random.uniform(40, 90) if not args.dry else 1)
        print("Skrinshotlar:", tmp)


if __name__ == "__main__":
    asyncio.run(main())
