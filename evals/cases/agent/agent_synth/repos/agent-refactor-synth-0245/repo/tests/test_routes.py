import unittest

from foundry.routes import bucket
from foundry import routes


class Routes(unittest.TestCase):
    def test_bucket(self):
        self.assertEqual(bucket(5, [0, 5, 10]), 2)
        self.assertEqual(bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(bucket(12, [0, 5, 10]), 3)

    def test_top_n(self):
        self.assertEqual(routes.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(routes.top_n({'a': 1}, 5), ['a'])
