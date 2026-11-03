import unittest

from atlas import tickets
from atlas import catalog
from atlas import budget
from atlas import overview


class Hidden(unittest.TestCase):
    def test_tickets_clamp(self):
        self.assertEqual(tickets.clamp(5, 0, 10), 5)
        self.assertEqual(tickets.clamp(-3, 0, 10), 0)
        self.assertEqual(tickets.clamp(15, 0, 10), 10)
        self.assertEqual(tickets.clamp(10, 0, 10), 10)
        self.assertEqual(tickets.clamp(0, 0, 10), 0)
        self.assertEqual(tickets.clamp(7, 7, 7), 7)
        self.assertEqual(tickets.clamp(-20, -30, -10), -20)

    def test_tickets_snake_case(self):
        self.assertEqual(tickets.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(tickets.snake_case('plain'), 'plain')
        self.assertEqual(tickets.snake_case('A'), 'a')
        self.assertEqual(tickets.snake_case('ShipToCity'), 'ship_to_city')

    def test_tickets_moving_average(self):
        self.assertEqual(tickets.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(tickets.moving_average([5], 1), [5.0])
        self.assertEqual(tickets.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(tickets.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            tickets.moving_average([1, 2], 0)

    def test_catalog_grade(self):
        self.assertEqual(catalog.grade(95), 'A')
        self.assertEqual(catalog.grade(90), 'A')
        self.assertEqual(catalog.grade(85), 'B')
        self.assertEqual(catalog.grade(80), 'B')
        self.assertEqual(catalog.grade(61), 'D')
        self.assertEqual(catalog.grade(59), 'F')
        self.assertEqual(catalog.grade(0), 'F')

    def test_catalog_is_leap(self):
        self.assertEqual(catalog.is_leap(2024), True)
        self.assertEqual(catalog.is_leap(1900), False)
        self.assertEqual(catalog.is_leap(2000), True)
        self.assertEqual(catalog.is_leap(2023), False)
        self.assertEqual(catalog.is_leap(2400), True)
        self.assertEqual(catalog.is_leap(2100), False)

    def test_budget_running_total(self):
        self.assertEqual(budget.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(budget.running_total([]), [])
        self.assertEqual(budget.running_total([5]), [5])
        self.assertEqual(budget.running_total([2, -2, 2]), [2, 0, 2])

    def test_budget_invert(self):
        self.assertEqual(budget.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(budget.invert({}), {})
        self.assertEqual(budget.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(budget.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_overview_berth_row(self):
        self.assertEqual(overview.berth_row(5, 0, 10), {'berth_row': 5})
        self.assertEqual(overview.berth_row(-3, 0, 10), {'berth_row': 0})
        self.assertEqual(overview.berth_row(15, 0, 10), {'berth_row': 10})
        self.assertEqual(overview.berth_row(10, 0, 10), {'berth_row': 10})
        self.assertEqual(overview.berth_row(0, 0, 10), {'berth_row': 0})
        self.assertEqual(overview.berth_row(7, 7, 7), {'berth_row': 7})
        self.assertEqual(overview.berth_row(-20, -30, -10), {'berth_row': -20})

    def test_overview_quay_total(self):
        self.assertEqual(overview.quay_total('OrderTotal'), {'quay_total': 'order_total'})
        self.assertEqual(overview.quay_total('plain'), {'quay_total': 'plain'})
        self.assertEqual(overview.quay_total('A'), {'quay_total': 'a'})
        self.assertEqual(overview.quay_total('ShipToCity'), {'quay_total': 'ship_to_city'})

    def test_overview_tide_summary(self):
        self.assertEqual(overview.tide_summary([1, 2, 3, 4], 2), {'tide_summary': [1.5, 2.5, 3.5]})
        self.assertEqual(overview.tide_summary([5], 1), {'tide_summary': [5.0]})
        self.assertEqual(overview.tide_summary([1, 2, 3], 3), {'tide_summary': [2.0]})
        self.assertEqual(overview.tide_summary([2, 4, 6, 8, 10], 3), {'tide_summary': [4.0, 6.0, 8.0]})
        with self.assertRaises(ValueError):
            overview.tide_summary([1, 2], 0)

    def test_overview_lantern_entry(self):
        self.assertEqual(overview.lantern_entry(95), {'lantern_entry': 'A'})
        self.assertEqual(overview.lantern_entry(90), {'lantern_entry': 'A'})
        self.assertEqual(overview.lantern_entry(85), {'lantern_entry': 'B'})
        self.assertEqual(overview.lantern_entry(80), {'lantern_entry': 'B'})
        self.assertEqual(overview.lantern_entry(61), {'lantern_entry': 'D'})
        self.assertEqual(overview.lantern_entry(59), {'lantern_entry': 'F'})
        self.assertEqual(overview.lantern_entry(0), {'lantern_entry': 'F'})
