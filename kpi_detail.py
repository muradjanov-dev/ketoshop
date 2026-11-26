"""Dashboard KPI kartochkasi bosilganda — ichki tafsilot (egasi, 2026-11-26: "davr
xarajatlari ustiga bosganda xarajatlar qayerga ketayotganini ko'rib tura olaylik,
har bir tugmani dashboardning asosiy oynasidagi bosilganda ichki detallarini ko'ra
olaylik, qayerga va qayerdan").

Davr — dashboard bilan bir xil (database._period_range). Har KPI uchun bir xil
shakl: {"title", "summary": [[nomi, qiymat]], "groups": [{"title", "rows": [[...]],
"head": [...]}]} — admin.html uni bitta oynada chizadi. Faqat o'qish.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import timedelta

import database
import order_origin

PLACED = {"bot": "🤖 Bot", "site": "🌐 Sayt", "app": "📱 Ilova"}
SOURCE = {"bot": "Mijoz o'zi", "manual": "📝 Qo'lda (admin)", "b2b": "🏢 B2B (optom)"}
DELIVERY = {"self": "🚚 Kuryer (Toshkent)", "pickup": "🏪 Olib ketish", "yandex": "🚕 Yandex",
            "uzpost": "📮 UzPost", "bts": "📦 BTS", "emu": "📦 EMU"}
TOUCH = {"instagram": "📸 Instagram", "link": "🔗 Havola", "ad": "📣 Reklama", "blogger": "🎤 Bloger",
         "referral": "👥 Taklif (referal)"}
MAX_ROWS = 300


def _som(v) -> str:
    return f"{int(round(float(v or 0))):,}".replace(",", " ") + " so'm"


def _tk(dt) -> str:
    return (dt + timedelta(hours=5)).strftime("%d.%m %H:%M") if dt else "—"


def _where(period, column: str, extra: str = "") -> tuple[str, list]:
    start, end = database._period_range(period)
    conds, args = ([extra] if extra else []), []
    if start:
        args.append(start)
        conds.append(f"{column} >= ${len(args)}")
    if end:
        args.append(end)
        conds.append(f"{column} <= ${len(args)}")
    return (" WHERE " + " AND ".join(conds)) if conds else "", args


async def _orders(period, delivered: bool, b2b_only: bool = False) -> list[dict]:
    col = "delivered_at" if delivered else "created_at"
    extra = "status = 'delivered'" if delivered else database.SALE_SQL
    if b2b_only:
        extra += " AND COALESCE(source, 'bot') = 'b2b'"
    where, args = _where(period, col, extra)
    async with database.pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, created_at, delivered_at, status, total, customer_name, source, origin, "
            f"delivery_method, payment_method, keto_redeemed FROM orders{where} ORDER BY total DESC", *args)
    return [dict(r) for r in rows]


def _breakdown(orders: list[dict], key) -> list[list]:
    sums, counts = defaultdict(float), defaultdict(int)
    for o in orders:
        k = key(o)
        sums[k] += float(o.get("total") or 0)
        counts[k] += 1
    total = sum(sums.values()) or 1
    return [[k, f"{counts[k]} ta", _som(v), f"{round(100 * v / total)}%"]
            for k, v in sorted(sums.items(), key=lambda x: -x[1])]


def _placed(o: dict) -> str:
    src = o.get("source") or "bot"
    if src != "bot":
        return SOURCE.get(src, src)
    origin = order_origin.parse(o.get("origin")) or {}
    return PLACED.get(origin.get("placed"), "🤖 Bot")


def _touch(o: dict) -> str:
    origin = order_origin.parse(o.get("origin")) or {}
    touch = origin.get("touch") or {}
    label = TOUCH.get(touch.get("kind"), "To'g'ridan-to'g'ri / noma'lum")
    if origin.get("ai"):
        label += " · AI bilan"
    return label


def _order_groups(orders: list[dict], date_key: str) -> list[dict]:
    head = ["Qayerdan", "Soni", "Summa", "Ulush"]
    return [
        {"title": "🧭 Qayerdan buyurtma berildi", "head": head, "rows": _breakdown(orders, _placed)},
        {"title": "📣 Mijoz qanday kelgan", "head": ["Manba", "Soni", "Summa", "Ulush"],
         "rows": _breakdown(orders, _touch)},
        {"title": "🚚 Yetkazish usuli", "head": ["Usul", "Soni", "Summa", "Ulush"],
         "rows": _breakdown(orders, lambda o: DELIVERY.get(o.get("delivery_method"), o.get("delivery_method") or "—"))},
        {"title": "💳 To'lov", "head": ["Turi", "Soni", "Summa", "Ulush"],
         "rows": _breakdown(orders, lambda o: "💳 Karta" if o.get("payment_method") == "online" else "💵 Naqd")},
        {"title": f"🧾 Buyurtmalar (eng kattasi birinchi, {min(len(orders), MAX_ROWS)} ta)",
         "head": ["#", "Sana", "Mijoz", "Qayerdan", "Summa"],
         "rows": [[f"#{o['id']}", _tk(o.get(date_key)), o.get("customer_name") or "—", _placed(o), _som(o.get("total"))]
                  for o in orders[:MAX_ROWS]]},
    ]


async def _expenses(period) -> dict:
    cats = await database.get_expense_totals_by_category(period)
    where, args = _where(period, "e.created_at")
    async with database.pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT e.name, e.amount, e.created_at, e.bonus_order_id, e.gift_order_id, e.delivery_order_id, "
            "e.category_id, c.name AS category_name FROM expenses e "
            f"LEFT JOIN expense_categories c ON c.id = e.category_id{where} ORDER BY e.amount DESC LIMIT {MAX_ROWS}",
            *args)
    labels = {key: label for _, key, label in database.EXPENSE_AUTO_CATEGORIES}
    total = sum(c["total"] for c in cats) or 1
    entries = []
    for r in rows:
        r = dict(r)
        key = database.expense_category_key(r)
        entries.append([_tk(r["created_at"]), labels.get(key) or r.get("category_name") or "Kategoriyasiz",
                        r.get("name") or "—", _som(r["amount"])])
    uncategorised = next((c for c in cats if c["key"] == "none"), None)
    note = (f"⚠️ {_som(uncategorised['total'])} ({uncategorised['count']} ta) kategoriyasiz — «Chiqimlar»da "
            "kategoriya qo'ysangiz, qayerga ketgani aniq ko'rinadi.") if uncategorised else ""
    return {"title": "💸 Davr xarajatlari — qayerga ketdi",
            "summary": [["Jami", _som(sum(c["total"] for c in cats))], ["Yozuvlar", f"{sum(c['count'] for c in cats)} ta"]],
            "note": note,
            "groups": [
                {"title": "📂 Kategoriyalar bo'yicha", "head": ["Kategoriya", "Soni", "Summa", "Ulush"],
                 "rows": [[c["name"], f"{c['count']} ta", _som(c["total"]), f"{round(100 * c['total'] / total)}%"]
                          for c in cats]},
                {"title": "🧾 Har bir yozuv (eng kattasi birinchi)", "head": ["Sana", "Kategoriya", "Nima uchun", "Summa"],
                 "rows": entries},
            ]}


async def _products(period, title: str, sort: str) -> dict:
    sales = await database.get_product_sales(period)
    rows = [r for r in sales.get("rows", [])]
    rows.sort(key=lambda r: -float(r.get(sort) or 0))
    out = []
    for r in rows[:MAX_ROWS]:
        revenue, cost = float(r.get("revenue") or 0), float(r.get("cost") or 0)
        profit = revenue - cost
        margin = f"{round(100 * profit / revenue)}%" if revenue else "—"
        out.append([r.get("name") or "—", f"{float(r.get('qty') or 0):g}", _som(revenue), _som(cost), _som(profit),
                    margin + ("" if r.get("cost_known", True) else " ⚠️ tannarx yo'q")])
    return {"title": title, "summary": [], "groups": [
        {"title": "📦 Mahsulotlar bo'yicha", "head": ["Mahsulot", "Soni", "Tushum", "Tannarx", "Foyda", "Marja"],
         "rows": out}]}


async def detail(kpi: str, period) -> dict:
    if kpi == "expenses":
        return await _expenses(period)
    if kpi in ("booked_value", "orders_sold", "aov", "orders_total"):
        orders = await _orders(period, delivered=False)
        total = sum(float(o.get("total") or 0) for o in orders)
        return {"title": "🛒 Buyurtmalar — qayerdan keldi",
                "summary": [["Buyurtmalar", f"{len(orders)} ta"], ["Qiymati", _som(total)],
                            ["O'rtacha", _som(total / len(orders)) if orders else "—"]],
                "groups": _order_groups(orders, "created_at")}
    if kpi in ("delivered_revenue", "b2b_revenue"):
        orders = await _orders(period, delivered=True, b2b_only=kpi == "b2b_revenue")
        total = sum(float(o.get("total") or 0) for o in orders)
        title = "🏢 B2B tushum" if kpi == "b2b_revenue" else "💰 Yetkazilgan tushum — qayerdan"
        return {"title": title, "summary": [["Buyurtmalar", f"{len(orders)} ta"], ["Tushum", _som(total)]],
                "groups": _order_groups(orders, "delivered_at")}
    if kpi in ("product_cost", "gross_profit", "missing_cost"):
        return await _products(period, "📦 Tannarx va marja — mahsulotlar bo'yicha",
                               "cost" if kpi == "product_cost" else "revenue")
    if kpi == "profit":
        stats = await database.get_admin_stats(period)
        cats = await database.get_expense_totals_by_category(period)
        steps = [["Yetkazilgan tushum", _som(stats.get("delivered_revenue"))],
                 ["− Mahsulot tannarxi", _som(stats.get("product_cost"))],
                 ["= Yalpi foyda", _som(stats.get("gross_profit"))]]
        steps += [[f"− {c['name']}", _som(c["total"])] for c in cats]
        steps.append(["= Sof foyda", _som(stats.get("profit"))])
        products = await _products(period, "", "revenue")
        return {"title": "📈 Sof foyda — qanday hosil bo'ldi", "summary": [],
                "groups": [{"title": "🧮 Hisob", "head": ["Qator", "Summa"], "rows": steps}] + products["groups"]}
    if kpi == "keto_discount":
        orders = [o for o in await _orders(period, delivered=True) if int(o.get("keto_redeemed") or 0) > 0]
        return {"title": "🪙 Keto chegirmasi", "summary": [["Buyurtmalar", f"{len(orders)} ta"],
                                                          ["Jami", _som(sum(int(o['keto_redeemed']) for o in orders))]],
                "groups": [{"title": "🧾 Buyurtmalar", "head": ["#", "Sana", "Mijoz", "Keto", "Summa"],
                            "rows": [[f"#{o['id']}", _tk(o.get("delivered_at")), o.get("customer_name") or "—",
                                      _som(o["keto_redeemed"]), _som(o.get("total"))] for o in orders]}]}
    if kpi == "users_new":
        where, args = _where(period, "u.created_at")
        has_ads = await _has_table("ad_referrals")
        async with database.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT COALESCE(a.source, '') AS src, COUNT(*) AS n FROM users u "
                f"LEFT JOIN ad_referrals a ON a.user_id = u.user_id{where} GROUP BY 1 ORDER BY 2 DESC",
                *args) if has_ads else []
            days = await conn.fetch(
                "SELECT ((u.created_at + INTERVAL '5 hours')::date) AS d, COUNT(*) AS n FROM users u"
                f"{where} GROUP BY 1 ORDER BY 1 DESC", *args)
        groups = []
        if rows:
            groups.append({"title": "📣 Qayerdan kelgan", "head": ["Manba", "Soni"],
                           "rows": [[r["src"] or "To'g'ridan-to'g'ri / noma'lum", f"{r['n']} ta"] for r in rows]})
        groups.append({"title": "📅 Kunlar bo'yicha", "head": ["Kun", "Yangi mijoz"],
                       "rows": [[r["d"].strftime("%d.%m"), f"{r['n']} ta"] for r in days]})
        return {"title": "👤 Yangi mijozlar", "summary": [["Jami", f"{sum(r['n'] for r in days)} ta"]], "groups": groups}
    return {"title": "—", "summary": [], "groups": [], "note": "Bu ko'rsatkich uchun tafsilot yo'q."}


async def _has_table(name: str) -> bool:
    async with database.pool.acquire() as conn:
        return bool(await conn.fetchval("SELECT to_regclass($1)", name))
