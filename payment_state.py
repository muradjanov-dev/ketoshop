"""To'lov holati — bot kartochkalari (handlers/cart.py) va kuryer doskasi
(courier_board.py) uchun bitta qoida. Sof funksiya: aiogram ham, baza ham yo'q,
shuning uchun admin_web/courier_board uni bot routerlarini tortmasdan ishlatadi.

AI sotuvchi (ai_sales.py) karta to'lovli buyurtmani PUL KELMASDAN tuzadi:
payment_method 'cash' bo'lib qoladi, izohda "To'lov: KARTA (chek kutilmoqda)".
Bunday buyurtma hech qayerda "naqd — yetkazilganda to'lanadi" bo'lib
ko'rinmasligi kerak (egasi, 2026-10-14: "to'lanmagan buyurtmani hali
to'lanmaganini bildiradigan belgi qo'sh").
"""


def card_payment_state(payment_method: str | None, address_note: str | None,
                       cheque_file_id: str | None = None) -> str | None:
    """'unpaid' — chek hali yo'q; 'cheque' — chek keldi, admin tasdiqlamagan;
    None — boshqa har qanday buyurtma (naqd, tugmali online, to'langan AI karta)."""
    if payment_method == "online" or "KARTA" not in (address_note or ""):
        return None
    return "cheque" if cheque_file_id else "unpaid"
