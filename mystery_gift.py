"""
Sirli sovg'a — a surprise pack from the Ketoshop team on every order of
MYSTERY_GIFT_FROM so'm or more (owner, 2026-09-19).

Unlike the Eritritol campaign (gift_campaign.py) this one is deliberately NOT
a catalogue line: what goes in the box is the team's choice, and the buyer is
told only that something is coming. The intrigue is the offer, so no line of
copy here ever names the gift — and because nothing lands in `items`, the
packing note to the admins is what makes it actually happen.

Every place that shows money to a buyer shows one of these lines:

  card_line()   — the standing promise, on every product card
  cart_hint()   — "yours" once the cart is there, "X more" while it is close
  order_line()  — on the order summary and the confirmation
  admin_note()  — "put one in the box" on the admins' order card

All of them measure the goods subtotal: products after discounts, before any
Keto redemption and without the delivery fee — the same basis as free
delivery, so a buyer can never be told two different sums for the same cart.
"""
from config import MYSTERY_GIFT_FROM
from locales import get_text

# How close the cart has to be before we nudge. Further out the nudge reads
# as an ad for a sum they were never going to spend; inside it, it reads as
# "you are nearly there".
NEAR_WINDOW = 150_000


def _som(amount) -> str:
    return f"{int(amount):,}".replace(",", " ")


def qualifies(subtotal) -> bool:
    return float(subtotal or 0) >= MYSTERY_GIFT_FROM


def card_line(lang: str) -> str:
    """The promise, for a product card / channel post."""
    return get_text("mystery_card_line", lang, amount=_som(MYSTERY_GIFT_FROM))


def cart_hint(subtotal, lang: str) -> str:
    """'Sovg'a sizniki' once the cart qualifies, 'yana X so'm' while it is
    within reach, '' when it is too far away to be worth saying."""
    subtotal = float(subtotal or 0)
    if qualifies(subtotal):
        return get_text("mystery_reached", lang)
    left = MYSTERY_GIFT_FROM - subtotal
    if left <= NEAR_WINDOW:
        return get_text("mystery_hint", lang, left=_som(left))
    return ""


def order_line(subtotal, lang: str) -> str:
    """Confirmation of what they earned, for the order summary/confirmation."""
    return get_text("mystery_order_line", lang) if qualifies(subtotal) else ""


def admin_note(subtotal, lang: str = "uz") -> str:
    """The packing instruction on the admins' order card. Nothing else tells
    them — the gift has no order line of its own."""
    if not qualifies(subtotal):
        return ""
    return get_text("mystery_admin_note", lang, amount=_som(MYSTERY_GIFT_FROM))


def free_delivery_card_line(lang: str) -> str:
    """The other standing promise, shown right under this one wherever the
    shop advertises both."""
    from config import FREE_DELIVERY_FROM
    return get_text("free_delivery_card_line", lang, amount=_som(FREE_DELIVERY_FROM))
