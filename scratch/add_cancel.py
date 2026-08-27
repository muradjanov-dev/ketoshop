import re

with open('handlers/admin.py', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace(
    'admin_panel_keyboard, admin_order_filter_keyboard, admin_stats_keyboard,',
    'admin_panel_keyboard, admin_cancel_keyboard, admin_order_filter_keyboard, admin_stats_keyboard,'
)

content = content.replace(
    '@router.callback_query(F.data == "admin_panel")\nasync def show_admin_panel(callback: CallbackQuery):',
    '@router.callback_query(F.data == "admin_panel")\nasync def show_admin_panel(callback: CallbackQuery, state: FSMContext = None):\n    if state:\n        await state.clear()'
)

# b2b_eritritol_start already uses edit_text without keyboard in the beginning of flow
# Wait, b2b_eritritol_start has:
# await callback.message.edit_text(
#     get_text("b2b_eritritol_address", lang),
#     parse_mode="HTML",
# )
content = content.replace(
    'get_text("b2b_eritritol_address", lang),\n        parse_mode="HTML",\n    )',
    'get_text("b2b_eritritol_address", lang),\n        parse_mode="HTML",\n        reply_markup=admin_cancel_keyboard(lang)\n    )'
)

def add_kbd(match):
    prefix = match.group(1)
    if 'reply_markup' in prefix:
        return match.group(0)
    return prefix + ', reply_markup=admin_cancel_keyboard(lang))'

content = re.sub(r'(await message\.answer\(get_text\("b2b_eritritol_[a-z]+", lang\))\)', add_kbd, content)
content = re.sub(r'(await message\.answer\(get_text\("manual_[a-z_]+", lang\))\)', add_kbd, content)

with open('handlers/admin.py', 'w', encoding='utf-8') as f:
    f.write(content)
