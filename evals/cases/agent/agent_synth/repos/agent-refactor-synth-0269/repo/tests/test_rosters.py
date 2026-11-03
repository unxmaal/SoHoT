import unittest

from kiln import rosters


class Rosters(unittest.TestCase):
    def test_buoy_view(self):
        self.assertEqual(rosters.buoy_view(5, [0, 5, 10]), {'buoy_view': 2})
        self.assertEqual(rosters.buoy_view(-1, [0, 5, 10]), {'buoy_view': 0})

    def test_paginate(self):
        self.assertEqual(rosters.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(rosters.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])

    def test_moving_average(self):
        self.assertEqual(rosters.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(rosters.moving_average([5], 1), [5.0])
