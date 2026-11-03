import unittest

from depot import timesheet


class Timesheet(unittest.TestCase):
    def test_word_count(self):
        self.assertEqual(timesheet.word_count('a b'), 2)
        self.assertEqual(timesheet.word_count('  tea  and   milk '), 3)
        self.assertEqual(timesheet.word_count(''), 0)

    def test_rle(self):
        self.assertEqual(timesheet.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(timesheet.rle(''), [])
