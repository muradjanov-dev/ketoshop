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
    "MCT",        # "MCT yog'i" came out "МCТ" — C has no Uzbek letter
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
# @usernames and links must stay exactly as typed — "@ketoshopbot" rendered
# as "@кетошопбот" in a Cyrillic tip is a handle nobody can open (2026-09-17).
_HANDLE_OR_LINK_RE = re.compile(r"@[A-Za-z0-9_]{3,}|(?:https?://|t\.me/|www\.)\S+")

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
    # 2026 alphabet (Law OʻRQ-1184): ö ğ ş ç are ў ғ ш ч.
    "ö": "ў", "ğ": "ғ", "ş": "ш", "ç": "ч",
    "Ö": "Ў", "Ğ": "Ғ", "Ş": "Ш", "Ç": "Ч",
}

# Word-initial e/E. The lookbehind has to reject ANY letter, not just a Latin
# one: this runs after the digraph pass, so by now "ch" is already "ч" and a
# Latin-only test read the "e" of "pechene" as word-initial and gave "печэне".
# The same went for every e after sh/o'/g'/yo/yu/ya — "chek" came out "чэк".
# `[^\W\d_]` is "any letter" in Unicode, which covers both alphabets; a stash
# placeholder is a private-use char, not a letter, so "<b>Eng" still counts as
# word-initial. Apostrophes get their own lookbehind because a character class
# cannot nest inside another one.
_WORD_INITIAL_E_RE = re.compile(r"(?<![^\W\d_])(?<!['ʻ’])[eE]")

# Loanwords where Latin "ts" stands for Cyrillic "ц": "Ретсептни очиш" was
# printed for "Рецептни очиш" (owner, 2026-10-13). Native Uzbek "ts" must
# stay "тс" — aytsa → айтса, ketsa → кетса, shartsiz → шартсиз,
# muvaffaqiyatsiz → муваффақиятсиз — so these are narrow rules, never a
# blanket ts → ц:
#   • stems borrowed whole (retsept, ratsion, …), in any case;
#   • the "-tsiya" ending (lokatsiya, kombinatsiya, integratsiya → -ция);
#   • "ts" at the start of a word (tsikl → цикл); no Uzbek word starts so.
_TS_STEMS: tuple[tuple[str, str], ...] = (
    ("retsept", "рецепт"),
    ("ratsion", "рацион"),
    ("antotsian", "антоциан"),
    ("protsess", "процесс"),
    ("protsedur", "процедур"),
    ("kontsentrat", "концентрат"),
    ("kontsert", "концерт"),
    ("pitsa", "пицца"),           # keto pitsa (site recipes, 2026-10-17)
    ("porsiya", "порция"),        # "1 porsiyada" — no "ts" in the Latin, but порция in Cyrillic
    ("aksiya", "акция"),          # aksiya → акция, not "аксия" (gift extension, 2026-10-17)
)
_TS_STEM_RES = tuple((re.compile(lat, re.IGNORECASE), cyr) for lat, cyr in _TS_STEMS)
_TSIYA_RE = re.compile(r"(?<=[^\W\d_])ts(?=iya)", re.IGNORECASE)
_WORD_INITIAL_TS_RE = re.compile(r"(?<![^\W\d_])(?<!['ʻ’])ts", re.IGNORECASE)


def _same_case(src: str, cyr: str) -> str:
    """Cyrillic replacement in the case of the Latin original: retsept →
    рецепт, Retsept → Рецепт, RETSEPT → РЕЦЕПТ."""
    if src.isupper() and len(src) > 1:
        return cyr.upper()
    if src[:1].isupper():
        return cyr[:1].upper() + cyr[1:]
    return cyr


def _ts_loanwords(text: str) -> str:
    for rx, cyr in _TS_STEM_RES:
        text = rx.sub(lambda m, c=cyr: _same_case(m.group(0), c), text)
    text = _TSIYA_RE.sub(lambda m: _same_case(m.group(0), "ц"), text)
    return _WORD_INITIAL_TS_RE.sub(lambda m: _same_case(m.group(0), "ц"), text)


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
    text = _stash(text, _HANDLE_OR_LINK_RE, store, counter)
    text = _stash(text, _BOT_COMMAND_RE, store, counter)
    for brand in _BRANDS:
        text = _stash(text, brand, store, counter)

    # Loanword "ts" → "ц" before anything else touches those letters.
    text = _ts_loanwords(text)

    # Digraphs first
    for lat, cyr in _DIGRAPHS:
        if lat in text:
            text = text.replace(lat, cyr)

    # Word-initial "e" is э in Uzbek Cyrillic, not е: emas → эмас, eng → энг,
    # eritritol → эритритол. Applied after the digraph pass so "ye"/"Ye" has
    # already become е/Е (yetarli → етарли stays correct), and before the
    # single-letter pass, which leaves э/Э alone since they aren't Latin.
    # A preceding letter or apostrophe means we're mid-word, so it stays е.
    text = _WORD_INITIAL_E_RE.sub(lambda m: "Э" if m.group(0) == "E" else "э", text)

    # Then single-letter substitution
    text = "".join(_SINGLES.get(ch, ch) for ch in text)

    # Restore stashed pieces, newest first: a later stash (a link) can swallow
    # an earlier placeholder (the </b> right after it), which must come back
    # out after its container does.
    for token, original in reversed(list(store.items())):
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


