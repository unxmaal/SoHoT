import unittest

from wharf import sensors


class Sensors(unittest.TestCase):
    def test_crate_figure(self):
        self.assertEqual(sensors.crate_figure(0), {'crate_figure': '$0.00'})
        self.assertEqual(sensors.crate_figure(123456), {'crate_figure': '$1,234.56'})

    def test_snake_case(self):
        self.assertEqual(sensors.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(sensors.snake_case('plain'), 'plain')

    def test_merge_ranges(self):
        self.assertEqual(sensors.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(sensors.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
