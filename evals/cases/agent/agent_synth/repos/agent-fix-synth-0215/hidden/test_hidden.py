import unittest

from orchard import shipping
from orchard import ledger
from orchard import sensors
from orchard import survey
from orchard import report


class Hidden(unittest.TestCase):
    def test_shipping_format_cents(self):
        self.assertEqual(shipping.format_cents(0), '$0.00')
        self.assertEqual(shipping.format_cents(123456), '$1,234.56')
        self.assertEqual(shipping.format_cents(-105), '-$1.05')
        self.assertEqual(shipping.format_cents(5), '$0.05')
        self.assertEqual(shipping.format_cents(100000000), '$1,000,000.00')

    def test_shipping_is_leap(self):
        self.assertEqual(shipping.is_leap(2024), True)
        self.assertEqual(shipping.is_leap(1900), False)
        self.assertEqual(shipping.is_leap(2000), True)
        self.assertEqual(shipping.is_leap(2023), False)
        self.assertEqual(shipping.is_leap(2400), True)
        self.assertEqual(shipping.is_leap(2100), False)

    def test_shipping_chunk(self):
        self.assertEqual(shipping.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(shipping.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(shipping.chunk([], 3), [])
        self.assertEqual(shipping.chunk(['a'], 1), [['a']])
        self.assertEqual(shipping.chunk([1, 2, 3], 5), [[1, 2, 3]])
        with self.assertRaises(ValueError):
            shipping.chunk([1, 2], 0)

    def test_ledger_percent_change(self):
        self.assertEqual(ledger.percent_change(50, 75), 50.0)
        self.assertEqual(ledger.percent_change(200, 150), -25.0)
        self.assertEqual(ledger.percent_change(80, 80), 0.0)
        self.assertEqual(ledger.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            ledger.percent_change(0, 5)
        self.assertEqual(ledger.percent_change(-10, -5), -50.0)

    def test_ledger_top_n(self):
        self.assertEqual(ledger.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(ledger.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(ledger.top_n({}, 2), [])
        self.assertEqual(ledger.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])

    def test_ledger_luhn_valid(self):
        self.assertEqual(ledger.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(ledger.luhn_valid('79927398713'), True)
        self.assertEqual(ledger.luhn_valid('79927398710'), False)
        self.assertEqual(ledger.luhn_valid(''), False)
        self.assertEqual(ledger.luhn_valid('059'), True)

    def test_sensors_rle(self):
        self.assertEqual(sensors.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(sensors.rle(''), [])
        self.assertEqual(sensors.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(sensors.rle('zz'), [('z', 2)])

    def test_sensors_grade(self):
        self.assertEqual(sensors.grade(95), 'A')
        self.assertEqual(sensors.grade(90), 'A')
        self.assertEqual(sensors.grade(85), 'B')
        self.assertEqual(sensors.grade(80), 'B')
        self.assertEqual(sensors.grade(61), 'D')
        self.assertEqual(sensors.grade(59), 'F')
        self.assertEqual(sensors.grade(0), 'F')

    def test_survey_median(self):
        self.assertEqual(survey.median([3, 1, 2]), 2)
        self.assertEqual(survey.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(survey.median([5]), 5)
        self.assertEqual(survey.median([1, 2]), 1.5)
        self.assertEqual(survey.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            survey.median([])

    def test_survey_moving_average(self):
        self.assertEqual(survey.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(survey.moving_average([5], 1), [5.0])
        self.assertEqual(survey.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(survey.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            survey.moving_average([1, 2], 0)

    def test_survey_weighted_mean(self):
        self.assertEqual(survey.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(survey.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(survey.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            survey.weighted_mean([5, 5], [0, 0])
        self.assertEqual(survey.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_report_keel_entry(self):
        self.assertEqual(report.keel_entry(0), {'keel_entry': '$0.00'})
        self.assertEqual(report.keel_entry(123456), {'keel_entry': '$1,234.56'})
        self.assertEqual(report.keel_entry(-105), {'keel_entry': '-$1.05'})
        self.assertEqual(report.keel_entry(5), {'keel_entry': '$0.05'})
        self.assertEqual(report.keel_entry(100000000), {'keel_entry': '$1,000,000.00'})

    def test_report_crate_line(self):
        self.assertEqual(report.crate_line(2024), {'crate_line': True})
        self.assertEqual(report.crate_line(1900), {'crate_line': False})
        self.assertEqual(report.crate_line(2000), {'crate_line': True})
        self.assertEqual(report.crate_line(2023), {'crate_line': False})
        self.assertEqual(report.crate_line(2400), {'crate_line': True})
        self.assertEqual(report.crate_line(2100), {'crate_line': False})

    def test_report_pallet_check(self):
        self.assertEqual(report.pallet_check([1, 2, 3, 4, 5], 2), {'pallet_check': [[1, 2], [3, 4], [5]]})
        self.assertEqual(report.pallet_check([1, 2, 3, 4], 2), {'pallet_check': [[1, 2], [3, 4]]})
        self.assertEqual(report.pallet_check([], 3), {'pallet_check': []})
        self.assertEqual(report.pallet_check(['a'], 1), {'pallet_check': [['a']]})
        self.assertEqual(report.pallet_check([1, 2, 3], 5), {'pallet_check': [[1, 2, 3]]})
        with self.assertRaises(ValueError):
            report.pallet_check([1, 2], 0)

    def test_report_hull_entry(self):
        self.assertEqual(report.hull_entry(50, 75), {'hull_entry': 50.0})
        self.assertEqual(report.hull_entry(200, 150), {'hull_entry': -25.0})
        self.assertEqual(report.hull_entry(80, 80), {'hull_entry': 0.0})
        self.assertEqual(report.hull_entry(3, 4), {'hull_entry': 33.33})
        with self.assertRaises(ValueError):
            report.hull_entry(0, 5)
        self.assertEqual(report.hull_entry(-10, -5), {'hull_entry': -50.0})

    def test_report_barge_total(self):
        self.assertEqual(report.barge_total([3, 1, 2]), {'barge_total': 2})
        self.assertEqual(report.barge_total([4, 1, 3, 2]), {'barge_total': 2.5})
        self.assertEqual(report.barge_total([5]), {'barge_total': 5})
        self.assertEqual(report.barge_total([1, 2]), {'barge_total': 1.5})
        self.assertEqual(report.barge_total([10, 2, 38, 23, 38, 23]), {'barge_total': 23.0})
        with self.assertRaises(ValueError):
            report.barge_total([])
