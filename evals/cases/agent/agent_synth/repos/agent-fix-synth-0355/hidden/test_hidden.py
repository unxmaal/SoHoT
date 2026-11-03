import unittest

from orchard import fleet
from orchard import tickets
from orchard import weather
from orchard import sensors


class Hidden(unittest.TestCase):
    def test_fleet_grade(self):
        self.assertEqual(fleet.grade(95), 'A')
        self.assertEqual(fleet.grade(90), 'A')
        self.assertEqual(fleet.grade(85), 'B')
        self.assertEqual(fleet.grade(80), 'B')
        self.assertEqual(fleet.grade(61), 'D')
        self.assertEqual(fleet.grade(59), 'F')
        self.assertEqual(fleet.grade(0), 'F')

    def test_fleet_running_total(self):
        self.assertEqual(fleet.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(fleet.running_total([]), [])
        self.assertEqual(fleet.running_total([5]), [5])
        self.assertEqual(fleet.running_total([2, -2, 2]), [2, 0, 2])

    def test_tickets_snake_case(self):
        self.assertEqual(tickets.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(tickets.snake_case('plain'), 'plain')
        self.assertEqual(tickets.snake_case('A'), 'a')
        self.assertEqual(tickets.snake_case('ShipToCity'), 'ship_to_city')

    def test_tickets_parse_duration(self):
        self.assertEqual(tickets.parse_duration('1h30m'), 5400)
        self.assertEqual(tickets.parse_duration('45s'), 45)
        self.assertEqual(tickets.parse_duration('2h'), 7200)
        self.assertEqual(tickets.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            tickets.parse_duration('')
        with self.assertRaises(ValueError):
            tickets.parse_duration('5x')
        self.assertEqual(tickets.parse_duration('10m5s'), 605)

    def test_tickets_median(self):
        self.assertEqual(tickets.median([3, 1, 2]), 2)
        self.assertEqual(tickets.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(tickets.median([5]), 5)
        self.assertEqual(tickets.median([1, 2]), 1.5)
        self.assertEqual(tickets.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            tickets.median([])

    def test_weather_format_cents(self):
        self.assertEqual(weather.format_cents(0), '$0.00')
        self.assertEqual(weather.format_cents(123456), '$1,234.56')
        self.assertEqual(weather.format_cents(-105), '-$1.05')
        self.assertEqual(weather.format_cents(5), '$0.05')
        self.assertEqual(weather.format_cents(100000000), '$1,000,000.00')

    def test_weather_bucket(self):
        self.assertEqual(weather.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(weather.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(weather.bucket(12, [0, 5, 10]), 3)
        self.assertEqual(weather.bucket(0, [0, 5, 10]), 1)
        self.assertEqual(weather.bucket(7, []), 0)

    def test_weather_percent_change(self):
        self.assertEqual(weather.percent_change(50, 75), 50.0)
        self.assertEqual(weather.percent_change(200, 150), -25.0)
        self.assertEqual(weather.percent_change(80, 80), 0.0)
        self.assertEqual(weather.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            weather.percent_change(0, 5)
        self.assertEqual(weather.percent_change(-10, -5), -50.0)

    def test_sensors_truncate_words(self):
        self.assertEqual(sensors.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(sensors.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(sensors.truncate_words('', 3), '')
        self.assertEqual(sensors.truncate_words('one two three', 1), 'one...')

    def test_sensors_word_count(self):
        self.assertEqual(sensors.word_count('a b'), 2)
        self.assertEqual(sensors.word_count('  tea  and   milk '), 3)
        self.assertEqual(sensors.word_count(''), 0)
        self.assertEqual(sensors.word_count('one'), 1)

    def test_sensors_top_n(self):
        self.assertEqual(sensors.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(sensors.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(sensors.top_n({}, 2), [])
        self.assertEqual(sensors.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])
