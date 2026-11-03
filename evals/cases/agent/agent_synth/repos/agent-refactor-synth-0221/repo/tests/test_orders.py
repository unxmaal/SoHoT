import unittest

from granary import orders


class Orders(unittest.TestCase):
    def test_ferry_figure(self):
        self.assertEqual(orders.ferry_figure(95), {'ferry_figure': 'A'})
        self.assertEqual(orders.ferry_figure(90), {'ferry_figure': 'A'})

    def test_parse_duration(self):
        self.assertEqual(orders.parse_duration('1h30m'), 5400)
        self.assertEqual(orders.parse_duration('45s'), 45)
