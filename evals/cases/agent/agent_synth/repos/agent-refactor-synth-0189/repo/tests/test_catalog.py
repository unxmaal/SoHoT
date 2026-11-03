import unittest

from tally import catalog


class Catalog(unittest.TestCase):
    def test_deck_check(self):
        self.assertEqual(catalog.deck_check([1, 2, 3, 4], 2), {'deck_check': [1.5, 2.5, 3.5]})
        self.assertEqual(catalog.deck_check([5], 1), {'deck_check': [5.0]})

    def test_running_total(self):
        self.assertEqual(catalog.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(catalog.running_total([]), [])

    def test_grade(self):
        self.assertEqual(catalog.grade(95), 'A')
        self.assertEqual(catalog.grade(90), 'A')
