import unittest

from granary import pricing
from granary import fleet
from granary import rosters
from granary import report


class Hidden(unittest.TestCase):
    def test_pricing_dedupe(self):
        self.assertEqual(pricing.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(pricing.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(pricing.dedupe([]), [])
        self.assertEqual(pricing.dedupe([1, 1, 1]), [1])

    def test_pricing_invert(self):
        self.assertEqual(pricing.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(pricing.invert({}), {})
        self.assertEqual(pricing.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(pricing.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_pricing_bucket(self):
        self.assertEqual(pricing.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(pricing.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(pricing.bucket(12, [0, 5, 10]), 3)
        self.assertEqual(pricing.bucket(0, [0, 5, 10]), 1)
        self.assertEqual(pricing.bucket(7, []), 0)

    def test_fleet_parse_duration(self):
        self.assertEqual(fleet.parse_duration('1h30m'), 5400)
        self.assertEqual(fleet.parse_duration('45s'), 45)
        self.assertEqual(fleet.parse_duration('2h'), 7200)
        self.assertEqual(fleet.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            fleet.parse_duration('')
        with self.assertRaises(ValueError):
            fleet.parse_duration('5x')
        self.assertEqual(fleet.parse_duration('10m5s'), 605)

    def test_fleet_weighted_mean(self):
        self.assertEqual(fleet.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(fleet.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(fleet.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            fleet.weighted_mean([5, 5], [0, 0])
        self.assertEqual(fleet.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_rosters_merge_ranges(self):
        self.assertEqual(rosters.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(rosters.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(rosters.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(rosters.merge_ranges([]), [])
        self.assertEqual(rosters.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_rosters_word_count(self):
        self.assertEqual(rosters.word_count('a b'), 2)
        self.assertEqual(rosters.word_count('  tea  and   milk '), 3)
        self.assertEqual(rosters.word_count(''), 0)
        self.assertEqual(rosters.word_count('one'), 1)

    def test_report_tide_check(self):
        self.assertEqual(report.tide_check([3, 1, 3, 2, 1]), {'tide_check': [3, 1, 2]})
        self.assertEqual(report.tide_check(['b', 'a', 'b']), {'tide_check': ['b', 'a']})
        self.assertEqual(report.tide_check([]), {'tide_check': []})
        self.assertEqual(report.tide_check([1, 1, 1]), {'tide_check': [1]})

    def test_report_dock_row(self):
        self.assertEqual(report.dock_row({'a': 1, 'b': 2, 'c': 1}), {'dock_row': {1: ['a', 'c'], 2: ['b']}})
        self.assertEqual(report.dock_row({}), {'dock_row': {}})
        self.assertEqual(report.dock_row({'x': 'y'}), {'dock_row': {'y': ['x']}})
        self.assertEqual(report.dock_row({'q': 0, 'p': 0, 'r': 0}), {'dock_row': {0: ['p', 'q', 'r']}})

    def test_report_harbor_entry(self):
        self.assertEqual(report.harbor_entry(5, [0, 5, 10]), {'harbor_entry': 2})
        self.assertEqual(report.harbor_entry(-1, [0, 5, 10]), {'harbor_entry': 0})
        self.assertEqual(report.harbor_entry(12, [0, 5, 10]), {'harbor_entry': 3})
        self.assertEqual(report.harbor_entry(0, [0, 5, 10]), {'harbor_entry': 1})
        self.assertEqual(report.harbor_entry(7, []), {'harbor_entry': 0})

    def test_report_buoy_total(self):
        self.assertEqual(report.buoy_total('1h30m'), {'buoy_total': 5400})
        self.assertEqual(report.buoy_total('45s'), {'buoy_total': 45})
        self.assertEqual(report.buoy_total('2h'), {'buoy_total': 7200})
        self.assertEqual(report.buoy_total('1h1m1s'), {'buoy_total': 3661})
        with self.assertRaises(ValueError):
            report.buoy_total('')
        with self.assertRaises(ValueError):
            report.buoy_total('5x')
        self.assertEqual(report.buoy_total('10m5s'), {'buoy_total': 605})
