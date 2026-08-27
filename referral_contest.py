"""
Keto musobaqasi — referral contest (2026-07-30).

Anyone can open "Keto musobaqasi" from the main menu and get their own
referral deep link (t.me/<bot>?start=ref<user_id>). Whoever brings in the
most new users during the contest's window (10 days by default, admin-configurable)
wins one of 3 prizes (admin
sets the prize text and picks the launch date/image from the admin panel —
see admin_web.py's /admin/api/contest/* routes). The contest is dormant
(referral_contest_state.active = FALSE) until an admin explicitly starts it;
deploying this code changes nothing for real users by itself.

Independent of whether a contest is currently running, every successful
referral (a brand-new user whose first /start carried someone's ref<id>
payload) pays BOTH sides 10 Keto immediately — see award_referral(). Every
new user, referred or not, also triggers an admin notification — see
notify_admins_new_user() in handlers/start.py's call site.

Public API:
  award_referral(referrer_id, referred_id, bot)  -> credit 10 Keto to both + DM each
  build_contest_screen(user_id, lang)            -> (intro_text, detail_text, has_share_button, media, share_url, guide_video_file_id)
  build_share_text(user_id, lang, prizes)        -> ready-to-forward post + prizes + referral link (used by daily reminders)
  share_deeplink(user_id, lang, prizes)          -> t.me/share/url link (carries prizes) that opens Telegram's chat picker
  scheduler_loop(bot)                            -> daily reminder while active; auto-finish at ends_at
"""
import asyncio
import logging
from datetime import datetime, timedelta
from urllib.parse import quote

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest, TelegramRetryAfter
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import database
from config import ADMIN_IDS, BOT_USERNAME, WEBAPP_URL

logger = logging.getLogger(__name__)

REFERRAL_KETO_REWARD = 10
TZ_OFFSET = timedelta(hours=5)  # Asia/Tashkent, fixed UTC+5, no DST
REMINDER_HOUR = 9               # daily nudge fires shortly after 09:00 Tashkent
CHECK_EVERY = 900               # re-check every 15 minutes, same cadence as broadcast.py
SEND_DELAY = 0.05


def _now_utc() -> datetime:
    """Naive UTC — the same reference frame CURRENT_TIMESTAMP writes to the
    DB in (started_at/ends_at/created_at), so it's what all duration math
    against those columns must use."""
    return datetime.utcnow()


def _now_tk() -> datetime:
    """Tashkent local — only for calendar-day/hour gating (matching
    last_reminder_date and the daily REMINDER_HOUR), never for comparing
    against ends_at/started_at directly (see _now_utc)."""
    return datetime.utcnow() + TZ_OFFSET


def _fmt(n: int) -> str:
    return f"{int(n):,}".replace(",", " ")


def _excluded() -> set[int]:
    return set(ADMIN_IDS) | database.LEADERBOARD_EXCLUDED_USER_IDS


def _contest_media(state: dict) -> tuple[str, str] | None:
    """Priority: video > bot-uploaded photo > website-uploaded photo — a clip
    is the strongest hook, and a native Telegram file_id (bot upload) needs
    no extra network hop the way a webapp-hosted URL does. Returns
    ("video", file_id) or ("tg_photo", file_id) — both native Telegram
    file_ids, sent as-is — or ("photo", relative_path), which the caller must
    prefix with WEBAPP_URL before handing to send_photo. None if the admin
    hasn't uploaded any of the three."""
    if state.get("video_file_id"):
        return "video", state["video_file_id"]
    if state.get("image_file_id"):
        return "tg_photo", state["image_file_id"]
    if state.get("image_url"):
        return "photo", state["image_url"]
    return None


def referral_link(user_id: int) -> str:
    return f"https://t.me/{BOT_USERNAME}?start=ref{user_id}"


def parse_ref_payload(payload: str | None) -> int | None:
    """'ref123456789' -> 123456789, or None for anything else. Shared by
    handlers/start.py (normal /start) and subscription_gate.py (which has
    to replay a blocked-then-confirmed user's original payload)."""
    if not payload or not payload.startswith("ref"):
        return None
    try:
        return int(payload[3:])
    except ValueError:
        return None


def _display_name(username: str | None, full_name: str | None, user_id: int) -> str:
    if username:
        return f"@{username}"
    if full_name:
        return full_name
    return f"ID {user_id}"


async def is_eligible_pair(referrer_id: int, referred_id: int) -> bool:
    if referrer_id == referred_id:
        return False
    excluded = _excluded()
    if referrer_id in excluded or referred_id in excluded:
        return False
    return True


