import unittest

from lantern.ledger import page_of


class Ledger(unittest.TestCase):
    def test_page_of(self):
        self.assertEqual(page_of([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(page_of([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])
        self.assertEqual(page_of([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5, 3), [])
