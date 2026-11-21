"""📞 Call Centre CRM (egasi, 2026-11-22) — KPI qoidalari PDF misollari bilan,
salyut chegaralari, forma tekshiruvi, rollar va kirish huquqi. Bazaga va
Telegram'ga ulanmaydi."""
import asyncio
import os
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import call_centre as cc
import call_centre_bot as ccb
import call_centre_content as content
from config import ADMIN_IDS, OPERATOR_IDS

S = dict(cc.DEFAULT_SETTINGS)


def run(coro):
    return asyncio.run(coro)


class KpiTest(unittest.TestCase):
    def test_pdf_examples(self):
        self.assertEqual(cc.kpi_points(594, 660, 30), 27)
        self.assertEqual(cc.kpi_points(99, 110, 50), 45)
        self.assertEqual(cc.kpi_points(1584, 1760, 10), 9)

    def test_points_never_exceed_the_weight(self):
        self.assertEqual(cc.kpi_points(5000, 1760, 10), 10)
        self.assertEqual(cc.kpi_points(3, 0, 10), 0)

    def test_monthly_targets_from_daily_plan(self):
        self.assertEqual(cc.monthly_targets(S), {"outbound": 1760, "meaningful": 660, "orders": 110})

    def test_bonus_tiers(self):
        self.assertEqual(cc.kpi_bonus(69.9), 0)
        self.assertEqual(cc.kpi_bonus(70), 500_000)
        self.assertEqual(cc.kpi_bonus(85), 750_000)
        self.assertEqual(cc.kpi_bonus(90), 1_000_000)
        self.assertEqual(cc.kpi_bonus(100), 1_000_000)

    def test_summary_adds_up(self):
        k = cc.kpi_summary({"meaningful": 594, "orders": 99, "outbound": 1584}, S, 9)
        self.assertEqual(k["total"], 27 + 45 + 9 + 9)
        self.assertEqual(k["bonus"], 1_000_000)
        unrated = cc.kpi_summary({"meaningful": 594, "orders": 99, "outbound": 1584}, S, None)
        self.assertEqual(unrated["total"], 81)
        self.assertFalse(unrated["crm_rated"])

    def test_commission_tiers_and_unapproved_plan(self):
        self.assertIsNone(cc.commission_rate(None))
        self.assertEqual(cc.commission_rate(69), 0)
        self.assertEqual(cc.commission_rate(70), 1.0)
        self.assertEqual(cc.commission_rate(95), 1.5)
        self.assertEqual(cc.commission_rate(100), 2.0)
        self.assertEqual(cc.commission_rate(120), 2.5)

    def test_pdf_commission_example(self):
        e = cc.earnings(S, 1_000_000, ["asoslar", "un", "nonsense"], 33_068_349, 27_000_000)
        self.assertEqual(e["commission_rate"], 2.5)
        self.assertEqual(e["commission"], 826_709)
        self.assertEqual(e["knowledge_bonus"], 200_000)
        self.assertEqual(e["total"], 3_500_000 + 1_000_000 + 200_000 + 826_709)

    def test_no_commission_until_plan_is_approved(self):
        e = cc.earnings(S, 0, [], 10_000_000, None)
        self.assertIsNone(e["commission_rate"])
        self.assertEqual(e["commission"], 0)
        self.assertEqual(e["total"], 3_500_000)

    def test_meaningful_needs_both_tick_and_30_seconds(self):
        self.assertTrue(cc.is_meaningful(30, True))
        self.assertFalse(cc.is_meaningful(29, True))
        self.assertFalse(cc.is_meaningful(300, False))

    def test_month_range_is_tashkent_days(self):
        start, end = cc.month_range_utc("2026-12")
        self.assertEqual(start, datetime(2026, 11, 30, 19))
        self.assertEqual(end, datetime(2026, 12, 31, 19))
        self.assertIsNone(cc.valid_month("2026-13"))
        self.assertEqual(cc.valid_month("2026-1"), "2026-01")


