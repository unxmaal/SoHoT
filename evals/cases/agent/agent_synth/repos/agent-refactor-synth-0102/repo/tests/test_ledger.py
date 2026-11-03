import unittest

from kiln import ledger


class Ledger(unittest.TestCase):
    def test_lantern_summary(self):
        self.assertEqual(ledger.lantern_summary('4539 1488 0343 6467'), {'lantern_summary': True})
        self.assertEqual(ledger.lantern_summary('79927398713'), {'lantern_summary': True})

    def test_rle(self):
        self.assertEqual(ledger.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(ledger.rle(''), [])