# ─────────────────────── the 2026 Latin alphabet ────────────────────────────
#
# Law OʻRQ-1184 (signed 21.10.2026, in force 22.04.2027): Oʻ → Ö, Gʻ → Ğ,
# Sh → Ş, Ch → Ç; "ng" is no longer a letter of its own (still written ng);
# the apostrophe stays as the tutuq belgisi (ma'lumot, ta'm). Owner,
# 2026-10-28: "loyihani yangi alifboga o'tkaz" — shown now, with a switch
# (alphabet.py). Every text in the code and the database stays in the old
# Latin; this runs where the text leaves for a reader.

_APOSTROPHES = "'ʻ‘’`ʼ"
# Words that keep their sh/ch: our own brand (and its handle, already a link)
# and foreign product names.
_NEW_LATIN_KEEP_RE = re.compile(r"keto\s?shop|charged", re.IGNORECASE)
# 'Kakao' — a word in single quotes. Its closing quote is not the oʻ/gʻ mark.
_SINGLE_QUOTED_RE = re.compile(r"(?<![^\W_])['‘]([^'‘’\n]{1,60})['’](?![^\W_])")
# Is'hoq, as'hob: the apostrophe only kept s and h apart; with ş in the
# alphabet they are just written "sh".
_S_H_SPLIT_RE = re.compile(r"([sScC])[%s]([hH])" % _APOSTROPHES)
_OG_RE = re.compile(r"([oOgG])[%s]" % _APOSTROPHES)
_SH_CH_RE = re.compile(r"([sScC])([hH])")
_NEW_OG = {"o": "ö", "O": "Ö", "g": "ğ", "G": "Ğ"}
# Private-use markers of our own \u2014 _stash's tokens are \ue000\u2026\ue001, so these
# must not be: "s and h stay two letters", and the two quotes of a 'word'.
_SPLIT = "\ue011"
_QUOTE_OPEN, _QUOTE_CLOSE = "\ue012", "\ue013"


def _new_digraph(m: re.Match) -> str:
    first, second = m.group(1), m.group(2)
    letter = "ş" if first in "sS" else "ç"
    # Sh / SH → Ş; sh / sH → ş (case follows the first letter).
    return letter.upper() if first.isupper() else letter


def to_new_latin(text: str) -> str:
    """Old Uzbek Latin → the 2026 alphabet: oʻ gʻ sh ch → ö ğ ş ç.

    Leaves HTML tags, {format} tokens, links, @handles, /commands and
    brands untouched; Cyrillic and Russian pass through as they are.
    Idempotent: new-alphabet text has nothing left to change."""
    if not text or not any(c in text for c in "oOgGsScC"):
        return text
    store: dict[str, str] = {}
    counter = [0]
    text = _stash(text, _HTML_TAG_RE, store, counter)
    text = _stash(text, _FMT_TOKEN_RE, store, counter)
    text = _stash(text, _HANDLE_OR_LINK_RE, store, counter)
    text = _stash(text, _BOT_COMMAND_RE, store, counter)
    text = _stash(text, _NEW_LATIN_KEEP_RE, store, counter)

    # 'Kakao' keeps its quotes as quotes.
    quotes: list[tuple[str, str]] = []

    def _hold(m: re.Match) -> str:
        quotes.append((m.group(0)[0], m.group(0)[-1]))
        return f"{_QUOTE_OPEN}{m.group(1)}{_QUOTE_CLOSE}"

    text = _SINGLE_QUOTED_RE.sub(_hold, text)
    text = _S_H_SPLIT_RE.sub(lambda m: m.group(1) + _SPLIT + m.group(2), text)
    text = _OG_RE.sub(lambda m: _NEW_OG[m.group(1)], text)
    text = _SH_CH_RE.sub(_new_digraph, text)
    # An invisible joiner-breaker keeps that s and h apart for good, so a
    # second pass (the Mini App re-reads what it wrote) can't make it ş.
    text = text.replace(_SPLIT, "\u200c")
    for open_q, close_q in quotes:
        text = text.replace(_QUOTE_OPEN, open_q, 1).replace(_QUOTE_CLOSE, close_q, 1)

    for token, original in reversed(list(store.items())):
        text = text.replace(token, original)
    return text


_OLD_LATIN = {"ö": "o'", "Ö": "O'", "ğ": "g'", "Ğ": "G'", "ş": "sh", "Ş": "Sh",
              "ç": "ch", "Ç": "Ch"}


def to_old_latin(text: str) -> str:
    """The 2026 letters back to the old Latin the database is written in —
    for search: a buyer typing "şokolad" must find "Shokolad"."""
    if not text:
        return text
    return "".join(_OLD_LATIN.get(ch, ch) for ch in text)
