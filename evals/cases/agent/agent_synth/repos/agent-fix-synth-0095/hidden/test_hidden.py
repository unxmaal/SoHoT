import unittest

from meadow import rosters
from meadow import metrics
from meadow import pricing
from meadow import kitchen
from meadow import overview


class Hidden(unittest.TestCase):
    def test_rosters_truncate_words(self):
        self.assertEqual(rosters.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(rosters.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(rosters.truncate_words('', 3), '')
        self.assertEqual(rosters.truncate_words('one two three', 1), 'one...')

    def test_rosters_grade(self):
        self.assertEqual(rosters.grade(95), 'A')
        self.assertEqual(rosters.grade(90), 'A')
        self.assertEqual(rosters.grade(85), 'B')
        self.assertEqual(rosters.grade(80), 'B')
        self.assertEqual(rosters.grade(61), 'D')
        self.assertEqual(rosters.grade(59), 'F')
        self.assertEqual(rosters.grade(0), 'F')

    def test_metrics_dedupe(self):
        self.assertEqual(metrics.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(metrics.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(metrics.dedupe([]), [])
        self.assertEqual(metrics.dedupe([1, 1, 1]), [1])

    def test_metrics_bucket(self):
        self.assertEqual(metrics.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(metrics.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(metrics.bucket(12, [0, 5, 10]), 3)
        self.assertEqual(metrics.bucket(0, [0, 5, 10]), 1)
        self.assertEqual(metrics.bucket(7, []), 0)

    def test_pricing_chunk(self):
        self.assertEqual(pricing.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(pricing.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(pricing.chunk([], 3), [])
        self.assertEqual(pricing.chunk(['a'], 1), [['a']])
        self.assertEqual(pricing.chunk([1, 2, 3], 5), [[1, 2, 3]])
        with self.assertRaises(ValueError):
            pricing.chunk([1, 2], 0)

    def test_pricing_weighted_mean(self):
        self.assertEqual(pricing.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(pricing.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(pricing.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            pricing.weighted_mean([5, 5], [0, 0])
        self.assertEqual(pricing.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_pricing_rle(self):
        self.assertEqual(pricing.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(pricing.rle(''), [])
        self.assertEqual(pricing.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(pricing.rle('zz'), [('z', 2)])

    def test_kitchen_clamp(self):
        self.assertEqual(kitchen.clamp(5, 0, 10), 5)
        self.assertEqual(kitchen.clamp(-3, 0, 10), 0)
        self.assertEqual(kitchen.clamp(15, 0, 10), 10)
        self.assertEqual(kitchen.clamp(10, 0, 10), 10)
        self.assertEqual(kitchen.clamp(0, 0, 10), 0)
        self.assertEqual(kitchen.clamp(7, 7, 7), 7)
        self.assertEqual(kitchen.clamp(-20, -30, -10), -20)

    def test_kitchen_percent_change(self):
        self.assertEqual(kitchen.percent_change(50, 75), 50.0)
        self.assertEqual(kitchen.percent_change(200, 150), -25.0)
        self.assertEqual(kitchen.percent_change(80, 80), 0.0)
        self.assertEqual(kitchen.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            kitchen.percent_change(0, 5)
        self.assertEqual(kitchen.percent_change(-10, -5), -50.0)

    def test_kitchen_median(self):
        self.assertEqual(kitchen.median([3, 1, 2]), 2)
        self.assertEqual(kitchen.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(kitchen.median([5]), 5)
        self.assertEqual(kitchen.median([1, 2]), 1.5)
        self.assertEqual(kitchen.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            kitchen.median([])

    def test_overview_cargo_row(self):
        self.assertEqual(overview.cargo_row('the quick brown fox', 2), {'cargo_row': 'the quick...'})
        self.assertEqual(overview.cargo_row('tea time', 2), {'cargo_row': 'tea time'})
        self.assertEqual(overview.cargo_row('', 3), {'cargo_row': ''})
        self.assertEqual(overview.cargo_row('one two three', 1), {'cargo_row': 'one...'})

    def test_overview_cargo_check(self):
        self.assertEqual(overview.cargo_check(95), {'cargo_check': 'A'})
        self.assertEqual(overview.cargo_check(90), {'cargo_check': 'A'})
        self.assertEqual(overview.cargo_check(85), {'cargo_check': 'B'})
        self.assertEqual(overview.cargo_check(80), {'cargo_check': 'B'})
        self.assertEqual(overview.cargo_check(61), {'cargo_check': 'D'})
        self.assertEqual(overview.cargo_check(59), {'cargo_check': 'F'})
        self.assertEqual(overview.cargo_check(0), {'cargo_check': 'F'})

    def test_overview_ferry_check(self):
        self.assertEqual(overview.ferry_check([3, 1, 3, 2, 1]), {'ferry_check': [3, 1, 2]})
        self.assertEqual(overview.ferry_check(['b', 'a', 'b']), {'ferry_check': ['b', 'a']})
        self.assertEqual(overview.ferry_check([]), {'ferry_check': []})
        self.assertEqual(overview.ferry_check([1, 1, 1]), {'ferry_check': [1]})

    def test_overview_berth_total(self):
        self.assertEqual(overview.berth_total(5, [0, 5, 10]), {'berth_total': 2})
        self.assertEqual(overview.berth_total(-1, [0, 5, 10]), {'berth_total': 0})
        self.assertEqual(overview.berth_total(12, [0, 5, 10]), {'berth_total': 3})
        self.assertEqual(overview.berth_total(0, [0, 5, 10]), {'berth_total': 1})
        self.assertEqual(overview.berth_total(7, []), {'berth_total': 0})

    def test_overview_rope_row(self):
        self.assertEqual(overview.rope_row([3, 1, 2]), {'rope_row': 2})
        self.assertEqual(overview.rope_row([4, 1, 3, 2]), {'rope_row': 2.5})
        self.assertEqual(overview.rope_row([5]), {'rope_row': 5})
        self.assertEqual(overview.rope_row([1, 2]), {'rope_row': 1.5})
        self.assertEqual(overview.rope_row([10, 2, 38, 23, 38, 23]), {'rope_row': 23.0})
        with self.assertRaises(ValueError):
            overview.rope_row([])
