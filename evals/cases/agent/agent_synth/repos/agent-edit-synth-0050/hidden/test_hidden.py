import unittest

from depot import weather
from depot import tickets
from depot import shipping


class Hidden(unittest.TestCase):
    def test_weather_truncate_words(self):
        self.assertEqual(weather.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(weather.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(weather.truncate_words('', 3), '')
        self.assertEqual(weather.truncate_words('one two three', 1), 'one...')

    def test_weather_grade(self):
        self.assertEqual(weather.grade(95), 'A')
        self.assertEqual(weather.grade(90), 'A')
        self.assertEqual(weather.grade(85), 'B')
        self.assertEqual(weather.grade(80), 'B')
        self.assertEqual(weather.grade(61), 'D')
        self.assertEqual(weather.grade(59), 'F')
        self.assertEqual(weather.grade(0), 'F')

    def test_weather_merge_ranges(self):
        self.assertEqual(weather.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(weather.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(weather.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(weather.merge_ranges([]), [])
        self.assertEqual(weather.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_tickets_dedupe(self):
        self.assertEqual(tickets.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(tickets.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(tickets.dedupe([]), [])
        self.assertEqual(tickets.dedupe([1, 1, 1]), [1])

    def test_tickets_running_total(self):
        self.assertEqual(tickets.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(tickets.running_total([]), [])
        self.assertEqual(tickets.running_total([5]), [5])
        self.assertEqual(tickets.running_total([2, -2, 2]), [2, 0, 2])

    def test_shipping_rle(self):
        self.assertEqual(shipping.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(shipping.rle(''), [])
        self.assertEqual(shipping.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(shipping.rle('zz'), [('z', 2)])

    def test_shipping_percent_change(self):
        self.assertEqual(shipping.percent_change(50, 75), 50.0)
        self.assertEqual(shipping.percent_change(200, 150), -25.0)
        self.assertEqual(shipping.percent_change(80, 80), 0.0)
        self.assertEqual(shipping.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            shipping.percent_change(0, 5)
        self.assertEqual(shipping.percent_change(-10, -5), -50.0)

    def test_shipping_top_n(self):
        self.assertEqual(shipping.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(shipping.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(shipping.top_n({}, 2), [])
        self.assertEqual(shipping.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])

    def test_feature(self):
        self.assertEqual(weather.merge_ranges([(1, 2), (3, 4)]), [(1, 4)])
        self.assertEqual(weather.merge_ranges([(7, 9), (1, 6)]), [(1, 9)])