def _rank_label(rank: int, lang: str) -> str:
    medal = {1: "🥇 ", 2: "🥈 ", 3: "🥉 "}.get(rank, "")
    suffix = "o'rin" if lang != "ru" else "место"
    return f"{medal}{rank}-{suffix}" if lang != "ru" else f"{medal}{rank}-е {suffix}"


async def award_referral(referrer_id: int, referred_id: int, bot: Bot) -> None:
    """Call once, right after a brand-new user's first /start is confirmed to
    carry a valid ref<id> payload. Both sides get +10 Keto and a congrats DM
    (owner request 2026-07-31: "qo'shilganga ham va taklif qilganga ham") —
    best-effort throughout: never raises, so a Keto bug can't block the new
    user's own onboarding message."""
    try:
        if not await is_eligible_pair(referrer_id, referred_id):
            return
        recorded = await database.record_referral(referred_id, referrer_id)
        if not recorded:
            return  # this person was already credited to someone else

        await database.credit_keto(
            referrer_id, order_id=None, amount=REFERRAL_KETO_REWARD, kind="referral",
            note=f"Taklif: user {referred_id} qo'shildi",
        )
        await database.credit_keto(
            referred_id, order_id=None, amount=REFERRAL_KETO_REWARD, kind="referral",
            note=f"Taklif orqali qo'shildi: referrer {referrer_id}",
        )

        referrer_user = await database.get_user(referrer_id)
        referred_user = await database.get_user(referred_id)
        if not referrer_user or not referred_user:
            return

        referrer_balance = int(referrer_user["keto_balance"])
        referrer_lang = referrer_user.get("language") or "uz"
        who_joined = _display_name(referred_user.get("username"), referred_user.get("full_name"), referred_id)

        L = lambda uz, ru: uz if referrer_lang != "ru" else ru
        lines = [
            L(f"🎉 <b>Tabriklaymiz!</b> Sizning havolangiz bilan <b>{who_joined}</b> Ketoshopga qo'shildi!",
              f"🎉 <b>Поздравляем!</b> По вашей ссылке в Ketoshop присоединился(-ась) <b>{who_joined}</b>!"),
            L(f"🥑 +{REFERRAL_KETO_REWARD} Keto tanga qo'lga kiritdingiz! Joriy balans: <b>{_fmt(referrer_balance)} Keto</b>",
              f"🥑 Вы получили +{REFERRAL_KETO_REWARD} монет Keto! Ваш баланс: <b>{_fmt(referrer_balance)} Keto</b>"),
        ]

        state = await database.get_referral_contest_state()
        if state.get("active") and state.get("started_at"):
            since, until = state["started_at"], state["ends_at"]
            excluded = _excluded()
            board = await database.get_contest_leaderboard(since, until, excluded, limit=100_000)
            idx = next((i for i, r in enumerate(board) if r["user_id"] == referrer_id), None)
            count = board[idx]["invites"] if idx is not None else await database.get_user_referral_count(referrer_id, since, until)
            if idx is not None:
                rank_text = _rank_label(idx + 1, referrer_lang)
                lines.append(L(f"🏆 Musobaqadagi hozirgi o'rningiz: <b>{rank_text}</b> ({count} kishi taklif qildingiz)",
                                f"🏆 Ваше текущее место в конкурсе: <b>{rank_text}</b> (приглашено {count} чел.)"))
            lines.append(L("📣 Yana ko'proq do'stlaringizni taklif qiling — yuqori o'rinlarga ko'tariling va Ketoshopdan maxsus sovg'alarni qo'lga kiriting!",
                            "📣 Приглашайте ещё друзей — поднимайтесь выше в рейтинге и получите специальный приз от Ketoshop!"))

        referrer_text = "\n\n".join(lines)
        try:
            await bot.send_message(referrer_id, referrer_text, parse_mode=ParseMode.HTML)
        except Exception:
            logger.warning("Referral award message failed for referrer %s", referrer_id, exc_info=True)

        # The newly joined side of the same event — their own welcome + bonus.
        referred_balance = int(referred_user["keto_balance"])
        referred_lang = referred_user.get("language") or "uz"
        who_invited = _display_name(referrer_user.get("username"), referrer_user.get("full_name"), referrer_id)
        L2 = lambda uz, ru: uz if referred_lang != "ru" else ru
        referred_text = "\n\n".join([
            L2(f"🎉 <b>Xush kelibsiz!</b> Siz <b>{who_invited}</b> taklifi bilan Ketoshop oilasiga qo'shildingiz!",
               f"🎉 <b>Добро пожаловать!</b> Вы присоединились к Ketoshop по приглашению <b>{who_invited}</b>!"),
            L2(f"🥑 Sovg'a sifatida +{REFERRAL_KETO_REWARD} Keto tanga oldingiz! Balansingiz: <b>{_fmt(referred_balance)} Keto</b>",
               f"🥑 В подарок вы получили +{REFERRAL_KETO_REWARD} монет Keto! Ваш баланс: <b>{_fmt(referred_balance)} Keto</b>"),
        ])
        try:
            await bot.send_message(referred_id, referred_text, parse_mode=ParseMode.HTML)
        except Exception:
            logger.warning("Referral welcome message failed for new user %s", referred_id, exc_info=True)
    except Exception:
        logger.exception("award_referral failed (referrer=%s, referred=%s)", referrer_id, referred_id)


