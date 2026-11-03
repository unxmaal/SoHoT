import unittest

from compass import rosters


class Rosters(unittest.TestCase):
    def test_format_cents(self):
        self.assertEqual(rosters.format_cents(0), '$0.00')
        self.assertEqual(rosters.format_cents(123456), '$1,234.56')
        self.assertEqual(rosters.format_cents(-105), '-$1.05')

    def test_running_total(self):
        self.assertEqual(rosters.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(rosters.running_total([]), [])
        self.assertEqual(rosters.running_total([5]), [5])
