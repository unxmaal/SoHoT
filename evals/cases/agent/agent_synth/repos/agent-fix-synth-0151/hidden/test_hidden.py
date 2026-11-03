import unittest

from quarry import kitchen
from quarry import billing
from quarry import survey
from quarry import shipping
from quarry import orders
from quarry import overview


class Hidden(unittest.TestCase):
    def test_kitchen_snake_case(self):
        self.assertEqual(kitchen.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(kitchen.snake_case('plain'), 'plain')
        self.assertEqual(kitchen.snake_case('A'), 'a')
        self.assertEqual(kitchen.snake_case('ShipToCity'), 'ship_to_city')

    def test_kitchen_truncate_words(self):
        self.assertEqual(kitchen.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(kitchen.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(kitchen.truncate_words('', 3), '')
        self.assertEqual(kitchen.truncate_words('one two three', 1), 'one...')

    def test_billing_median(self):
        self.assertEqual(billing.median([3, 1, 2]), 2)
        self.assertEqual(billing.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(billing.median([5]), 5)
        self.assertEqual(billing.median([1, 2]), 1.5)
        self.assertEqual(billing.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            billing.median([])

    def test_billing_running_total(self):
        self.assertEqual(billing.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(billing.running_total([]), [])
        self.assertEqual(billing.running_total([5]), [5])
        self.assertEqual(billing.running_total([2, -2, 2]), [2, 0, 2])

    def test_survey_moving_average(self):
        self.assertEqual(survey.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(survey.moving_average([5], 1), [5.0])
        self.assertEqual(survey.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(survey.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            survey.moving_average([1, 2], 0)

    def test_survey_format_cents(self):
        self.assertEqual(survey.format_cents(0), '$0.00')
        self.assertEqual(survey.format_cents(123456), '$1,234.56')
        self.assertEqual(survey.format_cents(-105), '-$1.05')
        self.assertEqual(survey.format_cents(5), '$0.05')
        self.assertEqual(survey.format_cents(100000000), '$1,000,000.00')

    def test_survey_weighted_mean(self):
        self.assertEqual(survey.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(survey.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(survey.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            survey.weighted_mean([5, 5], [0, 0])
        self.assertEqual(survey.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_shipping_grade(self):
        self.assertEqual(shipping.grade(95), 'A')
        self.assertEqual(shipping.grade(90), 'A')
        self.assertEqual(shipping.grade(85), 'B')
        self.assertEqual(shipping.grade(80), 'B')
        self.assertEqual(shipping.grade(61), 'D')
        self.assertEqual(shipping.grade(59), 'F')
        self.assertEqual(shipping.grade(0), 'F')

    def test_shipping_luhn_valid(self):
        self.assertEqual(shipping.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(shipping.luhn_valid('79927398713'), True)
        self.assertEqual(shipping.luhn_valid('79927398710'), False)
        self.assertEqual(shipping.luhn_valid(''), False)
        self.assertEqual(shipping.luhn_valid('059'), True)

    def test_shipping_clamp(self):
        self.assertEqual(shipping.clamp(5, 0, 10), 5)
        self.assertEqual(shipping.clamp(-3, 0, 10), 0)
        self.assertEqual(shipping.clamp(15, 0, 10), 10)
        self.assertEqual(shipping.clamp(10, 0, 10), 10)
        self.assertEqual(shipping.clamp(0, 0, 10), 0)
        self.assertEqual(shipping.clamp(7, 7, 7), 7)
        self.assertEqual(shipping.clamp(-20, -30, -10), -20)

    def test_orders_word_count(self):
        self.assertEqual(orders.word_count('a b'), 2)
        self.assertEqual(orders.word_count('  tea  and   milk '), 3)
        self.assertEqual(orders.word_count(''), 0)
        self.assertEqual(orders.word_count('one'), 1)

    def test_orders_parse_duration(self):
        self.assertEqual(orders.parse_duration('1h30m'), 5400)
        self.assertEqual(orders.parse_duration('45s'), 45)
        self.assertEqual(orders.parse_duration('2h'), 7200)
        self.assertEqual(orders.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            orders.parse_duration('')
        with self.assertRaises(ValueError):
            orders.parse_duration('5x')
        self.assertEqual(orders.parse_duration('10m5s'), 605)

    def test_orders_rle(self):
        self.assertEqual(orders.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(orders.rle(''), [])
        self.assertEqual(orders.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(orders.rle('zz'), [('z', 2)])

    def test_overview_harbor_total(self):
        self.assertEqual(overview.harbor_total('OrderTotal'), {'harbor_total': 'order_total'})
        self.assertEqual(overview.harbor_total('plain'), {'harbor_total': 'plain'})
        self.assertEqual(overview.harbor_total('A'), {'harbor_total': 'a'})
        self.assertEqual(overview.harbor_total('ShipToCity'), {'harbor_total': 'ship_to_city'})

    def test_overview_ferry_entry(self):
        self.assertEqual(overview.ferry_entry('the quick brown fox', 2), {'ferry_entry': 'the quick...'})
        self.assertEqual(overview.ferry_entry('tea time', 2), {'ferry_entry': 'tea time'})
        self.assertEqual(overview.ferry_entry('', 3), {'ferry_entry': ''})
        self.assertEqual(overview.ferry_entry('one two three', 1), {'ferry_entry': 'one...'})

    def test_overview_lantern_summary(self):
        self.assertEqual(overview.lantern_summary([3, 1, 2]), {'lantern_summary': 2})
        self.assertEqual(overview.lantern_summary([4, 1, 3, 2]), {'lantern_summary': 2.5})
        self.assertEqual(overview.lantern_summary([5]), {'lantern_summary': 5})
        self.assertEqual(overview.lantern_summary([1, 2]), {'lantern_summary': 1.5})
        self.assertEqual(overview.lantern_summary([10, 2, 38, 23, 38, 23]), {'lantern_summary': 23.0})
        with self.assertRaises(ValueError):
            overview.lantern_summary([])

    def test_overview_quay_view(self):
        self.assertEqual(overview.quay_view([1, 2, 3]), {'quay_view': [1, 3, 6]})
        self.assertEqual(overview.quay_view([]), {'quay_view': []})
        self.assertEqual(overview.quay_view([5]), {'quay_view': [5]})
        self.assertEqual(overview.quay_view([2, -2, 2]), {'quay_view': [2, 0, 2]})

    def test_overview_crate_line(self):
        self.assertEqual(overview.crate_line(95), {'crate_line': 'A'})
        self.assertEqual(overview.crate_line(90), {'crate_line': 'A'})
        self.assertEqual(overview.crate_line(85), {'crate_line': 'B'})
        self.assertEqual(overview.crate_line(80), {'crate_line': 'B'})
        self.assertEqual(overview.crate_line(61), {'crate_line': 'D'})
        self.assertEqual(overview.crate_line(59), {'crate_line': 'F'})
        self.assertEqual(overview.crate_line(0), {'crate_line': 'F'})
