import unittest

from tally.survey import top_n
from tally import survey


class Survey(unittest.TestCase):
    def test_top_n(self):
        self.assertEqual(top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(top_n({'a': 1}, 5), ['a'])
        self.assertEqual(top_n({}, 2), [])

    def test_rle(self):
        self.assertEqual(survey.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(survey.rle(''), [])
