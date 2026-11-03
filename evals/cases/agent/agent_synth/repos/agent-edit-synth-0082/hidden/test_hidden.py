import unittest

from compass import rosters
from compass import shipping
from compass import routes
from compass import sensors


class Hidden(unittest.TestCase):
    def test_rosters_format_cents(self):
        self.assertEqual(rosters.format_cents(0), '$0.00')
        self.assertEqual(rosters.format_cents(123456), '$1,234.56')
        self.assertEqual(rosters.format_cents(-105), '-$1.05')
        self.assertEqual(rosters.format_cents(5), '$0.05')
        self.assertEqual(rosters.format_cents(100000000), '$1,000,000.00')

    def test_rosters_running_total(self):
        self.assertEqual(rosters.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(rosters.running_total([]), [])
        self.assertEqual(rosters.running_total([5]), [5])
        self.assertEqual(rosters.running_total([2, -2, 2]), [2, 0, 2])

    def test_shipping_grade(self):
        self.assertEqual(shipping.grade(95), 'A')
        self.assertEqual(shipping.grade(90), 'A')
        self.assertEqual(shipping.grade(85), 'B')
        self.assertEqual(shipping.grade(80), 'B')
        self.assertEqual(shipping.grade(61), 'D')
        self.assertEqual(shipping.grade(59), 'F')
        self.assertEqual(shipping.grade(0), 'F')

    def test_shipping_bucket(self):
        self.assertEqual(shipping.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(shipping.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(shipping.bucket(12, [0, 5, 10]), 3)
        self.assertEqual(shipping.bucket(0, [0, 5, 10]), 1)
        self.assertEqual(shipping.bucket(7, []), 0)

    def test_shipping_truncate_words(self):
        self.assertEqual(shipping.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(shipping.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(shipping.truncate_words('', 3), '')
        self.assertEqual(shipping.truncate_words('one two three', 1), 'one...')

    def test_routes_luhn_valid(self):
        self.assertEqual(routes.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(routes.luhn_valid('79927398713'), True)
        self.assertEqual(routes.luhn_valid('79927398710'), False)
        self.assertEqual(routes.luhn_valid(''), False)
        self.assertEqual(routes.luhn_valid('059'), True)

    def test_routes_word_count(self):
        self.assertEqual(routes.word_count('a b'), 2)
        self.assertEqual(routes.word_count('  tea  and   milk '), 3)
        self.assertEqual(routes.word_count(''), 0)
        self.assertEqual(routes.word_count('one'), 1)

    def test_routes_parse_duration(self):
        self.assertEqual(routes.parse_duration('1h30m'), 5400)
        self.assertEqual(routes.parse_duration('45s'), 45)
        self.assertEqual(routes.parse_duration('2h'), 7200)
        self.assertEqual(routes.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            routes.parse_duration('')
        with self.assertRaises(ValueError):
            routes.parse_duration('5x')
        self.assertEqual(routes.parse_duration('10m5s'), 605)

    def test_sensors_is_leap(self):
        self.assertEqual(sensors.is_leap(2024), True)
        self.assertEqual(sensors.is_leap(1900), False)
        self.assertEqual(sensors.is_leap(2000), True)
        self.assertEqual(sensors.is_leap(2023), False)
        self.assertEqual(sensors.is_leap(2400), True)
        self.assertEqual(sensors.is_leap(2100), False)

    def test_sensors_weighted_mean(self):
        self.assertEqual(sensors.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(sensors.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(sensors.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            sensors.weighted_mean([5, 5], [0, 0])
        self.assertEqual(sensors.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_sensors_percent_change(self):
        self.assertEqual(sensors.percent_change(50, 75), 50.0)
        self.assertEqual(sensors.percent_change(200, 150), -25.0)
        self.assertEqual(sensors.percent_change(80, 80), 0.0)
        self.assertEqual(sensors.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            sensors.percent_change(0, 5)
        self.assertEqual(sensors.percent_change(-10, -5), -50.0)

    def test_feature(self):
        self.assertEqual(shipping.grade(88, plus=True), 'B+')
        self.assertEqual(shipping.grade(95, plus=True), 'A')
        self.assertEqual(shipping.grade(86, plus=True), 'B')
        self.assertEqual(shipping.grade(69, plus=True), 'D+')
