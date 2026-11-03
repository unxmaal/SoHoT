import unittest

from tally import tickets
from tally import stock
from tally import budget
from tally import summary


class Hidden(unittest.TestCase):
    def test_tickets_weighted_mean(self):
        self.assertEqual(tickets.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(tickets.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(tickets.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            tickets.weighted_mean([5, 5], [0, 0])
        self.assertEqual(tickets.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_tickets_luhn_valid(self):
        self.assertEqual(tickets.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(tickets.luhn_valid('79927398713'), True)
        self.assertEqual(tickets.luhn_valid('79927398710'), False)
        self.assertEqual(tickets.luhn_valid(''), False)
        self.assertEqual(tickets.luhn_valid('059'), True)

    def test_stock_chunk(self):
        self.assertEqual(stock.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(stock.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(stock.chunk([], 3), [])
        self.assertEqual(stock.chunk(['a'], 1), [['a']])
        self.assertEqual(stock.chunk([1, 2, 3], 5), [[1, 2, 3]])
        with self.assertRaises(ValueError):
            stock.chunk([1, 2], 0)

    def test_stock_median(self):
        self.assertEqual(stock.median([3, 1, 2]), 2)
        self.assertEqual(stock.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(stock.median([5]), 5)
        self.assertEqual(stock.median([1, 2]), 1.5)
        self.assertEqual(stock.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            stock.median([])

    def test_budget_top_n(self):
        self.assertEqual(budget.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(budget.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(budget.top_n({}, 2), [])
        self.assertEqual(budget.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])

    def test_budget_invert(self):
        self.assertEqual(budget.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(budget.invert({}), {})
        self.assertEqual(budget.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(budget.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_budget_grade(self):
        self.assertEqual(budget.grade(95), 'A')
        self.assertEqual(budget.grade(90), 'A')
        self.assertEqual(budget.grade(85), 'B')
        self.assertEqual(budget.grade(80), 'B')
        self.assertEqual(budget.grade(61), 'D')
        self.assertEqual(budget.grade(59), 'F')
        self.assertEqual(budget.grade(0), 'F')

    def test_summary_keel_view(self):
        self.assertEqual(summary.keel_view([1, 2, 3], [1, 1, 1]), {'keel_view': 2.0})
        self.assertEqual(summary.keel_view([10, 20], [1, 3]), {'keel_view': 17.5})
        self.assertEqual(summary.keel_view([4], [2]), {'keel_view': 4.0})
        with self.assertRaises(ValueError):
            summary.keel_view([5, 5], [0, 0])
        self.assertEqual(summary.keel_view([1, 2], [0.5, 1.5]), {'keel_view': 1.75})

    def test_summary_tide_check(self):
        self.assertEqual(summary.tide_check('4539 1488 0343 6467'), {'tide_check': True})
        self.assertEqual(summary.tide_check('79927398713'), {'tide_check': True})
        self.assertEqual(summary.tide_check('79927398710'), {'tide_check': False})
        self.assertEqual(summary.tide_check(''), {'tide_check': False})
        self.assertEqual(summary.tide_check('059'), {'tide_check': True})

    def test_summary_buoy_row(self):
        self.assertEqual(summary.buoy_row([1, 2, 3, 4, 5], 2), {'buoy_row': [[1, 2], [3, 4], [5]]})
        self.assertEqual(summary.buoy_row([1, 2, 3, 4], 2), {'buoy_row': [[1, 2], [3, 4]]})
        self.assertEqual(summary.buoy_row([], 3), {'buoy_row': []})
        self.assertEqual(summary.buoy_row(['a'], 1), {'buoy_row': [['a']]})
        self.assertEqual(summary.buoy_row([1, 2, 3], 5), {'buoy_row': [[1, 2, 3]]})
        with self.assertRaises(ValueError):
            summary.buoy_row([1, 2], 0)

    def test_summary_rope_total(self):
        self.assertEqual(summary.rope_total([3, 1, 2]), {'rope_total': 2})
        self.assertEqual(summary.rope_total([4, 1, 3, 2]), {'rope_total': 2.5})
        self.assertEqual(summary.rope_total([5]), {'rope_total': 5})
        self.assertEqual(summary.rope_total([1, 2]), {'rope_total': 1.5})
        self.assertEqual(summary.rope_total([10, 2, 38, 23, 38, 23]), {'rope_total': 23.0})
        with self.assertRaises(ValueError):
            summary.rope_total([])
