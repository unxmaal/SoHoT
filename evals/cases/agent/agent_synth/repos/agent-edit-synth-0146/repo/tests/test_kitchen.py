import unittest

from lantern import kitchen


class Kitchen(unittest.TestCase):
    def test_top_n(self):
        self.assertEqual(kitchen.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(kitchen.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(kitchen.top_n({}, 2), [])

    def test_grade(self):
        self.assertEqual(kitchen.grade(95), 'A')
        self.assertEqual(kitchen.grade(90), 'A')
        self.assertEqual(kitchen.grade(85), 'B')

    def test_rle(self):
        self.assertEqual(kitchen.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(kitchen.rle(''), [])
        self.assertEqual(kitchen.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
