import unittest

from tally.ledger import snake_case
from tally import ledger


class Ledger(unittest.TestCase):
    def test_snake_case(self):
        self.assertEqual(snake_case('OrderTotal'), 'order_total')
        self.assertEqual(snake_case('plain'), 'plain')
        self.assertEqual(snake_case('A'), 'a')

    def test_percent_change(self):
        self.assertEqual(ledger.percent_change(50, 75), 50.0)
        self.assertEqual(ledger.percent_change(200, 150), -25.0)
