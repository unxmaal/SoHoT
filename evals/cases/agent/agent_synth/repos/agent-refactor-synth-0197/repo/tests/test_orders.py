import unittest

from granary import orders


class Orders(unittest.TestCase):
    def test_ferry_entry(self):
        self.assertEqual(orders.ferry_entry(5, [0, 5, 10]), {'ferry_entry': 2})
        self.assertEqual(orders.ferry_entry(-1, [0, 5, 10]), {'ferry_entry': 0})

    def test_moving_average(self):
        self.assertEqual(orders.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(orders.moving_average([5], 1), [5.0])

    def test_merge_ranges(self):
        self.assertEqual(orders.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(orders.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