async def notify_admins_new_user(bot: Bot, new_user_id: int, username: str | None,
                                  full_name: str | None, referrer_id: int | None) -> None:
    """Fired for every brand-new registration, referred or not (owner
    request 2026-07-30: wants to see who joins and who invited them)."""
    who = _display_name(username, full_name, new_user_id)
    if referrer_id:
        ref_user = await database.get_user(referrer_id)
        ref_who = _display_name(
            ref_user.get("username") if ref_user else None,
            ref_user.get("full_name") if ref_user else None,
            referrer_id,
        )
        ref_line = f"🔗 Taklif qilgan: {ref_who} (ID {referrer_id})"
    else:
        ref_line = "🔗 Taklif qilgan: — (to'g'ridan-to'g'ri qo'shildi)"
    text = f"🆕 <b>Yangi foydalanuvchi qo'shildi!</b>\n👤 {who} (ID {new_user_id})\n{ref_line}"
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode=ParseMode.HTML)
        except Exception:
            pass


def _time_left_label(ends_at: datetime, lang: str) -> str:
    remaining = ends_at - _now_utc()
    L = lambda uz, ru: uz if lang != "ru" else ru
    if remaining.total_seconds() <= 0:
        return L("⏳ Musobaqa yakunlanmoqda, natijalar tez orada e'lon qilinadi.",
                  "⏳ Конкурс завершается, результаты скоро будут объявлены.")
    days = remaining.days
    hours = remaining.seconds // 3600
    if days > 0:
        return L(f"⏳ Tugashiga: {days} kun {hours} soat qoldi", f"⏳ До конца: {days} дн. {hours} ч.")
    return L(f"⏳ Tugashiga: {hours} soat qoldi", f"⏳ До конца: {hours} ч.")


_WINDOW_RADIUS = 5  # 5 ranks above + 5 below the viewer, per owner request


def _build_window_leaderboard_text(board: list[dict], user_id: int, lang: str) -> str:
    """Ranks around the viewer rather than a flat top-N — the standings that
    actually matter to someone are the ones right next to them."""
    L = lambda uz, ru: uz if lang != "ru" else ru
    if not board:
        return (L("📊 <b>Reyting:</b>", "📊 <b>Рейтинг:</b>") + "\n" +
                L("Hozircha hech kim ishtirok etmagan — birinchi bo'ling!",
                  "Пока никто не участвует — станьте первым!"))

    idx = next((i for i, r in enumerate(board) if r["user_id"] == user_id), None)
    if idx is None:
        start = 0
        window = board[:_WINDOW_RADIUS]
        header = L("📊 <b>Yetakchilar (Top 5):</b>", "📊 <b>Лидеры (Топ-5):</b>")
    else:
        start = max(0, idx - _WINDOW_RADIUS)
        window = board[start: idx + _WINDOW_RADIUS + 1]
        header = L("📊 <b>Reyting — sizning atrofingiz:</b>", "📊 <b>Рейтинг — вокруг вас:</b>")

    medals = {0: "🥇", 1: "🥈", 2: "🥉"}
    lines = [header]
    for offset, r in enumerate(window):
        rank = start + offset
        mark = medals.get(rank, f"{rank + 1}.")
        name = _display_name(r.get("username"), r.get("full_name"), r["user_id"])
        you = L(" ← Siz", " ← Вы") if r["user_id"] == user_id else ""
        lines.append(f"{mark} {name} — {r['invites']} " + L("kishi", "чел.") + you)

    if idx is None:
        lines.append(L("\n📍 Siz hali reytingda emassiz — birinchi do'stingizni taklif qiling!",
                        "\n📍 Вы ещё не в рейтинге — пригласите первого друга!"))
    return "\n".join(lines)


