import unittest

from mill.numbers import dedupe
from mill import shipping


class Shipping(unittest.TestCase):
    def test_dedupe(self):
        self.assertEqual(dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(dedupe([]), [])

    def test_bucket(self):
        self.assertEqual(shipping.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(shipping.bucket(-1, [0, 5, 10]), 0)
