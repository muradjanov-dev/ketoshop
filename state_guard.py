"""
Clears any in-progress FSM "waiting for X" state whenever the user sends a
slash command — owner complaint, 2026-08-12: a buyer stuck mid-checkout
(bot waiting for a phone number) typed "/admin" and got "invalid phone
number, try again" instead of the admin panel, trapping them in the stale
flow with no way out. A command is always a deliberate "start something
new" signal, so it must never be swallowed as an answer to whatever the bot
last asked — see also handlers/start.py's cmd_start/show_main_menu, which
clear state the same way for the "🏠 Asosiy menyu" button.

Registered as an outer middleware on dp.message (see bot.py), ahead of every
router, so the state is already gone by the time routers try to match the
command.
"""
from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject


class StateResetOnCommandMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data: dict):
        if isinstance(event, Message) and (event.text or "").startswith("/"):
            state = data.get("state")
            if state is not None and await state.get_state() is not None:
                await state.clear()
        return await handler(event, data)