def _prize_block_plain(prizes: list[str | None], lang: str) -> str:
    """Plain-text (no HTML — this rides inside share text/URLs) medal list,
    skipping any place the admin hasn't filled in yet. Owner request
    2026-07-31: "odamlar sovg'alarni ko'rishlari kerak" — whatever gets
    shared/forwarded must show the actual prizes, not just a vague mention
    that a contest exists."""
    medals = ["🥇", "🥈", "🥉"]
    lines = [f"{medal} {p}" for medal, p in zip(medals, prizes) if p]
    return "\n".join(lines)


def build_share_teaser(lang: str, prizes: list[str | None] | None = None) -> str:
    """Short pain-point hook for the t.me/share/url deep link — the link
    itself rides in the `url` param, so this stays link-free."""
    L = lambda uz, ru: uz if lang != "ru" else ru
    prize_block = _prize_block_plain(prizes or [], lang)
    prize_line = f"\n\n{prize_block}" if prize_block else ""
    return L(
        "😩 Yana bir bor parhez boshladingiz-u, keto mahsulot topa olmay charchadingizmi? "
        "O'zbekistondagi eng keng keto assortiment mahsulotlari — Ketoshop'da! 🥑\n\n"
        "🏆 Ustiga, hozir Keto musobaqasi ham davom etmoqda!" + prize_line + "\n\n"
        "Mening havolam orqali qo'shiling, ikkalamizga ham foyda! 🎁",
        "😩 Опять начали диету — и опять негде найти нормальные кето-продукты? Самый широкий "
        "ассортимент кето-продуктов в Узбекистане — в Ketoshop! 🥑\n\n"
        "🏆 А ещё сейчас идёт конкурс Keto!" + prize_line + "\n\n"
        "Присоединяйтесь по моей ссылке, выгодно обоим! 🎁",
    )


def share_deeplink(user_id: int, lang: str, prizes: list[str | None] | None = None) -> str:
    """A t.me/share/url link: tapping it opens Telegram's native chat picker
    with this text + the referral link pre-loaded, ready to forward to any
    chat(s) the user picks — no manual copy/forward needed."""
    link = referral_link(user_id)
    teaser = build_share_teaser(lang, prizes)
    return f"https://t.me/share/url?url={quote(link, safe='')}&text={quote(teaser, safe='')}"


