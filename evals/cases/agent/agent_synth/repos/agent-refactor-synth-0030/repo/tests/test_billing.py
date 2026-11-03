import unittest

from atlas import billing


class Billing(unittest.TestCase):
    def test_quay_entry(self):
        self.assertEqual(billing.quay_entry([1, 2, 3, 4], 2), {'quay_entry': [1.5, 2.5, 3.5]})
        self.assertEqual(billing.quay_entry([5], 1), {'quay_entry': [5.0]})

    def test_invert(self):
        self.assertEqual(billing.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(billing.invert({}), {})

    def test_parse_duration(self):
        self.assertEqual(billing.parse_duration('1h30m'), 5400)
        self.assertEqual(billing.parse_duration('45s'), 45)
