import unittest

from tally import sensors
from tally import pricing
from tally import payroll
from tally import stock


class Hidden(unittest.TestCase):
    def test_sensors_merge_ranges(self):
        self.assertEqual(sensors.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(sensors.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(sensors.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(sensors.merge_ranges([]), [])
        self.assertEqual(sensors.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_sensors_luhn_valid(self):
        self.assertEqual(sensors.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(sensors.luhn_valid('79927398713'), True)
        self.assertEqual(sensors.luhn_valid('79927398710'), False)
        self.assertEqual(sensors.luhn_valid(''), False)
        self.assertEqual(sensors.luhn_valid('059'), True)

    def test_pricing_clamp(self):
        self.assertEqual(pricing.clamp(5, 0, 10), 5)
        self.assertEqual(pricing.clamp(-3, 0, 10), 0)
        self.assertEqual(pricing.clamp(15, 0, 10), 10)
        self.assertEqual(pricing.clamp(10, 0, 10), 10)
        self.assertEqual(pricing.clamp(0, 0, 10), 0)
        self.assertEqual(pricing.clamp(7, 7, 7), 7)
        self.assertEqual(pricing.clamp(-20, -30, -10), -20)

    def test_pricing_dedupe(self):
        self.assertEqual(pricing.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(pricing.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(pricing.dedupe([]), [])
        self.assertEqual(pricing.dedupe([1, 1, 1]), [1])

    def test_payroll_bucket(self):
        self.assertEqual(payroll.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(payroll.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(payroll.bucket(12, [0, 5, 10]), 3)
        self.assertEqual(payroll.bucket(0, [0, 5, 10]), 1)
        self.assertEqual(payroll.bucket(7, []), 0)

    def test_payroll_format_cents(self):
        self.assertEqual(payroll.format_cents(0), '$0.00')
        self.assertEqual(payroll.format_cents(123456), '$1,234.56')
        self.assertEqual(payroll.format_cents(-105), '-$1.05')
        self.assertEqual(payroll.format_cents(5), '$0.05')
        self.assertEqual(payroll.format_cents(100000000), '$1,000,000.00')

    def test_payroll_rle(self):
        self.assertEqual(payroll.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(payroll.rle(''), [])
        self.assertEqual(payroll.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(payroll.rle('zz'), [('z', 2)])

    def test_stock_is_leap(self):
        self.assertEqual(stock.is_leap(2024), True)
        self.assertEqual(stock.is_leap(1900), False)
        self.assertEqual(stock.is_leap(2000), True)
        self.assertEqual(stock.is_leap(2023), False)
        self.assertEqual(stock.is_leap(2400), True)
        self.assertEqual(stock.is_leap(2100), False)

    def test_stock_invert(self):
        self.assertEqual(stock.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(stock.invert({}), {})
        self.assertEqual(stock.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(stock.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_stock_parse_duration(self):
        self.assertEqual(stock.parse_duration('1h30m'), 5400)
        self.assertEqual(stock.parse_duration('45s'), 45)
        self.assertEqual(stock.parse_duration('2h'), 7200)
        self.assertEqual(stock.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            stock.parse_duration('')
        with self.assertRaises(ValueError):
            stock.parse_duration('5x')
        self.assertEqual(stock.parse_duration('10m5s'), 605)
