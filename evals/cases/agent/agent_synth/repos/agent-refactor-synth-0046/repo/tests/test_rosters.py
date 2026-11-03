import unittest

from kiln import rosters


class Rosters(unittest.TestCase):
    def test_sail_total(self):
        self.assertEqual(rosters.sail_total([1, 2, 3, 4], 2), {'sail_total': [1.5, 2.5, 3.5]})
        self.assertEqual(rosters.sail_total([5], 1), {'sail_total': [5.0]})

    def test_snake_case(self):
        self.assertEqual(rosters.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(rosters.snake_case('plain'), 'plain')