async def build_contest_screen(user_id: int, lang: str) -> tuple[str, str, bool, tuple[str, str] | None, str | None, str | None]:
    """Returns (intro_text, detail_text, show_share_button, media, share_url, guide_video_file_id).

    Split in two on purpose: intro_text is a short, fixed-length block safe
    to use as a photo/video caption (Telegram's 1024-char cap); detail_text
    carries the admin-entered prize text (up to 500 chars each) and the
    leaderboard, which together can easily blow that cap, so it always goes
    out as a plain message. detail_text == "" means "contest not started" —
    the caller should send intro_text alone. media is whatever
    _contest_media() returns — ("video", file_id), ("tg_photo", file_id),
    ("photo", relative_path), or None. share_url is the ready t.me/share/url
    link (already carries the actual prizes, see share_deeplink), or None
    when there's nothing to share yet/anymore. guide_video_file_id is the
    optional, separate "how to participate" clip (see
    database.update_contest_guide_video) — sent as its own extra message,
    additive to `media`, not a replacement for it."""
    state = await database.get_referral_contest_state()
    L = lambda uz, ru: uz if lang != "ru" else ru

    if not state.get("started_at"):
        text = (
            L("🏆 <b>Keto musobaqasi</b>", "🏆 <b>Конкурс Keto</b>") + "\n\n" +
            L("Tez orada boshlanadi — kuzatib boring! 👀",
              "Скоро начнётся — следите за новостями! 👀")
        )
        return text, "", False, None, None, None

    since = state["started_at"]
    until = state["ends_at"]
    excluded = _excluded()
    board = await database.get_contest_leaderboard(since, until, excluded, limit=100_000)

    header = L("🏆 <b>Keto musobaqasi</b>", "🏆 <b>Конкурс Keto</b>")
    finished = state.get("winners_announced") or (not state["active"] and _now_utc() > until)

    if finished:
        status_line = L("🏁 Musobaqa yakunlandi. G'oliblar e'lon qilindi!",
                         "🏁 Конкурс завершён. Победители объявлены!")
        cta = ""
    else:
        status_line = _time_left_label(until, lang)
        cta = "\n\n" + L("💪 G'olib bo'lish uchun ko'proq do'stlaringizni taklif qiling!",
                          "💪 Чтобы стать победителем, приглашайте больше друзей!")

    intro_text = header + "\n" + status_line + cta

    rules = L(
        "📣 <b>Shartlar:</b> Pastdagi postni eng ko'p odamga yuboring — umumiy eng ko'p odam "
        "taklif qilgan ishtirokchilar sovg'alarga ega bo'lishadi. Jami <b>3 ta o'rin</b> mavjud.",
        "📣 <b>Условия:</b> Отправьте пост ниже как можно большему числу людей — участники, "
        "пригласившие больше всего человек, получат призы. Всего <b>3 призовых места</b>.",
    )

    medals = ["🥇 1-o'rin", "🥈 2-o'rin", "🥉 3-o'rin"] if lang != "ru" else ["🥇 1 место", "🥈 2 место", "🥉 3 место"]
    # Admin-entered prize text is itself multi-line (e.g. a set name + item
    # list + bonus line) — joined with a single "\n" the next place's medal
    # ran straight into the previous place's last line with no visible
    # break. A full blank line between entries keeps 1/2/3-o'rin visibly
    # separate (owner report 2026-08-01: "matnlari alohida ekani bilinsin").
    prize_entries = [
        f"{medal}: {prize}" if prize else f"{medal}: —"
        for medal, prize in zip(medals, [state.get("prize_1"), state.get("prize_2"), state.get("prize_3")])
    ]
    prize_lines = [L("🎁 <b>Sovg'alar:</b>", "🎁 <b>Призы:</b>"), "\n\n".join(prize_entries)]

    leaderboard = _build_window_leaderboard_text(board, user_id, lang)

    parts = [rules, "\n".join(prize_lines)]
    if not finished:
        # Owner request 2026-07-31: the link visible right in the post
        # itself, not only behind the share button — some people just
        # copy it directly instead of using the forward picker.
        link_block = L(
            f"🔗 Sizning shaxsiy havolangiz:\n{referral_link(user_id)}\n"
            "Do'stlaringizga yuboring va sovg'alarga ega bo'ling!",
            f"🔗 Ваша личная ссылка:\n{referral_link(user_id)}\n"
            "Отправьте друзьям и получите призы!",
        )
        parts.append(link_block)
    parts.append(leaderboard)
    detail_text = "\n\n".join(parts)

    prizes = [state.get("prize_1"), state.get("prize_2"), state.get("prize_3")]
    share_url = share_deeplink(user_id, lang, prizes) if not finished else None
    guide_video_file_id = state.get("guide_video_file_id")

    return intro_text, detail_text, not finished, _contest_media(state), share_url, guide_video_file_id


def build_share_text(user_id: int, lang: str, prizes: list[str | None] | None = None) -> str:
    """The ready-to-forward post: opens on a common frustration (nowhere to
    buy real keto products locally, or gaining weight back after diets),
    positions Ketoshop as the fix, then turns the contest into the reason to
    forward it right now. Deliberately plain-language — the audience skews
    older — but leads with a problem, not a feature list. Includes the actual
    prizes (owner request 2026-07-31) so whoever receives the forward sees
    what's at stake, not just that a contest exists."""
    L = lambda uz, ru: uz if lang != "ru" else ru
    link = referral_link(user_id)
    prize_block = _prize_block_plain(prizes or [], lang)
    prize_line = f"\n\n{prize_block}" if prize_block else ""
    return L(
        "😩 <b>Yana bir bor parhez boshladingiz-u, keto mahsulot topa olmay charchadingizmi?</b>\n\n"
        "Do'konlarda faqat oddiy un, oddiy shakar... Aslida esa O'zbekistondagi eng keng keto "
        "assortiment mahsulotlari bitta joyda — Ketoshop'da bor. 🥑\n\n"
        "🏆 Ustiga, hozir Keto musobaqasi ham davom etmoqda!" + prize_line + "\n\n"
        "Mening shaxsiy havolam orqali qo'shiling — Sizga sog'lom boshlanish, menga esa reytingda "
        "bir qadam yuqoriga chiqish imkoni. Ikkalamizga ham foyda! 🎁\n\n"
        f"👉 {link}",

        "😩 <b>Опять начали диету — и опять негде найти нормальные кето-продукты?</b>\n\n"
        "В обычных магазинах только белая мука и сахар... А самый широкий ассортимент "
        "кето-продуктов в Узбекистане — весь в одном месте, в Ketoshop. 🥑\n\n"
        "🏆 А ещё сейчас идёт конкурс Keto!" + prize_line + "\n\n"
        "Присоединяйтесь по моей личной ссылке — вам здоровый старт, а мне — шаг выше в "
        "рейтинге. Выгодно обоим! 🎁\n\n"
        f"👉 {link}",
    )


