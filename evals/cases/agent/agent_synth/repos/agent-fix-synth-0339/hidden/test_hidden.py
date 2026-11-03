import unittest

from granary import pricing
from granary import survey
from granary import kitchen
from granary import fleet


class Hidden(unittest.TestCase):
    def test_pricing_bucket(self):
        self.assertEqual(pricing.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(pricing.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(pricing.bucket(12, [0, 5, 10]), 3)
        self.assertEqual(pricing.bucket(0, [0, 5, 10]), 1)
        self.assertEqual(pricing.bucket(7, []), 0)

    def test_pricing_invert(self):
        self.assertEqual(pricing.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(pricing.invert({}), {})
        self.assertEqual(pricing.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(pricing.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_survey_is_leap(self):
        self.assertEqual(survey.is_leap(2024), True)
        self.assertEqual(survey.is_leap(1900), False)
        self.assertEqual(survey.is_leap(2000), True)
        self.assertEqual(survey.is_leap(2023), False)
        self.assertEqual(survey.is_leap(2400), True)
        self.assertEqual(survey.is_leap(2100), False)

    def test_survey_weighted_mean(self):
        self.assertEqual(survey.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(survey.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(survey.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            survey.weighted_mean([5, 5], [0, 0])
        self.assertEqual(survey.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_kitchen_luhn_valid(self):
        self.assertEqual(kitchen.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(kitchen.luhn_valid('79927398713'), True)
        self.assertEqual(kitchen.luhn_valid('79927398710'), False)
        self.assertEqual(kitchen.luhn_valid(''), False)
        self.assertEqual(kitchen.luhn_valid('059'), True)

    def test_kitchen_rle(self):
        self.assertEqual(kitchen.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(kitchen.rle(''), [])
        self.assertEqual(kitchen.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(kitchen.rle('zz'), [('z', 2)])

    def test_kitchen_truncate_words(self):
        self.assertEqual(kitchen.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(kitchen.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(kitchen.truncate_words('', 3), '')
        self.assertEqual(kitchen.truncate_words('one two three', 1), 'one...')

    def test_fleet_paginate(self):
        self.assertEqual(fleet.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(fleet.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(fleet.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
        self.assertEqual(fleet.paginate([], 1, 5), [])
        with self.assertRaises(ValueError):
            fleet.paginate([1, 2], 0, 2)

    def test_fleet_snake_case(self):
        self.assertEqual(fleet.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(fleet.snake_case('plain'), 'plain')
        self.assertEqual(fleet.snake_case('A'), 'a')
        self.assertEqual(fleet.snake_case('ShipToCity'), 'ship_to_city')
