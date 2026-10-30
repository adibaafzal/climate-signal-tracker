import sqlite3
import unittest

from climate_signal import analyse_signal, clean_text, fallback_analysis, initialise_db, store_signal, recent_signals


class ClimateSignalTests(unittest.TestCase):
    def test_clean_text_removes_html_and_decodes_entities(self):
        self.assertEqual(clean_text("<p>Battery &amp; storage</p>"), "Battery & storage")

    def test_funding_article_is_classified(self):
        signal = analyse_signal(
            "Battery startup raises €25 million in Series B",
            "The energy storage company will expand manufacturing capacity.",
        )
        self.assertIsNotNone(signal)
        self.assertEqual(signal["signal_type"], "Funding signal")
        self.assertEqual(signal["funding_stage"], "Series B")
        self.assertTrue(signal["funding_amount_mentioned"])
        self.assertIn("Batteries & energy storage", signal["sector_tags"])

    def test_off_topic_article_is_excluded(self):
        self.assertIsNone(analyse_signal("New social media app launches", "A consumer app adds video features."))

    def test_climate_commercial_signal_is_included(self):
        signal = analyse_signal(
            "Heat pump startup signs first commercial deployment contract",
            "The company will install systems for industrial customers.",
        )
        self.assertIsNotNone(signal)
        self.assertEqual(signal["signal_type"], "Startup / commercial signal")

    def test_fallback_is_source_bounded(self):
        signal = {"signal_type": "Funding signal"}
        result = fallback_analysis(
            "Solar startup raises seed round",
            "The company raised a seed round to expand its solar installation platform.",
            signal,
        )
        self.assertIn("seed round", result["summary"])
        self.assertIn("original article", result["verification_notes"])

    def test_database_deduplicates_urls(self):
        connection = sqlite3.connect(":memory:")
        initialise_db(connection)
        article = {
            "url": "https://example.com/climate-startup-series-a",
            "published_at": "2026-10-30T08:00:00+00:00",
            "source": "Test Feed",
            "title": "Climate startup raises Series A",
            "signal_type": "Funding signal",
            "sector_tags": "Climate-tech (cross-sector)",
            "funding_stage": "Series A",
            "funding_amount_mentioned": "",
            "relevance_score": 6,
            "summary": "A test summary.",
            "investment_relevance": "A test research angle.",
            "verification_notes": "Check the original source.",
        }
        self.assertTrue(store_signal(connection, article))
        self.assertFalse(store_signal(connection, article))
        self.assertEqual(len(recent_signals(connection, 365)), 1)
        connection.close()


if __name__ == "__main__":
    unittest.main()
