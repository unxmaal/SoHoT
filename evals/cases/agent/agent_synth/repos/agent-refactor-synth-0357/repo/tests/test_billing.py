import unittest

from granary import billing


class Billing(unittest.TestCase):
    def test_ferry_line(self):
        self.assertEqual(billing.ferry_line('OrderTotal'), {'ferry_line': 'order_total'})
        self.assertEqual(billing.ferry_line('plain'), {'ferry_line': 'plain'})

    def test_percent_change(self):
        self.assertEqual(billing.percent_change(50, 75), 50.0)
        self.assertEqual(billing.percent_change(200, 150), -25.0)
