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

# Commands that ANSWER the current step instead of starting something new.
# These must survive the reset below, or the flow that offered them can never
# see them: a wizard prompting "rasm yuboring yoki /skip" would have its state
# cleared by this middleware and the /skip would fall through to nothing
# (2026-08-31 — found while adding the aksiya wizard's optional photo step).
STEP_COMMANDS = {"/skip", "/cancel"}


class StateResetOnCommandMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data: dict):
        if isinstance(event, Message):
            text = (event.text or "").strip()
            # "/skip@BotName" is the same command in a group context.
            base = text.split()[0].split("@")[0].lower() if text else ""
            if text.startswith("/") and base not in STEP_COMMANDS:
                state = data.get("state")
                if state is not None and await state.get_state() is not None:
                    await state.clear()
        return await handler(event, data)
