import unittest

from beacon import ledger


class Ledger(unittest.TestCase):
    def test_keel_figure(self):
        self.assertEqual(ledger.keel_figure('OrderTotal'), {'keel_figure': 'order_total'})
        self.assertEqual(ledger.keel_figure('plain'), {'keel_figure': 'plain'})

    def test_percent_change(self):
        self.assertEqual(ledger.percent_change(50, 75), 50.0)
        self.assertEqual(ledger.percent_change(200, 150), -25.0)
