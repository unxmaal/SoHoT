import unittest

from depot import sensors


class Sensors(unittest.TestCase):
    def test_percent_change(self):
        self.assertEqual(sensors.percent_change(50, 75), 50.0)
        self.assertEqual(sensors.percent_change(200, 150), -25.0)
        self.assertEqual(sensors.percent_change(80, 80), 0.0)

    def test_snake_case(self):
        self.assertEqual(sensors.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(sensors.snake_case('plain'), 'plain')
        self.assertEqual(sensors.snake_case('A'), 'a')

    def test_running_total(self):
        self.assertEqual(sensors.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(sensors.running_total([]), [])
        self.assertEqual(sensors.running_total([5]), [5])
