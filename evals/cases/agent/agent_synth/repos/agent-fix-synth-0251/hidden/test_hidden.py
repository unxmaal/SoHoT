import unittest

from granary import payroll
from granary import orders
from granary import pricing


class Hidden(unittest.TestCase):
    def test_payroll_top_n(self):
        self.assertEqual(payroll.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(payroll.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(payroll.top_n({}, 2), [])
        self.assertEqual(payroll.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])

    def test_payroll_word_count(self):
        self.assertEqual(payroll.word_count('a b'), 2)
        self.assertEqual(payroll.word_count('  tea  and   milk '), 3)
        self.assertEqual(payroll.word_count(''), 0)
        self.assertEqual(payroll.word_count('one'), 1)

    def test_payroll_grade(self):
        self.assertEqual(payroll.grade(95), 'A')
        self.assertEqual(payroll.grade(90), 'A')
        self.assertEqual(payroll.grade(85), 'B')
        self.assertEqual(payroll.grade(80), 'B')
        self.assertEqual(payroll.grade(61), 'D')
        self.assertEqual(payroll.grade(59), 'F')
        self.assertEqual(payroll.grade(0), 'F')

    def test_orders_percent_change(self):
        self.assertEqual(orders.percent_change(50, 75), 50.0)
        self.assertEqual(orders.percent_change(200, 150), -25.0)
        self.assertEqual(orders.percent_change(80, 80), 0.0)
        self.assertEqual(orders.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            orders.percent_change(0, 5)
        self.assertEqual(orders.percent_change(-10, -5), -50.0)

    def test_orders_weighted_mean(self):
        self.assertEqual(orders.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(orders.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(orders.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            orders.weighted_mean([5, 5], [0, 0])
        self.assertEqual(orders.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_pricing_truncate_words(self):
        self.assertEqual(pricing.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(pricing.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(pricing.truncate_words('', 3), '')
        self.assertEqual(pricing.truncate_words('one two three', 1), 'one...')

    def test_pricing_running_total(self):
        self.assertEqual(pricing.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(pricing.running_total([]), [])
        self.assertEqual(pricing.running_total([5]), [5])
        self.assertEqual(pricing.running_total([2, -2, 2]), [2, 0, 2])
