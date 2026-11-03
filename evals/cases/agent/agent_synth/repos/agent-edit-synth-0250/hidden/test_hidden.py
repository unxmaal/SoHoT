import unittest

from wharf import budget
from wharf import fleet
from wharf import ledger


class Hidden(unittest.TestCase):
    def test_budget_grade(self):
        self.assertEqual(budget.grade(95), 'A')
        self.assertEqual(budget.grade(90), 'A')
        self.assertEqual(budget.grade(85), 'B')
        self.assertEqual(budget.grade(80), 'B')
        self.assertEqual(budget.grade(61), 'D')
        self.assertEqual(budget.grade(59), 'F')
        self.assertEqual(budget.grade(0), 'F')

    def test_budget_truncate_words(self):
        self.assertEqual(budget.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(budget.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(budget.truncate_words('', 3), '')
        self.assertEqual(budget.truncate_words('one two three', 1), 'one...')

    def test_fleet_dedupe(self):
        self.assertEqual(fleet.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(fleet.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(fleet.dedupe([]), [])
        self.assertEqual(fleet.dedupe([1, 1, 1]), [1])

    def test_fleet_bucket(self):
        self.assertEqual(fleet.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(fleet.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(fleet.bucket(12, [0, 5, 10]), 3)
        self.assertEqual(fleet.bucket(0, [0, 5, 10]), 1)
        self.assertEqual(fleet.bucket(7, []), 0)

    def test_ledger_invert(self):
        self.assertEqual(ledger.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(ledger.invert({}), {})
        self.assertEqual(ledger.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(ledger.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_ledger_parse_duration(self):
        self.assertEqual(ledger.parse_duration('1h30m'), 5400)
        self.assertEqual(ledger.parse_duration('45s'), 45)
        self.assertEqual(ledger.parse_duration('2h'), 7200)
        self.assertEqual(ledger.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            ledger.parse_duration('')
        with self.assertRaises(ValueError):
            ledger.parse_duration('5x')
        self.assertEqual(ledger.parse_duration('10m5s'), 605)

    def test_ledger_running_total(self):
        self.assertEqual(ledger.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(ledger.running_total([]), [])
        self.assertEqual(ledger.running_total([5]), [5])
        self.assertEqual(ledger.running_total([2, -2, 2]), [2, 0, 2])

    def test_feature(self):
        self.assertEqual(budget.truncate_words('the quick brown fox', 1, ellipsis=' [more]'), 'the [more]')
