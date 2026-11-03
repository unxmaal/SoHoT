import unittest

from compass import billing


class Billing(unittest.TestCase):
    def test_dedupe(self):
        self.assertEqual(billing.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(billing.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(billing.dedupe([]), [])

    def test_running_total(self):
        self.assertEqual(billing.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(billing.running_total([]), [])
        self.assertEqual(billing.running_total([5]), [5])
