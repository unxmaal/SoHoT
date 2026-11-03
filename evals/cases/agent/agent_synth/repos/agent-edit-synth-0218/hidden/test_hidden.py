import unittest

from depot import budget
from depot import catalog
from depot import weather


class Hidden(unittest.TestCase):
    def test_budget_luhn_valid(self):
        self.assertEqual(budget.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(budget.luhn_valid('79927398713'), True)
        self.assertEqual(budget.luhn_valid('79927398710'), False)
        self.assertEqual(budget.luhn_valid(''), False)
        self.assertEqual(budget.luhn_valid('059'), True)

    def test_budget_dedupe(self):
        self.assertEqual(budget.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(budget.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(budget.dedupe([]), [])
        self.assertEqual(budget.dedupe([1, 1, 1]), [1])

    def test_catalog_percent_change(self):
        self.assertEqual(catalog.percent_change(50, 75), 50.0)
        self.assertEqual(catalog.percent_change(200, 150), -25.0)
        self.assertEqual(catalog.percent_change(80, 80), 0.0)
        self.assertEqual(catalog.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            catalog.percent_change(0, 5)
        self.assertEqual(catalog.percent_change(-10, -5), -50.0)

    def test_catalog_grade(self):
        self.assertEqual(catalog.grade(95), 'A')
        self.assertEqual(catalog.grade(90), 'A')
        self.assertEqual(catalog.grade(85), 'B')
        self.assertEqual(catalog.grade(80), 'B')
        self.assertEqual(catalog.grade(61), 'D')
        self.assertEqual(catalog.grade(59), 'F')
        self.assertEqual(catalog.grade(0), 'F')

    def test_catalog_running_total(self):
        self.assertEqual(catalog.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(catalog.running_total([]), [])
        self.assertEqual(catalog.running_total([5]), [5])
        self.assertEqual(catalog.running_total([2, -2, 2]), [2, 0, 2])

    def test_weather_parse_duration(self):
        self.assertEqual(weather.parse_duration('1h30m'), 5400)
        self.assertEqual(weather.parse_duration('45s'), 45)
        self.assertEqual(weather.parse_duration('2h'), 7200)
        self.assertEqual(weather.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            weather.parse_duration('')
        with self.assertRaises(ValueError):
            weather.parse_duration('5x')
        self.assertEqual(weather.parse_duration('10m5s'), 605)

    def test_weather_merge_ranges(self):
        self.assertEqual(weather.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(weather.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(weather.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(weather.merge_ranges([]), [])
        self.assertEqual(weather.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_feature(self):
        self.assertEqual(catalog.running_total([1, 2], start=10), [11, 13])
        self.assertEqual(catalog.running_total([], start=4), [])
        self.assertEqual(catalog.running_total([3], start=-3), [0])
