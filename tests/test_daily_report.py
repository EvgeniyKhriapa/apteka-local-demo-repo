# -*- coding: utf-8 -*-
"""
tests/test_daily_report.py — базова перевірка, що seed_db.py + daily_report.py
разом дають коректно сформований data-словник і що report_text_formatter.py
(оригінальний, незмінений файл) вміє його відрендерити без винятків.

Запуск:
    python -m unittest tests.test_daily_report -v
(з кореня репозиторію; тест сам додає scripts/ у sys.path)
"""

import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import seed_db          # noqa: E402
import daily_report     # noqa: E402
import report_text_formatter  # noqa: E402


class TestDailyReportPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Перегенеровуємо демо-базу один раз для всіх тестів цього класу.
        seed_db.build_database()

    def test_database_has_recent_orders(self):
        conn = daily_report.connect()
        try:
            yesterday = date.today() - timedelta(days=1)
            count = daily_report.fetch_order_count(conn, yesterday)
            self.assertGreater(count, 0, "очікувались замовлення за вчора")
        finally:
            conn.close()

    def test_build_report_data_has_required_keys(self):
        report_date = date.today() - timedelta(days=1)
        data = daily_report.build_report_data(report_date)

        for key in ("apteky", "site", "analytics", "facebook", "google_ads"):
            self.assertIn(key, data)

        self.assertTrue(data["apteky"]["available"])
        self.assertTrue(data["site"]["available"])
        self.assertFalse(data["analytics"]["available"])
        self.assertFalse(data["facebook"]["available"])
        self.assertFalse(data["google_ads"]["available"])

        self.assertGreaterEqual(len(data["apteky"]["top5"]), 1)
        self.assertGreaterEqual(len(data["site"]["top5"]), 1)

    def test_original_formatter_renders_without_errors(self):
        report_date = date.today() - timedelta(days=1)
        data = daily_report.build_report_data(report_date)
        date_str = report_date.strftime("%d.%m.%Y")

        full_text = report_text_formatter.build_report(data, date_str, compact=False)
        compact_text = report_text_formatter.build_report(data, date_str, compact=True)

        self.assertIn("ГАРМОНІЯ 2000", full_text)
        self.assertIn("ПРОДАЖІ ПО АПТЕКАХ", full_text)
        self.assertLess(len(compact_text), len(full_text) + 500)

    def test_html_render_contains_key_sections(self):
        report_date = date.today() - timedelta(days=1)
        data = daily_report.build_report_data(report_date)
        html = daily_report.render_report_html(data, report_date)

        self.assertIn("<html", html)
        self.assertIn("Продажі по аптеках", html)
        self.assertIn("Google Ads", html)


if __name__ == "__main__":
    unittest.main()
