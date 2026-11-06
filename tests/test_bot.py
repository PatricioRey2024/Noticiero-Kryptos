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


    def test_format_weekly_report_includes_bea_agenda(self):
        report = bot.format_weekly_report(
            {"published_messages": {}},
            [{"title": "Reunión FOMC · December 8-9 2026"}],
            [],
            [{
                "title": "GDP (Advance Estimate) · November 25, 2026",
                "date": "November 25, 2026 · 08:30 AM ET",
            }],
        )
        self.assertIn("Agenda macroeconómica próxima · BEA", report)
        self.assertIn("GDP (Advance Estimate)", report)

    def test_unknown_bls_indicator_does_not_publish_unverified_values(self):
        self.assertEqual(bot.read_bls_official_snapshot("GDP"), {})

    def test_format_macro_event_keeps_missing_values_explicit(self):
        text = bot.format_macro_event({
            "title": "CPI · November 10, 2026",
            "previous": None,
            "expected": None,
            "actual": None,
            "core_previous": None,
            "core_expected": None,
            "core_actual": None,
            "status": "scheduled",
            "source": "BLS",
        })
        self.assertIn("Anterior: N/D", text)
        self.assertIn("Real: pendiente", text)
        self.assertIn("Core real: pendiente", text)

    def test_parse_macro_event_datetime_converts_et_to_utc(self):
        event = {"date": "November 10, 2026 · 08:30 AM ET"}
        parsed = bot.parse_macro_event_datetime(event)
        self.assertEqual(parsed.isoformat(), "2026-11-10T13:30:00+00:00")

    def test_macro_alert_window_only_matches_one_hour_before(self):
        event = {
            "date": "November 10, 2026 · 08:30 AM ET",
            "title": "Consumer Price Index · November 2026",
        }
        now = bot.datetime(2026, 11, 10, 12, 30, tzinfo=bot.timezone.utc)
        self.assertEqual(bot.macro_alert_window(event, now), "pre_release")
        now = bot.datetime(2026, 11, 9, 13, 30, tzinfo=bot.timezone.utc)
        self.assertIsNone(bot.macro_alert_window(event, now))


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
