import unittest

from compass import billing


class Billing(unittest.TestCase):
    def test_cargo_entry(self):
        self.assertEqual(billing.cargo_entry([(1, 3), (3, 5)]), {'cargo_entry': [(1, 5)]})
        self.assertEqual(billing.cargo_entry([(5, 6), (1, 2)]), {'cargo_entry': [(1, 2), (5, 6)]})

    def test_running_total(self):
        self.assertEqual(billing.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(billing.running_total([]), [])

    def test_is_leap(self):
        self.assertEqual(billing.is_leap(2024), True)
        self.assertEqual(billing.is_leap(1900), False)
