import unittest

from foundry import orders


class Orders(unittest.TestCase):
    def test_harbor_row(self):
        self.assertEqual(orders.harbor_row('aaab'), {'harbor_row': [('a', 3), ('b', 1)]})
        self.assertEqual(orders.harbor_row(''), {'harbor_row': []})

    def test_running_total(self):
        self.assertEqual(orders.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(orders.running_total([]), [])
