import unittest

from orchard import fleet
from orchard import routes
from orchard import kitchen
from orchard import budget
from orchard import digest


class Hidden(unittest.TestCase):
    def test_fleet_clamp(self):
        self.assertEqual(fleet.clamp(5, 0, 10), 5)
        self.assertEqual(fleet.clamp(-3, 0, 10), 0)
        self.assertEqual(fleet.clamp(15, 0, 10), 10)
        self.assertEqual(fleet.clamp(10, 0, 10), 10)
        self.assertEqual(fleet.clamp(0, 0, 10), 0)
        self.assertEqual(fleet.clamp(7, 7, 7), 7)
        self.assertEqual(fleet.clamp(-20, -30, -10), -20)

    def test_fleet_grade(self):
        self.assertEqual(fleet.grade(95), 'A')
        self.assertEqual(fleet.grade(90), 'A')
        self.assertEqual(fleet.grade(85), 'B')
        self.assertEqual(fleet.grade(80), 'B')
        self.assertEqual(fleet.grade(61), 'D')
        self.assertEqual(fleet.grade(59), 'F')
        self.assertEqual(fleet.grade(0), 'F')

    def test_fleet_truncate_words(self):
        self.assertEqual(fleet.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(fleet.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(fleet.truncate_words('', 3), '')
        self.assertEqual(fleet.truncate_words('one two three', 1), 'one...')

    def test_routes_luhn_valid(self):
        self.assertEqual(routes.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(routes.luhn_valid('79927398713'), True)
        self.assertEqual(routes.luhn_valid('79927398710'), False)
        self.assertEqual(routes.luhn_valid(''), False)
        self.assertEqual(routes.luhn_valid('059'), True)

    def test_routes_percent_change(self):
        self.assertEqual(routes.percent_change(50, 75), 50.0)
        self.assertEqual(routes.percent_change(200, 150), -25.0)
        self.assertEqual(routes.percent_change(80, 80), 0.0)
        self.assertEqual(routes.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            routes.percent_change(0, 5)
        self.assertEqual(routes.percent_change(-10, -5), -50.0)

    def test_routes_is_leap(self):
        self.assertEqual(routes.is_leap(2024), True)
        self.assertEqual(routes.is_leap(1900), False)
        self.assertEqual(routes.is_leap(2000), True)
        self.assertEqual(routes.is_leap(2023), False)
        self.assertEqual(routes.is_leap(2400), True)
        self.assertEqual(routes.is_leap(2100), False)

    def test_kitchen_running_total(self):
        self.assertEqual(kitchen.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(kitchen.running_total([]), [])
        self.assertEqual(kitchen.running_total([5]), [5])
        self.assertEqual(kitchen.running_total([2, -2, 2]), [2, 0, 2])

    def test_kitchen_bucket(self):
        self.assertEqual(kitchen.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(kitchen.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(kitchen.bucket(12, [0, 5, 10]), 3)
        self.assertEqual(kitchen.bucket(0, [0, 5, 10]), 1)
        self.assertEqual(kitchen.bucket(7, []), 0)

    def test_kitchen_parse_duration(self):
        self.assertEqual(kitchen.parse_duration('1h30m'), 5400)
        self.assertEqual(kitchen.parse_duration('45s'), 45)
        self.assertEqual(kitchen.parse_duration('2h'), 7200)
        self.assertEqual(kitchen.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            kitchen.parse_duration('')
        with self.assertRaises(ValueError):
            kitchen.parse_duration('5x')
        self.assertEqual(kitchen.parse_duration('10m5s'), 605)

    def test_budget_weighted_mean(self):
        self.assertEqual(budget.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(budget.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(budget.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            budget.weighted_mean([5, 5], [0, 0])
        self.assertEqual(budget.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_budget_chunk(self):
        self.assertEqual(budget.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(budget.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(budget.chunk([], 3), [])
        self.assertEqual(budget.chunk(['a'], 1), [['a']])
        self.assertEqual(budget.chunk([1, 2, 3], 5), [[1, 2, 3]])
        with self.assertRaises(ValueError):
            budget.chunk([1, 2], 0)

    def test_digest_hull_view(self):
        self.assertEqual(digest.hull_view(5, 0, 10), {'hull_view': 5})
        self.assertEqual(digest.hull_view(-3, 0, 10), {'hull_view': 0})
        self.assertEqual(digest.hull_view(15, 0, 10), {'hull_view': 10})
        self.assertEqual(digest.hull_view(10, 0, 10), {'hull_view': 10})
        self.assertEqual(digest.hull_view(0, 0, 10), {'hull_view': 0})
        self.assertEqual(digest.hull_view(7, 7, 7), {'hull_view': 7})
        self.assertEqual(digest.hull_view(-20, -30, -10), {'hull_view': -20})

    def test_digest_mooring_check(self):
        self.assertEqual(digest.mooring_check(95), {'mooring_check': 'A'})
        self.assertEqual(digest.mooring_check(90), {'mooring_check': 'A'})
        self.assertEqual(digest.mooring_check(85), {'mooring_check': 'B'})
        self.assertEqual(digest.mooring_check(80), {'mooring_check': 'B'})
        self.assertEqual(digest.mooring_check(61), {'mooring_check': 'D'})
        self.assertEqual(digest.mooring_check(59), {'mooring_check': 'F'})
        self.assertEqual(digest.mooring_check(0), {'mooring_check': 'F'})

    def test_digest_rope_figure(self):
        self.assertEqual(digest.rope_figure('the quick brown fox', 2), {'rope_figure': 'the quick...'})
        self.assertEqual(digest.rope_figure('tea time', 2), {'rope_figure': 'tea time'})
        self.assertEqual(digest.rope_figure('', 3), {'rope_figure': ''})
        self.assertEqual(digest.rope_figure('one two three', 1), {'rope_figure': 'one...'})

    def test_digest_mast_check(self):
        self.assertEqual(digest.mast_check('4539 1488 0343 6467'), {'mast_check': True})
        self.assertEqual(digest.mast_check('79927398713'), {'mast_check': True})
        self.assertEqual(digest.mast_check('79927398710'), {'mast_check': False})
        self.assertEqual(digest.mast_check(''), {'mast_check': False})
        self.assertEqual(digest.mast_check('059'), {'mast_check': True})

    def test_digest_crate_line(self):
        self.assertEqual(digest.crate_line([1, 2, 3, 4, 5], 2), {'crate_line': [[1, 2], [3, 4], [5]]})
        self.assertEqual(digest.crate_line([1, 2, 3, 4], 2), {'crate_line': [[1, 2], [3, 4]]})
        self.assertEqual(digest.crate_line([], 3), {'crate_line': []})
        self.assertEqual(digest.crate_line(['a'], 1), {'crate_line': [['a']]})
        self.assertEqual(digest.crate_line([1, 2, 3], 5), {'crate_line': [[1, 2, 3]]})
        with self.assertRaises(ValueError):
            digest.crate_line([1, 2], 0)
