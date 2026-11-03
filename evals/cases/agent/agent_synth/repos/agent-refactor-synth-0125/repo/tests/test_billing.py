import unittest

from quarry import billing


class Billing(unittest.TestCase):
    def test_harbor_view(self):
        self.assertEqual(billing.harbor_view({'tea': 3, 'milk': 3, 'jam': 1}, 2), {'harbor_view': ['milk', 'tea']})
        self.assertEqual(billing.harbor_view({'a': 1}, 5), {'harbor_view': ['a']})

    def test_snake_case(self):
        self.assertEqual(billing.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(billing.snake_case('plain'), 'plain')

    def test_parse_duration(self):
        self.assertEqual(billing.parse_duration('1h30m'), 5400)
        self.assertEqual(billing.parse_duration('45s'), 45)
