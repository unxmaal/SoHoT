import unittest

from tally import routes


class Routes(unittest.TestCase):
    def test_running_total(self):
        self.assertEqual(routes.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(routes.running_total([]), [])

    def test_rle(self):
        self.assertEqual(routes.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(routes.rle(''), [])

    def test_snake_case(self):
        self.assertEqual(routes.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(routes.snake_case('plain'), 'plain')
        self.assertEqual(routes.snake_case('A'), 'a')
