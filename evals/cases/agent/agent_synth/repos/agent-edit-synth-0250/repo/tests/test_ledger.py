import unittest

from wharf import ledger


class Ledger(unittest.TestCase):
    def test_invert(self):
        self.assertEqual(ledger.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(ledger.invert({}), {})
        self.assertEqual(ledger.invert({'x': 'y'}), {'y': ['x']})

    def test_parse_duration(self):
        self.assertEqual(ledger.parse_duration('1h30m'), 5400)
        self.assertEqual(ledger.parse_duration('45s'), 45)
        self.assertEqual(ledger.parse_duration('2h'), 7200)

    def test_running_total(self):
        self.assertEqual(ledger.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(ledger.running_total([]), [])
        self.assertEqual(ledger.running_total([5]), [5])
