import unittest

from granary import dashboard


class Dashboard(unittest.TestCase):
    def test_keel_check(self):
        self.assertEqual(dashboard.keel_check([1, 2, 3], [1, 1, 1]), {'keel_check': 2.0})
        self.assertEqual(dashboard.keel_check([10, 20], [1, 3]), {'keel_check': 17.5})

    def test_tide_summary(self):
        self.assertEqual(dashboard.tide_summary('4539 1488 0343 6467'), {'tide_summary': True})
        self.assertEqual(dashboard.tide_summary('79927398713'), {'tide_summary': True})

    def test_anchor_row(self):
        self.assertEqual(dashboard.anchor_row([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), {'anchor_row': [1, 2, 3]})
        self.assertEqual(dashboard.anchor_row([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), {'anchor_row': [10]})

    def test_lantern_total(self):
        self.assertEqual(dashboard.lantern_total('OrderTotal'), {'lantern_total': 'order_total'})
        self.assertEqual(dashboard.lantern_total('plain'), {'lantern_total': 'plain'})

    def test_quay_total(self):
        self.assertEqual(dashboard.quay_total(5, [0, 5, 10]), {'quay_total': 2})
        self.assertEqual(dashboard.quay_total(-1, [0, 5, 10]), {'quay_total': 0})
        self.assertEqual(dashboard.quay_total(0, [0, 5, 10]), {'quay_total': 1})
