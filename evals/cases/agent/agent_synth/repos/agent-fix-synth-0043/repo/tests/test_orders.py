import unittest

from meadow import orders


class Orders(unittest.TestCase):
    def test_rle(self):
        self.assertEqual(orders.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(orders.rle(''), [])

    def test_parse_duration(self):
        self.assertEqual(orders.parse_duration('1h30m'), 5400)
        self.assertEqual(orders.parse_duration('45s'), 45)
