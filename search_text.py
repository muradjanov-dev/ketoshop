"""
Product search that doesn't care which script the buyer types in (2026-11-11).

Mini App, 04–11.11: 20 of 88 searches came back empty. «кепак», «кепакли
бугдой», «какао», «жадвар» found nothing although «Kepakli bug'doy uni»,
«Kakao nibs 200gr» and «Javdar uni» are on the shelf — the names are kept
in Latin and the query went to ILIKE exactly as typed. Uzbek is written in
both alphabets, apostrophes come in five shapes (' ʻ ’ ‘ `), and on a
Russian keyboard ў ғ қ ҳ are typed as у г к х.

fold() reads a product name and a query into one key: Cyrillic → Latin
(translit.cyr_to_lat), the 2026 letters back to the old ones, lower case,
no apostrophes (o' = o, g' = g), and the letters a Russian keyboard swaps
merged (q = k, h = x, a lone c = k, ye = e, doubled letters single).
find() ranks the shop's products for a query; near() offers the closest
names when nothing matches. Used by the bot's 🔍 search and the Mini App's
/api/search alike (database.search_products / search_suggestions).
"""
from __future__ import annotations

import difflib
import functools
import re
import unicodedata

from translit import cyr_to_lat, to_old_latin

_APOSTROPHES_RE = re.compile(r"['ʻʼ’‘`´]")
_NOT_WORD_RE = re.compile(r"[^0-9a-zşç]+")
_DOUBLE_RE = re.compile(r"([a-zşç])\1+")


@functools.lru_cache(maxsize=4096)
def fold(text) -> str:
    """'Kepakli bugʻdoy uni' and 'кепакли буғдой' → 'kepakli bugdoy uni' /
    'kepakli bugdoy'. Idempotent: fold(fold(x)) == fold(x)."""
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", str(text))
    s = cyr_to_lat(to_old_latin(s).lower()).lower()
    s = _APOSTROPHES_RE.sub("", s)
    # sh / ch are one sound each: keep them apart from the h → x merge.
    s = s.replace("sh", "ş").replace("ch", "ç")
    s = s.replace("q", "k").replace("h", "x").replace("c", "k").replace("ye", "e")
    s = s.replace("iya", "ia")              # Steviya = Stevia = стевия
    s = _NOT_WORD_RE.sub(" ", s)
    s = _DOUBLE_RE.sub(r"\1", s)
    return " ".join(s.split())


def _osa(a: str, b: str) -> int:
    """Edit distance counting a swap of two neighbours as one edit
    (jadvar → javdar is 1)."""
    prev2: list[int] = []
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        prev2, prev = prev, cur
    return prev[-1]


def _tolerance(token: str) -> int:
    """Typos forgiven in one word: none up to 3 letters, 1 up to 5, else 2."""
    n = len(token)
    return 0 if n <= 3 else 1 if n <= 5 else 2


def _token_distance(token: str, words: list[str], strict: bool = False) -> int | None:
    """0 when the token is inside the name, else the fewest typos to a word
    (or to the start of a longer word, for a half-typed one); None if too far.
    strict: only one typo in a whole word of 6+ letters — the misspelt name
    «Eritrtitol» still shows up next to the «Eritritol» packs."""
    best = None
    tol = (1 if len(token) >= 6 else 0) if strict else _tolerance(token)
    for word in words:
        if token in word:
            return 0
        if not tol:
            continue
        # The whole word may be 2 typos away; a word's start only 1
        # («makaron» is not «makkajo'xori»).
        candidates = [(word, tol)]
        if len(word) > len(token) and not strict:
            candidates.append((word[:len(token)], 1))
        for cand, limit in candidates:
            if abs(len(cand) - len(token)) > limit:
                continue
            d = _osa(token, cand)
            if d <= limit and (best is None or d < best):
                best = d
    return best


def _name_keys(product: dict) -> str:
    return " ".join(k for k in (fold(product.get("name")), fold(product.get("name_ru"))) if k)


def _exact_rank(q: str, tokens: list[str], key: str) -> tuple[int, int] | None:
    """Where an exact hit sits: the name starts with the query, a word does,
    the query is inside, or all its words are there in another order. Then
    the shorter the word it starts, the closer: «yog'» → «Kokos yog'i»
    before «yog'lanmagan»."""
    padded = " " + key
    if " " + q in padded:
        extra = min((len(w) - len(tokens[0]) for w in key.split() if w.startswith(tokens[0])), default=0)
        return (0 if key.startswith(q) else 1, extra)
    if q in key:
        return (2, 0)
    if all(t in key for t in tokens):
        return (3, 0)
    return None


def find(query: str, products: list[dict]) -> list[dict]:
    """The products that match, best first: names that have the query (or,
    only when none has, names within a typo or two — «kakos» → Kokos), then
    descriptions that mention it. An empty query keeps every product in the
    given order."""
    q = fold(query)
    if not q:
        return list(products)
    tokens = q.split()
    exact, fuzzy, close, rest = [], [], [], []
    for i, p in enumerate(products):
        key = _name_keys(p)
        rank = _exact_rank(q, tokens, key) if key else None
        if rank is not None:
            exact.append((rank, i, p))
            continue
        words = key.split()
        total = _typos(tokens, words)
        if total is not None:
            fuzzy.append((total, i, p))
            if _typos(tokens, words, strict=True) is not None:
                close.append((total, i, p))
                continue
        rest.append((i, p))
    # Typos only when no name has the query as written: «shakar» must not
    # bring «makaron» along with «Kokos shakari» — bar a one-letter slip in a
    # long word.
    if exact:
        names = sorted(exact, key=lambda r: (r[0], r[1])) + sorted(close, key=lambda r: (r[0], r[1]))
    else:
        names = sorted(fuzzy, key=lambda r: (r[0], r[1]))
    taken = {i for _, i, _ in names}
    described = []
    if len(q) >= 3:
        for i, p in rest + [(i, p) for _, i, p in fuzzy]:
            if i in taken:
                continue
            desc = " " + fold(p.get("description")) + " " + fold(p.get("description_ru"))
            if " " + q in desc:
                described.append((i, p))
                taken.add(i)
    described.sort(key=lambda r: r[0])
    return [p for *_, p in names] + [p for _, p in described]


def _typos(tokens: list[str], words: list[str], strict: bool = False) -> int | None:
    """Typos in all the query's words together, or None if one is too far."""
    total = 0
    for t in tokens:
        d = _token_distance(t, words, strict)
        if d is None:
            return None
        total += d
    return total


def near(query: str, products: list[dict], limit: int = 4) -> list[dict]:
    """When find() has nothing: the names closest to the query, for «balki
    shulardir?». Each query word scores its best-matching name word (1 for a
    word that starts with it); a name needs a word of 3+ letters at least
    70% alike — «o'rik» must not offer «Oq kunjut»."""
    q = fold(query)
    if not q or limit <= 0:
        return []
    tokens = q.split()
    scored = []
    for i, p in enumerate(products):
        words = [w for w in _name_keys(p).split() if len(w) >= 3]
        if not words:
            continue
        score = 0.0
        for t in tokens:
            best = 0.0
            for w in words:
                r = 1.0 if w.startswith(t) else difflib.SequenceMatcher(None, t, w).ratio()
                best = max(best, r)
            if best >= 0.7:
                score += best
        if score > 0:
            scored.append((-score, i, p))
    scored.sort(key=lambda r: (r[0], r[1]))
    return [p for *_, p in scored[:limit]]
