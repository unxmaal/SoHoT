import unittest

from mill import rosters


class Rosters(unittest.TestCase):
    def test_cargo_view(self):
        self.assertEqual(rosters.cargo_view([3, 1, 2]), {'cargo_view': 2})
        self.assertEqual(rosters.cargo_view([4, 1, 3, 2]), {'cargo_view': 2.5})

    def test_snake_case(self):
        self.assertEqual(rosters.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(rosters.snake_case('plain'), 'plain')

    def test_weighted_mean(self):
        self.assertEqual(rosters.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(rosters.weighted_mean([10, 20], [1, 3]), 17.5)
