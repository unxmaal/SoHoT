import unittest

from beacon import sensors
from beacon import kitchen
from beacon import rosters
from beacon import budget


class Hidden(unittest.TestCase):
    def test_sensors_luhn_valid(self):
        self.assertEqual(sensors.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(sensors.luhn_valid('79927398713'), True)
        self.assertEqual(sensors.luhn_valid('79927398710'), False)
        self.assertEqual(sensors.luhn_valid(''), False)
        self.assertEqual(sensors.luhn_valid('059'), True)

    def test_sensors_clamp(self):
        self.assertEqual(sensors.clamp(5, 0, 10), 5)
        self.assertEqual(sensors.clamp(-3, 0, 10), 0)
        self.assertEqual(sensors.clamp(15, 0, 10), 10)
        self.assertEqual(sensors.clamp(10, 0, 10), 10)
        self.assertEqual(sensors.clamp(0, 0, 10), 0)
        self.assertEqual(sensors.clamp(7, 7, 7), 7)
        self.assertEqual(sensors.clamp(-20, -30, -10), -20)

    def test_sensors_top_n(self):
        self.assertEqual(sensors.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(sensors.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(sensors.top_n({}, 2), [])
        self.assertEqual(sensors.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])

    def test_kitchen_dedupe(self):
        self.assertEqual(kitchen.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(kitchen.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(kitchen.dedupe([]), [])
        self.assertEqual(kitchen.dedupe([1, 1, 1]), [1])

    def test_kitchen_chunk(self):
        self.assertEqual(kitchen.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(kitchen.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(kitchen.chunk([], 3), [])
        self.assertEqual(kitchen.chunk(['a'], 1), [['a']])
        self.assertEqual(kitchen.chunk([1, 2, 3], 5), [[1, 2, 3]])
        with self.assertRaises(ValueError):
            kitchen.chunk([1, 2], 0)

    def test_kitchen_rle(self):
        self.assertEqual(kitchen.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(kitchen.rle(''), [])
        self.assertEqual(kitchen.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(kitchen.rle('zz'), [('z', 2)])

    def test_rosters_median(self):
        self.assertEqual(rosters.median([3, 1, 2]), 2)
        self.assertEqual(rosters.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(rosters.median([5]), 5)
        self.assertEqual(rosters.median([1, 2]), 1.5)
        self.assertEqual(rosters.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            rosters.median([])

    def test_rosters_running_total(self):
        self.assertEqual(rosters.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(rosters.running_total([]), [])
        self.assertEqual(rosters.running_total([5]), [5])
        self.assertEqual(rosters.running_total([2, -2, 2]), [2, 0, 2])

    def test_budget_snake_case(self):
        self.assertEqual(budget.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(budget.snake_case('plain'), 'plain')
        self.assertEqual(budget.snake_case('A'), 'a')
        self.assertEqual(budget.snake_case('ShipToCity'), 'ship_to_city')

    def test_budget_moving_average(self):
        self.assertEqual(budget.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(budget.moving_average([5], 1), [5.0])
        self.assertEqual(budget.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(budget.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            budget.moving_average([1, 2], 0)

    def test_budget_merge_ranges(self):
        self.assertEqual(budget.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(budget.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(budget.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(budget.merge_ranges([]), [])
        self.assertEqual(budget.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_feature(self):
        self.assertEqual(budget.merge_ranges([(1, 2), (3, 4)]), [(1, 4)])
        self.assertEqual(budget.merge_ranges([(7, 9), (1, 6)]), [(1, 9)])
