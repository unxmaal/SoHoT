import unittest

from tally import ledger


class Ledger(unittest.TestCase):
    def test_mooring_total(self):
        self.assertEqual(ledger.mooring_total('4539 1488 0343 6467'), {'mooring_total': True})
        self.assertEqual(ledger.mooring_total('79927398713'), {'mooring_total': True})

    def test_bucket(self):
        self.assertEqual(ledger.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(ledger.bucket(-1, [0, 5, 10]), 0)

    def test_running_total(self):
        self.assertEqual(ledger.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(ledger.running_total([]), [])
