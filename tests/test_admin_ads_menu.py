"""Admin panel → «📣 Reklama va havolalar» (egasi, 2026-11-08: "/reklama bunday
yozishni bilmaydiganlar uchun admin panelda tushunarli qilib tugmalar ham
qo'sh"). Telegram mock — hech qanday haqiqiy so'rov yuborilmaydi."""
import asyncio
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import admin_ads_menu as menu
import keyboards

ADMIN = 4242


def run(coro):
    return asyncio.run(coro)


def datas(kb):
    return [b.callback_data for row in kb.inline_keyboard for b in row if b.callback_data]


class _State:
    def __init__(self):
        self.state, self.cleared = None, False

    async def set_state(self, s):
        self.state = s

    async def clear(self):
        self.cleared, self.state = True, None


def callback(data):
    cb = MagicMock()
    cb.data = data
    cb.from_user.id = ADMIN
    cb.answer = AsyncMock()
    cb.message.answer = AsyncMock()
    return cb


class MenuTest(unittest.TestCase):
    def test_reachable_from_the_admin_panel(self):
        self.assertIn("admin_menu:ads", datas(keyboards.admin_panel_keyboard("uz")))

    def test_every_ad_command_has_a_button(self):
        got = datas(keyboards.admin_ads_menu_keyboard("uz"))
        for data in ("ads:today", "ads:yesterday", "ads:last_7d",         # /reklama [kecha|7]
                     "adm_ads:holat",                                      # /reklama_holat
                     "adm_ads:bog",                                        # /reklama_bog
                     "shoplnk:30",                                         # /sayt_havolalar
                     "adm_ads:newlink",                                    # /sayt_havola
                     "adsrc:30",                                           # /reklama_manba
                     "adm_ads:leads",                                      # /leads
                     "adm_ads:token"):                                     # /reklama_token
            self.assertIn(data, got)
        self.assertIn("admin_panel", got)

    def test_stats_menu_button_does_not_promise_a_calendar_day(self):
        # Meta's day runs 13:00–13:00 Tashkent — «(bugun)» on the button misled (owner, 2026-11-08).
        texts = [b.text for row in keyboards.admin_stats_menu_keyboard("uz").inline_keyboard for b in row]
        self.assertIn("📣 Reklama natijalari", texts)
        self.assertFalse([t for t in texts if "(bugun)" in t])

    def test_reports_lead_back_to_the_menu(self):
        import ad_sources
        import meta_ads
        import shop_links
        with patch("ads_impact.view_rows", return_value=[]):
            self.assertIn("admin_menu:ads", datas(meta_ads._period_keyboard("today")))
        self.assertIn("admin_menu:ads", datas(shop_links._period_keyboard("30")))
        self.assertIn("adm_ads:newlink", datas(shop_links._period_keyboard("30")))
        self.assertIn("admin_menu:ads", datas(ad_sources._period_keyboard("30")))

    def test_submenu_opens(self):
        from handlers import admin
        cb = callback("admin_menu:ads")
        cb.message.edit_text = AsyncMock()
        with patch.object(admin, "is_admin", return_value=True), \
             patch.object(admin, "get_user_language", AsyncMock(return_value="uz")):
            run(admin.show_admin_submenu(cb, MagicMock()))
        self.assertIn("adm_ads:holat", datas(cb.message.edit_text.await_args.kwargs["reply_markup"]))


