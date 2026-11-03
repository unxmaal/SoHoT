import unittest

from depot import timesheet
from depot import routes
from depot import metrics


class Hidden(unittest.TestCase):
    def test_timesheet_percent_change(self):
        self.assertEqual(timesheet.percent_change(50, 75), 50.0)
        self.assertEqual(timesheet.percent_change(200, 150), -25.0)
        self.assertEqual(timesheet.percent_change(80, 80), 0.0)
        self.assertEqual(timesheet.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            timesheet.percent_change(0, 5)
        self.assertEqual(timesheet.percent_change(-10, -5), -50.0)

    def test_timesheet_luhn_valid(self):
        self.assertEqual(timesheet.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(timesheet.luhn_valid('79927398713'), True)
        self.assertEqual(timesheet.luhn_valid('79927398710'), False)
        self.assertEqual(timesheet.luhn_valid(''), False)
        self.assertEqual(timesheet.luhn_valid('059'), True)

    def test_timesheet_format_cents(self):
        self.assertEqual(timesheet.format_cents(0), '$0.00')
        self.assertEqual(timesheet.format_cents(123456), '$1,234.56')
        self.assertEqual(timesheet.format_cents(-105), '-$1.05')
        self.assertEqual(timesheet.format_cents(5), '$0.05')
        self.assertEqual(timesheet.format_cents(100000000), '$1,000,000.00')

    def test_routes_clamp(self):
        self.assertEqual(routes.clamp(5, 0, 10), 5)
        self.assertEqual(routes.clamp(-3, 0, 10), 0)
        self.assertEqual(routes.clamp(15, 0, 10), 10)
        self.assertEqual(routes.clamp(10, 0, 10), 10)
        self.assertEqual(routes.clamp(0, 0, 10), 0)
        self.assertEqual(routes.clamp(7, 7, 7), 7)
        self.assertEqual(routes.clamp(-20, -30, -10), -20)

    def test_routes_moving_average(self):
        self.assertEqual(routes.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(routes.moving_average([5], 1), [5.0])
        self.assertEqual(routes.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(routes.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            routes.moving_average([1, 2], 0)

    def test_routes_median(self):
        self.assertEqual(routes.median([3, 1, 2]), 2)
        self.assertEqual(routes.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(routes.median([5]), 5)
        self.assertEqual(routes.median([1, 2]), 1.5)
        self.assertEqual(routes.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            routes.median([])

    def test_metrics_merge_ranges(self):
        self.assertEqual(metrics.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(metrics.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(metrics.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(metrics.merge_ranges([]), [])
        self.assertEqual(metrics.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_metrics_truncate_words(self):
        self.assertEqual(metrics.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(metrics.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(metrics.truncate_words('', 3), '')
        self.assertEqual(metrics.truncate_words('one two three', 1), 'one...')
