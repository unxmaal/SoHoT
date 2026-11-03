import unittest

from tally import payroll


class Payroll(unittest.TestCase):
    def test_deck_total(self):
        self.assertEqual(payroll.deck_total({'tea': 3, 'milk': 3, 'jam': 1}, 2), {'deck_total': ['milk', 'tea']})
        self.assertEqual(payroll.deck_total({'a': 1}, 5), {'deck_total': ['a']})

    def test_running_total(self):
        self.assertEqual(payroll.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(payroll.running_total([]), [])

    def test_percent_change(self):
        self.assertEqual(payroll.percent_change(50, 75), 50.0)
        self.assertEqual(payroll.percent_change(200, 150), -25.0)