class MilestoneTest(unittest.TestCase):
    def test_small_steps_then_goal(self):
        out = cc.crossed_milestones({"outbound": 9}, {"outbound": 10}, S)
        self.assertEqual([(c["kind"], c["value"]) for c in out], [("small", 10)])
        out = cc.crossed_milestones({"outbound": 79}, {"outbound": 80}, S)
        self.assertEqual([(c["kind"], c["value"]) for c in out], [("goal", 80)])

    def test_nothing_when_count_does_not_grow(self):
        self.assertEqual(cc.crossed_milestones({"outbound": 12}, {"outbound": 12}, S), [])
        self.assertEqual(cc.crossed_milestones({"orders": 2}, {"orders": 1}, S), [])

    def test_first_sale_and_records_after_the_plan(self):
        self.assertEqual(cc.crossed_milestones({"orders": 0}, {"orders": 1}, S)[0]["kind"], "small")
        rec = cc.crossed_milestones({"orders": 5}, {"orders": 6}, S)
        self.assertEqual([(c["kind"], c["value"]) for c in rec], [("record", 6)])

    def test_certificate_once_all_three_goals_are_met(self):
        before = {"outbound": 80, "meaningful": 30, "orders": 4}
        after = {"outbound": 80, "meaningful": 30, "orders": 5}
        kinds = [c["kind"] for c in cc.crossed_milestones(before, after, S)]
        self.assertEqual(kinds, ["goal", "certificate"])
        again = cc.crossed_milestones(after, dict(after, orders=6), S)
        self.assertNotIn("certificate", [c["kind"] for c in again])


class ParseCallTest(unittest.TestCase):
    def base(self, **kw):
        b = {"call_type": "out", "status": "declined", "duration_sec": 45, "meaningful": True,
             "phone": "90 123 45 67", "customer_name": "  Ali  "}
        b.update(kw)
        return b

    def test_clean_record(self):
        f, err = cc.parse_call(self.base())
        self.assertIsNone(err)
        self.assertEqual(f["phone"], "+998901234567")
        self.assertEqual(f["customer_name"], "Ali")
        self.assertTrue(f["meaningful"])

    def test_rules(self):
        self.assertEqual(cc.parse_call(self.base(call_type="x"))[1], "Qo'ng'iroq turini tanlang")
        self.assertEqual(cc.parse_call(self.base(status=None))[1], "Natijani tanlang")
        self.assertIn("Telefon", cc.parse_call(self.base(phone="123"))[1])
        self.assertIn("sana", cc.parse_call(self.base(status="followup"))[1])
        self.assertIn("Sotuv", cc.parse_call(self.base(status="sold"))[1])
        f, err = cc.parse_call(self.base(status="sold", order_id="#42"))
        self.assertIsNone(err)
        self.assertEqual(f["order_id"], 42)
        f, _ = cc.parse_call(self.base(status="followup", follow_up_on="2026-11-23"))
        self.assertEqual(f["follow_up_on"], date(2026, 11, 23))
        f, _ = cc.parse_call(self.base(duration_sec=10))
        self.assertFalse(f["meaningful"])

    def test_crm_fill(self):
        calls = [{"status": "no_answer"},
                 {"status": "declined", "customer_name": "A", "phone": "+998901234567"},
                 {"status": "sold", "customer_name": "B", "phone": "+998901234568"},
                 {"status": "followup", "customer_name": "C", "phone": "+998901234569",
                  "follow_up_on": "2026-11-23"}]
        self.assertEqual(cc.crm_fill_percent(calls), 67)
        self.assertEqual(cc.crm_fill_percent([]), 100)


