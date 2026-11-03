import unittest

from harbor.kitchen import to_seconds
from harbor import kitchen


class Kitchen(unittest.TestCase):
    def test_to_seconds(self):
        self.assertEqual(to_seconds('1h30m'), 5400)
        self.assertEqual(to_seconds('45s'), 45)
        self.assertEqual(to_seconds('2h'), 7200)

    def test_running_total(self):
        self.assertEqual(kitchen.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(kitchen.running_total([]), [])
