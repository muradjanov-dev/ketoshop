"""Avval yuborilgan, javobsiz qolgan mijoz rasmlari bir marta adminlarga (egasi, 2026-11-27)."""
import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import database
import recover_photos


class RecoverPhotosTest(unittest.TestCase):
    def test_sent_once_with_a_note(self):
        relay = AsyncMock()
        photos = [(7, {"kind": "photo", "file_id": "PIE", "caption": "pishirdim"})]
        with patch("handlers.support_relay.relay_media", relay), \
                patch.object(recover_photos, "pending_photos", AsyncMock(return_value=photos)), \
                patch.object(database, "claim_release_notes", AsyncMock(side_effect=[True, False])), \
                patch.object(database, "get_user", AsyncMock(return_value={"full_name": "Ali"})), \
                patch.object(recover_photos, "PAUSE", 0):
            self.assertEqual(asyncio.run(recover_photos.run_once(object())), 1)
            self.assertEqual(asyncio.run(recover_photos.run_once(object())), 0)
        args = relay.await_args.args
        self.assertEqual(args[1].id, 7)
        self.assertEqual(args[2:4], ("photo", "PIE"))
        self.assertIn("avval yuborilgan", args[4])


if __name__ == "__main__":
    unittest.main()