class AccessTest(unittest.TestCase):
    def setUp(self):
        self._admins, self._ops = list(ADMIN_IDS), list(OPERATOR_IDS)

    def tearDown(self):
        ADMIN_IDS[:] = self._admins
        OPERATOR_IDS[:] = self._ops

    def req(self, header="tma x", query=None):
        r = MagicMock()
        r.headers = {"Authorization": header} if header else {}
        r.query = query or {}
        return r

    def test_roles(self):
        OPERATOR_IDS[:] = [555]
        self.assertEqual(cc.role_of(ADMIN_IDS[0]), "admin")
        self.assertEqual(cc.role_of(555), "operator")
        self.assertIsNone(cc.role_of(777))

    def test_buyer_is_forbidden_and_app_initdata_rejected(self):
        OPERATOR_IDS[:] = [555]
        with patch("webapp_server._validate_init_data", return_value={"user": {"id": 777}}) as v:
            self.assertEqual(cc._auth(self.req()).status, 403)
            self.assertFalse(v.call_args.kwargs["allow_app"])
        with patch("webapp_server._validate_init_data", return_value=None):
            self.assertEqual(cc._auth(self.req()).status, 401)
        self.assertEqual(cc._auth(self.req(header=None)).status, 401)
        with patch("webapp_server._validate_init_data", return_value={"user": {"id": 555}}):
            self.assertEqual(cc._auth(self.req())[:2], (555, "operator"))

    def test_operator_only_sees_self(self):
        OPERATOR_IDS[:] = [555, 556]
        self.assertEqual(cc._target(self.req(query={"operator": "556"}), 555, "operator"), 555)
        self.assertEqual(cc._target(self.req(query={"operator": "556"}), ADMIN_IDS[0], "admin"), 556)
        self.assertEqual(cc._target(self.req(query={"operator": "999"}), ADMIN_IDS[0], "admin").status, 404)

    def test_role_switch_moves_between_lists(self):
        OPERATOR_IDS[:] = []
        ccb._sync_lists(900, "operator")
        self.assertIn(900, OPERATOR_IDS)
        self.assertNotIn(900, ADMIN_IDS)
        ccb._sync_lists(900, "admin")
        self.assertIn(900, ADMIN_IDS)
        self.assertNotIn(900, OPERATOR_IDS)
        ccb._sync_lists(900, None)
        self.assertNotIn(900, ADMIN_IDS + OPERATOR_IDS)

    def test_apply_role_writes_db_and_commands(self):
        OPERATOR_IDS[:] = []
        bot = MagicMock(set_my_commands=AsyncMock(), send_message=AsyncMock())
        with patch.object(ccb.database, "add_admin_db", AsyncMock()) as add:
            run(ccb.apply_role(bot, 901, "operator", ADMIN_IDS[0]))
        add.assert_awaited_once_with(901, ADMIN_IDS[0], "operator")
        self.assertIn(901, OPERATOR_IDS)
        cmds = bot.set_my_commands.call_args.args[0]
        self.assertIn("callcentre", [c.command for c in cmds])
        self.assertNotIn("admin", [c.command for c in cmds])


class AdminRoleHandlersTest(unittest.TestCase):
    def setUp(self):
        self._admins, self._ops = list(ADMIN_IDS), list(OPERATOR_IDS)
        from handlers import admin
        self.admin = admin
        self.me = ADMIN_IDS[0]

    def tearDown(self):
        ADMIN_IDS[:] = self._admins
        OPERATOR_IDS[:] = self._ops

    def cb(self, data):
        c = MagicMock(data=data, answer=AsyncMock())
        c.from_user.id = self.me
        return c

    def call(self, handler, data):
        cb = self.cb(data)
        bot = MagicMock(send_message=AsyncMock())
        with patch("call_centre_bot.apply_role", AsyncMock()) as apply, \
             patch.object(self.admin, "_render_admin_list", AsyncMock(return_value=("t", None))), \
             patch.object(self.admin, "_support_show", AsyncMock()), \
             patch.object(self.admin, "_admin_name", AsyncMock(return_value="X")):
            run(handler(cb, bot))
        return cb, apply

    def test_permanent_admin_and_self_cannot_be_changed(self):
        permanent = next(iter(self.admin.PERMANENT_ADMIN_IDS))
        for target in (permanent, self.me):
            cb, apply = self.call(self.admin.admin_set_role, f"admin:setrole:{target}:operator")
            apply.assert_not_awaited()
            self.assertTrue(cb.answer.call_args.kwargs.get("show_alert"))

    def test_admin_becomes_operator(self):
        ADMIN_IDS.append(4242)
        cb, apply = self.call(self.admin.admin_set_role, "admin:setrole:4242:operator")
        apply.assert_awaited_once()
        self.assertEqual(apply.call_args.args[1:], (4242, "operator", self.me))

    def test_add_new_operator(self):
        cb, apply = self.call(self.admin.admin_add_with_role, "admin:addrole:4343:operator")
        self.assertEqual(apply.call_args.args[1:], (4343, "operator", self.me))
        cb, apply = self.call(self.admin.admin_add_with_role, "admin:addrole:4343:root")
        apply.assert_not_awaited()


