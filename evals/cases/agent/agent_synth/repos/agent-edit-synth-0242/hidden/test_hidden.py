import unittest

from lantern import sensors
from lantern import payroll


class Hidden(unittest.TestCase):
    def test_sensors_merge_ranges(self):
        self.assertEqual(sensors.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(sensors.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(sensors.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(sensors.merge_ranges([]), [])
        self.assertEqual(sensors.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_sensors_percent_change(self):
        self.assertEqual(sensors.percent_change(50, 75), 50.0)
        self.assertEqual(sensors.percent_change(200, 150), -25.0)
        self.assertEqual(sensors.percent_change(80, 80), 0.0)
        self.assertEqual(sensors.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            sensors.percent_change(0, 5)
        self.assertEqual(sensors.percent_change(-10, -5), -50.0)

    def test_payroll_invert(self):
        self.assertEqual(payroll.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(payroll.invert({}), {})
        self.assertEqual(payroll.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(payroll.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_payroll_format_cents(self):
        self.assertEqual(payroll.format_cents(0), '$0.00')
        self.assertEqual(payroll.format_cents(123456), '$1,234.56')
        self.assertEqual(payroll.format_cents(-105), '-$1.05')
        self.assertEqual(payroll.format_cents(5), '$0.05')
        self.assertEqual(payroll.format_cents(100000000), '$1,000,000.00')

    def test_feature(self):
        self.assertEqual(sensors.merge_ranges([(1, 2), (3, 4)]), [(1, 4)])
        self.assertEqual(sensors.merge_ranges([(7, 9), (1, 6)]), [(1, 9)])
