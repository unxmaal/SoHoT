import unittest

from kiln import tickets
from kiln import rosters
from kiln import billing
from kiln import catalog


class Hidden(unittest.TestCase):
    def test_tickets_parse_duration(self):
        self.assertEqual(tickets.parse_duration('1h30m'), 5400)
        self.assertEqual(tickets.parse_duration('45s'), 45)
        self.assertEqual(tickets.parse_duration('2h'), 7200)
        self.assertEqual(tickets.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            tickets.parse_duration('')
        with self.assertRaises(ValueError):
            tickets.parse_duration('5x')
        self.assertEqual(tickets.parse_duration('10m5s'), 605)

    def test_tickets_median(self):
        self.assertEqual(tickets.median([3, 1, 2]), 2)
        self.assertEqual(tickets.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(tickets.median([5]), 5)
        self.assertEqual(tickets.median([1, 2]), 1.5)
        self.assertEqual(tickets.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            tickets.median([])

    def test_rosters_top_n(self):
        self.assertEqual(rosters.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(rosters.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(rosters.top_n({}, 2), [])
        self.assertEqual(rosters.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])

    def test_rosters_invert(self):
        self.assertEqual(rosters.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(rosters.invert({}), {})
        self.assertEqual(rosters.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(rosters.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_rosters_dedupe(self):
        self.assertEqual(rosters.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(rosters.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(rosters.dedupe([]), [])
        self.assertEqual(rosters.dedupe([1, 1, 1]), [1])

    def test_billing_word_count(self):
        self.assertEqual(billing.word_count('a b'), 2)
        self.assertEqual(billing.word_count('  tea  and   milk '), 3)
        self.assertEqual(billing.word_count(''), 0)
        self.assertEqual(billing.word_count('one'), 1)

    def test_billing_snake_case(self):
        self.assertEqual(billing.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(billing.snake_case('plain'), 'plain')
        self.assertEqual(billing.snake_case('A'), 'a')
        self.assertEqual(billing.snake_case('ShipToCity'), 'ship_to_city')

    def test_catalog_merge_ranges(self):
        self.assertEqual(catalog.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(catalog.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(catalog.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(catalog.merge_ranges([]), [])
        self.assertEqual(catalog.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_catalog_truncate_words(self):
        self.assertEqual(catalog.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(catalog.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(catalog.truncate_words('', 3), '')
        self.assertEqual(catalog.truncate_words('one two three', 1), 'one...')
