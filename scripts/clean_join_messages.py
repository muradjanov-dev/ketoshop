"""
Guruhdagi ESKI "X guruhga qo'shildi" xabarlarini tozalash — bir martalik
(egasi so'rovi 2026-10-08).

Yangilarini bot o'zi o'chiradi (link_guard.py). Eskilarini bot o'chira
olmaydi: Telegram botga guruh tarixini bermaydi. Shuning uchun bu skript
guruh ADMININING shaxsiy akkaunti bilan ishlaydi (Telethon) — egasining
kompyuterida, serverda emas. Akkauntda "Xabarlarni o'chirish" huquqi bo'lishi
shart.

Ishga tushirish:
    1) pip install telethon
    2) https://my.telegram.org → API development tools → api_id va api_hash
    3) python scripts/clean_join_messages.py --dry-run   # faqat sanaydi
       python scripts/clean_join_messages.py             # sanaydi, so'raydi, o'chiradi

Telefon raqam va Telegram yuborgan kod so'raladi. Sessiya diskka yozilmaydi
va oxirida akkauntdan chiqiladi — kompyuterda hech qanday kirish izi qolmaydi.

Guruh o'zi topiladi: @ketoshop_uz kanaliga ulangan muhokama guruhi. Boshqa
guruh uchun: --group <username yoki -100... id>.
"""
import argparse
import asyncio
import os
import sys

try:
    from telethon import TelegramClient, functions, types
    from telethon.sessions import StringSession
except ImportError:
    sys.exit("Avval o'rnating:  pip install telethon")

CHANNEL = os.getenv("REQUIRED_CHANNEL_USERNAME", "ketoshop_uz")
JOIN_ACTIONS = (
    types.MessageActionChatAddUser,        # qo'shildi / admin qo'shdi
    types.MessageActionChatJoinedByLink,   # havola orqali qo'shildi
    types.MessageActionChatJoinedByRequest,  # so'rov tasdiqlanib qo'shildi
)


async def _find_group(client, group_arg):
    if group_arg:
        target = int(group_arg) if group_arg.lstrip("-").isdigit() else group_arg
        return await client.get_entity(target)
    channel = await client.get_entity(CHANNEL)
    full = await client(functions.channels.GetFullChannelRequest(channel))
    linked_id = full.full_chat.linked_chat_id
    if not linked_id:
        sys.exit(f"@{CHANNEL} kanaliga guruh ulanmagan. --group bilan ko'rsating.")
    for chat in full.chats:
        if chat.id == linked_id:
            return chat
    return await client.get_entity(types.PeerChannel(linked_id))


async def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--dry-run", action="store_true", help="faqat sanash, o'chirmaslik")
    parser.add_argument("--group", help="guruh username yoki id (standart: kanalga ulangan guruh)")
    args = parser.parse_args()

    api_id = os.getenv("TG_API_ID") or input("api_id: ").strip()
    api_hash = os.getenv("TG_API_HASH") or input("api_hash: ").strip()

    client = TelegramClient(StringSession(), int(api_id), api_hash)
    await client.start()
    try:
        group = await _find_group(client, args.group)
        print(f"Guruh: {getattr(group, 'title', group.id)}  — tarix ko'rib chiqilmoqda...")

        ids, scanned = [], 0
        async for message in client.iter_messages(group):
            scanned += 1
            if isinstance(getattr(message, "action", None), JOIN_ACTIONS):
                ids.append(message.id)
            if scanned % 2000 == 0:
                print(f"  {scanned} ta xabar ko'rildi, {len(ids)} ta 'qo'shildi' topildi")
        print(f"Jami: {scanned} ta xabar, ulardan {len(ids)} tasi 'qo'shildi' xabari.")

        if not ids or args.dry_run:
            return
        if input(f"{len(ids)} ta xabar o'chirilsinmi? (ha/yo'q): ").strip().lower() not in ("ha", "h", "yes", "y"):
            print("Bekor qilindi.")
            return
        try:
            await client.delete_messages(group, ids)
        except Exception as exc:
            sys.exit(f"O'chirib bo'lmadi ({exc}). Akkaunt guruhda 'Xabarlarni o'chirish' "
                     "huquqli adminmi?")
        print(f"Tayyor: {len(ids)} ta 'qo'shildi' xabari o'chirildi.")
    finally:
        await client.log_out()


if __name__ == "__main__":
    asyncio.run(main())
