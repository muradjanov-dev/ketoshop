"""⚖️ Yurist-agent (owner, 2026-10-28). No Telegram, no OpenAI, no database:
the model and the bot are fakes, nothing leaves the machine."""
import asyncio
import io
import json
import os
import unittest
import zipfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from xml.etree import ElementTree

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import docx_writer
import yurist

GROUP, TOPIC = -1001234567890, 45


def run(coro):
    return asyncio.run(coro)


def message(text="QQS qachon to'lanadi?", chat=GROUP, thread=TOPIC, uid=7, bot=False, document=None,
            chat_type="supergroup"):
    m = MagicMock()
    m.text = text
    m.caption = None
    m.document = document
    m.chat.id = chat
    m.chat.type = chat_type
    m.message_thread_id = thread
    m.is_topic_message = thread is not None
    m.from_user = SimpleNamespace(id=uid, is_bot=bot, full_name="Nodir")
    m.sender_chat = None
    m.message_id = 100
    m.reply = AsyncMock()
    m.answer = AsyncMock()
    m.delete = AsyncMock()
    return m


class DocxTest(unittest.TestCase):
    BLOCKS = [
        {"kind": "heading", "text": "1. Shartnoma predmeti", "items": [], "rows": []},
        {"kind": "paragraph", "text": "Sotuvchi & Xaridor <kelishdi>\nikkinchi qator", "items": [], "rows": []},
        {"kind": "bullets", "text": "", "items": ["Bodom uni", "Eritritol"], "rows": []},
        {"kind": "table", "text": "", "items": [], "rows": [["Mahsulot", "Narx"], ["Bodom uni 1000gr", "160 000"]]},
        {"kind": "signature", "text": "", "items": ["Sotuvchi: [Rahbar F.I.Sh.]", "Xaridor: ____"], "rows": []},
    ]

    def test_a_valid_word_file(self):
        data = docx_writer.build("DILER SHARTNOMASI № ___", self.BLOCKS)
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = set(z.namelist())
            self.assertTrue({"[Content_Types].xml", "_rels/.rels", "word/document.xml",
                             "word/styles.xml", "word/_rels/document.xml.rels"} <= names)
            for name in names:
                ElementTree.fromstring(z.read(name))           # every part is well-formed XML
        text = docx_writer.extract_text(data)
        for piece in ("DILER SHARTNOMASI № ___", "1. Shartnoma predmeti", "Sotuvchi & Xaridor <kelishdi>",
                      "ikkinchi qator", "•  Bodom uni", "Bodom uni 1000gr", "160 000",
                      "Sotuvchi: [Rahbar F.I.Sh.]", "(imzo)"):
            self.assertIn(piece, text)

    def test_filename(self):
        self.assertEqual(yurist._safe_filename("Diler shartnomasi (Samarqand)"), "Diler_shartnomasi_Samarqand.docx")
        self.assertEqual(yurist._safe_filename(""), "hujjat.docx")
        self.assertEqual(yurist._safe_filename("../../etc"), "etc.docx")


class SplitTest(unittest.TestCase):
    def test_pieces_fit(self):
        text = "\n\n".join(f"{i}. " + "soliq " * 120 for i in range(12))
        parts = yurist.split_text(text, 1000)
        self.assertTrue(all(len(p) <= 1000 for p in parts))
        self.assertEqual("".join(parts).replace(" ", "").replace("\n", ""),
                         text.replace(" ", "").replace("\n", ""))
        self.assertEqual(yurist.split_text("qisqa"), ["qisqa"])


class TopicTest(unittest.TestCase):
    def _check(self, m, bound={"yurist_chat": str(GROUP), "yurist_thread": str(TOPIC)}):
        with patch.object(yurist, "_settings", AsyncMock(return_value=bound)):
            return run(yurist.in_topic(m))

    def test_only_the_bound_topic(self):
        self.assertTrue(self._check(message()))
        self.assertFalse(self._check(message(thread=46)))
        self.assertFalse(self._check(message(chat=-100999)))
        self.assertFalse(self._check(message(text="/yurist_holat")))
        self.assertFalse(self._check(message(bot=True)))
        self.assertFalse(self._check(message(chat_type="private", chat=7, thread=None)))
        self.assertFalse(self._check(message(), bound={}))
        self.assertTrue(self._check(message(text=None, document=MagicMock())))

    def test_bind_command(self):
        m = message(text="/yurist_mavzu")
        bot = MagicMock()
        bot.send_message = AsyncMock()
        with patch.object(yurist, "ADMIN_IDS", [7]), \
                patch("ai_sales.set_setting", AsyncMock()) as set_setting:
            run(yurist.cmd_bind(m, bot))
            self.assertEqual([c.args[:2] for c in set_setting.await_args_list],
                             [("yurist_chat", str(GROUP)), ("yurist_thread", str(TOPIC))])
            self.assertEqual(bot.send_message.await_args.kwargs["message_thread_id"], TOPIC)
            m2 = message(text="/yurist_mavzu", uid=8)
            run(yurist.cmd_bind(m2, bot))
            self.assertEqual(set_setting.await_count, 2)           # a member can't move it


def _response(rid, text="", calls=(), tokens=(1000, 0, 500)):
    output = [SimpleNamespace(type="function_call", name=n, arguments=json.dumps(a), call_id=c)
              for n, a, c in calls]
    usage = SimpleNamespace(input_tokens=tokens[0], output_tokens=tokens[2],
                            input_tokens_details=SimpleNamespace(cached_tokens=tokens[1]))
    return SimpleNamespace(id=rid, output=output, output_text=text, usage=usage)


