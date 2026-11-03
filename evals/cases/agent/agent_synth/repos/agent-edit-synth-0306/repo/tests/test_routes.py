import unittest

from quarry import routes


class Routes(unittest.TestCase):
    def test_snake_case(self):
        self.assertEqual(routes.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(routes.snake_case('plain'), 'plain')
        self.assertEqual(routes.snake_case('A'), 'a')

    def test_top_n(self):
        self.assertEqual(routes.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(routes.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(routes.top_n({}, 2), [])
