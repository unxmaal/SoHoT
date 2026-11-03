import unittest

from depot import tickets
from depot import weather
from depot import shipping


class Hidden(unittest.TestCase):
    def test_tickets_running_total(self):
        self.assertEqual(tickets.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(tickets.running_total([]), [])
        self.assertEqual(tickets.running_total([5]), [5])
        self.assertEqual(tickets.running_total([2, -2, 2]), [2, 0, 2])

    def test_tickets_merge_ranges(self):
        self.assertEqual(tickets.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(tickets.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(tickets.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(tickets.merge_ranges([]), [])
        self.assertEqual(tickets.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_tickets_dedupe(self):
        self.assertEqual(tickets.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(tickets.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(tickets.dedupe([]), [])
        self.assertEqual(tickets.dedupe([1, 1, 1]), [1])

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

    def test_weather_bucket(self):
        self.assertEqual(weather.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(weather.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(weather.bucket(12, [0, 5, 10]), 3)
        self.assertEqual(weather.bucket(0, [0, 5, 10]), 1)
        self.assertEqual(weather.bucket(7, []), 0)

    def test_shipping_median(self):
        self.assertEqual(shipping.median([3, 1, 2]), 2)
        self.assertEqual(shipping.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(shipping.median([5]), 5)
        self.assertEqual(shipping.median([1, 2]), 1.5)
        self.assertEqual(shipping.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            shipping.median([])

    def test_shipping_rle(self):
        self.assertEqual(shipping.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(shipping.rle(''), [])
        self.assertEqual(shipping.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(shipping.rle('zz'), [('z', 2)])

    def test_shipping_top_n(self):
        self.assertEqual(shipping.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(shipping.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(shipping.top_n({}, 2), [])
        self.assertEqual(shipping.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])

    def test_feature(self):
        self.assertEqual(tickets.dedupe(['Tea', 'tea', 'Milk', 'TEA'], ignore_case=True), ['Tea', 'Milk'])
        self.assertEqual(tickets.dedupe(['a', 'A'], ignore_case=True), ['a'])
