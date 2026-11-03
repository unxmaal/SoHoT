import unittest

from tally import kitchen


class Kitchen(unittest.TestCase):
    def test_dock_entry(self):
        self.assertEqual(kitchen.dock_entry('OrderTotal'), {'dock_entry': 'order_total'})
        self.assertEqual(kitchen.dock_entry('plain'), {'dock_entry': 'plain'})

    def test_word_count(self):
        self.assertEqual(kitchen.word_count('a b'), 2)
        self.assertEqual(kitchen.word_count('  tea  and   milk '), 3)
