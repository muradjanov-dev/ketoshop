"""
Uzbek phone numbers as buyers actually type them (2026-10-21).

The Mini App's checkout only took "+998901234567" or "+998 90 123-45-67".
Buyers wrote "90 123 45 67", "+998 (90) 123-45-67" or "8 90 1234567", got
"Telefon raqamni kiriting" under a field they had scrolled past, and kept
pressing «Buyurtmani tasdiqlash»: in 7 days 7 of 11 checkouts hit it, 44
presses in all, one buyer 13 times. Every unambiguous spelling is accepted
now and stored the same way. The Mini App has a copy of this rule
(normalizeUzPhone in webapp/index.html) so it can tell the buyer before the
order is sent.
"""
import re


def normalize_uz_phone(raw) -> str | None:
    """'+998XXXXXXXXX', or None when it isn't an Uzbek number.

    Accepts the 9 local digits (operator code + number), 998 + 9 digits,
    00998 + 9 digits and the old trunk form 8 + 9 digits, with any spaces,
    dashes, brackets or dots in between."""
    if not isinstance(raw, str):
        return None
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) == 9:
        digits = "998" + digits
    elif len(digits) == 10 and digits.startswith("8"):
        digits = "998" + digits[1:]
    return "+" + digits if re.fullmatch(r"998\d{9}", digits) else None