class ActionTest(unittest.TestCase):
    def go(self, data, admin=True, **patches):
        cb = callback(data)
        st = _State()
        ctx = [patch.object(menu, "ADMIN_IDS", [ADMIN] if admin else [])]
        for target, value in patches.items():
            ctx.append(patch(target.replace("__", "."), value))
        for c in ctx:
            c.start()
        try:
            run(menu.cb_menu(cb, st))
        finally:
            for c in ctx:
                c.stop()
        return cb, st

    def test_campaign_links_table(self):
        cb, _ = self.go("adm_ads:bog", ad_campaigns__links_text=AsyncMock(return_value="TABLE"))
        self.assertEqual(cb.message.answer.await_args.args[0], "TABLE")
        self.assertIn("admin_menu:ads", datas(cb.message.answer.await_args.kwargs["reply_markup"]))

    def test_status_without_a_token_says_how_to_add_one(self):
        cb, _ = self.go("adm_ads:holat", meta_ads__is_enabled=MagicMock(return_value=False),
                        meta_ads__load_token=AsyncMock())
        self.assertIn("/reklama_token", cb.message.answer.await_args.args[0])

    def test_status_per_account(self):
        cb, _ = self.go("adm_ads:holat", meta_ads__is_enabled=MagicMock(return_value=True),
                        meta_ads__status_texts=AsyncMock(return_value=["A", "B"]))
        self.assertEqual([c.args[0] for c in cb.message.answer.await_args_list], ["A", "B"])
        self.assertIsNotNone(cb.message.answer.await_args_list[-1].kwargs["reply_markup"])

    def test_leads(self):
        cb, _ = self.go("adm_ads:leads", meta_leads__recent_text=AsyncMock(return_value="LEADS"))
        self.assertEqual(cb.message.answer.await_args.args[0], "LEADS")

    def test_token_status_offers_sending_one(self):
        cb, _ = self.go("adm_ads:token", meta_ads__token_status_text=AsyncMock(return_value="TOKEN"))
        self.assertIn("adm_ads:token_send", datas(cb.message.answer.await_args.kwargs["reply_markup"]))

    def test_trouble_is_reported_not_raised(self):
        cb, _ = self.go("adm_ads:leads", meta_leads__recent_text=AsyncMock(side_effect=RuntimeError("db")))
        self.assertIn("❌", cb.message.answer.await_args.args[0])

    def test_not_for_buyers(self):
        cb, st = self.go("adm_ads:newlink", admin=False)
        cb.message.answer.assert_not_awaited()
        self.assertIsNone(st.state)


class FlowTest(unittest.TestCase):
    def message(self, text):
        m = MagicMock()
        m.text = text
        m.from_user.id = ADMIN
        m.answer = AsyncMock()
        return m

    def test_new_link_asks_the_name_then_makes_it(self):
        cb = callback("adm_ads:newlink")
        st = _State()
        with patch.object(menu, "ADMIN_IDS", [ADMIN]):
            run(menu.cb_menu(cb, st))
        self.assertEqual(st.state, menu.AdsMenuStates.link_name)
        m = self.message("Chia urug'i")
        with patch.object(menu, "ADMIN_IDS", [ADMIN]), \
             patch("shop_links.create", AsyncMock(return_value=("chia_urugi", "Chia urug'i", True))) as create:
            run(menu.got_link_name(m, st))
        create.assert_awaited_once_with("Chia urug'i", ADMIN)
        self.assertIn("?start=chia_urugi", m.answer.await_args.args[0])
        self.assertTrue(st.cleared)

    def test_unusable_name_is_asked_again(self):
        st = _State()
        st.state = menu.AdsMenuStates.link_name
        m = self.message("!!!")
        with patch.object(menu, "ADMIN_IDS", [ADMIN]), patch("shop_links.create", AsyncMock(return_value=None)):
            run(menu.got_link_name(m, st))
        self.assertFalse(st.cleared)                                   # still waiting for a name
        self.assertIn("boshqa nom", m.answer.await_args.args[0])

    def test_token_goes_through_the_same_check_and_delete(self):
        st = _State()
        m = self.message("  EAAtoken123  ")
        with patch.object(menu, "ADMIN_IDS", [ADMIN]), patch("meta_ads.apply_token", AsyncMock()) as apply:
            run(menu.got_token(m, st))
        apply.assert_awaited_once_with(m, "EAAtoken123")
        self.assertTrue(st.cleared)


if __name__ == "__main__":
    unittest.main()
