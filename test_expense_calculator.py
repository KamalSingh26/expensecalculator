"""Run with: python -m unittest -v"""

import csv
import tempfile
import unittest
from pathlib import Path

from expense_calculator import (
    ExpenseStore, calculate_summary, export_csv, parse_amount,
    validate_date, validate_month,
)


class ExpenseTests(unittest.TestCase):
    def setUp(self):
        self.store = ExpenseStore(":memory:")

    def tearDown(self):
        self.store.close()

    def test_money_is_exact(self):
        self.assertEqual(parse_amount("0.10") + parse_amount("0.20"), 30)
        self.assertEqual(parse_amount(" 125.50 "), 12550)
        self.assertEqual(parse_amount("0", allow_zero=True), 0)
        self.assertEqual(parse_amount("9999999.99"), 999999999)

    def test_invalid_amounts_are_rejected(self):
        for text in ("", "0", "-2", "1.234", "NaN", "Infinity", "1e2", "1,000", "10000000", "abc"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_amount(text)
        with self.assertRaises(ValueError):
            parse_amount("1" * 10000)

    def test_dates_and_months_are_validated(self):
        self.assertEqual(validate_date("2024-02-29"), "2024-02-29")
        self.assertEqual(validate_month("2026-12"), "2026-12")
        for text in ("2026-02-29", "2026-04-31", "2026-1-01", "0000-01-01", "not a date"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                validate_date(text)
        for text in ("2026-13", "2026-1", "2026-00", "0000-01"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                validate_month(text)

    def test_month_boundaries_and_category_totals(self):
        self.store.add_expense("2026-12-31", "Food", "150.25", "Dinner")
        self.store.add_expense("2027-01-01", "Food", "100.10", "Breakfast")
        self.store.add_expense("2027-01-31", "Transport", "50.20", "Bus")
        self.store.add_expense("2027-01-31", "Food", "20.10", "Tea")
        self.store.add_expense("2027-02-01", "Food", "900")
        january = self.store.get_expenses("2027-01")
        total, categories = calculate_summary(january)
        self.assertEqual(len(january), 3)
        self.assertEqual(total, 17040)
        self.assertEqual(categories, {"Food": 12020, "Transport": 5020})
        self.assertEqual(january[0]["note"], "Tea")
        self.assertEqual(len(self.store.get_expenses("2026-12")), 1)

    def test_short_month_and_last_supported_year(self):
        self.store.add_expense("2024-02-29", "Other", "1")
        self.store.add_expense("2024-03-01", "Other", "2")
        self.store.add_expense("9999-12-31", "Other", "3")
        self.assertEqual(len(self.store.get_expenses("2024-02")), 1)
        self.assertEqual(len(self.store.get_expenses("9999-12")), 1)

    def test_empty_month(self):
        self.assertEqual(calculate_summary(self.store.get_expenses("2026-10")), (0, {}))
        self.assertIsNone(self.store.get_budget("2026-10"))

    def test_budget_updates_are_separate_for_each_month(self):
        self.store.set_budget("2026-10", "5000")
        self.store.set_budget("2026-11", "6000")
        self.store.set_budget("2026-10", "5500.50")
        self.assertEqual(self.store.get_budget("2026-10"), 550050)
        self.assertEqual(self.store.get_budget("2026-11"), 600000)
        self.store.set_budget("2026-10", "0")
        self.assertIsNone(self.store.get_budget("2026-10"))
        self.assertEqual(self.store.get_budget("2026-11"), 600000)

    def test_invalid_input_does_not_create_a_record(self):
        for args in (("2026-10-01", "Unknown", "10", ""),
                     ("2026-10-01", "Food", "10", "a" * 141),
                     ("2026-10-32", "Food", "10", ""),
                     ("2026-10-01", "Food", "-10", "")):
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.store.add_expense(*args)
        self.assertEqual(len(self.store.get_expenses("2026-10")), 0)

    def test_delete_removes_only_selected_record(self):
        expense_id = self.store.add_expense("2026-10-01", "Food", "20")
        self.store.add_expense("2026-10-01", "Bills", "50")
        self.assertTrue(self.store.delete_expense(expense_id))
        self.assertFalse(self.store.delete_expense(expense_id))
        self.assertEqual(calculate_summary(self.store.get_expenses("2026-10"))[0], 5000)

    def test_data_survives_reopening(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "expenses.db"
            first = ExpenseStore(path)
            first.add_expense("2026-10-01", "Food", "40.50", "Friend's lunch — café")
            first.set_budget("2026-10", "500")
            first.close()
            second = ExpenseStore(path)
            try:
                self.assertEqual(second.get_expenses("2026-10")[0]["note"], "Friend's lunch — café")
                self.assertEqual(second.get_budget("2026-10"), 50000)
            finally:
                second.close()

    def test_csv_export_round_trip(self):
        self.store.add_expense("2026-10-01", "Food", "50.10", 'Lunch, "special"')
        self.store.add_expense("2026-10-02", "Other", "10", "=1+1")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "expenses.csv"
            export_csv(path, self.store.get_expenses("2026-10"))
            with path.open(newline="", encoding="utf-8-sig") as file:
                rows = list(csv.reader(file))
        self.assertEqual(rows[0], ["Date", "Category", "Amount_INR", "Note"])
        self.assertEqual(rows[1], ["2026-10-02", "Other", "10.00", "'=1+1"])
        self.assertEqual(rows[2], ["2026-10-01", "Food", "50.10", 'Lunch, "special"'])


if __name__ == "__main__":
    unittest.main()
