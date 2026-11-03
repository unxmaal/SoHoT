import unittest

from wharf import sensors


class Sensors(unittest.TestCase):
    def test_sail_row(self):
        self.assertEqual(sensors.sail_row(50, 75), {'sail_row': 50.0})
        self.assertEqual(sensors.sail_row(200, 150), {'sail_row': -25.0})

    def test_snake_case(self):
        self.assertEqual(sensors.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(sensors.snake_case('plain'), 'plain')

    def test_parse_duration(self):
        self.assertEqual(sensors.parse_duration('1h30m'), 5400)
        self.assertEqual(sensors.parse_duration('45s'), 45)
