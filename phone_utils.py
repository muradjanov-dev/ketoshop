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

2026-11-11: still 18 of 45 checkouts hit the phone error. Also taken now:
digits from an Arabic or full-width keyboard (Python kept them as they were
and would have stored "+998٩٠…", the Mini App dropped them), and the
"+998 +998 90…" an autofill leaves after the buyer typed "+998". A number
whose operator code starts with 0 or 1 ("123456789") is no Uzbek number and
is refused. Keep normalizeUzPhone in webapp/index.html the same.
"""
import re

# Arabic-Indic, Extended Arabic-Indic (Persian) and full-width digits — the
# keyboards a pasted or typed number actually comes from besides ASCII. The
# Mini App maps exactly these blocks too; any other character is dropped.
_DIGIT_BLOCKS = (0x0660, 0x06F0, 0xFF10)


def _ascii_digits(raw: str) -> str:
    out = []
    for ch in raw:
        code = ord(ch)
        for base in _DIGIT_BLOCKS:
            if base <= code <= base + 9:
                code = 0x30 + code - base
        if 0x30 <= code <= 0x39:
            out.append(chr(code))
    return "".join(out)


def normalize_uz_phone(raw) -> str | None:
    """'+998XXXXXXXXX', or None when it isn't an Uzbek number.

    Accepts the 9 local digits (operator code + number), 998 + 9 digits,
    00998 + 9 digits, the old trunk form 8 + 9 digits and a doubled 998,
    with any spaces, dashes, brackets, dots or invisible marks in between.
    The operator code never starts with 0 or 1."""
    if not isinstance(raw, str):
        return None
    digits = _ascii_digits(raw)
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) == 15 and digits.startswith("998998"):
        digits = digits[3:]
    if len(digits) == 9:
        digits = "998" + digits
    elif len(digits) == 10 and digits.startswith("8"):
        digits = "998" + digits[1:]
    return "+" + digits if re.fullmatch(r"998[2-9][0-9]{8}", digits) else None


def format_uz_phone(phone: str | None) -> str:
    """'+998901234567' → '+998 90 123 45 67' — how the Mini App shows a
    number it fills in. Anything else comes back as it was."""
    p = normalize_uz_phone(phone) if phone else None
    if not p:
        return phone or ""
    return f"{p[:4]} {p[4:6]} {p[6:9]} {p[9:11]} {p[11:]}"