class AskTest(unittest.TestCase):
    def setUp(self):
        yurist._chains.clear()
        yurist._spend.update(day="", usd=0.0)

    def test_document_round_trip(self):
        doc_args = {"title": "TIJORAT TAKLIFI", "filename": "kp_bodom",
                    "blocks": [{"kind": "paragraph", "text": "Narxlar", "items": [], "rows": []}]}
        client = MagicMock()
        client.responses.create = AsyncMock(side_effect=[
            _response("r1", calls=[("make_document", doc_args, "c1")]),
            _response("r2", text="KP tayyor, faylni ko'ring."),
        ])
        bot = MagicMock()
        bot.send_document = AsyncMock()
        with patch.object(yurist, "_client_and_model", return_value=(client, "gpt-5.4-mini")):
            out = run(yurist.ask(bot, (GROUP, TOPIC), [{"type": "input_text", "text": "KP tayyorla"}]))
        self.assertEqual(out, "KP tayyor, faylni ko'ring.")
        first, second = [c.kwargs for c in client.responses.create.await_args_list]
        self.assertEqual(first["tools"][0], {"type": "web_search"})
        self.assertEqual(first["tools"][1]["name"], "make_document")
        self.assertNotIn("previous_response_id", first)
        self.assertEqual(second["previous_response_id"], "r1")
        self.assertEqual(second["input"][0]["type"], "function_call_output")
        sent = bot.send_document.await_args
        self.assertEqual(sent.args[0], GROUP)
        self.assertEqual(sent.kwargs["message_thread_id"], TOPIC)
        self.assertEqual(sent.args[1].filename, "kp_bodom.docx")
        self.assertGreater(yurist._spent(), 0)
        self.assertEqual(yurist._chains[(GROUP, TOPIC)]["prev_id"], "r2")

    def test_preview_tool_name_fallback(self):
        client = MagicMock()
        client.responses.create = AsyncMock(side_effect=[
            Exception("Invalid value: 'web_search'. Supported values are: 'web_search_preview'"),
            _response("r1", text="Javob"),
        ])
        with patch.object(yurist, "_client_and_model", return_value=(client, "gpt-5.4-mini")):
            self.assertEqual(run(yurist.ask(MagicMock(), (GROUP, TOPIC), [])), "Javob")
        self.assertEqual(client.responses.create.await_args.kwargs["tools"][0], {"type": "web_search_preview"})

    def test_no_key(self):
        with patch.object(yurist, "_client_and_model", return_value=(None, "gpt-5.4-mini")):
            self.assertIn("/ai_kalit", run(yurist.ask(MagicMock(), (GROUP, TOPIC), [])))

    def test_model_follows_the_ai_seller(self):
        import ai_sales
        fake = SimpleNamespace(name="openai", api_key="sk-test", model="gpt-5.5")
        with patch.object(ai_sales, "PROVIDER", fake), patch.dict(os.environ, {"YURIST_MODEL": ""}):
            client, model = yurist._client_and_model()
            self.assertEqual(model, "gpt-5.5")
            self.assertIsNotNone(client)
        with patch.object(ai_sales, "PROVIDER", fake), patch.dict(os.environ, {"YURIST_MODEL": "gpt-5.4"}):
            self.assertEqual(yurist._client_and_model()[1], "gpt-5.4")


class HandlerTest(unittest.TestCase):
    def setUp(self):
        yurist._spend.update(day="", usd=0.0)

    def test_answer_goes_back_into_the_topic(self):
        bot = MagicMock()
        bot.send_message = AsyncMock()
        bot.send_chat_action = AsyncMock()
        m = message()
        with patch.object(yurist, "ask", AsyncMock(return_value="QQS har oy 20-sanagacha …")) as ask:
            run(yurist.on_question(m, bot))
        self.assertEqual(ask.await_args.args[2][0]["text"], "Nodir: QQS qachon to'lanadi?")
        sent = bot.send_message.await_args
        self.assertEqual(sent.args[:2], (GROUP, "QQS har oy 20-sanagacha …"))
        self.assertEqual(sent.kwargs["message_thread_id"], TOPIC)
        self.assertEqual(sent.kwargs["reply_to_message_id"], 100)
        self.assertIsNone(sent.kwargs["parse_mode"])

    def test_daily_cap(self):
        yurist._spend.update(day=yurist._today(), usd=yurist.DAILY_USD + 1)
        m = message()
        with patch.object(yurist, "ask", AsyncMock()) as ask:
            run(yurist.on_question(m, MagicMock()))
        ask.assert_not_awaited()
        self.assertIn("limit", m.reply.await_args.args[0])

    def test_a_docx_is_read(self):
        doc = MagicMock()
        doc.file_name = "shartnoma.docx"
        doc.file_size = 1000
        data = docx_writer.build("SHARTNOMA", [{"kind": "paragraph", "text": "Jarima 0,5%", "items": [], "rows": []}])
        bot = MagicMock()
        bot.download = AsyncMock(return_value=io.BytesIO(data))
        parts = run(yurist._attachment(bot, message(document=doc)))
        self.assertIn("Jarima 0,5%", parts[0]["text"])
        doc.file_name = "skan.pdf"
        bot.download = AsyncMock(return_value=io.BytesIO(b"%PDF-1.4"))
        pdf = run(yurist._attachment(bot, message(document=doc)))[0]
        self.assertEqual(pdf["type"], "input_file")
        self.assertTrue(pdf["file_data"].startswith("data:application/pdf;base64,"))


if __name__ == "__main__":
    unittest.main()
