import unittest

from foundry import budget
from foundry import ledger
from foundry import sensors
from foundry import fleet


class Hidden(unittest.TestCase):
    def test_budget_format_cents(self):
        self.assertEqual(budget.format_cents(0), '$0.00')
        self.assertEqual(budget.format_cents(123456), '$1,234.56')
        self.assertEqual(budget.format_cents(-105), '-$1.05')
        self.assertEqual(budget.format_cents(5), '$0.05')
        self.assertEqual(budget.format_cents(100000000), '$1,000,000.00')

    def test_budget_merge_ranges(self):
        self.assertEqual(budget.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(budget.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(budget.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(budget.merge_ranges([]), [])
        self.assertEqual(budget.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_budget_bucket(self):
        self.assertEqual(budget.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(budget.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(budget.bucket(12, [0, 5, 10]), 3)
        self.assertEqual(budget.bucket(0, [0, 5, 10]), 1)
        self.assertEqual(budget.bucket(7, []), 0)

    def test_ledger_word_count(self):
        self.assertEqual(ledger.word_count('a b'), 2)
        self.assertEqual(ledger.word_count('  tea  and   milk '), 3)
        self.assertEqual(ledger.word_count(''), 0)
        self.assertEqual(ledger.word_count('one'), 1)

    def test_ledger_median(self):
        self.assertEqual(ledger.median([3, 1, 2]), 2)
        self.assertEqual(ledger.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(ledger.median([5]), 5)
        self.assertEqual(ledger.median([1, 2]), 1.5)
        self.assertEqual(ledger.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            ledger.median([])

    def test_ledger_truncate_words(self):
        self.assertEqual(ledger.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(ledger.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(ledger.truncate_words('', 3), '')
        self.assertEqual(ledger.truncate_words('one two three', 1), 'one...')

    def test_sensors_chunk(self):
        self.assertEqual(sensors.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(sensors.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(sensors.chunk([], 3), [])
        self.assertEqual(sensors.chunk(['a'], 1), [['a']])
        self.assertEqual(sensors.chunk([1, 2, 3], 5), [[1, 2, 3]])
        with self.assertRaises(ValueError):
            sensors.chunk([1, 2], 0)

    def test_sensors_clamp(self):
        self.assertEqual(sensors.clamp(5, 0, 10), 5)
        self.assertEqual(sensors.clamp(-3, 0, 10), 0)
        self.assertEqual(sensors.clamp(15, 0, 10), 10)
        self.assertEqual(sensors.clamp(10, 0, 10), 10)
        self.assertEqual(sensors.clamp(0, 0, 10), 0)
        self.assertEqual(sensors.clamp(7, 7, 7), 7)
        self.assertEqual(sensors.clamp(-20, -30, -10), -20)

    def test_sensors_luhn_valid(self):
        self.assertEqual(sensors.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(sensors.luhn_valid('79927398713'), True)
        self.assertEqual(sensors.luhn_valid('79927398710'), False)
        self.assertEqual(sensors.luhn_valid(''), False)
        self.assertEqual(sensors.luhn_valid('059'), True)

    def test_fleet_invert(self):
        self.assertEqual(fleet.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(fleet.invert({}), {})
        self.assertEqual(fleet.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(fleet.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_fleet_parse_duration(self):
        self.assertEqual(fleet.parse_duration('1h30m'), 5400)
        self.assertEqual(fleet.parse_duration('45s'), 45)
        self.assertEqual(fleet.parse_duration('2h'), 7200)
        self.assertEqual(fleet.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            fleet.parse_duration('')
        with self.assertRaises(ValueError):
            fleet.parse_duration('5x')
        self.assertEqual(fleet.parse_duration('10m5s'), 605)

    def test_feature(self):
        self.assertEqual(budget.merge_ranges([(1, 2), (3, 4)]), [(1, 4)])
        self.assertEqual(budget.merge_ranges([(7, 9), (1, 6)]), [(1, 9)])
