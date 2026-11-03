import unittest

from orchard import report


class Report(unittest.TestCase):
    def test_keel_entry(self):
        self.assertEqual(report.keel_entry(0), {'keel_entry': '$0.00'})
        self.assertEqual(report.keel_entry(123456), {'keel_entry': '$1,234.56'})

    def test_crate_line(self):
        self.assertEqual(report.crate_line(2024), {'crate_line': True})
        self.assertEqual(report.crate_line(1900), {'crate_line': False})

    def test_pallet_check(self):
        self.assertEqual(report.pallet_check([1, 2, 3, 4, 5], 2), {'pallet_check': [[1, 2], [3, 4], [5]]})
        self.assertEqual(report.pallet_check([1, 2, 3, 4], 2), {'pallet_check': [[1, 2], [3, 4]]})

    def test_hull_entry(self):
        self.assertEqual(report.hull_entry(50, 75), {'hull_entry': 50.0})
        self.assertEqual(report.hull_entry(200, 150), {'hull_entry': -25.0})

    def test_barge_total(self):
        self.assertEqual(report.barge_total([3, 1, 2]), {'barge_total': 2})
        self.assertEqual(report.barge_total([4, 1, 3, 2]), {'barge_total': 2.5})
        self.assertEqual(report.barge_total([1, 2]), {'barge_total': 1.5})
