"""
Chakana va optom (B2B) narxini solishtirish — admin sayti uchun (2026-10-01).

Owner's ask: "admin panelda b2b mahsulotlari va umumiy mahsulotlarni
tushunarli qilib ko'rsatish, narxdagi farqni ham".

The catch is the units. A retail price is per PACKAGE ("Bodom uni 200gr" —
45 000 so'm), the wholesale price is per KILOGRAM (admin form: "Optom narx
(so'm / 1 kg)"). Comparing the two raw numbers is meaningless, so the package
size is read from the product name and the retail price is scaled to 1 kg (or
1 litre for oils, where the wholesale price is per litre the same way).
When the name carries no size, no comparison is made — a wrong one would be
worse than none.
"""
import re

# "200gr", "200 гр", "1kg", "1,5 кг", "500ml", "5 l", "(5 л)", "1 litr"
_SIZE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*"
    r"(kg|кг|gr|g|гр|г|ml|мл|litr|литр|l|л)"
    r"(?![a-zа-яёўқғҳ])",
    re.IGNORECASE,
)
_TO_BASE = {
    "kg": ("kg", 1.0), "кг": ("kg", 1.0),
    "gr": ("kg", 0.001), "g": ("kg", 0.001), "гр": ("kg", 0.001), "г": ("kg", 0.001),
    "l": ("l", 1.0), "л": ("l", 1.0), "litr": ("l", 1.0), "литр": ("l", 1.0),
    "ml": ("l", 0.001), "мл": ("l", 0.001),
}


def pack_size(name: str | None) -> tuple[float, str, str] | None:
    """(size in kg or l, base unit 'kg'/'l', label as written) from a product
    name, or None. The last size in the name wins: "Set 2×200gr — 1kg" is 1 kg."""
    matches = list(_SIZE.finditer(name or ""))
    if not matches:
        return None
    m = matches[-1]
    amount = float(m.group(1).replace(",", "."))
    base, factor = _TO_BASE[m.group(2).lower()]
    size = amount * factor
    if size <= 0:
        return None
    return size, base, f"{m.group(1)} {m.group(2)}"


def sale_kind(product: dict) -> str:
    """'b2b_only' — hidden from shoppers, sold wholesale only;
    'both'     — in the shop AND has a wholesale price;
    'retail'   — shop only."""
    if product.get("b2b_only"):
        return "b2b_only"
    if float(product.get("b2b_price") or 0) > 0:
        return "both"
    return "retail"


def compare(product: dict) -> dict:
    """Everything the products table needs to explain one row's pricing.

    retail_per_base — shop price scaled to 1 kg / 1 l (None if size unknown)
    diff_som        — retail_per_base − b2b_price: how much less a wholesale
                      buyer pays per kg (negative = wholesale is DEARER)
    diff_pct        — diff_som as % of retail_per_base, 1 decimal
    """
    kind = sale_kind(product)
    price = float(product.get("price") or 0)
    b2b = float(product.get("b2b_price") or 0)
    size = pack_size(product.get("name"))
    out = {"kind": kind, "pack": size[2] if size else None,
           "base": size[1] if size else "kg",
           "retail_per_base": None, "diff_som": None, "diff_pct": None}
    if size and price > 0 and kind != "b2b_only":
        out["retail_per_base"] = round(price / size[0])
        if b2b > 0:
            diff = out["retail_per_base"] - b2b
            out["diff_som"] = round(diff)
            out["diff_pct"] = round(diff * 100.0 / out["retail_per_base"], 1)
    return out