def _reminder_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🏆 Musobaqani ko'rish", callback_data="keto_contest"),
    ]])


# Daily reminder wording escalates in urgency as the contest runs down
# (owner request 2026-07-31: "xar safar yanada qiziqroq qilib yoz" — each one
# more engaging than the last) rather than rotating flat through one pool —
# the first half is a casual nudge, the back half leans into "the leaderboard
# is heating up", and the final couple of days go full urgency/FOMO. Within
# each tier there are still 2-3 variants so consecutive days in the same
# tier don't repeat either. Audience skews older, so language stays plain.
_REMINDER_TIERS: dict[str, list[tuple[str, str]]] = {
    "early": [
        (
            "🥑 <b>Keto musobaqasi davom etmoqda!</b>\n\n"
            "{days_left} kun qoldi. Do'stlaringizga xabar bering — Ketoshopning eng keng keto "
            "assortimentidan ular ham foydalansin!",
            "🥑 <b>Конкурс Keto продолжается!</b>\n\n"
            "Осталось {days_left} дн. Расскажите друзьям — пусть тоже узнают про самый широкий "
            "ассортимент кето-продуктов Ketoshop!",
        ),
        (
            "🏆 <b>Bugun kimnidir taklif qilishga nima deysiz?</b>\n\n"
            "Musobaqa hali {days_left} kun davom etadi — vaqt yetarli, lekin erta boshlagan "
            "ko'proq yutadi!",
            "🏆 <b>Как насчёт пригласить кого-нибудь сегодня?</b>\n\n"
            "Конкурс идёт ещё {days_left} дн. — времени хватает, но кто начал раньше, тот "
            "выигрывает больше!",
        ),
    ],
    "mid": [
        (
            "🔥 <b>Reyting qizib bormoqda!</b>\n\n"
            "{days_left} kun qoldi — hozir taklif qilganlar ertaga pushaymon bo'lmaydi. "
            "Sizniki qaysi o'rin bo'lmoqchi?",
            "🔥 <b>Рейтинг накаляется!</b>\n\n"
            "Осталось {days_left} дн. — кто приглашает сейчас, не пожалеет завтра. "
            "Какое место хотите занять?",
        ),
        (
            "🏆 <b>Yarim yo'l ortda qoldi!</b>\n\n"
            "{days_left} kun ichida yana bir necha do'stingizni taklif qilsangiz, reytingda "
            "sezilarli ko'tarilasiz.",
            "🏆 <b>Половина пути позади!</b>\n\n"
            "Пригласите ещё пару друзей за оставшиеся {days_left} дн. — и заметно "
            "подниметесь в рейтинге.",
        ),
    ],
    "late": [
        (
            "⏰ <b>Diqqat! Bor-yo'g'i {days_left} kun qoldi!</b>\n\n"
            "Musobaqa tugashiga oz qoldi — bugun taklif qiling, ertaga kech bo'lishi mumkin.",
            "⏰ <b>Внимание! Осталось всего {days_left} дн.!</b>\n\n"
            "До конца конкурса совсем немного — приглашайте сегодня, завтра может быть поздно.",
        ),
        (
            "🚨 <b>Oxirgi kunlar — {days_left} kun qoldi!</b>\n\n"
            "Sovg'alarga ega bo'lishning so'nggi imkoniyati. Hoziroq ulguring!",
            "🚨 <b>Последние дни — осталось {days_left} дн.!</b>\n\n"
            "Последний шанс получить приз. Успейте прямо сейчас!",
        ),
    ],
}


def _reminder_tier(days_left: int, days_total: int) -> str:
    if days_total <= 0:
        days_total = 1
    if days_left <= 2:
        return "late"
    if days_left / days_total <= 0.5:
        return "mid"
    return "early"


def _reminder_intro(lang: str, days_left: int, days_total: int, variant_idx: int) -> str:
    pool = _REMINDER_TIERS[_reminder_tier(days_left, days_total)]
    uz, ru = pool[variant_idx % len(pool)]
    text = uz if lang != "ru" else ru
    return text.format(days_left=days_left)


