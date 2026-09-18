"""Tannarx backfill — 2026-09-18.

Ikki ish qiladi:

1. Katalogdagi tannarxi kiritilmagan mahsulotlarga «Asl narx»ni yozadi
   (Keto muzqaymoqlari 25 000, Zig'ir urug'i 1000g 16 000).
2. Eski "Eritritol (B2B)" buyurtma qatorlariga kg boshiga tannarxni
   yozadi. Ular `"id": -1` bilan saqlangan edi — hech qaysi mahsulotga
   to'g'ri kelmaydi, shuning uchun database.line_cost ularni 0 so'mga
   hisoblagan va Maqsadlar hisoboti foydani butun partiya narxicha
   oshirib ko'rsatgan. Yangi kod qatorning o'z `cost_price` ini o'qiydi,
   bu skript esa eskilarini shu ko'rinishga keltiradi.

Ishlatish (serverda, bot konteyneri ichida — DATABASE_URL o'sha yerda):

    docker exec -i <container> python - < backfill_costs_2026_09_18.py
    docker exec -i <container> python - < backfill_costs_2026_09_18.py -- --apply

Argumentsiz ishga tushsa hech narsani o'zgartirmaydi, faqat nimani
o'zgartirishini ko'rsatadi. Avval shunday ko'ring: mahsulot nomi va
BIRLIGI to'g'rimi, tekshiring. Birlik "kg" bo'lsa tannarx 1 kg uchun,
"piece" bo'lsa 1 dona uchun yoziladi.

    --apply                  o'zgartirishlarni haqiqatan saqlaydi
    --eritritol-cost 30000   eski B2B Eritritol qatorlariga kg boshiga
                             tannarx (berilmasa, ular tegilmay qoladi)
"""
import argparse
import asyncio
import json
import os
import sys

import asyncpg

# Nom bo'yicha qidiriladi, chunki ID lar bu yerda ma'lum emas. ILIKE
# naqshlari apostrof turiga bog'liq bo'lmasin uchun ataylab "zig%ir urug%"
# shaklida — bazada ' ham, ’ ham uchraydi.
PRODUCT_COSTS = [
    ("%muzqaymoq%", 25_000, "Keto muzqaymoqlari"),
    ("%zig%ir urug%1000%", 16_000, "Zig'ir urug'i 1000g"),
]

ERITRITOL_LINE_NAME = "Eritritol (B2B)"


def fmt(n) -> str:
    return f"{int(n):,}".replace(",", " ")


async def fix_products(conn, apply: bool) -> None:
    print("\n=== 1. Mahsulot tannarxlari ===")
    for pattern, cost, label in PRODUCT_COSTS:
        rows = await conn.fetch(
            """SELECT id, name, unit, COALESCE(cost_price, 0) AS cost_price,
                      COALESCE(is_active, 1) AS is_active
                 FROM products
                WHERE name ILIKE $1
                ORDER BY name""",
            pattern,
        )
        print(f"\n{label}  (naqsh: {pattern})  -> {fmt(cost)} so'm")
        if not rows:
            print("  ⚠️  hech narsa topilmadi — nom o'zgargan bo'lishi mumkin")
            continue
        for r in rows:
            state = "" if r["is_active"] else "  [nofaol]"
            mark = "o'zgarmaydi" if r["cost_price"] else "YOZILADI"
            print(f"  #{r['id']:<5} {r['name'][:46]:<46} birlik={r['unit'] or '?':<7} "
                  f"hozir={fmt(r['cost_price']):>9}  {mark}{state}")

        if not apply:
            continue
        # Faqat bo'sh turganlari. Qo'lda kiritilgan tannarxni bu skript
        # bosib ketmasligi kerak — admin panelda aniqrog'i turgan bo'lishi
        # mumkin.
        updated = await conn.execute(
            """UPDATE products
                  SET cost_price = $2
                WHERE name ILIKE $1
                  AND COALESCE(cost_price, 0) = 0""",
            pattern, float(cost),
        )
        print(f"  ✅ {updated}")


async def fix_eritritol(conn, apply: bool, cost_per_kg: float) -> None:
    print("\n=== 2. Eski Eritritol (B2B) buyurtmalari ===")
    rows = await conn.fetch(
        """SELECT id, items, total, COALESCE(delivered_at, created_at) AS dt
             FROM orders
            WHERE source = 'b2b' AND items LIKE $1
            ORDER BY id""",
        f"%{ERITRITOL_LINE_NAME}%",
    )
    if not rows:
        print("  Bunday buyurtma yo'q.")
        return

    touched = []
    for r in rows:
        try:
            items = json.loads(r["items"] or "[]")
        except Exception:
            print(f"  #{r['id']}: items o'qib bo'lmadi, tashlab ketildi")
            continue
        needs = False
        for it in items:
            if it.get("name") != ERITRITOL_LINE_NAME:
                continue
            qty = float(it.get("quantity") or 0)
            have = float(it.get("cost_price") or 0)
            print(f"  #{r['id']:<5} {str(r['dt'])[:10]}  {qty:g} kg  "
                  f"jami={fmt(r['total']):>11}  tannarx={fmt(have) if have else '—'}")
            if not it.get("bulk"):
                # Miqdor bu yerda og'irlik (0.5 = yarim kilo). `bulk` belgisi
                # bo'lmasa locales.get_item_unit kg ni "dona" ga aylantiradi
                # va ro'yxatda "0.5 dona" deb chiqadi.
                it["bulk"] = True
                needs = True
            if have > 0:
                continue
            if cost_per_kg > 0:
                it.pop("id", None)          # o'lik -1
                it["cost_price"] = cost_per_kg
                needs = True
        if needs:
            touched.append((r["id"], json.dumps(items, ensure_ascii=False)))

    if cost_per_kg <= 0:
        print("\n  ⚠️  --eritritol-cost berilmadi, shuning uchun tannarx yozilmaydi."
              "\n     1 kg optom tannarxini bilsangiz, masalan:"
              "\n     --apply --eritritol-cost 30000")
    if not touched:
        print("\n  O'zgartiradigan narsa yo'q.")
        return
    print(f"\n  {len(touched)} ta buyurtma yangilanadi"
          + (f" ({fmt(cost_per_kg)} so'm/kg)." if cost_per_kg > 0 else "."))
    if not apply:
        return
    for oid, payload in touched:
        await conn.execute("UPDATE orders SET items = $2 WHERE id = $1", oid, payload)
    print(f"  ✅ {len(touched)} ta buyurtma yangilandi")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="haqiqatan saqlash (bo'lmasa faqat ko'rsatadi)")
    ap.add_argument("--eritritol-cost", type=float, default=0,
                    help="eski B2B Eritritol qatorlari uchun so'm/kg")
    args = ap.parse_args()

    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL yo'q — bu skriptni bot konteyneri ichida ishga tushiring.")
        return 1

    conn = await asyncpg.connect(dsn)
    try:
        print("KO'RIB CHIQISH (hech narsa o'zgarmaydi)" if not args.apply
              else "⚠️  APPLY — o'zgarishlar saqlanadi")
        await fix_products(conn, args.apply)
        await fix_eritritol(conn, args.apply, args.eritritol_cost)
    finally:
        await conn.close()

    if not args.apply:
        print("\nHammasi to'g'ri bo'lsa, yana bir marta --apply bilan ishga tushiring.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
