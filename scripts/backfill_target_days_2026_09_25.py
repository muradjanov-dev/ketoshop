"""Maqsadlar tarixini qayta hisoblash — 2026-09-25.

Nima uchun kerak:

  `target_days` jadvalidagi har bir kun o'sha kuni yozilgan. 17.09 dan
  25.09 gacha pul YETKAZILGAN buyurtmalar bo'yicha sanalgan edi, shuning
  uchun kunlik tushum va foyda kam ko'rsatilgan — masalan 24.09 uchun
  561 000 so'm, aslida 1 000 000 dan ortiq savdo bo'lgan kuni. Kod
  tuzatildi (database.SALE_SQL), lekin eski qatorlar o'sha eski raqamlar
  bilan turibdi va «📅 Oxirgi kunlar» ro'yxatida shular ko'rinadi.

  Bu skript har bir kunni yangi qoida bo'yicha qaytadan hisoblab, o'sha
  qatorlarni yangilaydi: sotuv = o'sha kuni tushgan, bekor qilinmagan
  buyurtmalar; tushum/foyda — o'shalarniki.

Ishlatish (serverda, bot konteyneri ichida — DATABASE_URL o'sha yerda):

    docker exec -i <container> python - < backfill_target_days_2026_09_25.py
    docker exec -i <container> python - < backfill_target_days_2026_09_25.py -- --apply

Argumentsiz hech narsa o'zgarmaydi: eski va yangi raqamlar yonma-yon
chiqadi, avval shuni ko'ring.

    --apply      o'zgarishlarni haqiqatan saqlaydi
    --days 30    nechta oxirgi kun qayta hisoblansin (default 30)
"""
import argparse
import asyncio
import os
import sys
from datetime import timedelta

import asyncpg

import database
import targets


def fmt(n) -> str:
    return f"{int(round(n or 0)):,}".replace(",", " ")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="haqiqatan saqlash (bo'lmasa faqat ko'rsatadi)")
    ap.add_argument("--days", type=int, default=30,
                    help="nechta oxirgi kun qayta hisoblansin")
    args = ap.parse_args()

    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL yo'q — bu skriptni bot konteyneri ichida ishga tushiring.")
        return 1

    # init_db() ni chaqirmaymiz: u migratsiyalarni ham yuritadi, bu yerda
    # esa faqat o'qish va bitta UPDATE kerak.
    database.pool = await asyncpg.create_pool(dsn)
    try:
        state = await database.get_targets_state()
        daily_target = int(state.get("daily_orders") or 10)
        monthly_usd = float(state.get("monthly_profit_usd") or 2000)

        today = targets._now_tk().date()
        async with database.pool.acquire() as conn:
            old_rows = {
                r["day"]: dict(r)
                for r in await conn.fetch(
                    "SELECT * FROM target_days ORDER BY day DESC LIMIT $1", args.days
                )
            }

        print("KO'RIB CHIQISH (hech narsa o'zgarmaydi)" if not args.apply
              else "⚠️  APPLY — o'zgarishlar saqlanadi")
        print(f"\n{'Kun':<11}{'sotuv':>12}{'tushum':>26}{'foyda':>26}")
        print("-" * 75)

        changed = 0
        for i in range(args.days):
            day = today - timedelta(days=i)
            period = {"start": day.isoformat(), "end": day.isoformat()}
            stats = await database.get_admin_stats(period)
            month_first = day.replace(day=1)
            month = await database.get_admin_stats(
                {"start": month_first.isoformat(), "end": day.isoformat()}
            )

            sales = int(stats.get("orders_sold") or 0)
            revenue = float(stats.get("revenue") or 0)
            profit = float(stats.get("profit") or 0)
            old = old_rows.get(day)
            if old is None and sales == 0 and revenue == 0:
                continue        # savdosi ham, qatori ham yo'q kun

            o_sales = int(old["orders"]) if old else 0
            o_rev = float(old["revenue"]) if old else 0.0
            o_profit = float(old["profit"]) if old else 0.0
            same = (o_sales == sales and round(o_rev) == round(revenue)
                    and round(o_profit) == round(profit))
            mark = "  " if same else "→ "
            print(f"{mark}{day:%d.%m.%y}{o_sales:>6} → {sales:<4}"
                  f"{fmt(o_rev):>12} → {fmt(revenue):<12}"
                  f"{fmt(o_profit):>12} → {fmt(profit):<12}")
            if same:
                continue
            changed += 1
            if not args.apply:
                continue
            await database.record_target_day(
                day, sales, int(old["daily_target"]) if old else daily_target,
                revenue, profit, float(month.get("profit") or 0),
                float(old["monthly_target_usd"]) if old else monthly_usd,
                float(old["usd_rate"]) if old else float(state.get("usd_rate") or 12800),
            )

        print(f"\n{changed} ta kun o'zgaradi.")
        if changed and not args.apply:
            print("To'g'ri ko'rinsa, yana bir marta --apply bilan ishga tushiring.")
    finally:
        await database.pool.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