def _rank_gap_line(lang: str, board: list[dict], user_id: int) -> str:
    """Tells the user exactly how many more invites close the gap to the
    person directly above them — a concrete, personal reason to act today."""
    L = lambda uz, ru: uz if lang != "ru" else ru
    idx = next((i for i, r in enumerate(board) if r["user_id"] == user_id), None)
    if idx is None:
        if not board:
            return L("🚀 Hali hech kim ishtirok etmadi — birinchi bo'lib boshlang!",
                      "🚀 Пока никто не участвует — станьте первым!")
        return L("🚀 Hali ishtirok etmadingiz. Bugun birinchi do'stingizni taklif qiling va reytingga kiring!",
                  "🚀 Вы ещё не участвуете. Пригласите первого друга сегодня и войдите в рейтинг!")
    if idx == 0:
        return L("🥇 Siz hozir 1-o'rindasiz! Bu joyni mustahkamlash uchun yana taklif qiling.",
                  "🥇 Вы сейчас на 1-м месте! Приглашайте ещё, чтобы закрепить лидерство.")
    above, mine = board[idx - 1], board[idx]
    need = max(1, above["invites"] - mine["invites"] + 1)
    return L(f"📈 Yuqoridagi ishtirokchidan o'tish uchun yana {need} kishi taklif qiling!",
              f"📈 Чтобы обойти участника выше, пригласите ещё {need} чел.!")


def _forward_line(lang: str) -> str:
    if lang == "ru":
        return "📤 Отправьте сообщение ниже как можно большему числу людей!"
    return "📤 Pastdagi xabarni iloji boricha ko'proq odamga jo'nating!"


async def _safe_send(send_coro) -> None:
    """Send once; on a flood-wait, sleep and retry exactly once. Other
    exceptions (forbidden, bad request, ...) propagate to the caller."""
    try:
        await send_coro()
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after + 1)
        await send_coro()


async def _send_daily_reminder(bot: Bot, state: dict) -> None:
    days_left = max(0, (state["ends_at"] - _now_utc()).days)
    days_total = max(1, (state["ends_at"] - state["started_at"]).days)
    day_number = max(0, (_now_tk().date() - (state["started_at"] + TZ_OFFSET).date()).days)
    excluded = _excluded()
    board = await database.get_contest_leaderboard(state["started_at"], state["ends_at"], excluded, limit=100_000)
    user_ids = await database.get_all_user_ids()
    kb = _reminder_keyboard()
    media = _contest_media(state)
    prizes = [state.get("prize_1"), state.get("prize_2"), state.get("prize_3")]
    sent = failed = 0
    for uid in user_ids:
        if uid in excluded:
            continue
        # Per-user language throughout — everyone gets this in their own
        # saved bot language (uz/uz_cyr/ru), not a single site-wide default.
        lang = await database.get_user_language(uid)
        # CTA and the "how many to pass the person above you" nudge are two
        # separate messages on purpose (owner request 2026-07-31: the rank
        # gap goes "faqat bu alohida xabarda" — only in its own message),
        # not mixed into the intro or the forwardable post below it.
        caption = _reminder_intro(lang, days_left, days_total, day_number)
        rank_gap = _rank_gap_line(lang, board, uid)
        share_msg = _forward_line(lang) + "\n\n" + build_share_text(uid, lang, prizes)
        try:
            if media and media[0] == "video":
                await _safe_send(lambda: bot.send_video(uid, media[1], caption=caption, parse_mode=ParseMode.HTML, reply_markup=kb))
            elif media and media[0] == "tg_photo":
                await _safe_send(lambda: bot.send_photo(uid, media[1], caption=caption, parse_mode=ParseMode.HTML, reply_markup=kb))
            elif media and media[0] == "photo" and WEBAPP_URL:
                photo_url = f"{WEBAPP_URL}{media[1]}"
                await _safe_send(lambda: bot.send_photo(uid, photo_url, caption=caption, parse_mode=ParseMode.HTML, reply_markup=kb))
            else:
                await _safe_send(lambda: bot.send_message(uid, caption, parse_mode=ParseMode.HTML, reply_markup=kb))
            await _safe_send(lambda: bot.send_message(uid, rank_gap, parse_mode=ParseMode.HTML))
            await _safe_send(lambda: bot.send_message(uid, share_msg, parse_mode=ParseMode.HTML))
            sent += 1
        except (TelegramForbiddenError, TelegramBadRequest):
            failed += 1
        except Exception:
            logger.exception("Contest reminder failed for user %s", uid)
            failed += 1
        await asyncio.sleep(SEND_DELAY)
    logger.info("Contest daily reminder sent: %d ok, %d failed", sent, failed)
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"📤 Musobaqa eslatmasi yuborildi.\n✅ {sent} ta yetkazildi, ⚠️ {failed} ta yetmadi.\n"
                f"📅 Yakunlanishiga {days_left} kun qoldi.",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass


