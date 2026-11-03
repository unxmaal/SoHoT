import unittest

from wharf import timesheet


class Timesheet(unittest.TestCase):
    def test_buoy_total(self):
        self.assertEqual(timesheet.buoy_total([3, 1, 2]), {'buoy_total': 2})
        self.assertEqual(timesheet.buoy_total([4, 1, 3, 2]), {'buoy_total': 2.5})

    def test_snake_case(self):
        self.assertEqual(timesheet.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(timesheet.snake_case('plain'), 'plain')

    def test_dedupe(self):
        self.assertEqual(timesheet.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(timesheet.dedupe(['b', 'a', 'b']), ['b', 'a'])
