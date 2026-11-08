"""Pastki menyu ko'rsatmasi (egasi, 2026-11-08: "birinchi kirganda 3 safar ...
qisqa qimirlaydigan va click qiladigan animatsiya ko'rsat 4-marotaba kirganda
bo'ldi ko'rsatma").

Checked in Edge while writing this: launches 1–3 show the hand tapping
«Bosh sahifa», «Savat», «Sevimlilar», «Profil»; launches 4 and 5 show
nothing; a touch removes it at once."""
import json
import os
import shutil
import subprocess
import unittest

PAGE = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "webapp", "index.html"),
            encoding="utf-8").read().replace("\r\n", "\n")


class WiringTest(unittest.TestCase):
    def test_started_after_the_shop_loads(self):
        init = PAGE[PAGE.index("(async function init()"):]
        self.assertLess(init.index("await loadCart();"), init.index("DockHint.maybe();"))

    def test_three_launches_then_never(self):
        hint = PAGE[PAGE.index("const DockHint = (() => {"):PAGE.index('// "Bot orqali buyurtmaga 10% chegirma"')]
        self.assertIn("const SHOWS = 3;", hint)
        self.assertIn("if (n >= SHOWS) return;", hint)
        self.assertIn("'ketoshop_dock_hint_'", hint)
        self.assertIn("document.addEventListener('pointerdown', stop, true)", hint)   # a touch stops it
        self.assertIn("#tab-bar .tab-item:not(.active)", hint)

    def test_slow_enough_to_follow(self):
        # Owner, 2026-11-08: "sekinroq chiqsin odam tushunmay qoldi" — measured
        # in Edge: the line at 1.1 s, then a button every ~2.4 s, done at ~13 s.
        hint = PAGE[PAGE.index("const DockHint = (() => {"):PAGE.index('// "Bot orqali buyurtmaga 10% chegirma"')]
        self.assertIn("const INTRO_MS = 2200, MOVE_MS = 700, PRESS_MS = 250, HOLD_MS = 1400;", hint)
        self.assertIn("Pastdagi tugmalar — boshqa bo'limlar", hint)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class CountTest(unittest.TestCase):
    def run_launches(self, n, storage_works=True):
        hint = PAGE[PAGE.index("const DockHint = (() => {"):PAGE.index('// "Bot orqali buyurtmaga 10% chegirma"')]
        code = """
const store = {};
const localStorage = %s;
const tg = {initDataUnsafe: {user: {id: 5}}};
const played = [];
const document = {getElementById: () => null, querySelector: () => null, querySelectorAll: () => [],
                  addEventListener() {}, removeEventListener() {}};
global.setTimeout = (fn) => fn();
%s
(async () => {
  const realPlay = [];
  for (let i = 0; i < %d; i++) {
    const before = store['ketoshop_dock_hint_5'] || '0';
    await DockHint.maybe();
    played.push(Number(store['ketoshop_dock_hint_5'] || 0) > Number(before));
  }
  process.stdout.write(JSON.stringify(played));
})();
""" % ("{getItem: k => store[k] ?? null, setItem: (k, v) => { store[k] = v; }}" if storage_works
       else "{getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); }}",
       hint, n)
        out = subprocess.run(["node", "-e", code], capture_output=True, text=True, check=True).stdout
        return json.loads(out)

    def test_first_three_launches_only(self):
        self.assertEqual(self.run_launches(5), [True, True, True, False, False])

    def test_no_storage_no_hint(self):
        self.assertEqual(self.run_launches(2, storage_works=False), [False, False])


if __name__ == "__main__":
    unittest.main()
