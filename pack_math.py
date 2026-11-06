"""
Qadoq tahlili — pack arithmetic the AI seller must not do in its head.

Owner, 2026-11-06, after «Bodom uni 500gr - 1 ta: 43 500 so'm» (the model read
a 500 g pack priced in "kg" as 0.5 kg): "yarim narx case ga o'xshash holatlarda
ai boshqa hecham xato qilmasin! buni tahlil qilishni o'rgansin".

The rule the whole shop runs on: a retail product is a pack. Its price is for
one pack, the size in its name («500gr», «1kg», «700ml») is that pack, and a
quantity is a count of packs — never a weight. So:

  * pack_size()     — the pack in grams/ml, read from the name;
  * pack_options()  — "1 kg of almond flour": which packs, how many, what total,
                      what per kilo — so the model copies, never divides;
  * line_mismatch() — a reply line that says «2 ta» or «1 kg» next to an amount
                      for a different number of packs.

Pure functions, no database — ai_sales.py feeds them the products.
"""
import math
import re

# «500gr», «1 kg», «1000g», «700ml», «1l», «0.5 l», «250 gramm», «1 litr» (also Cyrillic).
_SIZE_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(kg|кг|gr|gramm|g|гр|грамм|г|ml|мл|l|litr|литр|л)(?![a-zа-я])", re.I)
_TO_BASE = {"kg": 1000, "кг": 1000, "gr": 1, "gramm": 1, "g": 1, "гр": 1, "грамм": 1, "г": 1,
            "ml": 1, "мл": 1, "l": 1000, "litr": 1000, "литр": 1000, "л": 1000}
_VOLUME = {"ml", "мл", "l", "litr", "литр", "л"}


def _number(text: str) -> float:
    return float(text.replace(",", "."))


def pack_size(name: str, unit: str | None = None) -> tuple[float, str] | None:
    """(size, "g" or "ml") of ONE pack. From the name's last size; a weighed
    product with no size in its name is a 1 kg (1 l) pack — that is how its
    price is set. None when nothing says (dona, banka without a size)."""
    found = list(_SIZE_RE.finditer(name or ""))
    if found:
        amount, mark = found[-1].group(1), found[-1].group(2).lower()
        return _number(amount) * _TO_BASE[mark], ("ml" if mark in _VOLUME else "g")
    if unit == "kg":
        return 1000.0, "g"
    if unit in ("liter", "l"):
        return 1000.0, "ml"
    return None


def base_name(name: str) -> str:
    """The product without its pack size: «Bodom uni 500gr» → «bodom uni»."""
    text = re.sub(r"\s*\(ru:[^)]*\)", "", name or "")
    text = _SIZE_RE.sub("", text)
    text = re.sub(r"['ʻ’`‘]", "'", text.lower())
    return re.sub(r"[\s\-–—,]+$", "", re.sub(r"\s+", " ", text)).strip()


def requested_amount(amount: float, unit: str) -> float:
    """What the buyer asked for, in grams or ml."""
    return float(amount) * {"kg": 1000, "litr": 1000, "gramm": 1, "ml": 1}.get(unit, 1)


def _fmt(n) -> str:
    return f"{int(round(float(n or 0))):,}".replace(",", " ")


def _size_text(grams: float, kind: str) -> str:
    if grams >= 1000 and grams % 100 == 0:
        return f"{grams / 1000:g} {'l' if kind == 'ml' else 'kg'}"
    return f"{grams:g} {'ml' if kind == 'ml' else 'g'}"


