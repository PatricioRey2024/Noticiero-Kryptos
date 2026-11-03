import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bot


class BotStateTests(unittest.TestCase):
    def test_load_state_adds_delivery_registry_to_legacy_state(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            state_path.write_text(
                json.dumps({"processed_ids": ["news-1"]}),
                encoding="utf-8",
            )
            with patch.object(bot, "STATE_FILE", str(state_path)):
                state = bot.load_state()
            self.assertEqual(state["processed_ids"], ["news-1"])
            self.assertEqual(state["published_messages"], {})

    def test_save_state_limits_processed_ids_and_delivery_records(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            processed_ids = [f"news-{index}" for index in range(bot.MAX_PROCESSED_IDS + 1)]
            state = {
                "processed_ids": processed_ids,
                "published_messages": {
                    news_id: {"telegram_message_id": index}
                    for index, news_id in enumerate(processed_ids)
                },
            }
            with patch.object(bot, "STATE_FILE", str(state_path)):
                bot.save_state(state)
            saved = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(len(saved["processed_ids"]), bot.MAX_PROCESSED_IDS)
            self.assertEqual(len(saved["published_messages"]), bot.MAX_PROCESSED_IDS)
            self.assertNotIn("news-0", saved["published_messages"])


class MessageTests(unittest.TestCase):
    def test_build_message_preserves_source_and_link(self):
        message = bot.build_message(
            {
                "source": "Federal Reserve",
                "title": "Título original",
                "link": "https://example.com/news",
                "published": "2026-11-01T12:00:00Z",
            },
            {
                "title_es": "Título en español",
                "summary_es": "Resumen verificable.",
                "impact_es": "Impacto por evaluar.",
            },
        )
        self.assertIn("Federal Reserve", message)
        self.assertIn("https://example.com/news", message)
        self.assertIn("Impacto potencial en el mercado", message)


if __name__ == "__main__":
    unittest.main()
