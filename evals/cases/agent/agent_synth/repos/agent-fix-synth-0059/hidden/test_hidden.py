import unittest

from meadow import survey
from meadow import ledger
from meadow import metrics
from meadow import fleet
from meadow import billing


class Hidden(unittest.TestCase):
    def test_survey_parse_duration(self):
        self.assertEqual(survey.parse_duration('1h30m'), 5400)
        self.assertEqual(survey.parse_duration('45s'), 45)
        self.assertEqual(survey.parse_duration('2h'), 7200)
        self.assertEqual(survey.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            survey.parse_duration('')
        with self.assertRaises(ValueError):
            survey.parse_duration('5x')
        self.assertEqual(survey.parse_duration('10m5s'), 605)

    def test_survey_chunk(self):
        self.assertEqual(survey.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(survey.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(survey.chunk([], 3), [])
        self.assertEqual(survey.chunk(['a'], 1), [['a']])
        self.assertEqual(survey.chunk([1, 2, 3], 5), [[1, 2, 3]])
        with self.assertRaises(ValueError):
            survey.chunk([1, 2], 0)

    def test_survey_top_n(self):
        self.assertEqual(survey.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(survey.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(survey.top_n({}, 2), [])
        self.assertEqual(survey.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])

    def test_ledger_merge_ranges(self):
        self.assertEqual(ledger.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(ledger.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(ledger.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(ledger.merge_ranges([]), [])
        self.assertEqual(ledger.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_ledger_word_count(self):
        self.assertEqual(ledger.word_count('a b'), 2)
        self.assertEqual(ledger.word_count('  tea  and   milk '), 3)
        self.assertEqual(ledger.word_count(''), 0)
        self.assertEqual(ledger.word_count('one'), 1)

    def test_metrics_invert(self):
        self.assertEqual(metrics.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(metrics.invert({}), {})
        self.assertEqual(metrics.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(metrics.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_metrics_paginate(self):
        self.assertEqual(metrics.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(metrics.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(metrics.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(metrics.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            metrics.paginate([1, 2], 0, 2)

    def test_fleet_median(self):
        self.assertEqual(fleet.median([3, 1, 2]), 2)
        self.assertEqual(fleet.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(fleet.median([5]), 5)
        self.assertEqual(fleet.median([1, 2]), 1.5)
        self.assertEqual(fleet.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            fleet.median([])

    def test_fleet_dedupe(self):
        self.assertEqual(fleet.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(fleet.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(fleet.dedupe([]), [])
        self.assertEqual(fleet.dedupe([1, 1, 1]), [1])

    def test_billing_rle(self):
        self.assertEqual(billing.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(billing.rle(''), [])
        self.assertEqual(billing.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(billing.rle('zz'), [('z', 2)])

    def test_billing_moving_average(self):
        self.assertEqual(billing.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(billing.moving_average([5], 1), [5.0])
        self.assertEqual(billing.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(billing.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            billing.moving_average([1, 2], 0)

    def test_billing_truncate_words(self):
        self.assertEqual(billing.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(billing.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(billing.truncate_words('', 3), '')
        self.assertEqual(billing.truncate_words('one two three', 1), 'one...')
