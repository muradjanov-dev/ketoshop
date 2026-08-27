"""
Latin → Cyrillic transliteration for Uzbek.

Used at runtime to derive the Cyrillic UI when the buyer picks "Ўзбек
(Кирилл)" — Latin remains the canonical source-of-truth in locales.py
(and elsewhere) so we don't have to maintain two parallel string tables.

Mapping rules (Uzbek conventions, plain apostrophe):
  ch / sh / yo / yu / ya  → ч / ш / ё / ю / я
  o' / g'                 → ў / ғ
  bare apostrophe         → ъ   (glottal stop, e.g. ma'lum → маълум)
  single letters          → standard Uzbek-Cyrillic equivalents

Brand names and HTML tags are stashed as private-use placeholders before
the transliteration pass and restored afterwards, so:
  - "<b>Ketoshop</b>" stays exactly that
  - "Yandex Taxi" / "Yandex Market" / "Yandex" / "BTS" / "EMU" / "Telegram"
    / "UZS" pass through untouched
"""
from __future__ import annotations

import re

# Order matters: try longer brands before shorter prefixes (Yandex Taxi
# before Yandex). Add new brands here as they appear in the UI.
_BRANDS = (
    "Yandex Taxi",
    "Yandex Market",
    "Yandex",
    "KETO shop",
    "Ketoshop",
    "Telegram",
    "BTS",
    "EMU",
    "UZS",
)

_HTML_TAG_RE = re.compile(r"<[^>]+>")
# Telegram-format placeholders like {name}, {order_id} — keep intact.
_FMT_TOKEN_RE = re.compile(r"\{[^{}]*\}")
# Telegram bot commands like /skip, /done, /start — stay Latin so the user
# can actually type them. Match /<word> when the slash is NOT preceded by an
# alphanumeric char. That covers start-of-string, whitespace, punctuation, an
# HTML tag close (<b>/skip</b>) and our private-use stash placeholders — while
# still skipping dates/units/paths where a digit or letter precedes the slash
# (e.g. 100/kg, TCP/IP, 12/05). The earlier `(?:^|(?<=\s))` form missed the
# common <b>/skip</b> case, so it rendered as /скип in Cyrillic.
_BOT_COMMAND_RE = re.compile(r"(?<![A-Za-z0-9])/[a-zA-Z][a-zA-Z0-9_]*")

# Two-character sequences that map to a single Cyrillic letter. Apply BEFORE
# single-character substitution so "yo" doesn't become "йо".
_DIGRAPHS: tuple[tuple[str, str], ...] = (
    # o' and g' must be processed BEFORE yo / yu / ya so that "yo'l" becomes
    # 'y + o\'' → 'й + ў' = 'йўл' rather than 'yo + \'' = 'ёъл'.
    ("O'", "Ў"), ("o'", "ў"),
    ("G'", "Ғ"), ("g'", "ғ"),
    # Tolerate the modifier-letter apostrophe variant (ʻ, U+02BB) too
    ("Oʻ", "Ў"), ("oʻ", "ў"),
    ("Gʻ", "Ғ"), ("gʻ", "ғ"),
    ("Sh", "Ш"), ("SH", "Ш"), ("sh", "ш"),
    ("Ch", "Ч"), ("CH", "Ч"), ("ch", "ч"),
    ("Yo", "Ё"), ("YO", "Ё"), ("yo", "ё"),
    ("Yu", "Ю"), ("YU", "Ю"), ("yu", "ю"),
    ("Ya", "Я"), ("YA", "Я"), ("ya", "я"),
    # 'ye' is how 'е' (after consonants too) is often spelled in Latin Uzbek
    ("Ye", "Е"), ("YE", "Е"), ("ye", "е"),
)

_SINGLES = {
    "a": "а", "b": "б", "d": "д", "e": "е", "f": "ф", "g": "г", "h": "ҳ",
    "i": "и", "j": "ж", "k": "к", "l": "л", "m": "м", "n": "н", "o": "о",
    "p": "п", "q": "қ", "r": "р", "s": "с", "t": "т", "u": "у", "v": "в",
    "x": "х", "y": "й", "z": "з", "'": "ъ", "ʻ": "ъ",
    "A": "А", "B": "Б", "D": "Д", "E": "Е", "F": "Ф", "G": "Г", "H": "Ҳ",
    "I": "И", "J": "Ж", "K": "К", "L": "Л", "M": "М", "N": "Н", "O": "О",
    "P": "П", "Q": "Қ", "R": "Р", "S": "С", "T": "Т", "U": "У", "V": "В",
    "X": "Х", "Y": "Й", "Z": "З",
}

