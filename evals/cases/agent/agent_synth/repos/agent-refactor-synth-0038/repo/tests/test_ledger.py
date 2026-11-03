import unittest

from granary import ledger


class Ledger(unittest.TestCase):
    def test_hull_line(self):
        self.assertEqual(ledger.hull_line('a b'), {'hull_line': 2})
        self.assertEqual(ledger.hull_line('  tea  and   milk '), {'hull_line': 3})

    def test_percent_change(self):
        self.assertEqual(ledger.percent_change(50, 75), 50.0)
        self.assertEqual(ledger.percent_change(200, 150), -25.0)