class LeadStateTest(unittest.TestCase):
    NOW = datetime(2026, 11, 22, 8, 0)          # 13:00 Toshkent

    def test_never_contacted_is_stale(self):
        self.assertEqual(cc.lead_state(None, None, self.NOW), {"idle_days": None, "stale": True})

    def test_thirty_days_without_any_action_is_stale(self):
        last = self.NOW - timedelta(days=31)
        self.assertEqual(cc.lead_state(last, last, self.NOW), {"idle_days": 31, "stale": True})
        last = self.NOW - timedelta(days=20)
        self.assertEqual(cc.lead_state(last, None, self.NOW), {"idle_days": 20, "stale": False})

    def test_answered_rests_14_days(self):
        last = self.NOW - timedelta(days=5)
        self.assertIsNone(cc.lead_state(last, last, self.NOW))
        last = self.NOW - timedelta(days=15)
        self.assertEqual(cc.lead_state(last, last, self.NOW)["stale"], False)

    def test_no_answer_hides_only_until_tomorrow(self):
        this_morning = datetime(2026, 11, 22, 4, 30)      # 09:30 Toshkent
        self.assertIsNone(cc.lead_state(this_morning, None, self.NOW))
        yesterday = datetime(2026, 11, 21, 12, 0)
        self.assertEqual(cc.lead_state(yesterday, None, self.NOW), {"idle_days": 0, "stale": False})


class UndoRightsTest(unittest.TestCase):
    TODAY = date(2026, 11, 22)

    def call(self, op=5, day="2026-11-22"):
        return {"operator_id": op, "called_at_local": day + "T10:00"}

    def test_operator_only_own_today(self):
        self.assertIsNone(cc.can_touch(self.call(), 5, "operator", self.TODAY))
        self.assertIn("bugungi", cc.can_touch(self.call(op=6), 5, "operator", self.TODAY))
        self.assertIn("bugungi", cc.can_touch(self.call(day="2026-11-21"), 5, "operator", self.TODAY))
        self.assertEqual(cc.can_touch(None, 5, "operator", self.TODAY), "Topilmadi")

    def test_admin_any(self):
        self.assertIsNone(cc.can_touch(self.call(op=6, day="2026-10-01"), 1, "admin", self.TODAY))


class ContentTest(unittest.TestCase):
    def test_plenty_and_clean(self):
        self.assertGreaterEqual(len(content.JOKES), 25)
        text = " ".join(content.JOKES + content.MOTIVATION + content.THANKS).lower()
        for banned in ("qaynona", "arzon", "cho'chqa", "davolaydi"):
            self.assertNotIn(banned, text)

    def test_every_metric_has_cheers(self):
        for metric in cc.MILESTONES:
            self.assertTrue(content.SMALL_CHEERS[metric])
            self.assertIn("{n}", content.GOAL_CHEERS[metric])

    def test_joke_of_day_is_stable(self):
        self.assertEqual(content.joke_of_day(10), content.joke_of_day(10))


class ReportTest(unittest.TestCase):
    def test_report_escapes_and_shows_plan(self):
        t = cc.report_text("<Ali>", date(2026, 11, 22),
                           {"outbound": 50, "meaningful": 20, "orders": 3, "inbound": 4,
                            "followups": 2, "sales": 1_250_000}, S, 90, "alluloza", None)
        self.assertIn("&lt;Ali&gt;", t)
        self.assertIn("<b>50</b> / 80", t)
        self.assertIn("1 250 000 so'm", t)


if __name__ == "__main__":
    unittest.main()
