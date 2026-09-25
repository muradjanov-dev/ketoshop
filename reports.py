"""
Excel report generator — orders + per-line-item breakdown.

Used by the admin "📊 Excel hisobot" entry. Returns an in-memory .xlsx
file built with openpyxl so we don't touch the filesystem.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from io import BytesIO
from typing import Iterable

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from database import (get_orders_for_export, get_delivered_orders_for_period,
                      get_expenses_for_period, get_all_cost_prices, get_set_costs,
                      get_admin_stats, format_local_dt, line_cost)
from locales import get_delivery_method_name, get_order_status


# ----- Styling -----------------------------------------------------

_HEADER_FILL = PatternFill(start_color="2563EB", end_color="2563EB", fill_type="solid")
_HEADER_FONT = Font(color="FFFFFF", bold=True)
_BORDER = Border(
    left=Side(style="thin", color="DDDDDD"),
    right=Side(style="thin", color="DDDDDD"),
    top=Side(style="thin", color="DDDDDD"),
    bottom=Side(style="thin", color="DDDDDD"),
)
_TOTAL_FILL = PatternFill(start_color="FEF3C7", end_color="FEF3C7", fill_type="solid")
_TOTAL_FONT = Font(bold=True)


def _write_header(ws, headers: list[str]) -> None:
    for col, title in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col, value=title)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = _BORDER
    ws.row_dimensions[1].height = 24
    ws.freeze_panes = "A2"


def _autosize(ws, min_widths: list[int] | None = None) -> None:
    """Auto-size columns based on content; cap at 50 chars."""
    for col_idx in range(1, ws.max_column + 1):
        col_letter = get_column_letter(col_idx)
        max_len = 0
        for cell in ws[col_letter]:
            v = cell.value
            if v is None:
                continue
            length = len(str(v))
            if length > max_len:
                max_len = length
        width = min(max_len + 2, 50)
        if min_widths and col_idx <= len(min_widths):
            width = max(width, min_widths[col_idx - 1])
        ws.column_dimensions[col_letter].width = width


# ----- Builder -----------------------------------------------------

def _fmt_dt(dt) -> str:
    """Format an order timestamp in Asia/Tashkent local time for the Excel
    report. Stored values are naive UTC; format_local_dt applies the +5h
    shift consistently with the rest of the bot UI."""
    return format_local_dt(dt, "%Y-%m-%d %H:%M")


def _payment_label(method: str | None, lang: str) -> str:
    if method == "cash":
        return "💵 Naqd" if lang == "uz" else "💵 Наличные"
    if method == "online":
        return "💳 Onlayn" if lang == "uz" else "💳 Онлайн"
    return "—"


def _source_label(source: str | None, lang: str) -> str:
    if source == "manual":
        return "📝 Qo'lda" if lang == "uz" else "📝 Вручную"
    if source == "webapp":
        return "📱 Mini App"
    return "🤖 Bot"


PERIOD_LABELS = {
    "today": {"uz": "Bugun",          "ru": "Сегодня"},
    "7d":    {"uz": "Oxirgi 7 kun",   "ru": "Последние 7 дней"},
    "30d":   {"uz": "Oxirgi 30 kun",  "ru": "Последние 30 дней"},
    "all":   {"uz": "Barcha vaqt",    "ru": "За всё время"},
}


def _orders_sheet(ws, orders: list[dict], lang: str, cost_map: dict[int, float],
                  set_costs: dict[int, float] | None = None) -> None:
    ws.title = "Buyurtmalar" if lang == "uz" else "Заказы"
    headers_uz = [
        "Buyurtma №", "Sana", "Mijoz", "Telefon",
        "Mahsulot", "Miqdor", "Birlik narx", "Qator summa",
        "Asl narx", "Qator yalpi foyda",
        "Buyurtma jami (bekor qilinmagan)", "To'lov", "Yetkazib berish", "Holat", "Manba",
        "Manzil", "Izoh", "Tasdiqlangan", "Yo'lda", "Yetkazilgan",
    ]
    headers_ru = [
        "Заказ №", "Дата", "Клиент", "Телефон",
        "Товар", "Кол-во", "Цена за ед.", "Сумма строки",
        "Себестоимость", "Валовая прибыль строки",
        "Сумма заказа (без отмены)", "Оплата", "Доставка", "Статус", "Источник",
        "Адрес", "Комментарий", "Подтверждён", "В пути", "Доставлен",
    ]
    headers = headers_uz if lang == "uz" else headers_ru
    _write_header(ws, headers)

    row = 2
    for o in orders:
        items = o.get("items_data") or []
        if not items:
            items = [{"name": "—", "quantity": 1, "price": float(o.get("total") or 0)}]
        # One row per item — accountants want each line separately.
        first_item = True
        for it in items:
            qty = float(it.get("quantity") or 0)
            price = float(it.get("price") or 0)
            line_total = qty * price
            # Shared costing rule (database.line_cost) — sets are costed from
            # their components instead of 0.
            cost, _ = line_cost(it, cost_map, set_costs or {})
            unit_cost = (cost / qty) if qty else 0.0
            line_profit = line_total - cost

            ws.cell(row=row, column=1,  value=int(o["id"]))
            ws.cell(row=row, column=2,  value=_fmt_dt(o.get("created_at")))
            ws.cell(row=row, column=3,  value=o.get("customer_name") or "—")
            ws.cell(row=row, column=4,  value=o.get("phone") or "—")
            ws.cell(row=row, column=5,  value=it.get("name") or "—")
            ws.cell(row=row, column=6,  value=qty)
            ws.cell(row=row, column=7,  value=int(price))
            ws.cell(row=row, column=8,  value=int(line_total))
            ws.cell(row=row, column=9,  value=int(unit_cost))
            ws.cell(row=row, column=10, value=int(line_profit))
            # Order totals repeat on every item row, which makes a flat export
            # easy to over-sum. Keep the total on the first line only.
            booked_order = (o.get("status") or "pending") != "cancelled"
            ws.cell(row=row, column=11, value=(int(float(o.get("total") or 0))
                                                if first_item and booked_order else None))
            ws.cell(row=row, column=12, value=_payment_label(o.get("payment_method"), lang))
            ws.cell(row=row, column=13, value=get_delivery_method_name(o.get("delivery_method"), lang))
            ws.cell(row=row, column=14, value=get_order_status(o.get("status") or "pending", lang))
            ws.cell(row=row, column=15, value=_source_label(o.get("source"), lang))
            ws.cell(row=row, column=16, value=o.get("address") or "—")
            ws.cell(row=row, column=17, value=o.get("address_note") or "")
            ws.cell(row=row, column=18, value=_fmt_dt(o.get("confirmed_at")))
            ws.cell(row=row, column=19, value=_fmt_dt(o.get("shipped_at")))
            ws.cell(row=row, column=20, value=_fmt_dt(o.get("delivered_at")))

            # Right-align numeric columns
            for col in (1, 6, 7, 8, 9, 10, 11):
                ws.cell(row=row, column=col).alignment = Alignment(horizontal="right")
            for col in range(1, 21):
                ws.cell(row=row, column=col).border = _BORDER
            row += 1
            first_item = False
    _autosize(ws, min_widths=[10, 17, 18, 14, 24, 8, 12, 12, 12, 12, 14, 14, 18, 16, 12, 28, 22, 17, 17, 17])


def _summary_sheet(ws, orders: list[dict], lang: str, period: str,
                   stats: dict) -> None:
    ws.title = "Xulosa" if lang == "uz" else "Сводка"

    booked_value = float(stats.get("booked_value") or 0)
    delivered_revenue = float(stats.get("delivered_revenue", stats.get("revenue", 0)) or 0)
    delivered_cost = float(stats.get("product_cost") or 0)
    expenses = float(stats.get("expenses") or 0)
    net_profit = float(stats.get("profit") or 0)
    gross_profit = delivered_revenue - delivered_cost
    margin_pct = (gross_profit / delivered_revenue * 100) if delivered_revenue else 0

    by_status: dict[str, int] = {}
    for o in orders:
        s = o.get("status") or "pending"
        by_status[s] = by_status.get(s, 0) + 1

    by_source: dict[str, int] = {}
    for o in orders:
        s = (o.get("source") or "bot")
        by_source[s] = by_source.get(s, 0) + 1

    period_label = PERIOD_LABELS.get(period, {}).get(lang, period)

    rows: list[tuple[str, object]] = [
        (("Davr"             if lang == "uz" else "Период"), period_label),
        (("Buyurtmalar varag'i yaratilgan sana bo'yicha; sof foyda yetkazilgan sana va shu davr xarajatlari bo'yicha" if lang == "uz" else "Лист заказов сгруппирован по дате создания; чистая прибыль — по дате доставки и расходам периода"), ""),
        (("Buyurtmalar (yaratilgan davr)" if lang == "uz" else "Заказы (по дате создания)"), len(orders)),
        (("Bekor qilinmagan savdolar" if lang == "uz" else "Заказы без отмен"), int(stats.get("orders_sold") or 0)),
        (("Yangi buyurtmalar qiymati (yaratilgan sana)" if lang == "uz" else "Сумма новых заказов (по дате создания)"), int(booked_value)),
        (("Yetkazilgan buyurtmalar (yetkazilgan sana bo'yicha)" if lang == "uz" else "Доставлено (по дате доставки)"), int(stats.get("orders_delivered") or 0)),
        (("Yetkazilgan tushum" if lang == "uz" else "Выручка по доставленным"), int(delivered_revenue)),
        (("Yetkazilgan mahsulot tannarxi" if lang == "uz" else "Себестоимость доставленных"), int(delivered_cost)),
        (("Yalpi foyda" if lang == "uz" else "Валовая прибыль"), int(gross_profit)),
        (("Yalpi foyda %" if lang == "uz" else "Валовая маржа %"), round(margin_pct, 1)),
        (("Davr xarajatlari" if lang == "uz" else "Расходы за период"), int(expenses)),
        (("Sof foyda (yetkazilgan tushum − tannarx − xarajat)" if lang == "uz" else "Чистая прибыль (доставки − себестоимость − расходы)"), int(net_profit)),
        (("O'rtacha buyurtma qiymati" if lang == "uz" else "Средняя сумма заказа"), int(booked_value / int(stats.get("orders_sold") or 1)) if stats.get("orders_sold") else 0),
        ("", ""),
        (("Buyurtmalar holati (yaratilgan sana bo'yicha)" if lang == "uz" else "Статусы заказов (по дате создания)"), ""),
    ]
    for status, count in sorted(by_status.items()):
        rows.append((get_order_status(status, lang), count))
    rows.append(("", ""))
    rows.append(((" Manba bo'yicha" if lang == "uz" else " По источнику"), ""))
    for source, count in sorted(by_source.items()):
        rows.append((_source_label(source, lang), count))

    # Highlight the accounting totals separately from the detail breakdown.
    HIGHLIGHT_TOP_ROWS = 13
    for i, (k, v) in enumerate(rows, start=1):
        a = ws.cell(row=i, column=1, value=k)
        b = ws.cell(row=i, column=2, value=v)
        if k and not v and ("bo'yicha" in str(k) or "По" in str(k)):
            a.font = _TOTAL_FONT
            a.fill = _TOTAL_FILL
        if i <= HIGHLIGHT_TOP_ROWS:
            a.font = _TOTAL_FONT
            b.font = _TOTAL_FONT
            a.fill = _TOTAL_FILL
            b.fill = _TOTAL_FILL
    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 22


def _decoded_items(order: dict) -> list[dict]:
    items = order.get("items_data", order.get("items")) or []
    if isinstance(items, str):
        try:
            items = json.loads(items)
        except (TypeError, ValueError):
            return []
    return items if isinstance(items, list) else []


def _delivered_orders_sheet(ws, orders: list[dict], lang: str,
                            cost_map: dict[int, float],
                            set_costs: dict[int, float],
                            delivered_revenue: int,
                            delivered_cost: int) -> None:
    ws.title = "Yetkazilganlar" if lang == "uz" else "Доставленные"
    headers = (["Buyurtma №", "Yetkazilgan sana", "Mahsulot", "Miqdor",
                "Qator summa", "Tannarx", "Qator yalpi foyda", "Yetkazilgan tushum"]
               if lang == "uz" else
               ["Заказ №", "Дата доставки", "Товар", "Кол-во",
                "Сумма строки", "Себестоимость", "Валовая прибыль строки", "Выручка доставки"])
    _write_header(ws, headers)
    row = 2
    revenue_total = 0.0
    cost_total = 0.0
    for order in orders:
        items = _decoded_items(order)
        if not items:
            items = [{"name": "—", "quantity": 1, "price": float(order.get("total") or 0)}]
        first_item = True
        for item in items:
            quantity = float(item.get("quantity") or 0)
            line_total = quantity * float(item.get("price") or 0)
            line_total_cost, _ = line_cost(item, cost_map, set_costs)
            order_total = float(order.get("total") or 0) if first_item else None
            if first_item:
                revenue_total += order_total or 0
            cost_total += line_total_cost
            values = [
                int(order["id"]), _fmt_dt(order.get("delivered_at")),
                item.get("name") or "—", quantity, int(line_total),
                int(line_total_cost), int(line_total - line_total_cost), order_total,
            ]
            for col, value in enumerate(values, start=1):
                cell = ws.cell(row=row, column=col, value=value)
                cell.border = _BORDER
                if col in (1, 4, 5, 6, 7, 8):
                    cell.alignment = Alignment(horizontal="right")
            row += 1
            first_item = False

    revenue_rounding = delivered_revenue - revenue_total
    cost_rounding = delivered_cost - cost_total
    if abs(revenue_rounding) > 1e-8 or abs(cost_rounding) > 1e-8:
        ws.cell(row, 7, "Hisobot bilan tafovut" if lang == "uz" else "Разница с итогом отчёта")
        ws.cell(row, 6, cost_rounding)
        ws.cell(row, 8, revenue_rounding)
        for cell in ws[row]:
            cell.border = _BORDER
        row += 1
    ws.cell(row, 1, (f"Jami ({len(orders)} ta buyurtma)" if lang == "uz" else
                     f"Итого ({len(orders)} заказов)"))
    ws.cell(row, 6, delivered_cost)
    ws.cell(row, 8, delivered_revenue)
    for cell in ws[row]:
        cell.fill = _TOTAL_FILL
        cell.font = _TOTAL_FONT
        cell.border = _BORDER
    _autosize(ws, [10, 18, 24, 10, 14, 14, 20, 17])


def _expenses_sheet(ws, expenses: list[dict], lang: str, period_total: int) -> None:
    ws.title = "Xarajatlar" if lang == "uz" else "Расходы"
    headers = (["Sana", "Xarajat", "Summa"] if lang == "uz" else
               ["Дата", "Расход", "Сумма"])
    _write_header(ws, headers)
    total = 0.0
    for row, expense in enumerate(expenses, start=2):
        amount = float(expense.get("amount") or 0)
        total += amount
        values = [_fmt_dt(expense.get("created_at")), expense.get("name") or "—", amount]
        for col, value in enumerate(values, start=1):
            cell = ws.cell(row=row, column=col, value=value)
            cell.border = _BORDER
            if col == 3:
                cell.alignment = Alignment(horizontal="right")
    total_row = len(expenses) + 2
    rounding = period_total - total
    if abs(rounding) > 1e-8:
        ws.cell(total_row, 2, "Hisobot bilan tafovut" if lang == "uz" else "Разница с итогом отчёта")
        ws.cell(total_row, 3, rounding)
        for cell in ws[total_row]:
            cell.border = _BORDER
        total_row += 1
    ws.cell(total_row, 2, "Jami" if lang == "uz" else "Итого")
    ws.cell(total_row, 3, period_total)
    for cell in ws[total_row]:
        cell.fill = _TOTAL_FILL
        cell.font = _TOTAL_FONT
        cell.border = _BORDER
    _autosize(ws, [18, 30, 16])


# ----- Public API --------------------------------------------------

async def generate_orders_excel(period: str = "all", lang: str = "uz") -> tuple[BytesIO, str]:
    """Build an .xlsx report for the given period. Returns (buffer, filename)."""
    orders, stats, delivered_orders, expenses = await asyncio.gather(
        get_orders_for_export(period), get_admin_stats(period),
        get_delivered_orders_for_period(period), get_expenses_for_period(period),
    )
    # One DB call → in-memory map; avoids N+1 lookups while iterating items.
    cost_map = await get_all_cost_prices()
    set_costs = await get_set_costs()

    wb = Workbook()
    _orders_sheet(wb.active, orders, lang, cost_map, set_costs)
    summary = wb.create_sheet()
    _summary_sheet(summary, orders, lang, period, stats)
    delivered = wb.create_sheet()
    _delivered_orders_sheet(
        delivered, delivered_orders, lang, cost_map, set_costs,
        int(stats.get("delivered_revenue", stats.get("revenue", 0)) or 0),
        int(stats.get("product_cost") or 0),
    )
    expense_sheet = wb.create_sheet()
    _expenses_sheet(expense_sheet, expenses, lang, int(stats.get("expenses") or 0))

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    today = datetime.now().strftime("%Y-%m-%d")
    filename = f"safran_orders_{period}_{today}.xlsx"
    return buf, filename
