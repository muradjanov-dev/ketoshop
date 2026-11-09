"""
Katalog tartibi (owner, 2026-11-08: "birxil kategoriyada bir xil nomlilar
yonma yon chiqsin"): products whose names differ only by the pack size —
«Stevia 200gr», «Stevia 1000g» — stand next to each other, smallest first.
Plain alphabetical order split them («1000g» sorts before «200gr», and a
product in between could sit in the gap).

The bot's catalog uses sort_key (database.get_products_by_category); the
Mini App's orderCatalog() in webapp/index.html reads names the same way.
"""
import re

# A pack size: number + unit, the unit not running on into a word («200 гречка»).
SIZE_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(kg|кг|gr|гр|g|г|ml|мл|l|л)(?![a-zа-яё])", re.IGNORECASE)
_THOUSANDS = {"kg", "кг", "l", "л"}


def size_of(name: str | None) -> float | None:
    """'Stevia 1000g' -> 1000.0, 'Kokos yog'i 1 l' -> 1000.0, no size -> None."""
    m = SIZE_RE.search(name or "")
    if not m:
        return None
    value = float(m.group(1).replace(",", "."))
    return value * 1000 if m.group(2).lower() in _THOUSANDS else value


def base_name(name: str | None) -> str:
    """The name without its pack size, lower-cased: 'Stevia 200gr' -> 'stevia'."""
    text = SIZE_RE.sub(" ", name or "").lower()
    text = re.sub(r"[\s\-–—_.,()]+", " ", text)
    return text.strip()


def sort_key(name: str | None, pid: int = 0) -> tuple:
    size = size_of(name)
    return (base_name(name), size is None, size or 0.0, (name or "").lower(), pid)