def pack_options(products: list[dict], wanted: float) -> list[dict]:
    """Ways to cover `wanted` grams/ml with whole packs of one product family.

    One entry per pack size (that pack × n) and, when there are two sizes or
    more, the cheapest mix of them that covers it. Each: packs [(product, n)],
    total grams, total price, price per kilo/litre, `exact` (= what was asked).
    Cheapest first."""
    sized = []
    for p in products:
        size = pack_size(p.get("name"), p.get("unit"))
        if size and float(p.get("price") or 0) > 0:
            sized.append((p, size[0]))
    out = []
    for p, size in sized:
        n = max(1, math.ceil(wanted / size - 1e-9))
        out.append({"packs": [(p, n)], "grams": n * size, "price": n * float(p["price"])})
    sizes = sorted(sized, key=lambda ps: -ps[1])
    if len(sizes) >= 2:
        # Largest packs first, the remainder from the cheapest-per-gram pack that fits.
        big, big_size = sizes[0]
        whole = int(wanted // big_size)
        rest = wanted - whole * big_size
        if whole and rest > 1e-9:
            best = None
            for p, size in sizes[1:]:
                n = math.ceil(rest / size - 1e-9)
                cost = n * float(p["price"])
                if best is None or cost < best[2]:
                    best = (p, n, cost, n * size)
            if best:
                out.append({"packs": [(big, whole), (best[0], best[1])],
                            "grams": whole * big_size + best[3],
                            "price": whole * float(big["price"]) + best[2]})
    for o in out:
        o["per_kilo"] = o["price"] / o["grams"] * 1000 if o["grams"] else 0
        o["exact"] = abs(o["grams"] - wanted) < 1
    # Cheapest for at least the asked amount; ties — the one closest to it.
    out.sort(key=lambda o: (o["price"], o["grams"]))
    seen, unique = set(), []
    for o in out:
        key = tuple((p["id"], n) for p, n in o["packs"])
        if key not in seen:
            seen.add(key)
            unique.append(o)
    return unique


def options_text(products: list[dict], wanted: float, kind: str) -> str:
    """The tool answer the model copies from."""
    options = pack_options(products, wanted)
    if not options:
        return ("Xato: bu mahsulotning qadoq hajmi nomida yo'q — og'irlik bo'yicha hisoblab bo'lmaydi. "
                "Mijozga bitta dona narxini ayt, hajmini so'rasa — operatorimiz aniqlaydi.")
    smallest = min(pack_size(p.get("name"), p.get("unit"))[0] for o in options for p, _ in o["packs"])
    lines = [f"SO'RALGAN: {_size_text(wanted, kind)}. Narx — bitta qadoq uchun; miqdor — qadoqlar soni:"]
    for i, o in enumerate(options):
        packs = " + ".join(f"{p['name']} (id {p['id']}) × {n} dona" for p, n in o["packs"])
        tail = "" if o["exact"] else f" — so'ralgandan ko'p: {_size_text(o['grams'], kind)}"
        mark = "  ← eng arzon" if i == 0 else ""
        lines.append(f"- {packs} = {_size_text(o['grams'], kind)}, {_fmt(o['price'])} so'm "
                     f"(1 {'litr' if kind == 'ml' else 'kg'} — {_fmt(o['per_kilo'])} so'm){tail}{mark}")
    if wanted < smallest - 1:
        lines.append(f"DIQQAT: {_size_text(wanted, kind)} alohida sotilmaydi — eng kichik qadoq "
                     f"{_size_text(smallest, kind)}. Buni mijozga ochiq ayt, narxni BO'LMA.")
    lines.append("Mijozga variantni qadoq soni va narxi bilan ayt; savatga_qoshish / hisob ga "
                 "miqdor sifatida shu qadoq sonini ber.")
    return "\n".join(lines)


# ─────────────────────── a reply line vs its own amount ─────────────────────
_COUNT_RE = re.compile(r"(\d+)\s*(?:ta|dona|qadoq|pachka|paket|шт|штук\w*|упаков\w*|пачк\w*|ед)\b", re.I)
_HALF_RE = re.compile(r"\b(?:yarim|pol)\s*(?:kilo\w*|kg|кило\w*|кг)|\bполкило\w*|\bполовин\w*\s+кило\w*",
                      re.I)
_MONEY_RE = re.compile(r"(\d{1,3}(?:[   .,]\d{3})+|\d{4,})\s*(?:so['ʻ’`‘]?m|сўм|сум|sum)", re.I)


def _money(line: str) -> list[int]:
    return [int(re.sub(r"\D", "", m.group(1))) for m in _MONEY_RE.finditer(line)]


def stated_packs(rest: str, pack: tuple[float, str] | None) -> int | None:
    """How many packs a line says, from what is left of it after the product name:
    «2 ta», «3 dona» → 2, 3; «1 kg» of a 500 g pack → 2; «yarim kilo» → 1."""
    count = _COUNT_RE.search(rest)
    if count:
        return int(count.group(1))
    if not pack:
        return None
    if _HALF_RE.search(rest):
        return max(1, math.ceil(500 / pack[0] - 1e-9))
    weight = _SIZE_RE.search(rest)
    if weight:
        grams = _number(weight.group(1)) * _TO_BASE[weight.group(2).lower()]
        return max(1, math.ceil(grams / pack[0] - 1e-9))
    return None


def line_mismatch(text: str, products: list[dict], trusted=frozenset()) -> list[dict]:
    """Lines whose single amount is not (their pack price × the packs they state).

    `trusted` — numbers from this turn's tool results (the cart, hisob): a line
    copied from them (a bot-discounted cart price, say) is taken as it is when
    both its amount and amount / packs came from a tool.

    Only a line that names one catalog product in full («Bodom uni 500gr») and
    carries one amount is judged — a price list «500gr — 87 000, 1 kg — 169 000»
    or a loose mention is left alone."""
    by_name = sorted(((re.sub(r"['ʻ’`‘]", "'", p["name"].lower()), p) for p in products if p.get("name")),
                     key=lambda np: -len(np[0]))
    out = []
    for line in (text or "").split("\n"):
        amounts = [a for a in _money(line) if a >= 1000]
        if len(amounts) != 1:
            continue
        low = re.sub(r"['ʻ’`‘]", "'", line.lower())
        hit = next(((n, p) for n, p in by_name if n in low), None)
        if not hit:
            continue
        name, product = hit
        rest = low.replace(name, " ", 1)
        rest = _MONEY_RE.sub(" ", rest)
        packs = stated_packs(rest, pack_size(product["name"], product.get("unit")))
        if not packs:
            continue
        prices = {float(product["price"])} | ({float(product["original_price"])}
                                               if product.get("original_price") else set())
        found = amounts[0]
        if found in trusted and found % packs == 0 and found // packs in trusted:
            continue
        if not any(abs(packs * pr - found) < 1 for pr in prices):
            out.append({"line": line.strip(), "name": product["name"], "packs": packs,
                        "expected": packs * float(product["price"]), "found": amounts[0]})
    return out


def mismatch_fix(issues: list[dict]) -> str:
    shown = "; ".join(f"«{i['line']}» — {i['packs']} qadoq = {_fmt(i['expected'])} so'm" for i in issues[:3])
    return (f"[TIZIM: miqdor va summa mos emas: {shown}. Narx — BITTA QADOQ narxi (nomidagi 500gr/1kg "
            "— o'sha qadoq); summa = qadoq soni × narx. Og'irlik so'ralsa qadoq_tanlash ni chaqir, "
            "ro'yxat va jamini hisob dan ko'chir, qatorda qadoq sonini yoz. Javobni qayta yoz.]")
