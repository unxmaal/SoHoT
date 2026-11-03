import unittest

from mill import budget
from mill import tickets


class Hidden(unittest.TestCase):
    def test_budget_clamp(self):
        self.assertEqual(budget.clamp(5, 0, 10), 5)
        self.assertEqual(budget.clamp(-3, 0, 10), 0)
        self.assertEqual(budget.clamp(15, 0, 10), 10)
        self.assertEqual(budget.clamp(10, 0, 10), 10)
        self.assertEqual(budget.clamp(0, 0, 10), 0)
        self.assertEqual(budget.clamp(7, 7, 7), 7)
        self.assertEqual(budget.clamp(-20, -30, -10), -20)

    def test_budget_is_leap(self):
        self.assertEqual(budget.is_leap(2024), True)
        self.assertEqual(budget.is_leap(1900), False)
        self.assertEqual(budget.is_leap(2000), True)
        self.assertEqual(budget.is_leap(2023), False)
        self.assertEqual(budget.is_leap(2400), True)
        self.assertEqual(budget.is_leap(2100), False)

    def test_tickets_bucket(self):
        self.assertEqual(tickets.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(tickets.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(tickets.bucket(12, [0, 5, 10]), 3)
        self.assertEqual(tickets.bucket(0, [0, 5, 10]), 1)
        self.assertEqual(tickets.bucket(7, []), 0)

    def test_tickets_parse_duration(self):
        self.assertEqual(tickets.parse_duration('1h30m'), 5400)
        self.assertEqual(tickets.parse_duration('45s'), 45)
        self.assertEqual(tickets.parse_duration('2h'), 7200)
        self.assertEqual(tickets.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            tickets.parse_duration('')
        with self.assertRaises(ValueError):
            tickets.parse_duration('5x')
        self.assertEqual(tickets.parse_duration('10m5s'), 605)

    def test_feature(self):
        self.assertEqual(tickets.bucket(5, [0, 5, 10], labels=['none', 'low', 'mid', 'high']), 'mid')
        self.assertEqual(tickets.bucket(-2, [0], labels=['below', 'above']), 'below')
