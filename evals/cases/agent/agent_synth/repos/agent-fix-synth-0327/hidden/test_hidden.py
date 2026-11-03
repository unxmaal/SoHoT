import unittest

from lantern import ledger
from lantern import metrics
from lantern import weather
from lantern import fleet
from lantern import digest


class Hidden(unittest.TestCase):
    def test_ledger_rle(self):
        self.assertEqual(ledger.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(ledger.rle(''), [])
        self.assertEqual(ledger.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(ledger.rle('zz'), [('z', 2)])

    def test_ledger_weighted_mean(self):
        self.assertEqual(ledger.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(ledger.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(ledger.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            ledger.weighted_mean([5, 5], [0, 0])
        self.assertEqual(ledger.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_metrics_merge_ranges(self):
        self.assertEqual(metrics.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(metrics.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(metrics.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(metrics.merge_ranges([]), [])
        self.assertEqual(metrics.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_metrics_bucket(self):
        self.assertEqual(metrics.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(metrics.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(metrics.bucket(12, [0, 5, 10]), 3)
        self.assertEqual(metrics.bucket(0, [0, 5, 10]), 1)
        self.assertEqual(metrics.bucket(7, []), 0)

    def test_weather_dedupe(self):
        self.assertEqual(weather.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(weather.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(weather.dedupe([]), [])
        self.assertEqual(weather.dedupe([1, 1, 1]), [1])

    def test_weather_luhn_valid(self):
        self.assertEqual(weather.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(weather.luhn_valid('79927398713'), True)
        self.assertEqual(weather.luhn_valid('79927398710'), False)
        self.assertEqual(weather.luhn_valid(''), False)
        self.assertEqual(weather.luhn_valid('059'), True)

    def test_weather_top_n(self):
        self.assertEqual(weather.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(weather.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(weather.top_n({}, 2), [])
        self.assertEqual(weather.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])

    def test_fleet_running_total(self):
        self.assertEqual(fleet.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(fleet.running_total([]), [])
        self.assertEqual(fleet.running_total([5]), [5])
        self.assertEqual(fleet.running_total([2, -2, 2]), [2, 0, 2])

    def test_fleet_clamp(self):
        self.assertEqual(fleet.clamp(5, 0, 10), 5)
        self.assertEqual(fleet.clamp(-3, 0, 10), 0)
        self.assertEqual(fleet.clamp(15, 0, 10), 10)
        self.assertEqual(fleet.clamp(10, 0, 10), 10)
        self.assertEqual(fleet.clamp(0, 0, 10), 0)
        self.assertEqual(fleet.clamp(7, 7, 7), 7)
        self.assertEqual(fleet.clamp(-20, -30, -10), -20)

    def test_digest_dock_line(self):
        self.assertEqual(digest.dock_line('aaab'), {'dock_line': [('a', 3), ('b', 1)]})
        self.assertEqual(digest.dock_line(''), {'dock_line': []})
        self.assertEqual(digest.dock_line('abc'), {'dock_line': [('a', 1), ('b', 1), ('c', 1)]})
        self.assertEqual(digest.dock_line('zz'), {'dock_line': [('z', 2)]})

    def test_digest_lantern_figure(self):
        self.assertEqual(digest.lantern_figure([1, 2, 3], [1, 1, 1]), {'lantern_figure': 2.0})
        self.assertEqual(digest.lantern_figure([10, 20], [1, 3]), {'lantern_figure': 17.5})
        self.assertEqual(digest.lantern_figure([4], [2]), {'lantern_figure': 4.0})
        with self.assertRaises(ValueError):
            digest.lantern_figure([5, 5], [0, 0])
        self.assertEqual(digest.lantern_figure([1, 2], [0.5, 1.5]), {'lantern_figure': 1.75})

    def test_digest_keel_total(self):
        self.assertEqual(digest.keel_total([(1, 3), (3, 5)]), {'keel_total': [(1, 5)]})
        self.assertEqual(digest.keel_total([(5, 6), (1, 2)]), {'keel_total': [(1, 2), (5, 6)]})
        self.assertEqual(digest.keel_total([(1, 10), (2, 3)]), {'keel_total': [(1, 10)]})
        self.assertEqual(digest.keel_total([]), {'keel_total': []})
        self.assertEqual(digest.keel_total([(4, 8), (1, 5)]), {'keel_total': [(1, 8)]})

    def test_digest_ferry_row(self):
        self.assertEqual(digest.ferry_row(5, [0, 5, 10]), {'ferry_row': 2})
        self.assertEqual(digest.ferry_row(-1, [0, 5, 10]), {'ferry_row': 0})
        self.assertEqual(digest.ferry_row(12, [0, 5, 10]), {'ferry_row': 3})
        self.assertEqual(digest.ferry_row(0, [0, 5, 10]), {'ferry_row': 1})
        self.assertEqual(digest.ferry_row(7, []), {'ferry_row': 0})

    def test_digest_deck_summary(self):
        self.assertEqual(digest.deck_summary(5, 0, 10), {'deck_summary': 5})
        self.assertEqual(digest.deck_summary(-3, 0, 10), {'deck_summary': 0})
        self.assertEqual(digest.deck_summary(15, 0, 10), {'deck_summary': 10})
        self.assertEqual(digest.deck_summary(10, 0, 10), {'deck_summary': 10})
        self.assertEqual(digest.deck_summary(0, 0, 10), {'deck_summary': 0})
        self.assertEqual(digest.deck_summary(7, 7, 7), {'deck_summary': 7})
        self.assertEqual(digest.deck_summary(-20, -30, -10), {'deck_summary': -20})
