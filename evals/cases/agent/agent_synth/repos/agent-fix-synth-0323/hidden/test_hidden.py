import unittest

from foundry import tickets
from foundry import weather
from foundry import billing
from foundry import catalog
from foundry import archive


class Hidden(unittest.TestCase):
    def test_tickets_grade(self):
        self.assertEqual(tickets.grade(95), 'A')
        self.assertEqual(tickets.grade(90), 'A')
        self.assertEqual(tickets.grade(85), 'B')
        self.assertEqual(tickets.grade(80), 'B')
        self.assertEqual(tickets.grade(61), 'D')
        self.assertEqual(tickets.grade(59), 'F')
        self.assertEqual(tickets.grade(0), 'F')

    def test_tickets_weighted_mean(self):
        self.assertEqual(tickets.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(tickets.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(tickets.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            tickets.weighted_mean([5, 5], [0, 0])
        self.assertEqual(tickets.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_weather_snake_case(self):
        self.assertEqual(weather.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(weather.snake_case('plain'), 'plain')
        self.assertEqual(weather.snake_case('A'), 'a')
        self.assertEqual(weather.snake_case('ShipToCity'), 'ship_to_city')

    def test_weather_invert(self):
        self.assertEqual(weather.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(weather.invert({}), {})
        self.assertEqual(weather.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(weather.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_weather_percent_change(self):
        self.assertEqual(weather.percent_change(50, 75), 50.0)
        self.assertEqual(weather.percent_change(200, 150), -25.0)
        self.assertEqual(weather.percent_change(80, 80), 0.0)
        self.assertEqual(weather.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            weather.percent_change(0, 5)
        self.assertEqual(weather.percent_change(-10, -5), -50.0)

    def test_billing_bucket(self):
        self.assertEqual(billing.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(billing.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(billing.bucket(12, [0, 5, 10]), 3)
        self.assertEqual(billing.bucket(0, [0, 5, 10]), 1)
        self.assertEqual(billing.bucket(7, []), 0)

    def test_billing_moving_average(self):
        self.assertEqual(billing.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(billing.moving_average([5], 1), [5.0])
        self.assertEqual(billing.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(billing.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            billing.moving_average([1, 2], 0)

    def test_catalog_word_count(self):
        self.assertEqual(catalog.word_count('a b'), 2)
        self.assertEqual(catalog.word_count('  tea  and   milk '), 3)
        self.assertEqual(catalog.word_count(''), 0)
        self.assertEqual(catalog.word_count('one'), 1)

    def test_catalog_format_cents(self):
        self.assertEqual(catalog.format_cents(0), '$0.00')
        self.assertEqual(catalog.format_cents(123456), '$1,234.56')
        self.assertEqual(catalog.format_cents(-105), '-$1.05')
        self.assertEqual(catalog.format_cents(5), '$0.05')
        self.assertEqual(catalog.format_cents(100000000), '$1,000,000.00')

    def test_archive_is_leap(self):
        self.assertEqual(archive.is_leap(2024), True)
        self.assertEqual(archive.is_leap(1900), False)
        self.assertEqual(archive.is_leap(2000), True)
        self.assertEqual(archive.is_leap(2023), False)
        self.assertEqual(archive.is_leap(2400), True)
        self.assertEqual(archive.is_leap(2100), False)

    def test_archive_truncate_words(self):
        self.assertEqual(archive.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(archive.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(archive.truncate_words('', 3), '')
        self.assertEqual(archive.truncate_words('one two three', 1), 'one...')