async def _finish_contest(bot: Bot, state: dict) -> None:
    """Contest window is over: compute the top 3, tell the admins, publicly
    congratulate the winners, and DM each winner their placement + prize
    text. Prize *fulfillment* (contacting winners, sending gifts) is the
    owner's own follow-up — this only announces results."""
    since, until = state["started_at"], state["ends_at"]
    excluded = _excluded()
    top3 = await database.get_contest_leaderboard(since, until, excluded, limit=3)
    await database.mark_contest_finished()

    prizes = [state.get("prize_1"), state.get("prize_2"), state.get("prize_3")]
    medals = ["🥇", "🥈", "🥉"]

    if not top3:
        admin_msg = "🏁 <b>Keto musobaqasi yakunlandi.</b>\nAfsuski, hech kim ishtirok etmadi."
    else:
        lines = ["🏁 <b>Keto musobaqasi yakunlandi! G'oliblar:</b>"]
        for i, r in enumerate(top3):
            name = _display_name(r.get("username"), r.get("full_name"), r["user_id"])
            lines.append(f"{medals[i]} {name} (ID {r['user_id']}) — {r['invites']} kishi taklif qildi. Sovg'a: {prizes[i] or '—'}")
        admin_msg = "\n".join(lines)
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, admin_msg, parse_mode=ParseMode.HTML)
        except Exception:
            pass

    if not top3:
        return

    # Public results broadcast.
    public_lines_uz = ["🏆 <b>Keto musobaqasi yakunlandi!</b>", "", "G'oliblar:"]
    public_lines_ru = ["🏆 <b>Конкурс Keto завершён!</b>", "", "Победители:"]
    for i, r in enumerate(top3):
        name = _display_name(r.get("username"), r.get("full_name"), r["user_id"])
        public_lines_uz.append(f"{medals[i]} {name} — {r['invites']} kishi taklif qildi")
        public_lines_ru.append(f"{medals[i]} {name} — пригласил(а) {r['invites']} чел.")
    public_lines_uz.append("\nG'olib bo'lganlarga tabriklar! 🎉 Barchaga ishtirok etganingiz uchun rahmat.")
    public_lines_ru.append("\nПоздравляем победителей! 🎉 Спасибо всем за участие.")

    excluded_all = excluded
    for uid in await database.get_all_user_ids():
        if uid in excluded_all:
            continue
        lang = await database.get_user_language(uid)
        text = "\n".join(public_lines_uz if lang != "ru" else public_lines_ru)
        try:
            await bot.send_message(uid, text, parse_mode=ParseMode.HTML)
        except Exception:
            pass
        await asyncio.sleep(SEND_DELAY)

    # Individual congrats to each winner with their prize text.
    for i, r in enumerate(top3):
        lang = await database.get_user_language(r["user_id"])
        L = lambda uz, ru: uz if lang != "ru" else ru
        text = (
            L(f"🎉 <b>Tabriklaymiz! Siz Keto musobaqasida {i + 1}-o'rinni egalladingiz!</b>",
              f"🎉 <b>Поздравляем! Вы заняли {i + 1}-е место в конкурсе Keto!</b>") + "\n\n" +
            L(f"🎁 Sovg'angiz: <b>{prizes[i] or '—'}</b>", f"🎁 Ваш приз: <b>{prizes[i] or '—'}</b>") + "\n" +
            L("Tez orada admin siz bilan bog'lanadi.", "Скоро с вами свяжется администратор.")
        )
        try:
            await bot.send_message(r["user_id"], text, parse_mode=ParseMode.HTML)
        except Exception:
            pass


async def _tick(bot: Bot) -> None:
    state = await database.get_referral_contest_state()
    if not state["active"] or not state.get("ends_at"):
        return

    if _now_utc() >= state["ends_at"]:
        await _finish_contest(bot, state)
        return

    now_tk = _now_tk()
    already_today = state.get("last_reminder_date") == now_tk.date()
    if not already_today and now_tk.hour >= REMINDER_HOUR:
        await _send_daily_reminder(bot, state)
        await database.set_contest_reminder_date(now_tk.date())


async def scheduler_loop(bot: Bot) -> None:
    logger.info("Keto musobaqasi scheduler started")
    while True:
        try:
            await _tick(bot)
        except Exception:
            logger.exception("Keto musobaqasi tick failed")
        await asyncio.sleep(CHECK_EVERY)