# Private-use range — guaranteed not to appear in real text.
_PH_OPEN = ""
_PH_CLOSE = ""


def _stash(text: str, pattern: re.Pattern | str, store: dict[str, str], counter: list[int]) -> str:
    """Replace each match of `pattern` in `text` with a unique placeholder
    that survives the transliteration pass."""
    if isinstance(pattern, str):
        if pattern not in text:
            return text
        token = f"{_PH_OPEN}{counter[0]}{_PH_CLOSE}"
        counter[0] += 1
        store[token] = pattern
        return text.replace(pattern, token)
    # regex
    def _sub(m: re.Match) -> str:
        token = f"{_PH_OPEN}{counter[0]}{_PH_CLOSE}"
        counter[0] += 1
        store[token] = m.group(0)
        return token
    return pattern.sub(_sub, text)


def lat_to_cyr(text: str) -> str:
    """Transliterate Latin Uzbek text into Cyrillic, leaving brands, HTML
    tags, and {format_tokens} untouched. Idempotent against already-Cyrillic
    input (no Latin letters → no changes)."""
    if not text:
        return text

    store: dict[str, str] = {}
    counter = [0]

    # Order: HTML tags (most specific structure) → format tokens → bot
    # commands → brands.
    text = _stash(text, _HTML_TAG_RE, store, counter)
    text = _stash(text, _FMT_TOKEN_RE, store, counter)
    text = _stash(text, _BOT_COMMAND_RE, store, counter)
    for brand in _BRANDS:
        text = _stash(text, brand, store, counter)

    # Digraphs first
    for lat, cyr in _DIGRAPHS:
        if lat in text:
            text = text.replace(lat, cyr)

    # Then single-letter substitution
    text = "".join(_SINGLES.get(ch, ch) for ch in text)

    # Restore stashed pieces
    for token, original in store.items():
        text = text.replace(token, original)
    return text


# Cyrillic → Latin reverse map. Used when a seller types Cyrillic into a
# field meant to hold Latin source — without this, UZ Latin users see
# Cyrillic descriptions because we only ever map Latin → Cyrillic, never
# the other way. Idempotent against already-Latin input (Latin chars
# aren't in the Cyrillic map).
_CYR_DIGRAPHS: tuple[tuple[str, str], ...] = (
    ("Ў", "O'"), ("ў", "o'"),
    ("Ғ", "G'"), ("ғ", "g'"),
    ("Ш", "Sh"), ("ш", "sh"),
    ("Ч", "Ch"), ("ч", "ch"),
    ("Ё", "Yo"), ("ё", "yo"),
    ("Ю", "Yu"), ("ю", "yu"),
    ("Я", "Ya"), ("я", "ya"),
)

_CYR_SINGLES = {
    "а": "a", "б": "b", "д": "d", "е": "e", "ф": "f", "г": "g", "ҳ": "h",
    "и": "i", "ж": "j", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "қ": "q", "р": "r", "с": "s", "т": "t", "у": "u", "в": "v",
    "х": "x", "й": "y", "з": "z", "ъ": "'",
    "А": "A", "Б": "B", "Д": "D", "Е": "E", "Ф": "F", "Г": "G", "Ҳ": "H",
    "И": "I", "Ж": "J", "К": "K", "Л": "L", "М": "M", "Н": "N", "О": "O",
    "П": "P", "Қ": "Q", "Р": "R", "С": "S", "Т": "T", "У": "U", "В": "V",
    "Х": "X", "Й": "Y", "З": "Z",
    # Russian-specific Cyrillic letters that show up in loanwords/imports.
    # Best-effort mapping so the Latin reader still gets pronounceable text
    # rather than a hole in the string.
    "ц": "ts", "Ц": "Ts", "щ": "shch", "Щ": "Shch",
    "ы": "i", "Ы": "I", "э": "e", "Э": "E", "ь": "",
}


def cyr_to_lat(text: str) -> str:
    """Transliterate Cyrillic Uzbek text into Latin, preserving brands,
    HTML tags, format tokens, and bot commands. Idempotent on already-Latin
    input."""
    if not text:
        return text

    store: dict[str, str] = {}
    counter = [0]

    text = _stash(text, _HTML_TAG_RE, store, counter)
    text = _stash(text, _FMT_TOKEN_RE, store, counter)
    text = _stash(text, _BOT_COMMAND_RE, store, counter)
    for brand in _BRANDS:
        text = _stash(text, brand, store, counter)

    for cyr, lat in _CYR_DIGRAPHS:
        if cyr in text:
            text = text.replace(cyr, lat)

    text = "".join(_CYR_SINGLES.get(ch, ch) for ch in text)

    for token, original in store.items():
        text = text.replace(token, original)
    return text
