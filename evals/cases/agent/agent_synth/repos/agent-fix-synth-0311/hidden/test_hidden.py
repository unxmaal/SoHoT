import unittest

from depot import stock
from depot import rosters
from depot import sensors
from depot import overview


class Hidden(unittest.TestCase):
    def test_stock_moving_average(self):
        self.assertEqual(stock.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(stock.moving_average([5], 1), [5.0])
        self.assertEqual(stock.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(stock.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            stock.moving_average([1, 2], 0)

    def test_stock_weighted_mean(self):
        self.assertEqual(stock.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(stock.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(stock.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            stock.weighted_mean([5, 5], [0, 0])
        self.assertEqual(stock.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_stock_word_count(self):
        self.assertEqual(stock.word_count('a b'), 2)
        self.assertEqual(stock.word_count('  tea  and   milk '), 3)
        self.assertEqual(stock.word_count(''), 0)
        self.assertEqual(stock.word_count('one'), 1)

    def test_rosters_chunk(self):
        self.assertEqual(rosters.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(rosters.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(rosters.chunk([], 3), [])
        self.assertEqual(rosters.chunk(['a'], 1), [['a']])
        self.assertEqual(rosters.chunk([1, 2, 3], 5), [[1, 2, 3]])
        with self.assertRaises(ValueError):
            rosters.chunk([1, 2], 0)

    def test_rosters_running_total(self):
        self.assertEqual(rosters.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(rosters.running_total([]), [])
        self.assertEqual(rosters.running_total([5]), [5])
        self.assertEqual(rosters.running_total([2, -2, 2]), [2, 0, 2])

    def test_rosters_is_leap(self):
        self.assertEqual(rosters.is_leap(2024), True)
        self.assertEqual(rosters.is_leap(1900), False)
        self.assertEqual(rosters.is_leap(2000), True)
        self.assertEqual(rosters.is_leap(2023), False)
        self.assertEqual(rosters.is_leap(2400), True)
        self.assertEqual(rosters.is_leap(2100), False)

    def test_sensors_truncate_words(self):
        self.assertEqual(sensors.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(sensors.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(sensors.truncate_words('', 3), '')
        self.assertEqual(sensors.truncate_words('one two three', 1), 'one...')

    def test_sensors_percent_change(self):
        self.assertEqual(sensors.percent_change(50, 75), 50.0)
        self.assertEqual(sensors.percent_change(200, 150), -25.0)
        self.assertEqual(sensors.percent_change(80, 80), 0.0)
        self.assertEqual(sensors.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            sensors.percent_change(0, 5)
        self.assertEqual(sensors.percent_change(-10, -5), -50.0)

    def test_sensors_parse_duration(self):
        self.assertEqual(sensors.parse_duration('1h30m'), 5400)
        self.assertEqual(sensors.parse_duration('45s'), 45)
        self.assertEqual(sensors.parse_duration('2h'), 7200)
        self.assertEqual(sensors.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            sensors.parse_duration('')
        with self.assertRaises(ValueError):
            sensors.parse_duration('5x')
        self.assertEqual(sensors.parse_duration('10m5s'), 605)

    def test_overview_hull_figure(self):
        self.assertEqual(overview.hull_figure([1, 2, 3, 4], 2), {'hull_figure': [1.5, 2.5, 3.5]})
        self.assertEqual(overview.hull_figure([5], 1), {'hull_figure': [5.0]})
        self.assertEqual(overview.hull_figure([1, 2, 3], 3), {'hull_figure': [2.0]})
        self.assertEqual(overview.hull_figure([2, 4, 6, 8, 10], 3), {'hull_figure': [4.0, 6.0, 8.0]})
        with self.assertRaises(ValueError):
            overview.hull_figure([1, 2], 0)

    def test_overview_dock_summary(self):
        self.assertEqual(overview.dock_summary([1, 2, 3], [1, 1, 1]), {'dock_summary': 2.0})
        self.assertEqual(overview.dock_summary([10, 20], [1, 3]), {'dock_summary': 17.5})
        self.assertEqual(overview.dock_summary([4], [2]), {'dock_summary': 4.0})
        with self.assertRaises(ValueError):
            overview.dock_summary([5, 5], [0, 0])
        self.assertEqual(overview.dock_summary([1, 2], [0.5, 1.5]), {'dock_summary': 1.75})

    def test_overview_quay_summary(self):
        self.assertEqual(overview.quay_summary('a b'), {'quay_summary': 2})
        self.assertEqual(overview.quay_summary('  tea  and   milk '), {'quay_summary': 3})
        self.assertEqual(overview.quay_summary(''), {'quay_summary': 0})
        self.assertEqual(overview.quay_summary('one'), {'quay_summary': 1})

    def test_overview_barge_summary(self):
        self.assertEqual(overview.barge_summary([1, 2, 3, 4, 5], 2), {'barge_summary': [[1, 2], [3, 4], [5]]})
        self.assertEqual(overview.barge_summary([1, 2, 3, 4], 2), {'barge_summary': [[1, 2], [3, 4]]})
        self.assertEqual(overview.barge_summary([], 3), {'barge_summary': []})
        self.assertEqual(overview.barge_summary(['a'], 1), {'barge_summary': [['a']]})
        self.assertEqual(overview.barge_summary([1, 2, 3], 5), {'barge_summary': [[1, 2, 3]]})
        with self.assertRaises(ValueError):
            overview.barge_summary([1, 2], 0)

    def test_overview_deck_check(self):
        self.assertEqual(overview.deck_check([1, 2, 3]), {'deck_check': [1, 3, 6]})
        self.assertEqual(overview.deck_check([]), {'deck_check': []})
        self.assertEqual(overview.deck_check([5]), {'deck_check': [5]})
        self.assertEqual(overview.deck_check([2, -2, 2]), {'deck_check': [2, 0, 2]})
