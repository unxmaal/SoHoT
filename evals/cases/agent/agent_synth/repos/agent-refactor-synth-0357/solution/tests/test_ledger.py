import unittest

from granary.shared import snake_case
from granary import ledger


class Ledger(unittest.TestCase):
    def test_snake_case(self):
        self.assertEqual(snake_case('OrderTotal'), 'order_total')
        self.assertEqual(snake_case('plain'), 'plain')
        self.assertEqual(snake_case('A'), 'a')

    def test_truncate_words(self):
        self.assertEqual(ledger.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(ledger.truncate_words('tea time', 2), 'tea time')
